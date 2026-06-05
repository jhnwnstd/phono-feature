"""The Inventory contract.

This module validates inventory STRUCTURE, not phonological theory.
It enforces JSON shape, stable identifiers, declared feature keys,
allowed cell values (``+`` / ``-`` / ``0``), Unicode safety, size
limits, and crash-safe writes. It does not infer feature values
from segment labels and does not reject feature bundles for being
phonologically unusual. Segment labels are identifiers; feature
values are the semantics.

One source of truth for the question "is this inventory data
structurally valid". Every loader, editor, and saver routes
through this module. The only entry points that accept untrusted
data are :py:meth:`Inventory.parse`, :py:meth:`Inventory.from_grid`,
and :py:meth:`Inventory.load`, and each funnels through ``parse``
so the validation code path is singular.

Parse-don't-validate: ``parse`` either returns a fully normalized
:py:class:`Inventory` whose invariants hold for the life of the value,
or raises :py:class:`ValidationError` carrying every problem it found
(not just the first). Downstream code never re-checks.

The instance is structurally immutable: ``features`` is a tuple and
``segments`` is a :py:class:`MappingProxyType` of MappingProxyType.
Holders may store the value directly without a defensive copy because
the caller cannot mutate it after construction. Edits produce a new
``Inventory``.

Writes go through :py:func:`atomic_write_json`, which writes to a tmp
file and ``os.replace``s onto the target so a crash mid-write never
leaves a truncated JSON on disk.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from types import MappingProxyType
from typing import Any

from phonology_shared.data.limits import (
    ADVISORY_FEATURE_THRESHOLD,
    ADVISORY_SEGMENT_THRESHOLD,
    MAX_FEATURES,
    MAX_FILE_BYTES,
    MAX_NAME_LENGTH,
    MAX_SEGMENTS,
)

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

    Hayes (2009) treats ``"0"`` as a deliberate "don't care" value
    distinct from a missing key; see :py:class:`FeatureState` in
    :py:mod:`phonology_shared.chart.vowels` for the four-state model
    that distinguishes them.
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

    Lowercases, collapses delimiters (``.``, ``_``, ``-``, space) to
    empty, and rewrites a small set of common multi-word aliases so
    engine consumers (matching, grouping, alias-collision detection at
    parse time) see one operational identity for variants like
    ``"DelRel"`` / ``"delayed_release"`` / ``"del.rel."``,
    ``"r-colored"`` / ``"rhotacized"`` / ``"rhotic"``, or
    ``"breathy voice"`` / ``"breathy"``. Memoized because the same
    handful of names recur for every segment and every reload.

    Lives in :py:mod:`inventory` so :py:meth:`Inventory.parse` can
    detect alias collisions at the boundary without depending on
    the display layer; :py:mod:`segment_grouper` re-imports it for
    its own bundle normalisation.
    """
    k = key.lower()
    k = k.replace("del.rel.", "delrel")
    k = k.replace("delayed_release", "delrel")
    k = k.replace("s.g.", "spreadgl")
    k = k.replace("c.g.", "constrgl")
    k = k.replace(".", "").replace("_", "").replace(" ", "").replace("-", "")
    if k in ("rcolored", "rcoloured", "rhotacized"):
        return "rhotic"
    if k == "breathyvoice":
        return "breathy"
    if k == "creakyvoice":
        return "creaky"
    return k


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
    result: dict[str, str] = {}
    collisions: dict[str, list[str]] = {}
    for k, v in feat_dict.items():
        canonical = normalize_feature_key(k)
        if canonical in result and k not in collisions.get(canonical, ()):
            collisions.setdefault(canonical, []).append(
                _find_existing_alias(feat_dict, result, canonical, exclude=k)
            )
            collisions[canonical].append(k)
        result[canonical] = v
    if collisions:
        raise AliasCollisionError(collisions)
    return result


def _find_existing_alias(
    feat_dict: Mapping[str, str],
    result: Mapping[str, str],
    canonical: str,
    *,
    exclude: str,
) -> str:
    """Recover the original key that produced ``canonical`` (other
    than ``exclude``). Used to build a helpful collision report."""
    for k in feat_dict:
        if k == exclude:
            continue
        if normalize_feature_key(k) == canonical:
            return k
    # Unreachable when called from the collision path.
    return canonical


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
    :py:func:`_invisible_format_chars` rather than silently stripped.
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


