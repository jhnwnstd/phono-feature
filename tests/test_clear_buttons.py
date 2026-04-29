"""Tests for the Clear buttons. Each panel's Clear should:

1. Wipe its own selection state and visual state.
2. Also wipe any DERIVED display on the OTHER panel (e.g. the feat row
   informational tinting that mirrors a segment selection in seg mode,
   or the matched/unmatched seg button styling that mirrors a feature
   query in feat mode).
3. NEVER touch the other panel's primary state. Clearing segments must
   not corrupt the user's feature query, and vice versa.
"""

from __future__ import annotations

from gui.main_window import Mode
from gui.widgets import SegmentState


def _selected_feat_rows(window) -> set[str]:
    return {f for f, row in window._feat_rows.items() if row._current_value}


def _non_default_seg_buttons(window) -> int:
    return sum(
        1
        for b in window._seg_buttons.values()
        if b._state != SegmentState.DEFAULT
    )


def _feat_rows_with_styling(window) -> int:
    """Rows whose stylesheet is non-empty (i.e. have visible tinting)."""
    return sum(1 for r in window._feat_rows.values() if r.styleSheet())


# ---------------------------------------------------------------------------
# Same-panel Clear: should fully reset the active panel + downstream display
# ---------------------------------------------------------------------------


def test_clear_segments_in_seg_mode_resets_everything(window):
    """In seg mode, clicking Clear on seg panel must wipe segs AND any
    feat-row informational tinting that was derived from those segs."""
    window._on_segment_clicked("b", True)
    window._on_segment_clicked("d", True)
    window._run_pending_update()

    # Sanity: seg-mode update populated feat-row visual styling
    assert _feat_rows_with_styling(window) > 0

    window._clear_segments()

    assert window._selected_segments == []
    assert _non_default_seg_buttons(window) == 0
    assert _selected_feat_rows(window) == set()
    # Feat rows should no longer show seg-derived tinting (badge text reset
    # plus row stylesheet at neutral)
    for row in window._feat_rows.values():
        assert row.badge.text() == "·"  # neutral middle-dot


def test_clear_features_in_feat_mode_resets_everything(window):
    """In feat mode, clicking Clear on feat panel must wipe feats AND the
    matched/unmatched seg button display derived from the query."""
    window._set_mode(Mode.FEAT_TO_SEG)
    window._feat_rows["Voice"]._on_click("+")
    window._feat_rows["Continuant"]._on_click("-")
    window._run_pending_update()

    # Sanity: every seg button got matched/unmatched styling
    assert _non_default_seg_buttons(window) == len(window._seg_buttons)

    window._clear_features()

    assert window._selected_features == {}
    assert _selected_feat_rows(window) == set()
    assert _non_default_seg_buttons(window) == 0


# ---------------------------------------------------------------------------
# Cross-panel Clear: must not corrupt the active panel's primary state
# ---------------------------------------------------------------------------


def test_clear_features_in_seg_mode_preserves_segment_selection(window):
    """REGRESSION: clicking the feat-side Clear in seg mode must NOT silently
    wipe the user's segment selection. Previously this method reset every
    seg button to default, leaving _selected_segments populated but the
    buttons all visually unselected — data and visual state diverged.
    """
    window._on_segment_clicked("b", True)
    window._on_segment_clicked("d", True)
    window._run_pending_update()

    selected_before = list(window._selected_segments)
    selected_button_count = _non_default_seg_buttons(window)

    window._clear_features()

    # _selected_features was already empty in seg mode; clearing is a no-op
    # for that. CRITICAL: the seg-side state must be untouched.
    assert window._selected_segments == selected_before
    assert _non_default_seg_buttons(window) == selected_button_count


def test_clear_segments_in_feat_mode_preserves_feature_query(window):
    """Clicking the seg-side Clear in feat mode must NOT wipe the user's
    feature query. The query lives in _selected_features and the feat row
    visuals — both must survive."""
    window._set_mode(Mode.FEAT_TO_SEG)
    window._feat_rows["Voice"]._on_click("+")
    window._feat_rows["Continuant"]._on_click("-")
    window._run_pending_update()

    feats_before = dict(window._selected_features)
    feat_rows_before = _selected_feat_rows(window)

    window._clear_segments()

    assert window._selected_features == feats_before
    assert _selected_feat_rows(window) == feat_rows_before


# ---------------------------------------------------------------------------
# Symmetry: the two clear methods are structurally mirror-images
# ---------------------------------------------------------------------------


def test_clear_buttons_are_symmetric(window):
    """Behavioral symmetry: clearing in active mode produces equivalent
    fully-reset state regardless of which panel was active."""
    # Seg mode flow: select, clear-segs
    window._on_segment_clicked("b", True)
    window._on_segment_clicked("d", True)
    window._run_pending_update()
    window._clear_segments()
    seg_state_after = (
        list(window._selected_segments),
        dict(window._selected_features),
        _non_default_seg_buttons(window),
        _selected_feat_rows(window),
    )

    # Feat mode flow: select, clear-feats
    window._set_mode(Mode.FEAT_TO_SEG)
    window._feat_rows["Voice"]._on_click("+")
    window._feat_rows["Continuant"]._on_click("-")
    window._run_pending_update()
    window._clear_features()
    feat_state_after = (
        list(window._selected_segments),
        dict(window._selected_features),
        _non_default_seg_buttons(window),
        _selected_feat_rows(window),
    )

    # Both flows should land in the same fully-empty state.
    assert (
        seg_state_after
        == feat_state_after
        == (
            [],  # no selected segments
            {},  # no selected features
            0,  # no non-default seg buttons
            set(),  # no feat rows showing values
        )
    )


def test_silent_clear_in_inventory_reload_resets_both_sides(window):
    """The internal silent=True path used by _apply_mode_to_new_widgets must
    fully reset both data structures and visual state regardless of mode.
    This is what runs when you switch inventories."""
    # Populate state first
    window._on_segment_clicked("b", True)
    window._on_segment_clicked("d", True)
    window._run_pending_update()

    # Simulate the reload path
    window._clear_segments(silent=True)
    window._clear_features(silent=True)

    assert window._selected_segments == []
    assert window._selected_features == {}
    assert _non_default_seg_buttons(window) == 0
    assert _selected_feat_rows(window) == set()
    # silent=True must NOT touch saved_*_state (those preserve toggle history)
    # Set them to known values, then verify they aren't clobbered.
    window._saved_seg_state = ["sentinel"]
    window._saved_feat_state = {"sentinel": "+"}
    window._clear_segments(silent=True)
    window._clear_features(silent=True)
    assert window._saved_seg_state == ["sentinel"]
    assert window._saved_feat_state == {"sentinel": "+"}
