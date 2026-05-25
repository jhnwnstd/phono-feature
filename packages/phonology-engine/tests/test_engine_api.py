"""
Public-API tests for ``phonology_engine``.

These exercise the engine without any PyQt6 import path. They double as the
smoke test the README points new users at: a clean run here proves the
install works and the API behaves correctly against the Hayes inventory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from phonology_engine.feature_engine import FeatureEngine
from phonology_engine.geometry import GeometryAnalyzer


def _find_repo_root() -> Path:
    """Walk up from this file until we find the workspace root.

    The bundled inventories currently ship with the desktop app at
    ``app/inventories/``; the engine package is at
    ``packages/phonology-engine/``. From either depth, the workspace
    root is the first ancestor that contains both ``app`` and
    ``packages`` directories.
    """
    for ancestor in Path(__file__).resolve().parents:
        if (ancestor / "app").is_dir() and (ancestor / "packages").is_dir():
            return ancestor
    raise RuntimeError("could not locate workspace root from test file")


REPO_ROOT = _find_repo_root()
HAYES_INVENTORY = str(
    REPO_ROOT / "app" / "inventories" / "hayes_features.json"
)


@pytest.fixture(scope="module")
def engine() -> FeatureEngine:
    """One Hayes-loaded engine shared across the module."""
    return FeatureEngine.from_path(HAYES_INVENTORY)


# ----------------------------------------------------------------------
# Inventory loading
# ----------------------------------------------------------------------


def test_metadata_present(engine: FeatureEngine) -> None:
    assert "name" in engine.metadata
    assert "Hayes" in engine.metadata["name"]


def test_inventory_is_nonempty(engine: FeatureEngine) -> None:
    assert len(engine.segments) > 0
    assert len(engine.features) > 0


# ----------------------------------------------------------------------
# Segment-feature lookup
# ----------------------------------------------------------------------


def test_segment_features_complete_for_b(engine: FeatureEngine) -> None:
    """Every feature in the inventory must be set on every segment."""
    feats = engine.get_segment_features("b")
    assert set(feats.keys()) == set(engine.features)


def test_b_is_voiced_stop(engine: FeatureEngine) -> None:
    feats = engine.get_segment_features("b")
    assert feats["Voice"] == "+"
    assert feats["Continuant"] == "-"


def test_unknown_segment_raises(engine: FeatureEngine) -> None:
    with pytest.raises(KeyError):
        engine.get_segment_features("zzz_not_a_segment")


# ----------------------------------------------------------------------
# Feature-driven segment lookup
# ----------------------------------------------------------------------


def test_find_segments_returns_voiced_stops(engine: FeatureEngine) -> None:
    voiced_stops = engine.find_segments({"Voice": "+", "Continuant": "-"})
    # ɡ = IPA voiced velar; the canonical voiced-stop trio must all be in.
    assert {"b", "d", "ɡ"}.issubset(set(voiced_stops))


def test_find_segments_unknown_feature_raises(engine: FeatureEngine) -> None:
    with pytest.raises(KeyError):
        engine.find_segments({"NotAFeature": "+"})


# ----------------------------------------------------------------------
# Mode-switch projection: shared by the desktop's _ModeController and
# the web bridge so toggling modes produces identical pre-filled
# states across both UIs.
# ----------------------------------------------------------------------
def test_project_segments_to_features_empty(engine: FeatureEngine) -> None:
    assert engine.project_segments_to_features([]) == {}


def test_project_segments_to_features_drops_zero(
    engine: FeatureEngine,
) -> None:
    """Only '+' / '-' values survive; '0' values are dropped so the
    projected query doesn't pin features the user didn't explicitly
    set."""
    projection = engine.project_segments_to_features(["b", "d", "ɡ"])
    assert all(v in ("+", "-") for v in projection.values())


def test_project_round_trips_to_natural_class(
    engine: FeatureEngine,
) -> None:
    """Projecting a natural class to a feature query and then
    matching segments against that query must include every input
    segment. This is the round-trip the GUI relies on: seg→feat→seg
    on a natural class must not silently lose the original segments.
    """
    seed = ["b", "d", "ɡ"]
    spec = engine.project_segments_to_features(seed)
    matched = set(engine.find_segments(spec))
    assert set(seed).issubset(matched), (
        f"round-trip lost segments: spec={spec}, matched={matched}"
    )


# ----------------------------------------------------------------------
# Natural class computation
# ----------------------------------------------------------------------

# ɡ = IPA voiced velar stop; ŋ = IPA velar nasal.
NATURAL_CLASS_CASES = [
    pytest.param(["b", "d", "ɡ"], id="voiced_stops"),
    pytest.param(["p", "t", "k"], id="voiceless_stops"),
    pytest.param(["m", "n", "ŋ"], id="nasals"),
    pytest.param(["f", "v", "s", "z"], id="fricatives_subset"),
    pytest.param(["l"], id="lateral"),
]


@pytest.mark.parametrize("segments", NATURAL_CLASS_CASES)
def test_natural_class_bundle_recovers_originals(
    engine: FeatureEngine, segments: list[str]
) -> None:
    """The bundle returned by ``compute_natural_class`` must, when fed back
    into ``find_segments``, include all of the input segments.

    The engine's contract allows the returned class to be a superset of the
    input (a true minimal class isn't always achievable); we assert that
    direction here without demanding strict equality.
    """
    bundle = engine.compute_natural_class(segments)
    assert bundle is not None
    recovered = set(engine.find_segments(bundle))
    assert set(segments).issubset(
        recovered
    ), f"bundle {bundle} did not recover {segments}: got {recovered}"


# ----------------------------------------------------------------------
# Distance / nearest neighbors
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b"),
    [("b", "d"), ("b", "p"), ("b", "m"), ("b", "v")],
)
def test_segment_distance_is_nonneg_int(
    engine: FeatureEngine, a: str, b: str
) -> None:
    d = engine.segment_distance(a, b)
    assert isinstance(d, int)
    assert d >= 0


def test_distance_is_symmetric(engine: FeatureEngine) -> None:
    assert engine.segment_distance("b", "p") == engine.segment_distance(
        "p", "b"
    )


def test_distance_to_self_is_zero(engine: FeatureEngine) -> None:
    assert engine.segment_distance("b", "b") == 0


def test_nearest_neighbors_returns_requested_count(
    engine: FeatureEngine,
) -> None:
    neighbors = engine.find_nearest_segments("b", n=5)
    assert len(neighbors) == 5
    for entry in neighbors:
        assert isinstance(entry, tuple) and len(entry) == 2
        sym, dist = entry
        assert isinstance(sym, str)
        assert isinstance(dist, int)
        assert dist >= 0


def test_nearest_neighbors_sorted_by_distance(engine: FeatureEngine) -> None:
    neighbors = engine.find_nearest_segments("b", n=10)
    distances = [d for _, d in neighbors]
    assert distances == sorted(distances)


# ----------------------------------------------------------------------
# Inventory statistics
# ----------------------------------------------------------------------


def test_inventory_stats_has_required_keys(engine: FeatureEngine) -> None:
    stats = engine.get_inventory_stats()
    expected = {
        "segment_count",
        "feature_count",
        "contrastive_features",
        "avg_feature_distance",
    }
    assert expected.issubset(stats.keys())


def test_inventory_stats_counts_match(engine: FeatureEngine) -> None:
    stats = engine.get_inventory_stats()
    assert stats["segment_count"] == len(engine.segments)
    assert stats["feature_count"] == len(engine.features)


# ----------------------------------------------------------------------
# Feature geometry inference
#
# Runs permutation tests across every feature pair. Fast on the Hayes
# inventory (~0.1 s) thanks to the engine's vectorized inner loop; kept
# in the default suite because geometry inference is part of the public
# contract.
# ----------------------------------------------------------------------


def test_geometry_analysis_produces_dependencies(
    engine: FeatureEngine,
) -> None:
    analyzer = GeometryAnalyzer(engine)
    analyzer.analyze()
    deps = analyzer.get_dependency_summary()
    assert isinstance(deps, list)
    assert len(deps) > 0
    for dep in deps:
        assert {"child", "parent", "coverage", "confidence"}.issubset(
            dep.keys()
        )
        assert dep["confidence"] in {"high", "medium", "low"}
        assert 0.0 <= dep["coverage"] <= 1.0
