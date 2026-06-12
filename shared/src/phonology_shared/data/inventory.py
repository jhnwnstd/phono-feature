"""The Inventory contract: structural validation, not phonological theory.

Enforces JSON shape, stable identifiers, declared feature keys,
allowed cell values (``+`` / ``-`` / ``0``), Unicode safety, size
limits, and crash-safe writes. Segment labels are identifiers;
feature values are the semantics. The parse pipeline lives in
:py:mod:`._parse`; see :py:meth:`Inventory.parse` for the
parse-don't-validate contract.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from typing import Any

from phonology_shared.data.limits import MAX_INVENTORY_FILE_BYTES

_log = logging.getLogger(__name__)


class FeatureValue(StrEnum):
    """The three valid values a feature can take in a segment bundle.

    Inventories on disk use the raw strings ``"+"`` / ``"-"`` / ``"0"``
    and the parser preserves that on round-trip. Inside the validated
    :py:class:`Inventory` the values are :py:class:`FeatureValue`
    instances so engine code can switch on a typed enum instead of
    bare strings. StrEnum members compare equal to their string value
    (``FeatureValue.PLUS == "+"``), so existing call sites that do
    ``value == "+"`` keep working unchanged.

    Canonical semantics (load-bearing, do not infer ``-`` from ``0``):

    - ``PLUS``: the feature is specified as positive for this segment.
    - ``MINUS``: the feature is specified as negative.
    - ``ZERO``: the feature is **not applicable** to this segment OR
      **underspecified** by the source. ``ZERO`` is NOT a negative
      value; natural-class queries that infer ``MINUS`` from absence
      conflate orthogonal concepts and break under-specification
      analyses and harmony logic.

    Concretely: a ``+round`` query against a vowel inventory must
    not match consonants that carry ``round = 0`` (the feature is
    not applicable to most consonants), and a Hindi inventory's
    all-``0`` ``LowerLarynx`` row must read as "Hindi does not
    specify this feature", not "Hindi is uniformly ``-LowerLarynx``".

    The ternary distinction is the single most important
    interoperability invariant between SPE-, PHOIBLE-, PanPhon-,
    and CLTS-style feature systems. Underspecification theory
    (Archangeli 1988; Mohanan 1991) operationalises the same
    distinction.

    Hayes (2009) treats ``"0"`` the same way; see
    :py:class:`FeatureState` in
    :py:mod:`phonology_shared.chart.vowels` for the four-state model
    that further distinguishes "absent key" from "explicit zero".
    """

    PLUS = "+"
    MINUS = "-"
    ZERO = "0"


#: Frozen set of the three valid feature values. Derived from
#: :py:class:`FeatureValue` so adding or removing a member only
#: requires editing the enum. Membership against a raw string still
#: works (``"+" in VALID_VALUES is True``) because StrEnum members
#: equal their string values.
VALID_VALUES: frozenset[FeatureValue] = frozenset(FeatureValue)


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One structured problem found by the inventory validator.

    Carries a stable :py:attr:`code` (the contract: tests assert on
    these), the JSON path (``("features", 3)`` for the fourth feature
    or ``("segments", "p", "Voice")`` for the Voice value of segment
    ``p``), and a human-facing :py:attr:`message` already rendered
    with the ``source:`` prefix when known. :py:class:`ValidationError`
    derives the legacy ``issues: tuple[str, ...]`` from the messages
    so existing UI code continues to work.
    """

    code: str
    path: tuple[str | int, ...]
    message: str


