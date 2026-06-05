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
