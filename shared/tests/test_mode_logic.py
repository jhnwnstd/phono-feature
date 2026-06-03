"""Tests for :py:mod:`phonology_shared.render.mode_logic`.

Pure-Python contract tests for the top-level seg/feat mode transition.
"""

from __future__ import annotations

import json
from pathlib import Path

from phonology_shared.engine.feature_engine import FeatureEngine
from phonology_shared.engine.inventory import Inventory
from phonology_shared.render.mode_logic import (
    Mode,
    mode_status_text,
    project_mode_transition,
)

INVENTORIES_DIR = Path(__file__).resolve().parents[2] / "desktop" / "inventories"


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
    # FEAT→SEG carries the natural class (the strict matches of
    # the query) over as the new SEG selection. The user sees in
    # SEG the same segments they were just inspecting in FEAT.
    assert sorted(transition.selected_segments) == sorted(
        engine.find_segments(spec)
    )


def test_feat_to_seg_carries_natural_class_over() -> None:
    """**FEAT→SEG carry-over invariant**: switching from FEAT to
    SEG sets the SEG selection to the natural class the FEAT
    query picked out -- the same segments that were highlighted
    in FEAT mode.
    """
    engine = _engine("english_features.json")
    spec = {"High": "+", "Front": "+"}
    transition = project_mode_transition(
        Mode.FEAT_TO_SEG,
        Mode.SEG_TO_FEAT,
        selected_segments=[],
        selected_features=spec,
        engine=engine,
    )
    expected = engine.find_segments(spec)
    assert sorted(transition.selected_segments) == sorted(expected)
    # And what FEAT was showing as the highlighted natural class is
    # exactly what SEG is now showing as the selection.
    is_nc, _ = engine.is_natural_class(transition.selected_segments)
    assert is_nc


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
            assert sorted(engine.find_segments(dict(b))) == sorted(landed), (
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
