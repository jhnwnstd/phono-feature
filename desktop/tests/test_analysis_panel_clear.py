"""Invariant tests for :py:meth:`AnalysisPanel.clear`.

The panel grows new display cues over time (tab colour, tab enable,
active tab, chips strip, body content). Each new cue is a new way
for state to leak across a Clear or mode switch and surface stale
information to the user. These tests pin the contract that
``clear()`` returns the panel to its post-construction state,
observably equal across every cue, so a future regression breaks
here instead of in the UI.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from phonology_features.gui.widgets import AnalysisPanel


@pytest.fixture()
def panel(qapp: QApplication) -> AnalysisPanel:
    return AnalysisPanel()


def test_clear_resets_class_state_to_neutral(panel: AnalysisPanel) -> None:
    """Painting a green/red Class tab then calling clear must wipe
    the colour back to neutral. Regression: previously the tab kept
    its green/red background after the user hit Clear because
    ``clear()`` skipped ``_apply_class_state``.
    """
    panel.set_sections(
        "<p>Selected (3)</p>",
        "<p>specs</p>",
        "<p>features</p>",
        "<p>contrasts</p>",
        class_state="not_natural",
    )
    assert panel._class_state == "not_natural"
    panel.clear()
    assert panel._class_state == "neutral"
    stylesheet = panel.tabs.styleSheet()
    assert (
        "natural" not in stylesheet.lower() or "neutral" in stylesheet.lower()
    )


def test_clear_reenables_contrasts_tab(panel: AnalysisPanel) -> None:
    """A previously-disabled Contrasts tab (FEAT mode, or any legacy
    single-segment-disables path) must come back enabled after
    clear, otherwise the user is stuck with a greyed tab even after
    starting over.
    """
    panel.set_sections("", "", "", "", contrasts_enabled=False)
    assert not panel.tabs.isTabEnabled(panel._TAB_CONTRASTS_IDX)
    panel.clear()
    assert panel.tabs.isTabEnabled(panel._TAB_CONTRASTS_IDX)


def test_clear_returns_to_class_tab(panel: AnalysisPanel) -> None:
    """Clear must drop the active tab back to Class so the user
    doesn't land on an empty Features/Contrasts body. Pins literal
    indices (Class=0, Features=1) so reshuffling the tab order
    surfaces here rather than silently passing."""
    panel.set_sections(
        "<p>x</p>", "<p>y</p>", "<p>z</p>", "<p>w</p>", contrasts_enabled=True
    )
    panel.tabs.setCurrentIndex(1)  # Features
    assert panel.tabs.currentIndex() == 1
    panel.clear()
    assert panel.tabs.currentIndex() == 0  # Class


def test_clear_hides_selection_strip(panel: AnalysisPanel) -> None:
    """The chips strip must be hidden after clear so it doesn't
    reserve its 38-px row above the tabs for nothing."""
    panel.set_sections(
        "<p>Selected (1): /b/</p>", "", "", "", contrasts_enabled=True
    )
    assert (
        panel.selection_label.isVisibleTo(panel)
        or panel.selection_label.isVisible()
    )
    panel.clear()
    assert not panel.selection_label.isVisible()


def test_clear_empties_all_tab_bodies(panel: AnalysisPanel) -> None:
    """Every tab body must be empty after clear so no stale HTML
    survives across mode swaps."""
    panel.set_sections("<p>sel</p>", "<p>cls</p>", "<p>feat</p>", "<p>con</p>")
    panel.clear()
    assert panel._tab_class.toPlainText().strip() == ""
    assert panel._tab_features.toPlainText().strip() == ""
    assert panel._tab_contrasts.toPlainText().strip() == ""
    assert panel.selection_label.toPlainText().strip() == ""


def test_clear_matches_construction_state(panel: AnalysisPanel) -> None:
    """The strongest invariant: after Clear, the panel is
    observably equal to a freshly-constructed one across every
    cue we track. New cues added later should extend this test."""
    panel.set_sections(
        "<p>sel</p>",
        "<p>cls</p>",
        "<p>feat</p>",
        "<p>con</p>",
        contrasts_enabled=False,
        class_state="natural",
    )
    panel.tabs.setCurrentIndex(panel._TAB_FEATURES_IDX)
    panel.clear()
    fresh = AnalysisPanel()
    assert panel._class_state == fresh._class_state
    assert panel.tabs.isTabEnabled(panel._TAB_CONTRASTS_IDX) == (
        fresh.tabs.isTabEnabled(fresh._TAB_CONTRASTS_IDX)
    )
    assert panel.tabs.currentIndex() == fresh.tabs.currentIndex()
    assert (
        panel.selection_label.isVisible() == fresh.selection_label.isVisible()
    )


def test_expand_button_owned_by_panel_layout(panel: AnalysisPanel) -> None:
    """The expand toggle must be installed in the panel's QGridLayout
    rather than positioned via manual ``move()`` / ``resizeEvent``.

    Phase B refactor: previously the button was a free-floating child
    of the panel whose position was hand-tuned per resize, the sole
    layout-ownership exception in the GUI layer. The cell-overlay
    form preserves the historical visual placement while bringing
    the button under layout ownership so future-mantainer's
    ``setGeometry`` calls or splitter drags can't push it into
    nearby chrome.
    """
    grid = panel.layout()
    assert grid is not None, "AnalysisPanel must have a layout"
    # Every direct child of the panel should be the layout's
    # responsibility; assert the expand button is enumerated.
    index = grid.indexOf(panel.expand_btn)
    assert index >= 0, (
        "expand_btn must be added to the panel's layout, not"
        " positioned manually"
    )


def test_expand_button_no_overlap_with_tabs(panel: AnalysisPanel) -> None:
    """At a representative panel width, the expand button's geometry
    must not intersect the tab content area.

    The button is positioned at the top-right of the selection-label
    cell via ``AlignTop | AlignRight``; row 1 holds the tabs. The
    rows are siblings, so this is a structural guarantee, not a
    pixel-tuned one -- but assert it explicitly so any future row
    rearrangement that loses the separation trips the test.
    """
    panel.resize(600, 300)
    panel.show()
    panel.layout().activate()
    btn_rect = panel.expand_btn.geometry()
    tabs_rect = panel.tabs.geometry()
    assert not btn_rect.intersects(tabs_rect), (
        f"expand_btn {btn_rect} overlaps tabs {tabs_rect};"
        " row separation in the QGridLayout has been lost"
    )