class _IssueCodes:
    """Stable identifiers for every validator emission.

    Codes are dotted: the prefix names the validator domain, the
    suffix names the specific check. Tests assert on these instead
    of brittle substring matches on the message.

    Adding a new check adds a new code here; renaming an existing
    one is a breaking change for any external test that pins to it.
    """

    # Top-level shape.
    TOP_LEVEL_NOT_OBJECT = "inventory.top_level_not_object"
    SCHEMA_VERSION_TYPE = "inventory.schema_version_type"
    SCHEMA_VERSION_UNSUPPORTED = "inventory.schema_version_unsupported"
    MISSING_FEATURES = "inventory.missing_features"
    MISSING_SEGMENTS = "inventory.missing_segments"

    # Feature-table validation.
    FEATURES_NOT_LIST = "feature.list_not_list"
    FEATURES_OVER_CAP = "feature.over_cap"
    FEATURE_NOT_STRING = "feature.not_string"
    FEATURE_OVER_LENGTH = "feature.over_length"
    FEATURE_EMPTY = "feature.empty_after_canonicalize"
    FEATURE_INVISIBLE_CHAR = "feature.invisible_char"
    FEATURE_DUPLICATE = "feature.duplicate"
    FEATURE_CANONICAL_COLLISION = "feature.canonical_collision"
    FEATURE_ALIAS_COLLISION = "feature.alias_collision"

    # Segment-table validation.
    SEGMENTS_NOT_OBJECT = "segments.not_object"
    SEGMENTS_OVER_CAP = "segments.over_cap"
    SEGMENT_KEY_TYPE = "segment.key_type"
    SEGMENT_KEY_OVER_LENGTH = "segment.key_over_length"
    SEGMENT_KEY_EMPTY = "segment.key_empty_after_canonicalize"
    SEGMENT_KEY_INVISIBLE_CHAR = "segment.key_invisible_char"
    SEGMENT_KEY_COLLISION = "segment.key_canonical_collision"

    # Metadata validation.
    METADATA_NOT_OBJECT = "inventory.metadata_not_object"
    METADATA_NAME_NOT_STRING = "inventory.metadata_name_not_string"

    # Per-bundle validation.
    BUNDLE_NOT_OBJECT = "segment.bundle_not_object"
    BUNDLE_FEATURE_KEY_TYPE = "segment.bundle_feature_key_type"
    BUNDLE_FEATURE_KEY_OVER_LENGTH = "segment.bundle_feature_key_over_length"
    BUNDLE_FEATURE_KEY_EMPTY = "segment.bundle_feature_key_empty"
    BUNDLE_FEATURE_KEY_COLLISION = "segment.bundle_feature_key_collision"
    BUNDLE_FEATURE_NOT_DECLARED = "segment.bundle_feature_not_declared"
    BUNDLE_VALUE_TYPE = "segment.bundle_value_type"
    BUNDLE_VALUE_INVALID = "segment.bundle_value_invalid"


@dataclass(slots=True)
class _ValidationContext:
    """Mutable issue accumulator threaded through the validation
    phases.

    Each ``error`` call appends a :py:class:`ValidationIssue` with
    the source prefix baked into the message. The driver
    (:py:meth:`Inventory.parse`) reads :py:attr:`issues` at the end
    of the pipeline and raises :py:class:`ValidationError` if any
    were collected.
    """

    source: str | None
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def prefix(self) -> str:
        return f"{self.source}: " if self.source else ""

    def error(
        self,
        code: str,
        path: tuple[str | int, ...],
        message: str,
    ) -> None:
        """Record an issue. ``message`` is prepended with the
        ``source:`` prefix when known."""
        self.issues.append(
            ValidationIssue(
                code=code, path=path, message=f"{self.prefix}{message}"
            )
        )

    @property
    def has_errors(self) -> bool:
        return bool(self.issues)


@lru_cache(maxsize=512)
def normalize_feature_key(key: str) -> str:
    """Fold a feature name to its canonical engine-side spelling.

    First consults
    :py:data:`phonology_shared.presentation.feature_metadata.FEATURE_REGISTRY`
    via ``resolve_canonical``: every known alias (case variant,
    delimiter variant, PanPhon short code, PHOIBLE long form,
    semantic alias like ``periodicGlottalSource → voice``)
    resolves through one shared table. Falls back to the historical
    string-manipulation rules below for genuinely unregistered
    inputs (user-created inventories with novel feature names),
    preserving the prior contract that ``normalize_feature_key``
    never raises for any string.

    The two paths produce IDENTICAL output for every name the
    registry knows, so engine consumers (matching, grouping,
    alias-collision detection at parse time) and renderer
    consumers (sort, group, suprasegmental check) always agree on
    whether two surface forms are the same feature.

    Memoized because the same handful of names recur for every
    segment and every reload.

    Lives in :py:mod:`inventory` so :py:meth:`Inventory.parse` can
    detect alias collisions at the boundary without depending on
    the display layer; :py:mod:`segment_grouper` re-imports it for
    its own bundle normalisation.
    """
    # Local import to keep the dependency direction one-way: data
    # imports from presentation only here, at the metadata-resolver
    # boundary. The opposite import (presentation.feature_metadata
    # importing data.inventory) would be a cycle.
    from phonology_shared.presentation.feature_metadata import (
        fold_feature_name,
        resolve_canonical,
    )

    canonical = resolve_canonical(key)
    if canonical is not None:
        return canonical

    # Fallback for unregistered features: the same lowercase +
    # delimiter-strip fold the registry's alias index uses, so a
    # custom name like ``Foo_Bar`` deterministically becomes
    # ``foobar`` whether it's registered or not. The historical
    # special-case aliases that used to live here (``del.rel.``,
    # ``rcolored``, ``breathyvoice``, ...) are all registered, so
    # the resolver above handles them; a parity test in
    # ``test_feature_metadata.py`` pins that identity.
    return fold_feature_name(key)


