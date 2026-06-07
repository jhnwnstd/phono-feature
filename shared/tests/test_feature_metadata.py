"""Pin the :py:mod:`phonology_shared.presentation.feature_metadata`
registry contract.

The registry is the single source of truth for feature-name
metadata. These tests catch regressions across the contract:

- Every entry has a unique canonical key and sort position.
- Every declared alias resolves back to its entry via
  ``resolve_canonical``, regardless of case or delimiter.
- The aliases registered here are a superset of the surface forms
  the codebase has accumulated in other tables (Hayes inventory
  on disk, baked PHOIBLE feature names, PanPhon's short codes).
- The legacy folds inside
  :py:func:`phonology_shared.data.inventory.normalize_feature_key`
  (``del.rel. → delrel``, ``r-colored → rhotic``, etc.) keep
  producing values the registry recognises.
- Place subgrouping puts each modifier's ``sort_key`` immediately
  after its anchor's, so the rendered Place group clusters by
  anchor without any visual hierarchy work.
"""

from __future__ import annotations

import json
from pathlib import Path

from phonology_shared.data.inventory import normalize_feature_key
from phonology_shared.presentation.constants import (
    FEATURE_GROUPS,
    FEATURE_ORDER,
    SUPRASEGMENTAL_FEATURES,
    sort_features,
)
from phonology_shared.presentation.feature_metadata import (
    FEATURE_REGISTRY,
    GROUP_ORDER,
    USE_VOWEL_PAIR,
    all_aliases,
    feature_sort_key,
    features_for_use,
    is_suprasegmental,
    metadata_for,
    resolve_canonical,
)

# ---------------------------------------------------------------
# Registry shape invariants
# ---------------------------------------------------------------


def test_canonical_keys_are_unique() -> None:
    """``FEATURE_REGISTRY`` is keyed on canonical; the keys must
    match each entry's ``canonical`` field exactly."""
    for key, meta in FEATURE_REGISTRY.items():
        assert key == meta.canonical, (
            f"registry key {key!r} != entry canonical " f"{meta.canonical!r}"
        )


def test_sort_keys_are_unique() -> None:
    """Two entries with the same sort key would produce a
    non-deterministic display order."""
    sort_keys = [m.sort_key for m in FEATURE_REGISTRY.values()]
    assert len(sort_keys) == len(
        set(sort_keys)
    ), "duplicate sort_keys: " + str(
        sorted(k for k in sort_keys if sort_keys.count(k) > 1)
    )


def test_group_is_one_of_GROUP_ORDER() -> None:
    """Every entry's ``group`` must appear in ``GROUP_ORDER`` so the
    derived ``FEATURE_GROUPS`` table emits it under a known card."""
    valid_groups = set(GROUP_ORDER)
    for meta in FEATURE_REGISTRY.values():
        assert meta.group in valid_groups, (
            f"{meta.canonical!r} declares group {meta.group!r} "
            f"which is not in GROUP_ORDER ({sorted(valid_groups)})"
        )


# ---------------------------------------------------------------
# Alias resolution
# ---------------------------------------------------------------


def test_every_alias_resolves_back_to_canonical() -> None:
    """``resolve_canonical(alias)`` must equal the entry's canonical
    for every alias, with case + delimiter folding applied.

    This sweep covers every registered surface form (~100 aliases
    across 47 entries), so it strictly subsumes the prior hand-
    listed parametrised cases (case variants of place anchors,
    ``del.rel.`` delimiter forms, PHOIBLE long names, PanPhon short
    codes). Unknown inputs are pinned separately by
    :py:func:`test_resolve_canonical_returns_none_for_unknown` to
    keep this loop tightly scoped to the registry's contents.
    """
    for meta in FEATURE_REGISTRY.values():
        for alias in (meta.canonical, *meta.aliases):
            assert resolve_canonical(alias) == meta.canonical, (
                f"alias {alias!r} of {meta.canonical!r} did not "
                f"resolve back (got {resolve_canonical(alias)!r})"
            )


def test_resolve_canonical_returns_none_for_unknown() -> None:
    """Names not in the registry resolve to ``None``; consumers
    using ``resolve_canonical`` as a "do you know this feature?"
    check rely on the falsy return."""
    assert resolve_canonical("Phantom") is None
    assert resolve_canonical("nonexistent") is None
    assert resolve_canonical("ZZZZ") is None


