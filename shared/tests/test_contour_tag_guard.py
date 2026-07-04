"""Standing guards for the PROVISIONAL 'Contour Consonants' display tag.

The tag is a presentation-only, source-display convention (a consonant
that reaches several manner classes gets named honestly instead of
labelled by a privileged phase). Two properties must hold until the
deferred multi-membership pass retires it:

1. The tag must NOT leak into the engine's set-membership relations. The
   engine answers membership from the tiers; the day someone adds a class
   query they must not be able to source it from the display artifact.
   These tests fail the moment a membership/query module references the
   tag, or the engine's ∃ answers depend on it.

2. The captured ∃-reach fixture (``fixtures/contour_tag_reach.json``) must
   stay faithful to the live engine: every tagged segment reaches exactly
   the manner classes recorded for it. That fixture is the ground truth
   the multi-membership pass validates against (each tagged glyph should
   render in exactly those classes once the partition becomes a multiset),
   so it is spot-checked here against a live sample.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from phonology_shared.chart.consonants import CONTOUR_GROUP_NAME
from phonology_shared.editor.phoible_provider import PhoibleProvider
from phonology_shared.theory.feature_engine import FeatureEngine

# The committed ∃-reach helper lives beside the fixture (kept out of
# pytest collection by its non-test name); reuse its exact reach logic so
# the guard validates the fixture with the same computation that built it.
_FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(_FIXTURES))
from gen_contour_tag_reach import build_reach_map  # noqa: E402

_FIXTURE = json.loads((_FIXTURES / "contour_tag_reach.json").read_text())
_REGEN = "regenerate: python shared/tests/fixtures/gen_contour_tag_reach.py"

_SHARED_SRC = Path(__file__).resolve().parents[1] / "src"

# The GROUND + QUERY layers: the per-feature tier store and everything
# that answers a feature/class query from it. A membership answer must
# never be sourced from a display label, so the tag's literal value must
# appear in NONE of these modules. Globbed (not a fixed denylist) so a
# new query module cannot silently evade the freeze; the tag's only
# legitimate home is the chart layer (consonants.py), which is excluded.
_QUERY_LAYER_DIRS = ["phonology_shared/data", "phonology_shared/theory"]


# --------------------------------------------------------------------
# Guard 1: the tag does not leak into engine membership.
# --------------------------------------------------------------------


def test_query_layer_never_hardcodes_the_display_tag() -> None:
    """No module in the ground (data/) or query (theory/) layers contains
    the Contour Consonants tag's literal value. Freezes the separation
    across the WHOLE layer, not a hand-picked pair, so a future class-query
    module cannot source membership from the display artifact and slip
    past a stale denylist."""
    offenders = []
    for rel_dir in _QUERY_LAYER_DIRS:
        for py in sorted((_SHARED_SRC / rel_dir).rglob("*.py")):
            if CONTOUR_GROUP_NAME in py.read_text(encoding="utf-8"):
                offenders.append(str(py.relative_to(_SHARED_SRC)))
    assert not offenders, (
        f"display tag {CONTOUR_GROUP_NAME!r} leaked into the query layer: "
        f"{offenders}. A membership answer must come from the tiers, never "
        f"a display group label."
    )


def _mb_engine() -> FeatureEngine:
    from phonology_shared.data.inventory import Inventory

    feats = ["Consonantal", "Sonorant", "Continuant", "Nasal", "Syllabic"]
    segs = {
        "mb": {
            "Consonantal": "+",
            "Sonorant": "+",
            "Continuant": "-",
            "Nasal": "+",
            "Syllabic": "-",
        },
        "b": {
            "Consonantal": "+",
            "Sonorant": "-",
            "Continuant": "-",
            "Nasal": "-",
            "Syllabic": "-",
        },
        "a": {
            "Consonantal": "-",
            "Sonorant": "+",
            "Continuant": "+",
            "Nasal": "-",
            "Syllabic": "+",
        },
    }
    inv = Inventory.from_grid(
        name="t",
        features=feats,
        segments=segs,
        metadata={
            "segment_sequences": {
                "mb": {"Sonorant": ["+", "-"], "Nasal": ["+", "-"]}
            }
        },
    )
    return FeatureEngine(inv)


def test_tag_is_not_a_queryable_feature() -> None:
    """The tag is a group label, not a feature: the engine rejects it as
    a query key, and it is absent from the ± membership caches."""
    eng = _mb_engine()
    with pytest.raises((ValueError, KeyError)):
        eng.find_segments({CONTOUR_GROUP_NAME: "+"})
    assert CONTOUR_GROUP_NAME not in eng.plus_segs
    assert CONTOUR_GROUP_NAME not in eng.minus_segs


def test_tagged_segment_membership_reads_tiers_not_the_tag() -> None:
    """``mb`` is tagged for display, yet the engine's ∃ query returns it
    for both the nasal closure and the oral release, computed from the
    tiers. No query result is ever the tag string."""
    eng = _mb_engine()
    place = {s: n for n, segs in eng.grouped_segments.items() for s in segs}
    assert place["mb"] == CONTOUR_GROUP_NAME
    assert "mb" in eng.find_segments({"Nasal": "+"})
    assert "mb" in eng.find_segments({"Sonorant": "-"})
    for value in ("+", "-"):
        for feat in ("Nasal", "Sonorant", "Continuant"):
            assert CONTOUR_GROUP_NAME not in eng.find_segments({feat: value})
    # A second query surface (natural-class detection) is likewise
    # tier-sourced: the minimal bundles that pick out {mb} are feature
    # bundles, never the display tag, and are found without it.
    bundles = eng.find_all_minimal_bundles(["mb"])
    for bundle in bundles:
        assert CONTOUR_GROUP_NAME not in bundle
        assert CONTOUR_GROUP_NAME not in bundle.values()


# --------------------------------------------------------------------
# Guard 2: the ∃-reach fixture stays faithful to the live engine.
# --------------------------------------------------------------------


def _provider() -> tuple[PhoibleProvider, list[dict]]:
    editor = _SHARED_SRC / "phonology_shared" / "editor"
    idx_path = editor / "_phoible_index.generated.json"
    dat_path = editor / "_phoible_data.generated.json"
    if not (idx_path.exists() and dat_path.exists()):
        pytest.skip("baked PHOIBLE snapshot absent; run bake_phoible first")
    idx = json.loads(idx_path.read_text())
    dat = json.loads(dat_path.read_text())
    return PhoibleProvider(index_table=idx, data_table=dat), idx["inventories"]


def test_fixture_is_internally_consistent() -> None:
    """Schema + totals match the recorded segment map (fast; no corpus)."""
    assert _FIXTURE["schema"] == "contour-tag-reach/1"
    segs = _FIXTURE["segments"]
    assert _FIXTURE["totals"]["unique_glyphs"] == len(segs)
    # Every recorded class is a real spec key or the special ∃-rules.
    known = set(_FIXTURE["class_specs"]) | {"Affricates", "Clicks"}
    for glyph, classes in segs.items():
        assert classes, glyph  # a tagged glyph reaches >= 1 class
        assert set(classes) <= known, (glyph, classes)


def test_fixture_matches_live_engine_over_full_corpus() -> None:
    """Recompute the ENTIRE tagged population and its ∃-reach from the
    live engine and assert it equals the committed fixture, bidirectionally
    and including the totals. This pins the population against BOTH kinds
    of drift the sample missed: a gate change that DROPS the tag (the map
    shrinks) and one that captures MORE (a new glyph appears), each fails
    loudly here rather than slipping past a partial sample. Slow (full
    materialize loop) but the fixture is the multi-membership pass's ground
    truth, so it is pinned exactly."""
    provider, inventories = _provider()
    seg_reach, totals = build_reach_map(provider, inventories)
    assert seg_reach == _FIXTURE["segments"], _REGEN
    assert totals == _FIXTURE["totals"], _REGEN
