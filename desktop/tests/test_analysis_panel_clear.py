"""Invariant tests for :py:meth:`AnalysisPanel.clear`.

Each display cue on the panel is a place state can leak across a
Clear or mode switch and surface stale info. These tests pin that
``clear()`` returns the panel to its post-construction state.
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
    the colour back to neutral.
    """
    panel.set_sections(
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
    """A previously-disabled Contrasts tab (FEAT mode) must come
    back enabled after clear.
    """
    panel.set_sections("", "", "", contrasts_enabled=False)
    assert not panel.tabs.isTabEnabled(panel._TAB_CONTRASTS_IDX)
    panel.clear()
    assert panel.tabs.isTabEnabled(panel._TAB_CONTRASTS_IDX)


def test_clear_returns_to_class_tab(panel: AnalysisPanel) -> None:
    """Clear must drop the active tab back to Class."""
    panel.set_sections(
        "<p>y</p>", "<p>z</p>", "<p>w</p>", contrasts_enabled=True
    )
    panel.tabs.setCurrentIndex(1)  # Features
    assert panel.tabs.currentIndex() == 1
    panel.clear()
    assert panel.tabs.currentIndex() == 0  # Class


def test_clear_empties_all_tab_bodies(panel: AnalysisPanel) -> None:
    """Every tab body must be empty after clear."""
    panel.set_sections("<p>cls</p>", "<p>feat</p>", "<p>con</p>")
    panel.clear()
    assert panel._tab_class.toPlainText().strip() == ""
    assert panel._tab_features.toPlainText().strip() == ""
    assert panel._tab_contrasts.toPlainText().strip() == ""


def test_clear_matches_construction_state(panel: AnalysisPanel) -> None:
    """After Clear the panel is observably equal to a
    freshly-constructed one across every cue we track.
    """
    panel.set_sections(
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
