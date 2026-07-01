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
  (``del.rel.`` to ``delrel``, ``r-colored`` to ``rhotic``, etc.) keep
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
# Bake-time column-order guards.
#
# The bake script consumes ``PHOIBLE_TO_APP_FEATURE.keys()`` and
# ``PANPHON_TO_APP_FEATURE.keys()`` in dict-insertion order to fix
# the column order of the positional-encoded bundle string in the
# baked snapshot. Inserting in the middle or reordering rotates
# the encoding and silently invalidates every shipped bundle:
# downstream the engine reads the wrong feature for each position.
#
# These tests pin the current column order as a literal tuple in
# the test file. A future edit that reorders or inserts requires
# updating these tests (and re-baking every snapshot; the safer
# fix is usually to append to the end of the mapping rather than
# rotate). Each failure points at the exact mitigation in its
# message.
# ---------------------------------------------------------------


_PHOIBLE_COLUMN_ORDER: tuple[str, ...] = (
    "tone",
    "stress",
    "syllabic",
    "short",
    "long",
    "consonantal",
    "sonorant",
    "continuant",
    "delayedRelease",
    "approximant",
    "tap",
    "trill",
    "nasal",
    "lateral",
    "labial",
    "round",
    "labiodental",
    "coronal",
    "anterior",
    "distributed",
    "strident",
    "dorsal",
    "high",
    "low",
    "front",
    "back",
    "tense",
    "retractedTongueRoot",
    "advancedTongueRoot",
    "periodicGlottalSource",
    "epilaryngealSource",
    "spreadGlottis",
    "constrictedGlottis",
    "fortis",
    "lenis",
    "raisedLarynxEjective",
    "loweredLarynxImplosive",
    "click",
)


def test_phoible_column_order_is_pinned() -> None:
    """``PHOIBLE_TO_APP_FEATURE``'s key order IS the column order
    of the baked PHOIBLE snapshot's positional-encoded bundle
    string. Reordering or inserting in the middle silently
    invalidates every shipped baked snapshot (every segment now
    decodes the wrong feature for the rotated positions).

    Pinned as a literal tuple so a future edit that reorders or
    inserts trips this test and forces a deliberate decision:
    either preserve order (append-only) or re-bake every snapshot
    AND update this list. The failure message names both options.
    """
    from phonology_shared.editor.phoible_features import (
        PHOIBLE_TO_APP_FEATURE,
    )

    actual = tuple(PHOIBLE_TO_APP_FEATURE.keys())
    assert actual == _PHOIBLE_COLUMN_ORDER, (
        "PHOIBLE_TO_APP_FEATURE column order changed. The order IS "
        "the positional encoding of every baked snapshot; rotating "
        "it silently corrupts the engine's feature lookup. To fix:\n"
        "  (a) restore the previous order (preferred; append new "
        "columns to the end instead of inserting), OR\n"
        "  (b) re-bake every PHOIBLE snapshot and update "
        "_PHOIBLE_COLUMN_ORDER in this test to match.\n"
        f"  actual: {actual}\n"
        f"  expected: {_PHOIBLE_COLUMN_ORDER}"
    )


_PANPHON_COLUMN_ORDER: tuple[str, ...] = (
    "syl",
    "son",
    "cons",
    "cont",
    "delrel",
    "lat",
    "nas",
    "strid",
    "voi",
    "sg",
    "cg",
    "ant",
    "cor",
    "distr",
    "lab",
    "hi",
    "lo",
    "back",
    "round",
    "velaric",
    "tense",
    "long",
    "hitone",
    "hireg",
)


