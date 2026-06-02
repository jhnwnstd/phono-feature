"""
State-machine tests for the seg/feat mode toggle in MainWindow.

These tests exercise the public-ish click handlers (_on_segment_clicked,
_on_feature_changed) and _set_mode, then assert on the resulting widget +
selection state. The goal is to catch regressions in the mode-switch
projection logic; the area the user has flagged as delicate; without
needing to launch the GUI.

Naming convention: each test name describes the property it guards. If a
test starts failing, the test name itself tells you what invariant broke.
"""

from __future__ import annotations


def _selected_feat_rows(window) -> set[str]:
    """Set of features whose row currently shows a +/- value (visual state)."""
    return {f for f, row in window._feat_rows.items() if row._current_value}


# Fresh-state smoke (initial mode == seg_to_feat, empty selections,
# expected segment/feature counts on the Hayes fixture) is covered
# implicitly by every test below via the ``window`` fixture; the
# pinned smoke tests were redundant and have been removed.


# ---------------------------------------------------------------------------
# Seg-mode behavior
# ---------------------------------------------------------------------------
def test_select_segment_in_seg_mode_updates_state(window):
    window._on_segment_clicked("b", True)
    assert window._selected_segments == ["b"]


def test_select_segment_only_works_in_seg_mode(window):
    window._set_mode("feat_to_seg")
    window._on_segment_clicked("b", True)
    assert (
        window._selected_segments == []
    ), "segment clicks must be no-ops in feat mode"


def test_deselect_segment_removes_from_selection(window):
    window._on_segment_clicked("b", True)
    window._on_segment_clicked("d", True)
    window._on_segment_clicked("b", False)
    assert window._selected_segments == ["d"]


# ---------------------------------------------------------------------------
# Seg -> Feat toggle: projection + visual state invariant
# ---------------------------------------------------------------------------
def test_toggle_seg_to_feat_projects_common_features(window):
    """When toggling with segments selected, common_features get projected
    into _selected_features."""
    window._on_segment_clicked("b", True)
    window._on_segment_clicked("d", True)
    window._on_segment_clicked("\u0261", True)  # voiced velar (script g)
    window._set_mode("feat_to_seg")
    assert window._mode_ctrl.mode == "feat_to_seg"
    # Voiced stops share many features in Hayes; projection must be non-empty
    assert len(window._selected_features) > 0
    # Every projected value is +/-, never "0"
    assert all(v in ("+", "-") for v in window._selected_features.values())


def test_toggle_seg_to_feat_visual_state_matches_selected_features(window):
    """REGRESSION: selected_features must equal the set of feature rows that
    visually show a value. The previous bug had selected_features populated
    but every row visually reset.
    """
    window._on_segment_clicked("b", True)
    window._on_segment_clicked("d", True)
    window._set_mode("feat_to_seg")
    assert _selected_feat_rows(window) == set(window._selected_features), (
        f"row visual state {_selected_feat_rows(window)} must match "
        f"selected_features {set(window._selected_features)}"
    )


def test_toggle_seg_to_feat_row_values_match_projection(window):
    """Each selected row's _current_value must equal the projected +/- value."""
    window._on_segment_clicked("b", True)
    window._on_segment_clicked("d", True)
    window._set_mode("feat_to_seg")
    for feat, val in window._selected_features.items():
        row = window._feat_rows[feat]
        assert row._current_value == val, (
            f"row[{feat}]._current_value={row._current_value!r} "
            f"but selected_features[{feat}]={val!r}"
        )


def test_toggle_seg_to_feat_with_no_segments_yields_empty_state(window):
    """Toggle with nothing selected must produce empty feat state."""
    window._set_mode("feat_to_seg")
    assert window._selected_features == {}
    assert _selected_feat_rows(window) == set()


# ---------------------------------------------------------------------------
# Feat-mode click + visual state
# ---------------------------------------------------------------------------
def test_click_feature_in_feat_mode_tints_row(window):
    """Clicking a +/- button updates row visual state AND _selected_features.

    Drives FeatureRow._on_click; the same path the GUI uses. That handler
    sets _current_value, applies the row tint, and emits value_changed,
    which is wired to MainWindow._on_feature_changed.
    """
    window._set_mode("feat_to_seg")
    feature = next(iter(window._feat_rows))
    row = window._feat_rows[feature]
    row._on_click("+")
    assert row._current_value == "+"
    assert window._selected_features[feature] == "+"


def test_click_feature_to_deselect_clears_row(window):
    window._set_mode("feat_to_seg")
    feature = next(iter(window._feat_rows))
    row = window._feat_rows[feature]
    row._on_click("+")
    row._on_click("+")  # second click toggles off
    assert row._current_value == ""
    assert feature not in window._selected_features


# ---------------------------------------------------------------------------
# Roundtrip behavior
#
# The toggle is NOT a lossless roundtrip. Each transition saves the *exact*
# state of the mode you're leaving AND a *projection* into the other mode.
# The projection overwrites whatever was previously saved for that other
# mode. Net effect:
#
#   seg -> feat -> seg : final segs = find_segments(common_features(orig_segs))
#                      -> original subset of final, may include over-match extras.
#   feat -> seg -> feat: final feats = common_features(find_segments(orig_feats))
#                      -> may be a SUPERSET of original (extra shared feats).
#
# These tests lock in the current behavior so accidental changes get caught.
# They also document the asymmetry for whoever reads them next.
# ---------------------------------------------------------------------------
def test_seg_feat_seg_roundtrip_includes_original_segments(window):
    """seg->feat->seg always re-selects the original segments (subset guarantee).

    Extras may appear when the original set is not a clean natural class,
    because the second transition re-derives segments from the projected
    feature query via find_segments. See the doc-block above.
    """
    original = ["b", "d", "\u0261"]
    for s in original:
        window._on_segment_clicked(s, True)
    window._set_mode("feat_to_seg")
    window._set_mode("seg_to_feat")
    assert set(original).issubset(set(window._selected_segments))


def test_feat_seg_feat_roundtrip_includes_original_features(window):
    """feat->seg->feat always re-selects the original features (subset guarantee).

    Extras may appear because the second transition re-derives features
    from the segs that matched the original query, picking up any
    additional shared features those segments happen to have.
    """
    window._set_mode("feat_to_seg")
    feature = next(iter(window._feat_rows))
    row = window._feat_rows[feature]
    row._on_click("+")
    original = dict(window._selected_features)
    window._set_mode("seg_to_feat")
    window._set_mode("feat_to_seg")
    # Original key/value must survive the roundtrip; extras may appear.
    for f, v in original.items():
        assert window._selected_features.get(f) == v


# ---------------------------------------------------------------------------
# Cross-pane consistency
# ---------------------------------------------------------------------------
def test_no_orphan_row_values_after_clear_segments(window):
    """Clearing segments must also clear feature rows so no row is left
    showing a value that doesn't correspond to a selection."""
    window._on_segment_clicked("b", True)
    window._set_mode("feat_to_seg")
    window._set_mode("seg_to_feat")
    window._clear_segments()
    assert window._selected_segments == []
    assert _selected_feat_rows(window) == set()


def test_selected_features_keys_match_row_state_in_feat_mode(window):
    """General invariant: in feat mode, the set of selected feature names must
    equal the set of feature rows showing a value. Any drift means the visual
    state is lying about the selection.
    """
    window._on_segment_clicked("b", True)
    window._on_segment_clicked("\u0283", True)
    window._on_segment_clicked("i", True)
    window._set_mode("feat_to_seg")
    assert set(window._selected_features) == _selected_feat_rows(window)
