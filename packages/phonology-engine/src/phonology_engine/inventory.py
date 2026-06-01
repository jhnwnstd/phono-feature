"""The Inventory contract.

One source of truth for the question "is this inventory data valid".
Every loader, editor, and saver routes through this module. The only
entry points that accept untrusted data are :py:meth:`Inventory.parse`,
:py:meth:`Inventory.from_grid`, and :py:meth:`Inventory.load`, and each
funnels through ``parse`` so the validation code path is singular.

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
from types import MappingProxyType
from typing import Any

from phonology_engine.limits import (
    ADVISORY_FEATURE_THRESHOLD,
    ADVISORY_SEGMENT_THRESHOLD,
    MAX_FEATURES,
    MAX_FILE_BYTES,
    MAX_NAME_LENGTH,
    MAX_SEGMENTS,
)
from phonology_engine.segment_grouper import _normalize_key

_log = logging.getLogger(__name__)

VALID_VALUES: frozenset[str] = frozenset({"+", "-", "0"})

# Domain-specific identity folding for segment labels. ``r`` is
# deliberately excluded: it is the legitimate IPA alveolar trill, and
# folding it to ``ɹ`` (the approximant) would silently change meaning.
# ASCII ``:`` is not folded but surfaced as an advisory in
# :py:func:`_ipa_confusable_notes`, because the cost of getting vowel
# length wrong is too high to rewrite without consent.
_IPA_SEGMENT_TRANSLATIONS: dict[str, str] = {
    "'": "ʼ",  # APOSTROPHE -> MODIFIER LETTER APOSTROPHE (ejective)
    "g": "ɡ",  # ASCII g -> LATIN SMALL LETTER SCRIPT G (voiced velar)
}
_IPA_TRANSLATION_TABLE = str.maketrans(_IPA_SEGMENT_TRANSLATIONS)


def _ipa_normalize_segment(canonical: str) -> str:
    """Fold ASCII substitutes commonly typed for IPA characters in
    segment labels. Idempotent. Pure transformation, no validation."""
    return canonical.translate(_IPA_TRANSLATION_TABLE)


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

    ``str(err)`` is the first issue, useful for status bars.
    ``err.issues`` is the full tuple, in the order the parser found
    them (top-level shape first, then per-feature, then per-segment,
    then per-cell).
    """

    def __init__(self, issues: tuple[str, ...]) -> None:
        if not issues:
            issues = ("Invalid inventory (no issue detail)",)
        self.issues: tuple[str, ...] = issues
        super().__init__(issues[0])