class AliasCollisionError(ValueError):
    """Raised when two feature names in the same bundle collapse to
    the same canonical key under :py:func:`normalize_feature_key`
    (for example ``"DelRel"`` and ``"delayed_release"``). A plain
    dict-comprehension rebuild would silently keep whichever came
    last; surfacing the collision lets the caller rename or remove
    one. The blocked features are on ``.collisions`` as
    ``{canonical_key: [original_names]}``."""

    def __init__(self, collisions: dict[str, list[str]]):
        self.collisions = collisions
        sample = "; ".join(
            f"{canonical!r} <- {sorted(originals)}"
            for canonical, originals in sorted(collisions.items())
        )
        super().__init__(
            f"Feature name aliases collide after normalization: {sample}"
        )


def normalize_feature_bundle(
    feat_dict: Mapping[str, str],
) -> dict[str, str]:
    """Normalize the feature names of one segment's feature bundle.

    Returns ``{canonical_key: value}`` where each key is folded via
    :py:func:`normalize_feature_key`. Raises
    :py:class:`AliasCollisionError` when two distinct input keys
    collapse to the same canonical key, because silently dropping
    one would be data loss. The :py:meth:`Inventory.parse` boundary
    catches the same situation at parse time so engine consumers
    don't have to defend against the collision downstream.
    """
    groups: dict[str, list[str]] = {}
    for k in feat_dict:
        groups.setdefault(normalize_feature_key(k), []).append(k)
    collisions = {
        canonical: originals
        for canonical, originals in groups.items()
        if len(originals) > 1
    }
    if collisions:
        raise AliasCollisionError(collisions)
    return {
        canonical: feat_dict[originals[0]]
        for canonical, originals in groups.items()
    }


# Domain-specific identity folding for segment labels. ``r`` is
# deliberately excluded: it is the legitimate IPA alveolar trill, and
# folding it to ``ɹ`` (the approximant) would silently change meaning.
# ASCII ``:`` is not folded but surfaced as an advisory in
# :py:func:`_ipa_confusable_notes`, because the cost of getting vowel
# length wrong is too high to rewrite without consent.
_IPA_SEGMENT_TRANSLATIONS: dict[str, str] = {
    "'": "ʼ",  # APOSTROPHE -> MODIFIER LETTER APOSTROPHE (ejective)
    "g": "ɡ",  # ASCII g -> LATIN SMALL LETTER SCRIPT G (voiced velar)
    # Hayes-style advanced/retracted markers folded to ASCII so the
    # label is readable in the GUI and matches the bundled
    # Hayes (2009) inventory. Upstream kylebgorman/hayes2009 uses
    # the same convention.
    "̟": "+",  # COMBINING PLUS SIGN BELOW (advanced) -> ASCII +
    "̠": "-",  # COMBINING MINUS SIGN BELOW (retracted) -> ASCII -
}
_IPA_TRANSLATION_TABLE = str.maketrans(_IPA_SEGMENT_TRANSLATIONS)


def _ipa_normalize_segment(canonical: str) -> str:
    """Fold ASCII substitutes commonly typed for IPA characters in
    segment labels. Idempotent. Pure transformation, no validation."""
    return canonical.translate(_IPA_TRANSLATION_TABLE)


