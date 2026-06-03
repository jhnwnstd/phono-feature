"""Tests for :py:mod:`phonology_features.gui.shared.mode_logic`.

Pure-Python contract tests for the top-level seg/feat mode transition.
"""

from __future__ import annotations

import json
from pathlib import Path

from phonology_engine.feature_engine import FeatureEngine
from phonology_engine.inventory import Inventory
from phonology_features.gui.shared.mode_logic import (
    AnalysisTabId,
    ClearScope,
    Mode,
    clear_semantics_for,
    mode_status_text,
    preserved_analysis_tab,
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


# ---------------------------------------------------------------------------
# preserved_analysis_tab (Stage 1).
#
# Pins the rule: keep the active tab if it's still valid for the
# new state, otherwise return CLASS. The only way the current tab
# becomes invalid is for CONTRASTS to be active while
# contrasts_enabled=False. Both UIs consume this; the parity is
# what fixed the desktop-only "Class snap on mode toggle" bug.
# ---------------------------------------------------------------------------


def test_preserved_analysis_tab_keeps_class_and_features_unconditionally() -> (
    None
):
    """CLASS and FEATURES are always valid; preservation never
    snaps away from them regardless of contrasts_enabled."""
    for enabled in (True, False):
        assert (
            preserved_analysis_tab(
                AnalysisTabId.CLASS,
                contrasts_enabled=enabled,
            )
            is AnalysisTabId.CLASS
        )
        assert (
            preserved_analysis_tab(
                AnalysisTabId.FEATURES,
                contrasts_enabled=enabled,
            )
            is AnalysisTabId.FEATURES
        )


def test_preserved_analysis_tab_snaps_only_when_contrasts_disabled_and_active() -> (
    None
):
    """CONTRASTS is preserved when enabled, snaps to CLASS when
    disabled. This single transition is the entire snap-back rule."""
    assert (
        preserved_analysis_tab(
            AnalysisTabId.CONTRASTS,
            contrasts_enabled=True,
        )
        is AnalysisTabId.CONTRASTS
    )
    assert (
        preserved_analysis_tab(
            AnalysisTabId.CONTRASTS,
            contrasts_enabled=False,
        )
        is AnalysisTabId.CLASS
    )


def test_preserved_analysis_tab_accepts_string_input() -> None:
    """``AnalysisTabId`` is a StrEnum so the bridge can pass plain
    strings. The helper coerces and returns the enum, preserving
    parity between Python-typed callers and the JS-side string
    consumers."""
    assert (
        preserved_analysis_tab(
            "features",
            contrasts_enabled=False,
        )
        is AnalysisTabId.FEATURES
    )
    assert (
        preserved_analysis_tab(
            "contrasts",
            contrasts_enabled=False,
        )
        is AnalysisTabId.CLASS
    )
    assert (
        preserved_analysis_tab(
            "class",
            contrasts_enabled=True,
        )
        is AnalysisTabId.CLASS
    )


def test_preserved_analysis_tab_rejects_unknown_string() -> None:
    """An unknown tab id is a programming error, not a state to
    silently recover from."""
    import pytest as _pytest

    with _pytest.raises(ValueError):
        preserved_analysis_tab("wat", contrasts_enabled=True)


# ---------------------------------------------------------------------------
# clear_semantics_for (Stage 2).
#
# Pins the per-scope effect record. ``main_window._reset_both_sides``
# reads each field; the web's ``clearAll`` consumes the
# USER_INITIATED record directly. Drift between desktop and web on
# this rule was exactly the kind of "two code paths, two answers"
# pattern this stage exists to delete.
# ---------------------------------------------------------------------------


def test_clear_semantics_for_user_initiated_resets_everything() -> None:
    """USER_INITIATED is the Clear-button scope: the user expects
    a clean slate. Every effect fires."""
    sem = clear_semantics_for(ClearScope.USER_INITIATED)
    assert sem.reset_active_selection is True
    assert sem.reset_saved_state is True
    assert sem.reset_analysis_pane is True
    assert sem.collapse_expanded_analysis is True


def test_clear_semantics_for_silent_load_preserves_saved_state() -> None:
    """SILENT_LOAD runs during an inventory swap. Visible selection
    is reset (the new inventory has different segments) but the
    saved cross-mode state, analysis pane content, and any expand
    survive -- the user did not press Clear."""
    sem = clear_semantics_for(ClearScope.SILENT_LOAD)
    assert sem.reset_active_selection is True
    assert sem.reset_saved_state is False
    assert sem.reset_analysis_pane is False
    assert sem.collapse_expanded_analysis is False


def test_clear_semantics_factory_is_exhaustive() -> None:
    """Every ``ClearScope`` value must yield a record. A future
    scope that ships without a corresponding branch in
    ``clear_semantics_for`` would silently fall through to the
    raise at the bottom of the function; that's a programmer
    error this test forces to surface as a hard fail."""
    for scope in ClearScope:
        sem = clear_semantics_for(scope)
        assert sem is not None


def test_clear_semantics_for_rejects_unknown_scope() -> None:
    """An unknown scope string is a programming error."""
    import pytest as _pytest

    with _pytest.raises(ValueError):
        clear_semantics_for("wat")


def test_clear_semantics_web_mirror_matches_python() -> None:
    """The web's ``CLEAR_SEMANTICS_USER_INITIATED`` JS object in
    main.js is a manual mirror of the Python factory's output for
    the USER_INITIATED scope. Pin the EXACT field values here so
    any future change to the Python factory MUST be matched by a
    parallel change to main.js; otherwise a future drift slips
    through CI silently."""
    sem = clear_semantics_for(ClearScope.USER_INITIATED)
    expected_mirror = {
        "reset_active_selection": True,
        "reset_saved_state": True,
        "reset_analysis_pane": True,
        "collapse_expanded_analysis": True,
    }
    actual = {
        "reset_active_selection": sem.reset_active_selection,
        "reset_saved_state": sem.reset_saved_state,
        "reset_analysis_pane": sem.reset_analysis_pane,
        "collapse_expanded_analysis": sem.collapse_expanded_analysis,
    }
    assert actual == expected_mirror, (
        "Python ClearSemantics(USER_INITIATED) has drifted from the"
        " hand-mirrored constant in web/main.js"
        " CLEAR_SEMANTICS_USER_INITIATED; update both together."
    )
    # Also assert the mirror exists in main.js by grepping the
    # source. The keys must be present so a renamed field is caught
    # statically. If the web grows additional ClearScope handling,
    # extend this check.
    from pathlib import Path

    main_js = (
        Path(__file__).resolve().parents[2] / "web" / "main.js"
    ).read_text(encoding="utf-8")
    assert "CLEAR_SEMANTICS_USER_INITIATED" in main_js
    for key in expected_mirror:
        assert key in main_js, (
            f"ClearSemantics field {key!r} missing from web/main.js"
            f" CLEAR_SEMANTICS_USER_INITIATED mirror"
        )