@dataclass(frozen=True)
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
        them all. ``source`` is included in error messages when given,
        typically a file path, to disambiguate when the GUI is loading
        multiple inventories.
        """
        issues: list[str] = []
        prefix = f"{source}: " if source else ""

        if not isinstance(raw, dict):
            raise ValidationError(
                (
                    f"{prefix}top-level JSON value must be an object, "
                    f"got {type(raw).__name__}",
                )
            )

        # Schema version is checked before per-field validation: if we
        # cannot read the format, every subsequent issue is meaningless.
        # Missing is treated as version 1 so files written before this
        # field existed load without migration.
        if "schema_version" in raw:
            sv = raw["schema_version"]
            # bool is a subclass of int; reject it explicitly so True
            # and False cannot sneak through as "schema_version 1".
            if isinstance(sv, bool) or not isinstance(sv, int):
                raise ValidationError(
                    (
                        f"{prefix}'schema_version' must be an integer, "
                        f"got {type(sv).__name__}",
                    )
                )
            if sv not in SUPPORTED_SCHEMA_VERSIONS:
                supported = ", ".join(
                    str(v) for v in sorted(SUPPORTED_SCHEMA_VERSIONS)
                )
                raise ValidationError(
                    (
                        f"{prefix}unsupported schema_version {sv}; "
                        f"this build reads version(s) {supported}",
                    )
                )

        if "features" not in raw:
            issues.append(f"{prefix}missing required key 'features'")
            features_tuple: tuple[str, ...] = ()
            declared: set[str] = set()
        else:
            features_tuple, declared = _validate_features(
                raw["features"], issues, prefix
            )

        if "segments" not in raw:
            issues.append(f"{prefix}missing required key 'segments'")
            segments_view: Mapping[str, Mapping[str, str]] = MappingProxyType(
                {}
            )
        else:
            segments_view = _validate_segments(
                raw["segments"], declared, issues, prefix
            )

        if issues:
            raise ValidationError(tuple(issues))

        # Collect metadata from both conventions: an explicit
        # ``metadata`` object (Hayes shape) AND top-level extras
        # (general_features shape). The explicit metadata object wins
        # on key collision so callers can override.
        metadata: dict[str, Any] = {}
        for key, value in raw.items():
            # ``schema_version`` lives at the top level for tooling
            # visibility; never duplicate it into metadata or it would
            # round-trip into two places on save.
            if key in ("features", "segments", "metadata", "schema_version"):
                continue
            metadata[key] = value
        explicit_metadata = raw.get("metadata")
        if isinstance(explicit_metadata, dict):
            metadata.update(explicit_metadata)
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
        if len(features_tuple) > ADVISORY_FEATURE_THRESHOLD:
            advisories.append(
                f"unusually large feature set: {len(features_tuple)} "
                f"features (typical max ~{ADVISORY_FEATURE_THRESHOLD})"
            )
        for canonical_seg in segments_view:
            advisories.extend(_ipa_confusable_notes(canonical_seg))

        return cls(
            name=canonical_name,
            metadata=MappingProxyType(metadata),
            features=features_tuple,
            segments=segments_view,
            advisories=tuple(advisories),
        )

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
                # object_pairs_hook intercepts each JSON object literal
                # before dict construction so a duplicate key (which
                # plain json.load would silently collapse) is reported.
                # parse_constant rejects non-finite numeric literals
                # (NaN / Infinity / -Infinity) which would otherwise
                # flow into the parser as Python ``float('nan')`` and
                # break feature-set comparisons silently.
                raw = json.load(
                    f,
                    object_pairs_hook=_no_duplicate_keys,
                    parse_constant=_reject_non_finite,
                )
        except FileNotFoundError as e:
            _log.warning("inventory load failed: %s: file not found", basename)
            raise ValidationError((f"{path}: file not found",)) from e
        except _DuplicateJSONKey as e:
            _log.warning(
                "inventory load failed: %s: duplicate JSON key(s)", basename
            )
            raise ValidationError((f"{path}: {e}",)) from e
        except _NonFiniteJSONValue as e:
            _log.warning(
                "inventory load failed: %s: non-finite JSON value", basename
            )
            raise ValidationError((f"{path}: {e}",)) from e
        except json.JSONDecodeError as e:
            _log.warning(
                "inventory load failed: %s: invalid JSON (%s line %d)",
                basename,
                e.msg,
                e.lineno,
            )
            raise ValidationError(
                (f"{path}: invalid JSON ({e.msg} on line {e.lineno})",)
            ) from e
        except OSError as e:
            _log.warning("inventory load failed: %s: %s", basename, e)
            raise ValidationError((f"{path}: {e}",)) from e
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
        does not know about :py:class:`MappingProxyType`.
        ``schema_version`` is the first key by convention so tooling
        that inspects without parsing (jq, grep, future migrators) can
        find it without walking the whole file.
        """
        return {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "metadata": dict(self.metadata),
            "features": list(self.features),
            "segments": {
                seg: dict(feats) for seg, feats in self.segments.items()
            },
        }

    def write_atomic(self, path: str) -> None:
        """Crash-safe write via :py:func:`atomic_write_json`.

        Serializes to a sibling tmp file, fsyncs, then ``os.replace``s
        onto the target. An interrupted run leaves either the old file
        untouched or the new file fully written, never a half-written
        file. External file watchers see one atomic rename rather than
        a series of partial writes.
        """
        atomic_write_json(path, self.to_json_dict())

    def feature_value(self, segment: str, feature: str) -> str:
        """Value of ``feature`` for ``segment``; ``'0'`` if missing.

        Raises :py:class:`KeyError` for unknown segment or feature.
        """
        if segment not in self.segments:
            raise KeyError(f"Segment '{segment}' not in inventory")
        if feature not in self.features:
            raise KeyError(f"Feature '{feature}' not in inventory")
        return self.segments[segment].get(feature, "0")