def canonicalize_segment_label(label: str) -> str:
    """Public canonicalisation used by add-segment validators in
    both UIs.

    Same composition the inventory parser applies to incoming
    segment keys: NFC + strip via :py:func:`_canonicalize_name`,
    then the IPA folding (ASCII ``g``->``ɡ``, ``'``->``ʼ``, etc.)
    via :py:func:`_ipa_normalize_segment`. Exposed so the GUI's
    ``validate_new_segment_label`` can canonicalise candidate AND
    existing labels symmetrically before its duplicate-check;
    asymmetric normalisation lets add-time accept what save-time
    rejects, with the error landing far from the input.
    """
    return _ipa_normalize_segment(_canonicalize_name(label))


def canonicalize_feature_label(label: str) -> str:
    """Public canonicalisation used by add-feature validators.

    Same NFC + strip the parser applies to feature names. No IPA
    folding (features are typographic labels, not phonetic
    symbols). Exposed for the same reason as
    :py:func:`canonicalize_segment_label`.
    """
    return _canonicalize_name(label)


def _ipa_confusable_notes(canonical_seg: str) -> list[str]:
    """Return advisory notes for IPA-confusable characters in the
    segment label. Never an error; surfaces likely paste mistakes.

    Scope is deliberately narrow. The wider curated set (g/ɡ, '/ʼ,
    r/ɹ) produces false positives on bundled inventories (Hayes and
    Blevins use literal 'g' in 'g͡b'; the General inventory uses ASCII
    apostrophe for ejectives; 'r' is a legitimate IPA segment). ASCII
    colon is the one hazard with no realistic legitimate use in an
    IPA segment label.
    """
    notes: list[str] = []
    if ":" in canonical_seg:
        notes.append(
            f"segment {canonical_seg!r} contains U+003A COLON; if you "
            f"intended the IPA length mark, the canonical code point is "
            f"U+02D0 MODIFIER LETTER TRIANGULAR COLON (ː)"
        )
    return notes


@lru_cache(maxsize=4096)
def _canonicalize_name(s: str) -> str:
    """Apply the name-identity canonicalization (NFC, then strip).

    NFC (not NFKC) is deliberate: NFC merges canonical equivalents
    that look identical (precomposed vs combining), while NFKC also
    folds compatibility variants that may carry phonetic or
    orthographic meaning (ligatures, half-width forms).

    :py:meth:`str.strip` is Unicode-aware for whitespace (NBSP, NNBSP,
    and so on) but does not strip Unicode FORMAT characters (ZWJ, ZWNJ,
    LRM, RLM, BOM). Those survive canonicalization and create truly
    invisible distinct keys, so they are rejected separately via
    :py:func:`_disallowed_format_chars` rather than silently stripped.

    LRU-cached because PHOIBLE materialization fires this 540k+ times
    across 200 inventories on a working set of ~50 distinct feature
    names per inventory (the segment + feature names are reused
    cross-inventory). Pure function of ``s``; safe to cache.
    """
    return unicodedata.normalize("NFC", s).strip()


# Unicode general categories rejected inside canonical names.
#
#   Cf: FORMAT (ZWJ, ZWNJ, LRM, RLM, BOM). Invisible, survive NFC +
#       strip, produce distinct keys that look identical.
#   Cs: SURROGATE (lone halves like U+DCFF). NFC accepts them, but
#       ``str.encode('utf-8')`` raises "surrogates not allowed", so
#       the inventory loads and every save fails (save lockout).
#       Rejected at parse so the user never reaches that state.
#   Cc: CONTROL (NUL, BEL, CR, LF, TAB inside a name). ``strip`` only
#       removes Cc at the edges, not the interior. Hand-edited JSON
#       can embed them, producing odd rendering in grids, validation
#       reports, and logs.
_DISALLOWED_NAME_CATEGORIES: frozenset[str] = frozenset({"Cf", "Cs", "Cc"})


def _disallowed_format_chars(s: str) -> list[str]:
    """Return any disallowed-category characters in ``s``, formatted
    as "U+XXXX (NAME)" so the caller can include them in a user-facing
    error message. Empty when the string is clean.
    """
    found: list[str] = []
    for ch in s:
        if unicodedata.category(ch) in _DISALLOWED_NAME_CATEGORIES:
            try:
                cp_name = unicodedata.name(ch)
            except ValueError:
                cp_name = "UNNAMED"
            found.append(f"U+{ord(ch):04X} ({cp_name})")
    return found


