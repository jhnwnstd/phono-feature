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
# Mode-switch projection: shared by the desktop's ModeController and
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
    assert set(seed).issubset(
        matched
    ), f"round-trip lost segments: spec={spec}, matched={matched}"


# ----------------------------------------------------------------------
# Natural class computation
# ----------------------------------------------------------------------

# Candidate selections to probe. In Hayes some of the obvious
# linguistic groupings are NOT engine-natural classes because the
# inventory contains underspecified neighbours (for example several
# voiced obstruents beyond /b d ɡ/ share its +/- profile). The test
# below tolerates either outcome: ``compute_natural_class`` either
# returns a bundle that recovers the inputs under
# underspec-compatible matching, or returns ``None``.
# ɡ is the IPA voiced velar stop; ŋ is the velar nasal.
NATURAL_CLASS_CANDIDATES = [
    pytest.param(["b", "d", "ɡ"], id="voiced_stops"),
    pytest.param(["p", "t", "k"], id="voiceless_stops"),
    pytest.param(["m", "n", "ŋ"], id="nasals"),
    pytest.param(["f", "v", "s", "z"], id="fricatives_subset"),
    pytest.param(["l"], id="lateral"),
]


@pytest.mark.parametrize("segments", NATURAL_CLASS_CANDIDATES)
def test_natural_class_bundle_round_trip(
    engine: FeatureEngine, segments: list[str]
) -> None:
    """**Strict round-trip invariant** for
    :py:meth:`compute_natural_class`:

    * a bundle is returned: feeding it back through
      :py:meth:`find_segments` (default strict equality) returns
      EXACTLY the input set. This is the contract the analysis
      pane's bundle display rests on -- any spec the engine lists
      must round-trip when manually typed into the feat→seg pane.
    * ``None`` is returned: the input is not a natural class. The
      cross-check is that no strict bundle exists; equivalently,
      every potential strict bundle (the common-feature subset)
      matches more segments than the input.
    """
    bundle = engine.compute_natural_class(segments)
    if bundle is None:
        common = engine.common_features(segments)
        wider = set(engine.find_segments(common))
        assert set(segments).issubset(
            wider
        ), "common-feature bundle must at least cover the inputs"
        assert wider > set(
            segments
        ), f"engine returned None but no superset exists: {segments}"
        return
    recovered = engine.find_segments(bundle)
    assert sorted(recovered) == sorted(segments), (
        f"strict round-trip broken: bundle {dict(bundle)} returned "
        f"{recovered}, expected {sorted(segments)}"
    )


def test_listed_spec_round_trips_strictly(engine: FeatureEngine) -> None:
    """**Round-trip invariant**: any minimal feature specification
    the engine LISTS for a natural class, when manually typed into
    the feat pane (strict ``find_segments``), returns exactly the
    segments that generated it. This is the contract the analysis
    pane's bundle rendering rests on; a regression here means the
    Class tab can show a spec that doesn't behave as displayed.

    Stress: iterate over every singleton, pair, and triple of
    segments in the fixture inventory and assert every bundle in
    every ``is_natural_class`` response strictly round-trips. If
    the bundle list is empty, the verdict must be False.
    """
    from itertools import combinations

    all_segs = list(engine.segments)
    triples_to_check = (
        list(combinations(all_segs, 1))
        + list(combinations(all_segs, 2))
        + list(combinations(all_segs[:40], 3))
    )
    for combo in triples_to_check:
        segs = list(combo)
        is_nc, bundles = engine.is_natural_class(segs)
        if not is_nc:
            assert (
                bundles == ()
            ), f"{segs}: is_nc=False but bundles non-empty: {bundles!r}"
            continue
        assert bundles, f"{segs}: is_nc=True but no bundles returned"
        for b in bundles:
            recovered = engine.find_segments(dict(b))
            assert sorted(recovered) == sorted(segs), (
                f"{segs}: bundle {dict(b)} does not strictly round-"
                f"trip; recovered={recovered}"
            )


# ----------------------------------------------------------------------
# Natural-class extension suggestions
# ----------------------------------------------------------------------


def test_suggest_natural_class_extension_empty_for_natural_class(
    engine: FeatureEngine,
) -> None:
    """A selection that's already a natural class -> empty list.

    /l/ alone is a natural class per ``NATURAL_CLASS_CASES`` above,
    so the engine should suggest nothing further.
    """
    assert engine.suggest_natural_class_extension(["l"]) == []