def test_resolve_canonical_agrees_with_normalize_feature_key() -> None:
    """For every canonical key the registry knows, the engine-side
    normaliser must produce the same fold. Otherwise the engine and
    the renderer disagree on whether two surface forms are the same
    feature."""
    for meta in FEATURE_REGISTRY.values():
        for alias in (meta.canonical, *meta.aliases):
            engine_key = normalize_feature_key(alias)
            registry_key = resolve_canonical(alias)
            assert engine_key == registry_key, (
                f"alias {alias!r}: normalize_feature_key="
                f"{engine_key!r} but registry resolved "
                f"{registry_key!r}"
            )


# ---------------------------------------------------------------
# Coverage: provider rosters
# ---------------------------------------------------------------


def test_registry_covers_bundled_hayes_inventory(
    inventories_dir: Path,
) -> None:
    """Every feature in the bundled Hayes inventory must resolve to
    a registry entry. Any drift would mean a Hayes-named feature
    lands in the "Other" group instead of its semantic home."""
    raw = json.loads(
        (inventories_dir / "hayes_features.json").read_text(
            encoding="utf-8-sig"
        )
    )
    for feat in raw["features"]:
        assert resolve_canonical(feat) is not None, (
            f"bundled Hayes feature {feat!r} is not in "
            f"FEATURE_REGISTRY; the panel would route it to "
            f"'Other' instead of its semantic group"
        )


def test_registry_covers_phoible_baked_feature_names() -> None:
    """Every feature name in the baked PHOIBLE snapshot must
    resolve to a registry entry. The bake script's
    ``PHOIBLE_TO_APP_FEATURE`` table emits these labels, so the
    registry's aliases must be a superset of that table's values."""
    from phonology_shared.editor.phoible_features import (
        PHOIBLE_TO_APP_FEATURE,
    )

    for col, app_name in PHOIBLE_TO_APP_FEATURE.items():
        assert resolve_canonical(app_name) is not None, (
            f"PHOIBLE column {col!r} maps to app name {app_name!r} "
            f"which is not in FEATURE_REGISTRY"
        )


def test_registry_covers_panphon_mapping_values() -> None:
    """Same constraint for PanPhon: every short-code → app-name
    mapping value must resolve."""
    from phonology_shared.editor.panphon_features import (
        PANPHON_TO_APP_FEATURE,
    )

    for short_code, app_name in PANPHON_TO_APP_FEATURE.items():
        assert resolve_canonical(app_name) is not None, (
            f"PanPhon code {short_code!r} maps to app name "
            f"{app_name!r} which is not in FEATURE_REGISTRY"
        )


# ---------------------------------------------------------------
# Derived tables stay consistent with the registry
# ---------------------------------------------------------------


def test_FEATURE_ORDER_contains_every_alias() -> None:
    """``FEATURE_ORDER`` is derived from
    ``all_aliases(canonical)``. Every registered surface form must
    appear so legacy iteration sees the full set."""
    feature_order_set = set(FEATURE_ORDER)
    for canonical in FEATURE_REGISTRY:
        for alias in all_aliases(canonical):
            assert alias in feature_order_set, (
                f"surface form {alias!r} of {canonical!r} missing "
                f"from FEATURE_ORDER"
            )


def test_FEATURE_GROUPS_partitions_registry() -> None:
    """The union of every group's member list must equal
    FEATURE_ORDER (modulo unknown features outside the registry)."""
    grouped = {feat for _, feats in FEATURE_GROUPS for feat in feats}
    assert grouped == set(FEATURE_ORDER), (
        f"FEATURE_GROUPS membership diverged from FEATURE_ORDER; "
        f"missing from groups: {set(FEATURE_ORDER) - grouped}; "
        f"only in groups: {grouped - set(FEATURE_ORDER)}"
    )


def test_FEATURE_GROUPS_group_names_match_GROUP_ORDER() -> None:
    """The group titles must appear in the same order as
    ``GROUP_ORDER`` so the layout's left/right column distribution
    is deterministic."""
    titles = [name for name, _ in FEATURE_GROUPS]
    assert titles == list(GROUP_ORDER)