class _DuplicateJSONKey(ValueError):
    """Raised by :py:func:`_no_duplicate_keys` when ``json.load`` sees
    the same key twice in one object literal. The default dict-merge
    silently keeps the last value, which would lose user data without
    warning. Caught at the :py:meth:`Inventory.load` boundary and
    rewrapped as :py:class:`ValidationError`.
    """

    def __init__(self, keys: list[str]) -> None:
        self.keys = keys
        super().__init__(
            f"duplicate JSON key(s), earlier value would be silently "
            f"discarded: {sorted(set(keys))!r}"
        )


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """``object_pairs_hook`` for :py:func:`json.load` that rejects
    duplicate keys. Fires at decode time, because once json.load
    returns a dict the evidence is gone.
    """
    seen: dict[str, Any] = {}
    duplicates: list[str] = []
    for k, v in pairs:
        if k in seen:
            duplicates.append(k)
        seen[k] = v
    if duplicates:
        raise _DuplicateJSONKey(duplicates)
    return seen


class _NonFiniteJSONValue(ValueError):
    """Raised by :py:func:`_reject_non_finite` when ``json.load`` sees
    ``NaN`` / ``Infinity`` / ``-Infinity``. Inventory feature values
    are strings (``"+"`` / ``"-"`` / ``"0"``), never numeric, so a
    non-finite literal in user-supplied JSON is always malformed
    input. Caught at the :py:meth:`Inventory.load` boundary and
    rewrapped as :py:class:`ValidationError` so the error UX is the
    same as any other parse failure.
    """

    def __init__(self, token: str) -> None:
        self.token = token
        super().__init__(
            f"non-finite JSON numeric literal {token!r}; inventory "
            f"feature values must be strings"
        )


def _reject_non_finite(token: str) -> float:
    """``parse_constant`` hook for :py:func:`json.load`.

    The default ``parse_constant`` is :py:func:`float`, which
    happily accepts ``NaN`` and ``+/-Infinity``. Those would flow
    into :py:meth:`Inventory.parse` and either crash an isinstance
    check or, worse, silently propagate as ``float('nan')`` through
    feature comparisons (where ``nan != nan`` breaks set semantics).
    Reject them at decode time so the error attaches to the file
    path the user gave us.
    """
    raise _NonFiniteJSONValue(token)


def parse_inventory_json_text(text: str, source: str) -> Any:
    """Decode inventory JSON text with the canonical safety guards.

    Single entry-point so the desktop file loader
    (:py:meth:`Inventory.load`) and the web upload bridge both
    enforce the same contract: duplicate keys are rejected
    (silent merge would lose user data), ``NaN`` / ``Infinity``
    literals are rejected (non-finite floats break feature-set
    semantics), and JSON syntax errors come back as
    :py:class:`ValidationError` with a user-facing line number so
    the UI surfacing path is the same on both frontends.

    ``source`` is prepended to every issue message so the user can
    tell which file (or which upload) the error came from. Returns
    the parsed JSON object on success; callers still pass it
    through :py:meth:`Inventory.parse` for schema validation.
    """
    try:
        return json.loads(
            text,
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except _DuplicateJSONKey as e:
        raise ValidationError((f"{source}: {e}",)) from e
    except _NonFiniteJSONValue as e:
        raise ValidationError((f"{source}: {e}",)) from e
    except json.JSONDecodeError as e:
        raise ValidationError(
            (f"{source}: invalid JSON ({e.msg} on line {e.lineno})",)
        ) from e


# On-disk format version. Bumped when the shape changes in a way old
# readers cannot understand. Files written by this version always
# include ``schema_version`` at the top level. Files written before
# the field existed omit it; reads treat the absence as
# ``CURRENT_SCHEMA_VERSION`` so existing files load without migration.
# When adding version 2, keep version 1 in
# ``SUPPORTED_SCHEMA_VERSIONS`` until at least one release has shipped
# the migration path, then drop it.
CURRENT_SCHEMA_VERSION: int = 1
SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1})


