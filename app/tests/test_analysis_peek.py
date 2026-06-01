"""Invariant tests for :py:class:`AnalysisPeekPopup`.

The peek popup is a transient magnifier for the analysis pane's
active tab. These tests pin two contracts:

1. Toggling the peek never changes the splitter / pane layout.
   The seg pane and feat pane keep their geometry; only the
   floating popup moves.

2. The popup auto-sizes to fit the active tab's content height,
   capped at the caller-supplied maximum. Short content yields a
   short popup; long content saturates at the cap.

A regression on either contract surfaces here, not in the UI.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication, QWidget

from phonology_features.gui.widgets import (
    AnalysisPanel,
    AnalysisPeekPopup,
)


@pytest.fixture()
def host(qapp: QApplication) -> QWidget:
    w = QWidget()
    w.resize(1200, 800)
    return w


@pytest.fixture()
def panel(host: QWidget) -> AnalysisPanel:
    p = AnalysisPanel(host)
    p.setGeometry(0, 580, 1200, 220)
    return p


@pytest.fixture()
def peek(host: QWidget) -> AnalysisPeekPopup:
    return AnalysisPeekPopup(host)


def test_peek_starts_hidden(peek: AnalysisPeekPopup) -> None:
    """Fresh peek is hidden so it doesn't reserve layout space."""
    assert peek.isHidden()


def test_show_for_anchors_bottom_at_target(
    peek: AnalysisPeekPopup, panel: AnalysisPanel
) -> None:
    """The popup's bottom edge sits exactly at the target rect's
    bottom; growth happens upward only."""
    panel.set_sections(
        "<p>Selected (1): /b/</p>",
        "<p>specs</p>",
        "<p>features</p>",
        "<p>contrasts</p>",
    )
    target = QRect(0, 580, 1200, 220)
    peek.show_for(panel, max_height=400, target_rect=target)
    geom = peek.geometry()
    assert geom.bottom() == target.bottom()
    assert geom.right() == target.right()
    assert geom.left() == target.left()


def test_show_for_respects_max_height(
    peek: AnalysisPeekPopup, panel: AnalysisPanel
) -> None:
    """Content longer than the max gets capped at max_height; the
    popup does not exceed the caller-supplied cap."""
    long_body = "<p>" + "x " * 1000 + "</p>"
    panel.set_sections("<p>chips</p>", long_body, "<p>f</p>", "<p>c</p>")
    cap = 300
    peek.show_for(panel, max_height=cap, target_rect=QRect(0, 580, 1200, 220))
    assert peek.height() <= cap


def test_show_for_shrinks_to_short_content(
    peek: AnalysisPeekPopup, panel: AnalysisPanel
) -> None:
    """A tiny active tab does not balloon to the max. Height stays
    well below the cap when content is small."""
    panel.set_sections("<p>chips</p>", "<p>·</p>", "<p>·</p>", "<p>·</p>")
    cap = 600
    peek.show_for(panel, max_height=cap, target_rect=QRect(0, 580, 1200, 220))
    assert (
        peek.height() < cap
    ), f"short content yielded full {peek.height()}px; expected < {cap}"
    assert peek.height() >= AnalysisPeekPopup.MIN_HEIGHT


def test_show_then_dismiss(
    peek: AnalysisPeekPopup, panel: AnalysisPanel
) -> None:
    """Dismiss returns the popup to hidden state. Use ``isHidden``
    (not ``isVisible``) because under the offscreen platform Qt's
    visibility flag flips only once the parent is actually shown
    on screen, which doesn't happen in headless tests."""
    panel.set_sections("<p>x</p>", "<p>y</p>", "<p>z</p>", "<p>w</p>")
    peek.show_for(panel, max_height=400, target_rect=QRect(0, 580, 1200, 220))
    assert not peek.isHidden()
    peek.dismiss()
    assert peek.isHidden()


def test_peek_does_not_touch_panel_geometry(
    peek: AnalysisPeekPopup, panel: AnalysisPanel
) -> None:
    """The panel's own geometry is untouched by peek lifecycle.
    This is the contract that decouples the magnifier from the
    splitter layout."""
    panel.set_sections("<p>x</p>", "<p>y</p>", "<p>z</p>", "<p>w</p>")
    before = panel.geometry()
    peek.show_for(panel, max_height=400, target_rect=QRect(0, 580, 1200, 220))
    peek.dismiss()
    assert panel.geometry() == before