def _invisible_format_chars(s: str) -> list[str]:
    """Return any disallowed-category characters in ``s``, formatted
    as "U+XXXX (NAME)" so the caller can include them in a user-facing
    error message. Empty when the string is clean.

    The function name predates the broader scope (it now also catches
    surrogates and embedded controls) but is preserved for clarity at
    call sites.
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
class _RawInventory:
    """Top-level shape after the decode-and-classify phase.

    Fields are still loosely typed (``Any`` for individual feature
    entries and segment bundles) because the per-field validators
    consume them next. The phase boundary exists to (a) guarantee
    every downstream phase sees a real dict at the top level and a
    real list/dict for the two big slots, and (b) cache the
    schema-version + extras split so it isn't recomputed.
    """

    schema_version: int
    metadata: Mapping[str, Any]
    features: list[Any] | None
    segments: Mapping[Any, Any] | None
    explicit_metadata: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class _FeatureTable:
    """Result of the feature-list validation phase.

    Bundle validation reads this instead of a raw ``set[str]`` so it
    can fold bundle keys onto the declared canonical names via
    :py:attr:`normalized_to_canonical` (the alias-aware match). When
    a bundle uses ``"r-colored"`` against a declared ``"Rhotic"``,
    both normalize to ``"rhotic"``; the bundle key folds onto
    ``"Rhotic"`` in the stored bundle.
    """

    names: tuple[str, ...]
    declared: frozenset[str]
    normalized_to_canonical: Mapping[str, str]


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
    * ``feature_index`` / ``segment_index``: derived
      :py:class:`MappingProxyType` lookups built during parse so
      engine code can resolve a feature or segment to its position
      in O(1) instead of scanning the tuple. Read-only; the parse
      pipeline is the only writer.

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
    feature_index: Mapping[str, int] = field(
        default_factory=lambda: MappingProxyType({})
    )
    segment_index: Mapping[str, int] = field(
        default_factory=lambda: MappingProxyType({})
    )

    @classmethod
    def parse(cls, raw: Any, *, source: str | None = None) -> Inventory:
        """Validate raw (already JSON-decoded) data into an Inventory.

        Collects every issue before raising so the caller can show
        them all. ``source`` is included in error messages when given,
        typically a file path, to disambiguate when the GUI is loading
        multiple inventories.

        Pipeline (every phase is pure; the
        :py:class:`_ValidationContext` is the only mutable state):

          1. ``_decode_top_level`` -> :py:class:`_RawInventory`.
             Top-level shape, schema_version, presence of the two
             required keys. Fatal failures raise immediately because
             every later check would be meaningless.
          2. ``_validate_features`` -> :py:class:`_FeatureTable`.
             Declared feature names + alias-aware lookup map.
          3. ``_validate_segments`` -> mapping of canonical labels
             to validated bundles. Bundle feature keys are folded
             onto the declared canonical names via the
             :py:class:`_FeatureTable`.
          4. ``_assemble_inventory`` -> the final
             :py:class:`Inventory` (metadata, name, advisories,
             derived indexes).
        """
        ctx = _ValidationContext(source=source)
        raw_inv = _decode_top_level(raw, ctx)
        if raw_inv is None:
            raise ValidationError(tuple(ctx.issues))

        feature_table = (
            _validate_features(raw_inv.features, ctx)
            if raw_inv.features is not None
            else _FeatureTable(
                names=(), declared=frozenset(), normalized_to_canonical={}
            )
        )
        segments_view = (
            _validate_segments(raw_inv.segments, feature_table, ctx)
            if raw_inv.segments is not None
            else MappingProxyType({})
        )

        if ctx.has_errors:
            raise ValidationError(tuple(ctx.issues))

        return _assemble_inventory(cls, raw_inv, feature_table, segments_view)

    @classmethod
    def from_grid(
        cls,
        *,
        name: str,
        features: list[str],
        segments: dict[str, dict[str, str]],
    ) -> Inventory:
        """Construct from builder grid state.

        Validates by funneling through :py:meth:`parse` so there is
        exactly one validation code path. ASCII-minus normalization
        (Unicode ``−`` to ``-``) happens here because the grid stores
        the Unicode form for display.
        """
        normalized_segments: dict[str, dict[str, str]] = {}
        for seg, feats in segments.items():
            normalized: dict[str, str] = {}
            for f, v in feats.items():
                if v == "−":
                    v = "-"
                normalized[f] = v
            normalized_segments[seg] = normalized
        return cls.parse(
            {
                "metadata": {"name": name},
                "features": features,
                "segments": normalized_segments,
            }
        )

    @classmethod
    def load(cls, path: str) -> Inventory:
        """Read and parse a JSON inventory file.

        Raises :py:class:`ValidationError` (with ``source=path`` in
        messages) on any problem. :py:class:`OSError` and
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
        if size > MAX_FILE_BYTES:
            _log.warning(
                "inventory load failed: %s: file too large (%d bytes > %d)",
                basename,
                size,
                MAX_FILE_BYTES,
            )
            raise ValidationError(
                (
                    f"{path}: file is {size // (1024 * 1024)} MB, "
                    f"larger than the {MAX_FILE_BYTES // (1024 * 1024)} MB limit",
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
        file. External file watchers see one atomic rename rather than
        a series of partial writes.
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
        raw = self.segments[segment].get(feature, FeatureValue.ZERO)
        # Defensive cast: inner bundles built by parse already carry
        # FeatureValue, but other producers (test fixtures, dict
        # round-trips through view_models) may still hand in raw
        # strings. Convert through the enum so the return type is
        # honest.
        return raw if isinstance(raw, FeatureValue) else FeatureValue(raw)


def _validate_features(
    features_raw: Any, ctx: _ValidationContext
) -> _FeatureTable:
    """Return a :py:class:`_FeatureTable` describing the declared
    features. Issues are recorded on ``ctx``; the caller decides
    whether to raise once every phase has run.

    Names are stored in canonical form (NFC + stripped) so downstream
    lookups never see two spellings of the same intended identity.
    The returned :py:attr:`_FeatureTable.normalized_to_canonical`
    map lets bundle validation accept aliases (``r-colored`` for
    declared ``Rhotic``) by folding the bundle key onto the
    declared canonical name.
    """
    empty = _FeatureTable(
        names=(), declared=frozenset(), normalized_to_canonical={}
    )
    if not isinstance(features_raw, list):
        ctx.error(
            _IssueCodes.FEATURES_NOT_LIST,
            ("features",),
            f"'features' must be a list of strings, "
            f"got {type(features_raw).__name__}",
        )
        return empty

    if len(features_raw) > MAX_FEATURES:
        ctx.error(
            _IssueCodes.FEATURES_OVER_CAP,
            ("features",),
            f"'features' has {len(features_raw)} entries; "
            f"hard cap is {MAX_FEATURES}",
        )
        # Refuse to truncate. If the file is this far out of bounds,
        # it is almost certainly authored wrong, and per-feature noise
        # would drown the actionable message.
        return empty

    valid: list[str] = []
    seen: set[str] = set()
    # Original spelling per canonical name so a collision message can
    # show the user both forms.
    canonical_origin: dict[str, str] = {}
    for i, f in enumerate(features_raw):
        path: tuple[str | int, ...] = ("features", i)
        if not isinstance(f, str):
            ctx.error(
                _IssueCodes.FEATURE_NOT_STRING,
                path,
                f"'features[{i}]' is not a string "
                f"(got {type(f).__name__}: {f!r})",
            )
            continue
        if len(f) > MAX_NAME_LENGTH:
            ctx.error(
                _IssueCodes.FEATURE_OVER_LENGTH,
                path,
                f"'features[{i}]' is {len(f)} chars; "
                f"max is {MAX_NAME_LENGTH}",
            )
            continue
        canonical = _canonicalize_name(f)
        if not canonical:
            ctx.error(
                _IssueCodes.FEATURE_EMPTY,
                path,
                f"'features[{i}]' is empty after canonicalization",
            )
            continue
        invisible = _invisible_format_chars(canonical)
        if invisible:
            ctx.error(
                _IssueCodes.FEATURE_INVISIBLE_CHAR,
                path,
                f"'features[{i}]' ({f!r}) contains invisible "
                f"format character(s): {invisible}; these have no use "
                f"in feature identifiers and would create distinct keys "
                f"that look identical",
            )
            continue
        if canonical in seen:
            prior = canonical_origin[canonical]
            if prior == f:
                ctx.error(
                    _IssueCodes.FEATURE_DUPLICATE,
                    path,
                    f"'features' contains duplicate {f!r}",
                )
            else:
                # Two distinct spellings collapsed to the same identity
                # (for example " Voice " vs "Voice", or NFC vs NFD of
                # "é").
                ctx.error(
                    _IssueCodes.FEATURE_CANONICAL_COLLISION,
                    path,
                    f"features {prior!r} and {f!r} are the same "
                    f"after canonicalization ({canonical!r}); "
                    f"rename or remove one",
                )
            continue
        seen.add(canonical)
        canonical_origin[canonical] = f
        valid.append(canonical)

    # Alias-collision check on :py:func:`normalize_feature_key`
    # (case and delimiter folding). "DelRel" and "delayed_release"
    # are distinct in canonical form (different case + underscores)
    # but engine consumers fold them. Catching at the parser
    # boundary means the engine never has to defend against
    # ``AliasCollisionError`` downstream.
    by_alias: dict[str, list[str]] = {}
    normalized_to_canonical: dict[str, str] = {}
    for f in valid:
        norm = normalize_feature_key(f)
        by_alias.setdefault(norm, []).append(f)
    for normalized, originals in by_alias.items():
        if len(originals) > 1:
            ctx.error(
                _IssueCodes.FEATURE_ALIAS_COLLISION,
                ("features",),
                f"features {sorted(originals)} collide after "
                f"normalization to {normalized!r}; rename or remove one",
            )
        else:
            # Only build the alias map when there is no collision;
            # the bundle-key alias-aware lookup would be ambiguous
            # otherwise, and the collision issue above already
            # tells the user to fix it.
            normalized_to_canonical[normalized] = originals[0]
    return _FeatureTable(
        names=tuple(valid),
        declared=frozenset(seen),
        normalized_to_canonical=MappingProxyType(normalized_to_canonical),
    )


def _canonicalize_segment_key(
    seg_name: Any,
    ctx: _ValidationContext,
) -> str | None:
    """Run the canonicalisation + invisible-character + length
    checks for one segment key. Returns the canonical key on
    success or ``None`` on failure (after recording the appropriate
    issue on ``ctx``). Splits the per-key checks out of
    :py:func:`_validate_segments` so each one is independently
    testable and the driver loop stays scannable.
    """
    path: tuple[str | int, ...] = ("segments", seg_name)
    if not isinstance(seg_name, str) or not seg_name:
        ctx.error(
            _IssueCodes.SEGMENT_KEY_TYPE,
            path,
            f"segment key {seg_name!r} must be a non-empty string",
        )
        return None
    if len(seg_name) > MAX_NAME_LENGTH:
        ctx.error(
            _IssueCodes.SEGMENT_KEY_OVER_LENGTH,
            path,
            f"segment key {seg_name!r} is {len(seg_name)} "
            f"chars; max is {MAX_NAME_LENGTH}",
        )
        return None
    canonical_seg = _canonicalize_name(seg_name)
    if not canonical_seg:
        ctx.error(
            _IssueCodes.SEGMENT_KEY_EMPTY,
            path,
            f"segment key {seg_name!r} is empty after canonicalization",
        )
        return None
    # Domain-specific identity folding (ASCII g->ɡ, '->ʼ) runs
    # AFTER NFC canonicalization but BEFORE the collision check so
    # an inventory containing both "g" and "ɡ" is detected as a
    # duplicate rather than silently kept as two distinct keys.
    canonical_seg = _ipa_normalize_segment(canonical_seg)
    invisible = _invisible_format_chars(canonical_seg)
    if invisible:
        ctx.error(
            _IssueCodes.SEGMENT_KEY_INVISIBLE_CHAR,
            path,
            f"segment key {seg_name!r} contains invisible "
            f"format character(s): {invisible}; these would create "
            f"a distinct segment that looks identical to another",
        )
        return None
    return canonical_seg


def _resolve_bundle_feature_key(
    raw_feature_name: str,
    canonical_seg: str,
    feature_table: _FeatureTable,
    ctx: _ValidationContext,
) -> str | None:
    """Resolve a bundle's raw feature key to a declared canonical
    feature name. Returns ``None`` (with an issue recorded) when the
    key does not match any declared feature, even after alias
    folding.

    Resolution order: (1) direct canonical match against the
    declared name (NFC+strip); (2) alias-aware match via
    :py:func:`normalize_feature_key` against
    :py:attr:`_FeatureTable.normalized_to_canonical`. Lifting case
    (2) is the bundle-side counterpart to the declared-feature
    alias rule: if both ``r-colored`` and ``Rhotic`` normalize to
    ``rhotic`` and only ``Rhotic`` is declared, the bundle key
    folds onto ``Rhotic`` so engine code and on-disk storage stay
    consistent.
    """
    canonical_feature = _canonicalize_name(raw_feature_name)
    if canonical_feature in feature_table.declared:
        return canonical_feature
    normalized = normalize_feature_key(raw_feature_name)
    aliased = feature_table.normalized_to_canonical.get(normalized)
    if aliased is not None:
        return aliased
    ctx.error(
        _IssueCodes.BUNDLE_FEATURE_NOT_DECLARED,
        ("segments", canonical_seg, raw_feature_name),
        f"segment {canonical_seg!r}: feature "
        f"{raw_feature_name!r} is not declared in 'features'",
    )
    return None


def _validate_segment_bundle(
    canonical_seg: str,
    seg_feats: Any,
    feature_table: _FeatureTable,
    ctx: _ValidationContext,
) -> Mapping[str, FeatureValue] | None:
    """Validate one segment's feature bundle.

    Returns a read-only mapping on success, or ``None`` when the bundle
    is not an object and the whole segment should be skipped.

    Invalid feature entries are reported and dropped. The caller later
    raises if any issues were collected, so the partial bundle exists
    only to keep collecting all validation errors in one pass.

    Bundle feature keys are resolved via
    :py:func:`_resolve_bundle_feature_key`, which accepts aliases
    that normalize to the same key as a declared feature (e.g.
    ``"r-colored"`` against a declared ``"Rhotic"``). The stored
    bundle key is always the declared canonical name.
    """
    bundle_path: tuple[str | int, ...] = ("segments", canonical_seg)
    if not isinstance(seg_feats, dict):
        ctx.error(
            _IssueCodes.BUNDLE_NOT_OBJECT,
            bundle_path,
            f"segment {canonical_seg!r}: bundle must be an "
            f"object, got {type(seg_feats).__name__}",
        )
        return None

    validated: dict[str, FeatureValue] = {}
    original_by_canonical: dict[str, str] = {}

    for raw_feature_name, raw_feature_value in seg_feats.items():
        key_path: tuple[str | int, ...] = (
            "segments",
            canonical_seg,
            raw_feature_name,
        )
        if not isinstance(raw_feature_name, str) or not raw_feature_name:
            ctx.error(
                _IssueCodes.BUNDLE_FEATURE_KEY_TYPE,
                key_path,
                f"segment {canonical_seg!r}: feature key "
                f"{raw_feature_name!r} must be a non-empty string",
            )
            continue

        if len(raw_feature_name) > MAX_NAME_LENGTH:
            ctx.error(
                _IssueCodes.BUNDLE_FEATURE_KEY_OVER_LENGTH,
                key_path,
                f"segment {canonical_seg!r}: feature key "
                f"{raw_feature_name!r} is {len(raw_feature_name)} chars; "
                f"max is {MAX_NAME_LENGTH}",
            )
            continue

        if not _canonicalize_name(raw_feature_name):
            ctx.error(
                _IssueCodes.BUNDLE_FEATURE_KEY_EMPTY,
                key_path,
                f"segment {canonical_seg!r}: feature key "
                f"{raw_feature_name!r} is empty after canonicalization",
            )
            continue

        canonical_feature = _resolve_bundle_feature_key(
            raw_feature_name, canonical_seg, feature_table, ctx
        )
        if canonical_feature is None:
            continue

        prior_feature_name = original_by_canonical.get(canonical_feature)
        if prior_feature_name is not None:
            ctx.error(
                _IssueCodes.BUNDLE_FEATURE_KEY_COLLISION,
                key_path,
                f"segment {canonical_seg!r}: feature keys "
                f"{prior_feature_name!r} and {raw_feature_name!r} resolve "
                f"to the same declared feature ({canonical_feature!r}); "
                f"rename or remove one",
            )
            continue

        original_by_canonical[canonical_feature] = raw_feature_name

        if not isinstance(raw_feature_value, str):
            ctx.error(
                _IssueCodes.BUNDLE_VALUE_TYPE,
                key_path,
                f"segment {canonical_seg!r}."
                f"{canonical_feature!r}: value must be a string, got "
                f"{type(raw_feature_value).__name__} ({raw_feature_value!r})",
            )
            continue

        try:
            typed_value = FeatureValue(raw_feature_value)
        except ValueError:
            ctx.error(
                _IssueCodes.BUNDLE_VALUE_INVALID,
                key_path,
                f"segment {canonical_seg!r}."
                f"{canonical_feature!r}: invalid value {raw_feature_value!r} "
                f"(expected one of {sorted(str(v) for v in VALID_VALUES)})",
            )
            continue

        validated[canonical_feature] = typed_value

    return MappingProxyType(validated)


def _validate_segments(
    segments_raw: Any,
    feature_table: _FeatureTable,
    ctx: _ValidationContext,
) -> Mapping[str, Mapping[str, FeatureValue]]:
    """Return a read-only mapping of validated segment labels to bundles.

    Segment labels are treated as arbitrary identifiers. This function
    canonicalizes labels only for stable identity, checks for collisions,
    and validates each segment's feature bundle against the declared
    feature table via alias-aware key resolution.
    """
    if not isinstance(segments_raw, dict):
        ctx.error(
            _IssueCodes.SEGMENTS_NOT_OBJECT,
            ("segments",),
            f"'segments' must be an object, "
            f"got {type(segments_raw).__name__}",
        )
        return MappingProxyType({})

    if len(segments_raw) > MAX_SEGMENTS:
        ctx.error(
            _IssueCodes.SEGMENTS_OVER_CAP,
            ("segments",),
            f"'segments' has {len(segments_raw)} entries; "
            f"hard cap is {MAX_SEGMENTS}",
        )
        return MappingProxyType({})

    validated_segments: dict[str, Mapping[str, FeatureValue]] = {}
    original_by_canonical: dict[str, str] = {}

    for raw_segment_label, raw_feature_bundle in segments_raw.items():
        canonical_segment = _canonicalize_segment_key(raw_segment_label, ctx)
        if canonical_segment is None:
            continue

        prior_label = original_by_canonical.get(canonical_segment)
        if prior_label is not None:
            ctx.error(
                _IssueCodes.SEGMENT_KEY_COLLISION,
                ("segments", raw_segment_label),
                f"segments {prior_label!r} and "
                f"{raw_segment_label!r} are the same after "
                f"canonicalization ({canonical_segment!r}); "
                f"rename or remove one",
            )
            continue

        validated_bundle = _validate_segment_bundle(
            canonical_segment, raw_feature_bundle, feature_table, ctx
        )
        if validated_bundle is None:
            continue

        validated_segments[canonical_segment] = validated_bundle
        original_by_canonical[canonical_segment] = raw_segment_label

    return MappingProxyType(validated_segments)


def _decode_top_level(
    raw: Any, ctx: _ValidationContext
) -> _RawInventory | None:
    """Top-level shape + schema-version phase.

    Returns ``None`` on a fatal shape failure (so the caller can
    raise immediately; downstream phases would have nothing to
    validate). Successful return guarantees a real dict at the top
    and a validated :py:attr:`_RawInventory.schema_version`.
    Missing or wrong ``features`` / ``segments`` keys are recorded
    as issues but the per-key validators still run on whatever was
    provided, so the user sees every problem in one pass.
    """
    if not isinstance(raw, dict):
        ctx.error(
            _IssueCodes.TOP_LEVEL_NOT_OBJECT,
            (),
            f"top-level JSON value must be an object, "
            f"got {type(raw).__name__}",
        )
        return None

    # Schema version is checked before per-field validation: if we
    # cannot read the format, every subsequent issue is meaningless.
    # Missing is treated as version 1 so files written before this
    # field existed load without migration.
    schema_version = CURRENT_SCHEMA_VERSION
    if "schema_version" in raw:
        sv = raw["schema_version"]
        # bool is a subclass of int; reject it explicitly so True
        # and False cannot sneak through as "schema_version 1".
        if isinstance(sv, bool) or not isinstance(sv, int):
            ctx.error(
                _IssueCodes.SCHEMA_VERSION_TYPE,
                ("schema_version",),
                f"'schema_version' must be an integer, "
                f"got {type(sv).__name__}",
            )
            return None
        if sv not in SUPPORTED_SCHEMA_VERSIONS:
            supported = ", ".join(
                str(v) for v in sorted(SUPPORTED_SCHEMA_VERSIONS)
            )
            ctx.error(
                _IssueCodes.SCHEMA_VERSION_UNSUPPORTED,
                ("schema_version",),
                f"unsupported schema_version {sv}; "
                f"this build reads version(s) {supported}",
            )
            return None
        schema_version = sv

    features_raw: list[Any] | None
    if "features" not in raw:
        ctx.error(
            _IssueCodes.MISSING_FEATURES,
            ("features",),
            "missing required key 'features'",
        )
        features_raw = None
    else:
        features_raw = raw["features"]

    segments_raw: Mapping[Any, Any] | None
    if "segments" not in raw:
        ctx.error(
            _IssueCodes.MISSING_SEGMENTS,
            ("segments",),
            "missing required key 'segments'",
        )
        segments_raw = None
    else:
        segments_raw = raw["segments"]

    explicit_metadata = raw.get("metadata")
    explicit_metadata_view: Mapping[str, Any] | None = (
        MappingProxyType(dict(explicit_metadata))
        if isinstance(explicit_metadata, dict)
        else None
    )

    return _RawInventory(
        schema_version=schema_version,
        metadata=MappingProxyType(dict(raw)),
        features=features_raw,
        segments=segments_raw,
        explicit_metadata=explicit_metadata_view,
    )


def _assemble_inventory(
    cls: type[Inventory],
    raw_inv: _RawInventory,
    feature_table: _FeatureTable,
    segments_view: Mapping[str, Mapping[str, FeatureValue]],
) -> Inventory:
    """Final phase: collect metadata, canonicalise the inventory
    name, gather advisories, build derived indexes, return the
    immutable :py:class:`Inventory`.

    Runs only after both per-field validators have completed
    without errors (the caller already raised
    :py:class:`ValidationError` on issues).
    """
    # Collect metadata from both conventions: top-level extras (the
    # general_features shape) AND an explicit ``metadata`` object
    # (the Hayes shape). The explicit object wins on key collision
    # so callers can override.
    metadata: dict[str, Any] = {}
    for key, value in raw_inv.metadata.items():
        # ``schema_version`` lives at the top level for tooling
        # visibility; never duplicate it into metadata or it would
        # round-trip into two places on save.
        if key in ("features", "segments", "metadata", "schema_version"):
            continue
        metadata[key] = value
    if raw_inv.explicit_metadata is not None:
        metadata.update(raw_inv.explicit_metadata)

    # Inventory name is a display label, not a key, so policy is
    # lighter than segment/feature names: canonicalize and cap, but
    # skip the alias/collision/invisible-char checks. Length cap
    # protects the title bar and meta strip from a pasted paragraph.
    raw_name = metadata.get("name")
    canonical_name = (
        _canonicalize_name(raw_name) if isinstance(raw_name, str) else ""
    )
    if not canonical_name:
        canonical_name = "Untitled Inventory"
    if len(canonical_name) > MAX_NAME_LENGTH:
        canonical_name = canonical_name[:MAX_NAME_LENGTH]
    # Ensure name round-trips even when input had none, and that
    # on-disk metadata reflects the canonical form.
    metadata["name"] = canonical_name

    advisories: list[str] = []
    if len(segments_view) > ADVISORY_SEGMENT_THRESHOLD:
        advisories.append(
            f"unusually large inventory: {len(segments_view)} segments "
            f"(typical max ~{ADVISORY_SEGMENT_THRESHOLD})"
        )
    if len(feature_table.names) > ADVISORY_FEATURE_THRESHOLD:
        advisories.append(
            f"unusually large feature set: {len(feature_table.names)} "
            f"features (typical max ~{ADVISORY_FEATURE_THRESHOLD})"
        )
    for canonical_seg in segments_view:
        advisories.extend(_ipa_confusable_notes(canonical_seg))

    feature_index = MappingProxyType(
        {name: i for i, name in enumerate(feature_table.names)}
    )
    segment_index = MappingProxyType(
        {seg: i for i, seg in enumerate(segments_view)}
    )

    return cls(
        name=canonical_name,
        metadata=MappingProxyType(metadata),
        features=feature_table.names,
        segments=segments_view,
        advisories=tuple(advisories),
        feature_index=feature_index,
        segment_index=segment_index,
    )


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

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(rendered)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, path)
        _fsync_directory_best_effort(directory)

    except BaseException as e:
        _log.error("atomic write failed: %s: %s", basename, e)
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

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
