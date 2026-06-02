"""Tests for :py:mod:`phonology_features.gui.shared.mode_logic`.

Pure-Python contract tests for the top-level seg/feat mode transition.
"""

from __future__ import annotations

import json
from pathlib import Path

from phonology_engine.feature_engine import FeatureEngine
from phonology_engine.inventory import Inventory
from phonology_features.gui.shared.mode_logic import (
    Mode,
    mode_status_text,
    project_mode_transition,
)

INVENTORIES_DIR = Path(__file__).resolve().parents[1] / "inventories"


def _engine(name: str) -> FeatureEngine:
    path = INVENTORIES_DIR / name
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    return FeatureEngine(Inventory.parse(raw, source=str(path)))


def test_project_mode_transition_seg_to_feat() -> None:
    engine = _engine("hayes_features.json")
    segs = ["b", "d", "ɡ"]
    transition = project_mode_transition(
        Mode.SEG_TO_FEAT,
        Mode.FEAT_TO_SEG,
        selected_segments=segs,
        selected_features={},
        engine=engine,
    )
    assert transition.saved_seg_state == segs
    assert transition.selected_segments == []
    assert transition.saved_feat_state == transition.selected_features
    assert transition.saved_feat_state["Voice"] == "+"
    # SEG→FEAT with a non-empty selection marks the projected FEAT
    # query as ``"projected"`` so the FEAT-mode analysis preserves
    # the original seg set rather than doing a strict re-query that
    # would drop members whose values became '0' on the projected
    # features.
    assert transition.feature_query_origin == "projected"


def test_seg_to_feat_with_empty_selection_stays_typed() -> None:
    """No selection => no projection. ``feature_query_origin``
    stays ``"typed"`` so the FEAT-mode analysis behaves like a
    fresh, user-typed query."""
    engine = _engine("hayes_features.json")
    transition = project_mode_transition(
        Mode.SEG_TO_FEAT,
        Mode.FEAT_TO_SEG,
        selected_segments=[],
        selected_features={},
        engine=engine,
    )
    assert transition.feature_query_origin == "typed"
    assert transition.saved_seg_state == []
    assert transition.saved_feat_state == {}


def test_project_mode_transition_feat_to_seg() -> None:
    engine = _engine("hayes_features.json")
    spec = {"Voice": "+"}
    transition = project_mode_transition(
        Mode.FEAT_TO_SEG,
        Mode.SEG_TO_FEAT,
        selected_segments=[],
        selected_features=spec,
        engine=engine,
    )
    assert transition.saved_feat_state == spec
    assert transition.selected_features == {}
    assert set(engine.find_segments(spec)).issuperset(
        transition.selected_segments
    )
    # FEAT→SEG never marks the (next-mode's) FEAT query as
    # projected: we're leaving FEAT, not entering it.
    assert transition.feature_query_origin == "typed"


def test_feat_to_seg_projection_is_always_a_natural_class() -> None:
    """**Cross-mode display invariant**: in FEAT mode the matched
    segments highlighted in the segment grid are by construction
    a natural class characterised by the active query. Switching
    to SEG mode must therefore land on a selection that the SEG
    analysis reports as a natural class -- otherwise the display
    contradicts the engine.

    Pinned across a fan of representative queries so a future
    drift between ``project_mode_transition`` (which derives the
    seg selection via ``find_segments``) and
    :py:meth:`is_natural_class` fails loudly.
    """
    from phonology_engine.feature_engine import (
        FeatureEngine,  # noqa: F401  (kept for type clarity)
    )

    engine = _engine("hayes_features.json")
    queries = [
        {"Voice": "+"},
        {"Nasal": "+"},
        {"Voice": "-", "Continuant": "-"},
        {"Voice": "+", "Sonorant": "+"},
        {"Continuant": "+", "Voice": "-"},
    ]
    for spec in queries:
        transition = project_mode_transition(
            Mode.FEAT_TO_SEG,
            Mode.SEG_TO_FEAT,
            selected_segments=[],
            selected_features=spec,
            engine=engine,
        )
        landed = transition.selected_segments
        if not landed:
            continue
        is_nc, bundles = engine.is_natural_class(landed)
        assert is_nc, (
            f"FEAT→SEG landed on {landed} (from query {spec}) and "
            f"the SEG analysis reports NOT a natural class. The "
            f"display in FEAT mode says these segments form a "
            f"class; the SEG analysis must agree."
        )
        # Strict round-trip: at least one bundle (typically the
        # query itself, modulo redundancy) round-trips to ``landed``.
        assert bundles
        for b in bundles:
            assert sorted(engine.find_segments(dict(b))) == sorted(
                landed
            ), (
                f"FEAT→SEG round-trip broken: bundle {dict(b)} for "
                f"{landed} did not strictly round-trip."
            )


def test_project_mode_transition_without_engine_degrades_cleanly() -> None:
    transition = project_mode_transition(
        Mode.SEG_TO_FEAT,
        Mode.FEAT_TO_SEG,
        selected_segments=["b"],
        selected_features={},
        engine=None,
    )
    assert transition.saved_seg_state == ["b"]
    assert transition.saved_feat_state == {}
    assert transition.selected_segments == []
    assert transition.selected_features == {}


def test_mode_status_texts() -> None:
    assert mode_status_text(Mode.SEG_TO_FEAT, has_engine=False).startswith(
        "Select an inventory"
    )
    assert mode_status_text(Mode.SEG_TO_FEAT, has_engine=True).startswith(
        "Click a segment"
    )
    assert mode_status_text(Mode.FEAT_TO_SEG, has_engine=True).startswith(
        "Toggle feature values"
    )