class ValidationError(Exception):
    """Raised by :py:meth:`Inventory.parse` when the input is not a
    valid inventory. Carries every problem found so a GUI can show
    them all at once.

    Two shapes coexist for back-compat. ``validation_issues`` is the
    structural source of truth: a tuple of :py:class:`ValidationIssue`
    records, each with a stable :py:attr:`~ValidationIssue.code`,
    JSON path, and human-facing message. ``issues`` is the legacy
    derived tuple of messages-only; existing UI code that reads
    ``err.issues[0]`` keeps working. ``str(err)`` is the first
    message, useful for status bars.

    Constructors accept either:
      * a ``tuple[ValidationIssue, ...]`` (preferred);
      * a ``tuple[str, ...]`` of plain messages (legacy / JSON
        decoder shortcuts), which is wrapped as
        :py:class:`ValidationIssue` records with an empty code and
        path so downstream code can still read
        ``validation_issues``.
    """

    def __init__(
        self,
        issues: tuple[str, ...] | tuple[ValidationIssue, ...],
    ) -> None:
        if not issues:
            issues = ("Invalid inventory (no issue detail)",)
        structured: tuple[ValidationIssue, ...]
        first = issues[0]
        if isinstance(first, ValidationIssue):
            # mypy cannot narrow the whole tuple from a peek at
            # ``issues[0]``; the runtime callers that pass a
            # ValidationIssue at index 0 always pass them at every
            # index, so this cast is sound.
            structured = tuple(issues)  # type: ignore[arg-type]
        else:
            structured = tuple(
                ValidationIssue(code="", path=(), message=str(msg))
                for msg in issues
            )
        self.validation_issues: tuple[ValidationIssue, ...] = structured
        self.issues: tuple[str, ...] = tuple(vi.message for vi in structured)
        super().__init__(self.issues[0])