def test_SUPRASEGMENTAL_FEATURES_includes_every_alias() -> None:
    """A consumer doing ``if feat in SUPRASEGMENTAL_FEATURES``
    must catch any case variant of a tier-separate feature."""
    for meta in FEATURE_REGISTRY.values():
        if not meta.is_suprasegmental:
            continue
        for alias in all_aliases(meta.canonical):
            assert alias in SUPRASEGMENTAL_FEATURES


# ---------------------------------------------------------------
# Place subgrouping (sort adjacency only — no visual hierarchy)
# ---------------------------------------------------------------


def test_place_modifiers_sort_directly_after_their_anchor() -> None:
    """The Labial/Coronal/Dorsal anchors must precede their
    modifiers in the Place group's sort order. This is the registry-
    level contract that makes ``Round`` render right after ``Labial``
    in the Feature Pane regardless of which inventory loaded."""
    anchors = {"labial", "coronal", "dorsal"}
    for canonical, meta in FEATURE_REGISTRY.items():
        if meta.subgroup not in anchors or canonical in anchors:
            continue
        anchor_meta = FEATURE_REGISTRY[meta.subgroup]
        assert meta.sort_key > anchor_meta.sort_key, (
            f"place modifier {canonical!r} (sort={meta.sort_key}) "
            f"sorts BEFORE its anchor {meta.subgroup!r} "
            f"(sort={anchor_meta.sort_key})"
        )


def test_sort_features_canonicalises_case_variants() -> None:
    """``sort_features(["LABIAL", "Labial"])`` lands both case
    variants adjacent in the output — the fundamental visual fix
    for Hayes-vs-PHOIBLE drift."""
    out = sort_features(["LABIAL", "Round", "Labial", "Voice"])
    # Voice (200s) sorts before any Place feature; the two LABIAL
    # case variants sort to the same position (400) and end up
    # adjacent; Round (401) immediately follows.
    labial_indices = [
        i for i, f in enumerate(out) if resolve_canonical(f) == "labial"
    ]
    assert len(labial_indices) == 2
    assert labial_indices[1] == labial_indices[0] + 1, (
        "two case variants of Labial did not land adjacent in the "
        "sorted output"
    )
    voice_index = out.index("Voice")
    assert (
        voice_index < labial_indices[0]
    ), "Voice (Laryngeal) must sort before Labial (Place)"


def test_sort_features_unknowns_trail_at_end() -> None:
    """Backward compat with the prior behaviour: features absent
    from the registry sort after every known feature."""
    out = sort_features(["unknownThing", "Voice", "Labial"])
    assert out[-1] == "unknownThing"


# ---------------------------------------------------------------
# Vowel-pair contrast set (registry-driven)
# ---------------------------------------------------------------


def test_vowel_pair_contrast_set_matches_registry_uses_tag() -> None:
    """The vowel-pair contrast set the cell classifier reads must
    equal ``features_for_use(USE_VOWEL_PAIR)``. The
    :py:mod:`phonology_shared.chart.vowels` module relies on this
    so the two stay in sync."""
    from phonology_shared.chart.vowels import _DISPLAY_CONTRAST_FEATURES

    assert set(_DISPLAY_CONTRAST_FEATURES) == features_for_use(USE_VOWEL_PAIR)


# ---------------------------------------------------------------
# Helper-function contracts
# ---------------------------------------------------------------


def test_feature_sort_key_handles_unknown() -> None:
    """Unknown features get a large sort key (trail position),
    matching the prior ``unknown_index = len(FEATURE_ORDER)``
    fallback semantics."""
    sk_known = feature_sort_key("Voice")
    sk_unknown = feature_sort_key("ThisFeatureDoesNotExist")
    assert sk_unknown > sk_known


def test_metadata_for_returns_None_for_unknown() -> None:
    assert metadata_for("PhantomFeature") is None


def test_is_suprasegmental_recognises_aliases() -> None:
    assert is_suprasegmental("HighTone") is True
    assert is_suprasegmental("hightone") is True
    assert is_suprasegmental("hitone") is True  # PanPhon short code
    assert is_suprasegmental("Voice") is False
    assert is_suprasegmental("LABIAL") is False