def test_panphon_column_order_is_pinned() -> None:
    """``PANPHON_TO_APP_FEATURE``'s key order pins the column order
    PanPhon's bake artifact carries. Same rationale as the PHOIBLE
    column-order guard: reordering or inserting silently rotates
    every shipped bundle's feature lookup.

    PanPhon's load-time path also consults the mapping by key
    (``PANPHON_TO_APP_FEATURE.get(short_code)``), so a key rename
    breaks the runtime lookup too; the test catches that case as
    well.
    """
    from phonology_shared.editor.panphon_features import (
        PANPHON_TO_APP_FEATURE,
    )

    actual = tuple(PANPHON_TO_APP_FEATURE.keys())
    assert actual == _PANPHON_COLUMN_ORDER, (
        "PANPHON_TO_APP_FEATURE column order changed. Same fix "
        "options as the PHOIBLE guard: prefer append-only edits "
        "to the existing order; if a reorder is required, re-bake "
        "every PanPhon snapshot and update _PANPHON_COLUMN_ORDER.\n"
        f"  actual: {actual}\n"
        f"  expected: {_PANPHON_COLUMN_ORDER}"
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
# Subgrouping (sort adjacency only; no visual hierarchy)
# ---------------------------------------------------------------


def test_modifiers_sort_directly_after_their_anchor() -> None:
    """Every modifier (an entry whose ``subgroup`` points at another
    canonical key) must have a sort_key strictly greater than its
    anchor's. The registry-level contract makes anchored
    sub-clusters render contiguously regardless of which inventory
    loaded:

    - Place modifiers cluster under ``labial`` / ``coronal`` /
      ``dorsal`` (the original guarantee that prevents ``Round``
      from drifting away from ``Labial`` on PHOIBLE).
    - PHOIBLE-only Laryngeal modifiers cluster under ``voice``
      (epilaryngeal source, fortis/lenis, breathy/creaky) and
      ``constrgl`` (raised- / lowered-larynx ejective + implosive),
      so PHOIBLE inventories surface them as visibly anchored
      sub-clusters rather than five strangers at the bottom of the
      Laryngeal group.
    - Any future subgroup-anchored cluster inherits the contract
      automatically; no per-group special case here.

    Catches a regression where an edit reorders an anchor below
    its modifiers and the pane's adjacency promise breaks silently.
    """
    for canonical, meta in FEATURE_REGISTRY.items():
        if meta.subgroup is None or meta.subgroup == canonical:
            continue
        anchor_meta = FEATURE_REGISTRY.get(meta.subgroup)
        assert anchor_meta is not None, (
            f"{canonical!r} declares subgroup {meta.subgroup!r} "
            f"but no registry entry by that canonical exists"
        )
        assert meta.group == anchor_meta.group, (
            f"{canonical!r} (group {meta.group!r}) anchors to "
            f"{meta.subgroup!r} (group {anchor_meta.group!r}); the "
            f"contract pins same-group subgrouping so the renderer "
            f"can iterate one group at a time"
        )
        assert meta.sort_key > anchor_meta.sort_key, (
            f"modifier {canonical!r} (sort={meta.sort_key}) sorts "
            f"BEFORE its anchor {meta.subgroup!r} "
            f"(sort={anchor_meta.sort_key})"
        )


def test_sort_features_canonicalises_case_variants() -> None:
    """``sort_features(["LABIAL", "Labial"])`` lands both case
    variants adjacent in the output: the fundamental visual fix
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


def test_normalize_feature_key_matches_registry_for_every_alias() -> None:
    """The engine-side fold and the registry resolver answer
    identically for every name the registry knows. The docstring of
    ``normalize_feature_key`` asserts this identity; this test
    enforces it so the two paths cannot drift."""
    for canonical, meta in FEATURE_REGISTRY.items():
        for name in (canonical, *meta.aliases):
            assert normalize_feature_key(name) == resolve_canonical(name), (
                f"{name!r}: normalize_feature_key gives "
                f"{normalize_feature_key(name)!r}, registry gives "
                f"{resolve_canonical(name)!r}"
            )


def test_click_and_velaric_are_one_feature() -> None:
    """Clicks are the velaric-airstream consonants. Hayes writes the
    feature ``Click``; PHOIBLE and PanPhon write ``Velaric`` (PHOIBLE
    bakes its ``click`` column to that label). Every spelling folds to
    the single ``click`` canonical, so ``velaric`` is not a separate
    registry entry."""
    for name in ("click", "Click", "velaric", "Velaric"):
        assert resolve_canonical(name) == "click"
        assert normalize_feature_key(name) == "click"
    assert "velaric" not in FEATURE_REGISTRY


def test_velaric_authored_click_reaches_the_clicks_row() -> None:
    """A segment authored with PHOIBLE's ``Velaric`` feature reaches
    the consonant grouper as ``click`` and lands in the Clicks row.
    Regression guard: before click/velaric were unified the grouper
    read only ``click`` and silently missed every PHOIBLE click."""
    from phonology_shared.chart.consonants import group_segments

    groups = group_segments(
        {"ǃ": {"Velaric": "+", "consonantal": "+", "sonorant": "-"}}
    )
    assert "ǃ" in groups.get("Clicks", [])


def test_alternative_name_aliases_resolve() -> None:
    """Common alternative spellings of known features resolve to the
    canonical rather than falling through to the ``Other`` group."""
    assert resolve_canonical("voiced") == "voice"
    assert resolve_canonical("rounded") == "round"
    assert resolve_canonical("flap") == "tap"
    assert resolve_canonical("nasalized") == "nasal"
    assert resolve_canonical("nasality") == "nasal"


def test_register_is_one_feature() -> None:
    """Pitch register is one concept. Hayes writes ``UpperRegister``,
    PanPhon ``HighRegister`` / ``hireg``; all fold to a single
    ``highregister`` canonical, so ``upperregister`` is not a separate
    entry."""
    for name in ("HighRegister", "hireg", "UpperRegister", "upperregister"):
        assert resolve_canonical(name) == "highregister"
    assert "upperregister" not in FEATURE_REGISTRY


def test_tone_marker_and_level_are_distinct() -> None:
    """``tone`` is the generic tonality marker (PHOIBLE's ``tone``
    column, carried by every tone letter high or low); ``hightone`` is
    the pitch LEVEL (PanPhon's ``hitone``). They are separate features
    so a source that supplies pitch level can distinguish tones while
    one that supplies only the generic marker leaves them all the
    same."""
    assert resolve_canonical("Tone") == "tone"
    assert resolve_canonical("HighTone") == "hightone"
    assert resolve_canonical("hitone") == "hightone"
    assert FEATURE_REGISTRY["tone"].canonical != (
        FEATURE_REGISTRY["hightone"].canonical
    )