@dataclass(frozen=True, slots=True)
class Inventory:
    """A validated phonological inventory.

    Fields:

    * ``name``: human-readable display name, never empty.
    * ``metadata``: arbitrary metadata mapping (read-only view).
    * ``features``: declared feature names in their declared order;
      non-empty strings, unique.
    * ``segments``: ``{symbol: {feature: value}}``. Symbols are
      non-empty strings, feature keys are a subset of ``features``,
      values are in :py:data:`VALID_VALUES`. Inner maps are read-only
      views.
    * ``advisories``: soft observations collected by the parser. Not
      errors; surfaced in the status bar so the user knows when an
      inventory is outside the usual operating range.

    Missing-feature semantics: a segment bundle may omit a declared
    feature; readers treat the omission as ``"0"``. The parser does
    not auto-fill the omission because round-tripping should not
    silently inflate the on-disk file.
    """

    name: str
    metadata: Mapping[str, Any]
    features: tuple[str, ...]
    segments: Mapping[str, Mapping[str, str]]
    advisories: tuple[str, ...] = field(default=())

    @classmethod
    def parse(cls, raw: Any, *, source: str | None = None) -> Inventory:
        """Validate raw (already JSON-decoded) data into an Inventory.

        Collects every issue before raising so the caller can show
        them all. ``source`` is included in error messages when
        given, typically a file path, to disambiguate when the GUI
        is loading multiple inventories.

        Pipeline lives in :py:mod:`phonology_shared.data._parse`
        (lazy-imported here to break the import cycle: ``_parse``
        imports the helpers from this module at its top level, so
        deferring the import until first call keeps both modules
        load-time clean). See :py:func:`._parse.run_parse` for the
        four-phase orchestration.
        """
        from phonology_shared.data._parse import run_parse

        return run_parse(cls, raw, source=source)

    @classmethod
    def from_grid(
        cls,
        *,
        name: str,
        features: list[str],
        segments: dict[str, dict[str, str]],
        metadata: Mapping[str, Any] | None = None,
    ) -> Inventory:
        """Construct from builder grid state.

        Validates by funneling through :py:meth:`parse` so there is
        exactly one validation code path. ASCII-minus normalization
        (Unicode ``−`` to ``-``) happens here because the grid stores
        the Unicode form for display.

        ``metadata`` carries provenance the caller wants stamped on
        the resulting inventory (for example, the feature-provider
        name and version when the grid was bootstrapped from
        PanPhon). The keys are merged ALONGSIDE ``name``; if a
        caller passes ``"name"`` in ``metadata`` it is ignored in
        favour of the explicit ``name`` argument so there is one
        source of truth for the inventory's display name.
        """
        normalized_segments: dict[str, dict[str, str]] = {}
        for seg, feats in segments.items():
            normalized: dict[str, str] = {}
            for f, v in feats.items():
                if v == "−":
                    v = "-"
                normalized[f] = v
            normalized_segments[seg] = normalized
        meta_dict: dict[str, Any] = {"name": name}
        if metadata:
            for key, value in metadata.items():
                if key == "name":
                    continue
                meta_dict[key] = value
        return cls.parse(
            {
                "metadata": meta_dict,
                "features": features,
                "segments": normalized_segments,
            }
        )

    @classmethod
    def load(cls, path: str) -> Inventory:
        """Read and parse a JSON inventory file.

        Raises :py:class:`ValidationError` (with ``source=path`` in
        messages) on any problem. :py:class:`OSError`,
        :py:class:`UnicodeDecodeError`, and
        :py:class:`json.JSONDecodeError` are wrapped as ValidationError
        so callers only need one exception type.
        """
        basename = os.path.basename(path)
        _log.debug("inventory load start: %s", basename)
        # Cap before opening: refuse comically large files instead of
        # letting json.load allocate gigabytes trying to parse them.
        # getsize raises FileNotFoundError if the path is missing; let
        # the open() below produce the canonical error.
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        if size > MAX_INVENTORY_FILE_BYTES:
            limit_mb = MAX_INVENTORY_FILE_BYTES // (1024 * 1024)
            _log.warning(
                "inventory load failed: %s: file too large (%d bytes > %d)",
                basename,
                size,
                MAX_INVENTORY_FILE_BYTES,
            )
            raise ValidationError(
                (
                    f"{path}: file is {size // (1024 * 1024)} MB, "
                    f"larger than the {limit_mb} MB limit",
                )
            )
        try:
            # ``utf-8-sig`` transparently consumes a leading UTF-8 BOM.
            # Notepad, Excel, and many other Windows tools add one;
            # plain utf-8 would raise a cryptic "Unexpected UTF-8 BOM"
            # that tells a linguist nothing actionable. The codec
            # behaves identically to utf-8 for files without a BOM.
            with open(path, encoding="utf-8-sig") as f:
                text = f.read()
        except FileNotFoundError as e:
            _log.warning("inventory load failed: %s: file not found", basename)
            raise ValidationError((f"{path}: file not found",)) from e
        except UnicodeDecodeError as e:
            # UnicodeDecodeError subclasses ValueError, not OSError,
            # so without this clause it would escape raw and break
            # the ValidationError-only contract GUI callers rely on.
            _log.warning(
                "inventory load failed: %s: not valid UTF-8 (%s)",
                basename,
                e,
            )
            raise ValidationError(
                (
                    f"{path}: file is not UTF-8 encoded; "
                    f"re-save it as UTF-8 and load it again",
                )
            ) from e
        except OSError as e:
            _log.warning("inventory load failed: %s: %s", basename, e)
            raise ValidationError((f"{path}: {e}",)) from e
        # All JSON-level guards (duplicate keys, non-finite literals,
        # syntax errors) flow through one helper so the desktop
        # loader and the web upload bridge enforce the same contract.
        try:
            raw = parse_inventory_json_text(text, path)
        except ValidationError as e:
            # ValidationError already carries the path; log a one-line
            # summary at WARNING for ops while preserving the
            # exception for the GUI caller.
            _log.warning(
                "inventory load failed: %s: %s", basename, e.issues[0]
            )
            raise
        try:
            inv = cls.parse(raw, source=path)
        except ValidationError as e:
            _log.warning(
                "inventory validation failed: %s (%d issue%s)",
                basename,
                len(e.issues),
                "" if len(e.issues) == 1 else "s",
            )
            raise
        _log.info(
            "inventory loaded: %s (%d segments, %d features)",
            basename,
            len(inv.segments),
            len(inv.features),
        )
        return inv

    def to_json_dict(self) -> dict[str, Any]:
        """Plain dict suitable for :py:func:`json.dump`.

        Inner views are unwrapped to dicts because :py:func:`json.dump`
        does not know about :py:class:`MappingProxyType`. Stored
        values are :py:class:`FeatureValue` instances; converting
        with ``str(v)`` writes the underlying ``"+"`` / ``"-"`` /
        ``"0"`` string so the on-disk JSON is byte-identical to
        pre-FeatureValue files (StrEnum's ``__str__`` returns the
        value).
        ``schema_version`` is the first key by convention so tooling
        that inspects without parsing (jq, grep, future migrators) can
        find it without walking the whole file.
        """
        return {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "metadata": dict(self.metadata),
            "features": list(self.features),
            "segments": {
                seg: {feat: str(val) for feat, val in feats.items()}
                for seg, feats in self.segments.items()
            },
        }

    def write_atomic(self, path: str | os.PathLike[str]) -> None:
        """Crash-safe write via :py:func:`atomic_write_json`.

        Serializes to a sibling tmp file, fsyncs, then ``os.replace``s
        onto the target. An interrupted run leaves either the old file
        untouched or the new file fully written, never a half-written
        file. See :py:func:`atomic_write_json` for the platform-
        specific details (directory fsync is POSIX-only).
        """
        atomic_write_json(path, self.to_json_dict())

    def feature_value(self, segment: str, feature: str) -> FeatureValue:
        """Value of ``feature`` for ``segment``; ``FeatureValue.ZERO``
        if missing.

        Returns a :py:class:`FeatureValue` so engine code can switch
        on a typed enum. StrEnum members compare equal to their
        string value (``FeatureValue.PLUS == "+"``), so existing call
        sites that do ``value == "+"`` still work.

        Raises :py:class:`KeyError` for unknown segment or feature.
        """
        if segment not in self.segments:
            raise KeyError(f"Segment '{segment}' not in inventory")
        if feature not in self.features:
            raise KeyError(f"Feature '{feature}' not in inventory")
        # Bundles carry FeatureValue by the parse invariant
        # (parse/from_grid are the only producers). The enum call is
        # an identity lookup for members; it narrows the declared
        # ``Mapping[str, str]`` field type to the typed enum.
        return FeatureValue(self.segments[segment].get(feature, "0"))