def test_suggest_natural_class_extension_completes_partial(
    engine: FeatureEngine,
) -> None:
    """When the selection isn't a natural class, the engine should
    suggest the additional segments needed to complete it.

    In this Hayes inventory /b, d, ɡ/ alone aren't a natural class
    (other voiced stops match the same features); the suggestion
    must include some of those other voiced stops and never the
    already-selected segments.
    """
    selected = ["b", "d", "ɡ"]
    suggested = engine.suggest_natural_class_extension(selected)
    assert suggested, "expected non-empty extension for a partial class"
    assert not set(suggested) & set(
        selected
    ), "suggestion must not re-include selected segments"


def test_suggest_natural_class_extension_empty_input(
    engine: FeatureEngine,
) -> None:
    """Empty selection has no features to extend by -> empty list."""
    assert engine.suggest_natural_class_extension([]) == []


def test_suggest_natural_class_extension_completes_to_natural_class(
    engine: FeatureEngine,
) -> None:
    """**Round-trip invariant**: for any non-natural-class selection,
    the suggested extension MUST actually complete the selection
    into a natural class. Previously the algorithm returned the
    maximal extension (segments sharing the strict ``common_features``),
    but ``is_natural_class`` uses underspec-compatible matching that
    can find tighter bundles closing the class with a SMALLER subset.
    The function now searches for the minimum subset and returns it;
    this test pins that adding the suggestion always closes the class.
    """
    cases = [
        ["b", "d", "ɡ"],
        ["p", "t", "k"],
        ["m", "n"],
    ]
    for selected in cases:
        # Skip cases where any segment is missing from the test
        # inventory (the fixture inventory varies in conftest).
        if any(s not in engine.segments for s in selected):
            continue
        is_nc_before, _ = engine.is_natural_class(selected)
        if is_nc_before:
            continue
        suggested = engine.suggest_natural_class_extension(selected)
        assert suggested, f"{selected}: no suggestion but not a natural class"
        union = selected + list(suggested)
        is_nc_after, _ = engine.is_natural_class(union)
        assert is_nc_after, (
            f"{selected} + suggested {suggested} = {union}; "
            f"is_natural_class still returns False — algorithm is "
            f"inconsistent"
        )


def test_suggest_natural_class_extension_perf_floor(
    engine: FeatureEngine,
) -> None:
    """Perf-regression guard for the fast path in
    :py:meth:`suggest_natural_class_extension`. Before the fast path
    a 50-segment selection on Hayes ran at ~330 ms; the precomputed
    incremental candidate filter brings it to single-digit ms. The
    floor here is generous (50 ms on desktop CPython) so it catches
    a 10x regression while staying noise-tolerant. Skipped if the
    Hayes inventory isn't present.
    """
    import time

    segs = list(engine.segments)
    if len(segs) < 50:
        import pytest

        pytest.skip("fixture inventory too small for the perf floor")
    # Warm up: load Python bytecode + populate any one-time caches.
    engine.suggest_natural_class_extension(segs[:5])
    # Take the best-of-3 to dodge interpreter / GC jitter; the
    # measurement is interactive responsiveness, not steady-state
    # throughput.
    best = float("inf")
    for _ in range(3):
        engine._bundle_cache.clear()
        t0 = time.perf_counter()
        engine.suggest_natural_class_extension(segs[:50])
        best = min(best, (time.perf_counter() - t0) * 1000)
    assert best < 50.0, (
        f"suggest_natural_class_extension(N=50) took {best:.1f} ms; "
        f"perf floor is 50 ms (pre-fast-path baseline was ~330 ms). "
        f"A regression here means each user click in seg-mode will lag."
    )


def test_suggest_natural_class_extension_is_minimal(
    engine: FeatureEngine,
) -> None:
    """**Minimality invariant**: the suggested extension must be a
    minimum-size completion. No PROPER subset of the suggestion
    should also close the natural class. Pins that the algorithm
    doesn't over-suggest.
    """
    from itertools import combinations

    cases = [
        ["b", "d", "ɡ"],
        ["p", "t", "k"],
    ]
    for selected in cases:
        if any(s not in engine.segments for s in selected):
            continue
        if engine.is_natural_class(selected)[0]:
            continue
        suggested = engine.suggest_natural_class_extension(selected)
        if not suggested:
            continue
        # No PROPER subset of the suggestion should also close the
        # class. (Subsets of size |suggested| - 1.)
        if len(suggested) <= 1:
            # k=1 is trivially minimal; nothing to check.
            continue
        smaller_size = len(suggested) - 1
        for subset in combinations(suggested, smaller_size):
            union = selected + list(subset)
            is_nc, _ = engine.is_natural_class(union)
            assert not is_nc, (
                f"{selected}: returned {suggested} of size "
                f"{len(suggested)}, but the smaller subset {list(subset)} "
                f"already completes the natural class — algorithm is "
                f"not minimal"
            )


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
