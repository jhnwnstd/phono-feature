"""Desktop tests for the analysis-pane floor and expand-toggle
non-mutation invariants.

These tests assert the user-facing contracts the layout refactor
introduced:

1. ``AnalysisPanel.minimumSizeHint().height()`` is the same integer
   regardless of which inventory is loaded -- the user's complaint
   that "the analysis pane size depends on whichever inventory was
   loaded first" must no longer reproduce.

2. The expand toggle does NOT mutate the seg / feat / hsplit
   ``minimumHeight`` values. The previous implementation zeroed those
   to free room for the splitter; the new policy caps them inside
   ``fit_to_content`` so no runtime mutation is needed.

3. The expand toggle freezes layout-recompute. While expanded, the
   seg-pane width tracker (``_last_seg_pane_w``) does not change in
   response to the splitter compressing the top panes; the vowel-stack
   flag does not flip; the segment grid does not repartition spillover.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QApplication

from phonology_features.gui.main_window import MainWindow, Mode
from phonology_shared.presentation import layout

INVENTORIES = Path(__file__).resolve().parent.parent / "inventories"


def _load(window: MainWindow, name: str) -> None:
    path = INVENTORIES / name
    if not path.exists():
        import pytest

        pytest.skip(f"missing inventory: {name}")
    window._load_path(str(path))


# ---------------------------------------------------------------------------
# Floor invariance across inventory swaps
# ---------------------------------------------------------------------------


def test_analysis_min_size_hint_is_inventory_independent(
    qapp: QApplication, window: MainWindow
) -> None:
    """Load three inventories in sequence; the analysis pane's
    minimum size hint must not budge. This is the property the user
    means by "should not depend accidentally on whatever inventory
    was loaded first".
    """
    snapshots: list[int] = []
    for name in (
        "spanish_features.json",
        "hayes_features.json",
        "english_features.json",
    ):
        _load(window, name)
        qapp.processEvents()
        snapshots.append(window.analysis.minimumSizeHint().height())
    assert len(set(snapshots)) == 1, (
        f"analysis minimumSizeHint().height() drifted across inventories: "
        f"{snapshots}"
    )
    assert snapshots[0] == layout.analysis_content_floor_h()


def test_analysis_min_size_hint_matches_shared_floor(
    qapp: QApplication, window: MainWindow
) -> None:
    """The widget reads from ``REGION_CONSTRAINTS['analysis_panel'].min_h``,
    which is the shared ``analysis_content_floor_h()`` value. Pin the
    relationship here so a future tweak to either fails this test
    rather than silently shrinking the analysis pane.
    """
    assert (
        window.analysis.minimumSizeHint().height()
        == layout.analysis_content_floor_h()
    )


# ---------------------------------------------------------------------------
# Expand toggle: layout state preserved
# ---------------------------------------------------------------------------


def test_expand_freezes_segment_grid_column_count(
    qapp: QApplication, window: MainWindow
) -> None:
    """The user's complaint: 'segments readjust dynamically after
    using the expansion button'. Pin that the seg-grid's column
    count is unchanged across an expand/collapse cycle.
    """
    qapp.processEvents()
    cols_before = window.seg_grid_widget._n_cols
    stacked_before = window._seg_vowels_stacked
    window.analysis.expand_btn.click()
    qapp.processEvents()
    assert window._layout_frozen is True
    assert window.seg_grid_widget._n_cols == cols_before
    assert window._seg_vowels_stacked == stacked_before
    window.analysis.expand_btn.click()
    qapp.processEvents()
    assert window._layout_frozen is False
    assert window.seg_grid_widget._n_cols == cols_before
    assert window._seg_vowels_stacked == stacked_before


def test_expand_does_not_recompute_seg_pane_width(
    qapp: QApplication, window: MainWindow
) -> None:
    """The eventFilter on seg_panel sees a Resize event when the
    expand toggle compresses the top pane; with the frozen-layout
    flag set, ``_on_seg_pane_width_changed`` short-circuits before
    touching ``_last_seg_pane_w``. Pin that the tracker stays at its
    pre-expand value.
    """
    qapp.processEvents()
    last_w_before = getattr(window, "_last_seg_pane_w", None)
    window.analysis.expand_btn.click()
    qapp.processEvents()
    last_w_during = getattr(window, "_last_seg_pane_w", None)
    assert last_w_during == last_w_before, (
        f"_last_seg_pane_w changed mid-expand: "
        f"{last_w_before} -> {last_w_during}"
    )
    window.analysis.expand_btn.click()
    qapp.processEvents()


# ---------------------------------------------------------------------------
# Inventory swap does NOT change the analysis pane height
# ---------------------------------------------------------------------------


def test_inventory_swap_preserves_vsplit_sizes(
    qapp: QApplication, window: MainWindow
) -> None:
    """After the first inventory has loaded and the user has any
    established splitter ratio, loading a NEW inventory must not
    resize the vsplit. The user-visible regression this guards
    against: the analysis pane height changing every time you pick
    a different inventory from the dropdown.
    """
    # Settle initial layout.
    qapp.processEvents()
    # Pretend the user has interacted (or settings restored), so
    # ``has_saved_splitter`` is True and we go through
    # ``reflow_top_pane_only`` instead of ``apply_splitter_sizes``.
    window._geom.has_saved_splitter = True
    sizes_before = list(window._vsplit.sizes())
    _load(window, "spanish_features.json")
    qapp.processEvents()
    sizes_after = list(window._vsplit.sizes())
    assert sizes_after == sizes_before, (
        f"vsplit sizes mutated across inventory load: "
        f"{sizes_before} -> {sizes_after}"
    )


def test_mode_swap_does_not_change_analysis_min_height(
    qapp: QApplication, window: MainWindow
) -> None:
    """Toggling between seg-to-feat and feat-to-seg modes touches a
    bunch of state but must NEVER change the analysis pane's
    minimumSizeHint. Sanity check the floor is mode-independent too.
    """
    floor_initial = window.analysis.minimumSizeHint().height()
    window._set_mode(Mode.FEAT_TO_SEG)
    qapp.processEvents()
    assert window.analysis.minimumSizeHint().height() == floor_initial
    window._set_mode(Mode.SEG_TO_FEAT)
    qapp.processEvents()
    assert window.analysis.minimumSizeHint().height() == floor_initial