def _validate_features(
    features_raw: Any, issues: list[str], prefix: str
) -> tuple[tuple[str, ...], set[str]]:
    """Return ``(canonical feature names, set of those names)``.

    Appends any issues to ``issues``. Names are stored in canonical
    form (NFC + stripped) so downstream lookups never see two
    spellings of the same intended identity.
    """
    if not isinstance(features_raw, list):
        issues.append(
            f"{prefix}'features' must be a list of strings, "
            f"got {type(features_raw).__name__}"
        )
        return (), set()

    if len(features_raw) > MAX_FEATURES:
        issues.append(
            f"{prefix}'features' has {len(features_raw)} entries; "
            f"hard cap is {MAX_FEATURES}"
        )
        # Refuse to truncate. If the file is this far out of bounds,
        # it is almost certainly authored wrong, and per-feature noise
        # would drown the actionable message.
        return (), set()

    valid: list[str] = []
    seen: set[str] = set()
    # Original spelling per canonical name so a collision message can
    # show the user both forms.
    canonical_origin: dict[str, str] = {}
    for i, f in enumerate(features_raw):
        if not isinstance(f, str):
            issues.append(
                f"{prefix}'features[{i}]' is not a string "
                f"(got {type(f).__name__}: {f!r})"
            )
            continue
        if len(f) > MAX_NAME_LENGTH:
            issues.append(
                f"{prefix}'features[{i}]' is {len(f)} chars; "
                f"max is {MAX_NAME_LENGTH}"
            )
            continue
        canonical = _canonicalize_name(f)
        if not canonical:
            issues.append(
                f"{prefix}'features[{i}]' is empty after canonicalization"
            )
            continue
        invisible = _invisible_format_chars(canonical)
        if invisible:
            issues.append(
                f"{prefix}'features[{i}]' ({f!r}) contains invisible "
                f"format character(s): {invisible}; these have no use "
                f"in feature identifiers and would create distinct keys "
                f"that look identical"
            )
            continue
        if canonical in seen:
            prior = canonical_origin[canonical]
            if prior == f:
                issues.append(f"{prefix}'features' contains duplicate {f!r}")
            else:
                # Two distinct spellings collapsed to the same identity
                # (for example " Voice " vs "Voice", or NFC vs NFD of
                # "é").
                issues.append(
                    f"{prefix}features {prior!r} and {f!r} are the same "
                    f"after NFC + whitespace normalization "
                    f"({canonical!r}); rename or remove one"
                )
            continue
        seen.add(canonical)
        canonical_origin[canonical] = f
        valid.append(canonical)

    # Alias-collision check on the engine's :py:func:`_normalize_key`
    # (case and delimiter folding). "DelRel" and "delayed_release" are
    # distinct in canonical form (different case + underscores) but
    # engine consumers fold them. Catching at the parser boundary
    # means the engine never has to defend against
    # ``AliasCollisionError`` downstream.
    by_alias: dict[str, list[str]] = {}
    for f in valid:
        by_alias.setdefault(_normalize_key(f), []).append(f)
    for canonical, originals in by_alias.items():
        if len(originals) > 1:
            issues.append(
                f"{prefix}features {sorted(originals)} collide after "
                f"normalization to {canonical!r}; rename or remove one"
            )
    return tuple(valid), seen


def _canonicalize_segment_key(
    seg_name: Any,
    issues: list[str],
    prefix: str,
) -> str | None:
    """Run the canonicalisation + invisible-character + length
    checks for one segment key. Returns the canonical key on
    success or ``None`` on failure (after appending the
    appropriate issue text). Splits the per-key checks out of
    :py:func:`_validate_segments` so each one is independently
    testable and the driver loop stays scannable.
    """
    if not isinstance(seg_name, str) or not seg_name:
        issues.append(
            f"{prefix}segment key {seg_name!r} must be a non-empty string"
        )
        return None
    if len(seg_name) > MAX_NAME_LENGTH:
        issues.append(
            f"{prefix}segment key {seg_name!r} is {len(seg_name)} "
            f"chars; max is {MAX_NAME_LENGTH}"
        )
        return None
    canonical_seg = _canonicalize_name(seg_name)
    if not canonical_seg:
        issues.append(
            f"{prefix}segment key {seg_name!r} is empty after "
            f"canonicalization"
        )
        return None
    # Domain-specific identity folding (ASCII g->ɡ, '->ʼ) runs
    # AFTER NFC canonicalization but BEFORE the collision check so
    # an inventory containing both "g" and "ɡ" is detected as a
    # duplicate rather than silently kept as two distinct keys.
    canonical_seg = _ipa_normalize_segment(canonical_seg)
    invisible = _invisible_format_chars(canonical_seg)
    if invisible:
        issues.append(
            f"{prefix}segment key {seg_name!r} contains invisible "
            f"format character(s): {invisible}; these would create "
            f"a distinct segment that looks identical to another"
        )
        return None
    return canonical_seg


