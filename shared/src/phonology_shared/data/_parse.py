"""Multi-phase JSON-to-:py:class:`Inventory` validation pipeline.

Extracted from :py:mod:`phonology_shared.data.inventory` so that
module can host the public ``Inventory`` dataclass + its short
methods without burying the surface under ~600 lines of validators.
Every function here is pure (apart from the shared
:py:class:`_ValidationContext` it threads through) and called only
by :py:meth:`Inventory.parse`.

Circular-import note: :py:meth:`Inventory.parse` lazy-imports this
module inside the method body, so the top-level
``from phonology_shared.data.inventory import ...`` below resolves
cleanly: by the time this module is first imported, ``inventory``
has finished its top-level execution.

Pipeline (every phase is pure; the
:py:class:`_ValidationContext` is the only mutable state):

  1. :py:func:`_decode_top_level` -> :py:class:`_RawInventory`.
     Top-level shape, schema_version, presence of the two required
     keys. Fatal failures raise immediately because every later
     check would be meaningless.
  2. :py:func:`_validate_features` -> :py:class:`_FeatureTable`.
     Declared feature names + alias-aware lookup map.
  3. :py:func:`_validate_segments` -> mapping of canonical labels
     to validated bundles. Bundle feature keys are folded onto the
     declared canonical names via the :py:class:`_FeatureTable`.
  4. :py:func:`_assemble_inventory` -> the final
     :py:class:`Inventory` (metadata, name, advisories, derived
     indexes).

:py:func:`run_parse` orchestrates the four phases and is the single
entry point :py:meth:`Inventory.parse` calls.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from phonology_shared.data.inventory import (
    CURRENT_SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    VALID_VALUES,
    FeatureValue,
    ValidationError,
    _canonicalize_name,
    _invisible_format_chars,
    _ipa_confusable_notes,
    _ipa_normalize_segment,
    _IssueCodes,
    _ValidationContext,
    normalize_feature_key,
)
from phonology_shared.data.limits import (
    ADVISORY_FEATURE_THRESHOLD,
    ADVISORY_SEGMENT_THRESHOLD,
    MAX_FEATURES,
    MAX_NAME_LENGTH,
    MAX_SEGMENTS,
)

if TYPE_CHECKING:
    from phonology_shared.data.inventory import Inventory


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


def run_parse(
    cls: type[Inventory], raw: Any, *, source: str | None = None
) -> Inventory:
    """Orchestrate the four parsing phases. Single entry point
    :py:meth:`Inventory.parse` lazy-imports and calls.

    Collects every issue before raising so the caller can show them
    all. ``source`` is included in error messages when given,
    typically a file path, to disambiguate when the GUI is loading
    multiple inventories.
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