def atomic_write_json(path: str | os.PathLike[str], data: Any) -> None:
    """Write JSON to ``path`` using a temporary file and atomic replace.

    The JSON is serialized to a string FIRST (so a serialization
    error fires before any temp file is created), then written to a
    sibling temporary file in the same directory, flushed, and
    fsynced; finally :func:`os.replace` swaps the destination
    atomically. A failed write leaves the previous destination file
    untouched instead of truncating it.

    ``allow_nan=False`` is passed to :func:`json.dumps` because the
    read path
    (:py:func:`parse_inventory_json_text`) already rejects ``NaN`` /
    ``Infinity`` literals; the write path must match so a future
    caller cannot silently emit a non-standard JSON file that this
    library then refuses to load. ``json.dumps`` raises
    :py:class:`ValueError` for non-finite floats in that mode; the
    error surfaces with no FS side effects.

    On POSIX, the parent directory is fsynced after the replace on
    a best-effort basis so the rename itself is more durable across
    crashes. Directory fsync is skipped when unsupported.
    """
    path = os.fspath(path)
    basename = os.path.basename(path)
    _log.debug("atomic write start: %s", basename)

    # Pre-encode so any serialization error (allow_nan=False,
    # unsupported value type, etc.) raises BEFORE the temp file is
    # created. The size of the rendered text is also known in
    # advance, which is occasionally useful for diagnostics.
    rendered = (
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )

    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(
        prefix=".tmp_inv_", suffix=".json", dir=directory
    )

    success = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(rendered)
            f.flush()
            os.fsync(f.fileno())

        # mkstemp creates the temp file owner-only (0600), and
        # os.replace transplants that mode onto the destination.
        # Without this chmod every save would silently strip
        # group/other permissions from the user's file. Preserve an
        # existing destination's mode; for a brand-new file apply
        # the process umask to the conventional 0o666.
        try:
            mode = stat.S_IMODE(os.stat(path).st_mode)
        except FileNotFoundError:
            umask = os.umask(0)
            os.umask(umask)
            mode = 0o666 & ~umask
        os.chmod(tmp_path, mode)

        os.replace(tmp_path, path)
        _fsync_directory_best_effort(directory)
        success = True
    finally:
        # ``finally`` rather than ``except BaseException`` so the
        # temp file is removed on KeyboardInterrupt / SystemExit
        # without those non-error signals being silently logged
        # as "atomic write failed". The success flag distinguishes
        # the clean path (nothing to remove; tmp_path was renamed
        # by os.replace) from the failure path (tmp_path may still
        # exist and would otherwise leak into the directory).
        if not success:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    _log.info("atomic write complete: %s", basename)


def _fsync_directory_best_effort(directory: str) -> None:
    """Best-effort directory fsync for POSIX rename durability."""
    if os.name == "nt":
        return

    try:
        dir_fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return

    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)