def _validate_segment_bundle(
    canonical_seg: str,
    seg_feats: Any,
    declared: set[str],
    issues: list[str],
    prefix: str,
) -> Mapping[str, str] | None:
    """Validate one segment's feature bundle. Returns a read-only
    inner dict on success or ``None`` if the bundle isn't even a
    dict (skipping the segment entirely). Per-feature-key issues
    are appended and the offending entry is dropped; the bundle
    keeps the surviving features.
    """
    if not isinstance(seg_feats, dict):
        issues.append(
            f"{prefix}segment {canonical_seg!r}: bundle must be an "
            f"object, got {type(seg_feats).__name__}"
        )
        return None
    inner: dict[str, str] = {}
    for feat_name, feat_val in seg_feats.items():
        if not isinstance(feat_name, str) or not feat_name:
            issues.append(
                f"{prefix}segment {canonical_seg!r}: feature key "
                f"{feat_name!r} must be a non-empty string"
            )
            continue
        if len(feat_name) > MAX_NAME_LENGTH:
            issues.append(
                f"{prefix}segment {canonical_seg!r}: feature key "
                f"{feat_name!r} is {len(feat_name)} chars; max is "
                f"{MAX_NAME_LENGTH}"
            )
            continue
        canonical_feat = _canonicalize_name(feat_name)
        if not canonical_feat:
            issues.append(
                f"{prefix}segment {canonical_seg!r}: feature key "
                f"{feat_name!r} is empty after canonicalization"
            )
            continue
        # No ``if declared and ...`` short-circuit. An inventory
        # with ``features=[]`` AND per-segment feature keys would
        # otherwise be silently accepted, storing ghost data that
        # :py:meth:`Inventory.feature_value` can never reach.
        # Always cross-check so the contract holds at every count.
        if canonical_feat not in declared:
            issues.append(
                f"{prefix}segment {canonical_seg!r}: feature "
                f"{feat_name!r} is not declared in 'features'"
            )
            continue
        if not isinstance(feat_val, str):
            issues.append(
                f"{prefix}segment {canonical_seg!r}."
                f"{canonical_feat!r}: value must be a string, got "
                f"{type(feat_val).__name__} ({feat_val!r})"
            )
            continue
        if feat_val not in VALID_VALUES:
            issues.append(
                f"{prefix}segment {canonical_seg!r}."
                f"{canonical_feat!r}: invalid value {feat_val!r} "
                f"(expected one of {sorted(VALID_VALUES)})"
            )
            continue
        inner[canonical_feat] = feat_val
    return MappingProxyType(inner)


def _validate_segments(
    segments_raw: Any,
    declared: set[str],
    issues: list[str],
    prefix: str,
) -> Mapping[str, Mapping[str, str]]:
    """Return a read-only view of validated segments with CANONICAL
    keys (NFC + stripped). Appends issues. ``declared`` must already
    contain canonical feature names so per-bundle feature keys can be
    matched against it after canonicalization.

    Composes two single-concern helpers
    (:py:func:`_canonicalize_segment_key` and
    :py:func:`_validate_segment_bundle`) so the driver loop reads
    as "for each segment: canonicalise the key, check for
    collisions, validate the bundle".
    """
    if not isinstance(segments_raw, dict):
        issues.append(
            f"{prefix}'segments' must be an object, "
            f"got {type(segments_raw).__name__}"
        )
        return MappingProxyType({})

    if len(segments_raw) > MAX_SEGMENTS:
        issues.append(
            f"{prefix}'segments' has {len(segments_raw)} entries; "
            f"hard cap is {MAX_SEGMENTS}"
        )
        return MappingProxyType({})

    result: dict[str, Mapping[str, str]] = {}
    canonical_origin: dict[str, str] = {}
    for seg_name, seg_feats in segments_raw.items():
        canonical_seg = _canonicalize_segment_key(seg_name, issues, prefix)
        if canonical_seg is None:
            continue
        if canonical_seg in result:
            prior = canonical_origin[canonical_seg]
            if prior == seg_name:
                issues.append(
                    f"{prefix}segment key {seg_name!r} appears more than once"
                )
            else:
                issues.append(
                    f"{prefix}segments {prior!r} and {seg_name!r} are the "
                    f"same after NFC + whitespace normalization "
                    f"({canonical_seg!r}); rename or remove one"
                )
            continue
        inner = _validate_segment_bundle(
            canonical_seg, seg_feats, declared, issues, prefix
        )
        if inner is None:
            continue
        result[canonical_seg] = inner
        canonical_origin[canonical_seg] = seg_name
    return MappingProxyType(result)


def atomic_write_json(path: str, data: Any) -> None:
    """Write JSON to ``path`` atomically.

    Writes to a sibling tmp file in the same directory (so the rename
    is a same-filesystem move), fsyncs, then :py:func:`os.replace`s.
    A crash or kill anywhere before the replace leaves the destination
    untouched. The rename itself is atomic on POSIX and Windows.

    File watchers see exactly one filesystem event for the destination
    (the rename) rather than a sequence of write-truncate-write events
    that would each trigger a reload.
    """
    basename = os.path.basename(path)
    _log.debug("atomic write start: %s", basename)
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(
        prefix=".tmp_inv_", suffix=".json", dir=directory
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException as e:
        _log.error("atomic write failed: %s: %s", basename, e)
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    _log.info("atomic write complete: %s", basename)
