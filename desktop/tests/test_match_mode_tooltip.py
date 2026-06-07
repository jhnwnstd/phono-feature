"""Regression: the match-mode toggle's tooltip is set, displays on
a synthetic ``QEvent.ToolTip``, and survives every event that
could plausibly clear widget tooltips (theme restyle, feature
pane rebuild on inventory load, toggle round-trip)."""

from __future__ import annotations

from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QHelpEvent
from PyQt6.QtWidgets import QApplication, QToolTip

from phonology_shared.presentation.constants import (
    MATCH_MODE_TOOLTIP_STRICT_ACTIVE,
    MATCH_MODE_TOOLTIP_WILDCARD_ACTIVE,
)


def test_match_mode_btn_has_tooltip(window) -> None:
    """Initial-state contract: the button comes up with the strict-
    active tooltip baked in by ``_apply_match_mode_btn`` at build
    time."""
    btn = window._match_mode_btn
    assert btn.toolTip() == MATCH_MODE_TOOLTIP_STRICT_ACTIVE


def test_tooltip_event_shows_text(window) -> None:
    """Synthetic ``QEvent.ToolTip`` at the button's centre fires
    ``QToolTip``. The visible popover's text equals the button's
    tooltip — proves Qt's tooltip pipeline is unblocked for this
    widget end-to-end (event delivery + tooltip-system lookup +
    popover display)."""
    window.show()
    QApplication.processEvents()
    btn = window._match_mode_btn
    pos = btn.rect().center()
    global_pos = btn.mapToGlobal(pos)
    QApplication.sendEvent(
        btn, QHelpEvent(QEvent.Type.ToolTip, pos, global_pos)
    )
    QApplication.processEvents()
    assert QToolTip.isVisible()
    assert QToolTip.text() == MATCH_MODE_TOOLTIP_STRICT_ACTIVE


def test_tooltip_survives_feature_pane_rebuild(window) -> None:
    """``_populate_features`` is called on inventory load and after
    every ``_toggle_match_mode``. The rebuild must not clear the
    tooltip."""
    btn = window._match_mode_btn
    before = btn.toolTip()
    window._populate_features()
    QApplication.processEvents()
    assert btn.toolTip() == before


def test_tooltip_survives_theme_restyle(window) -> None:
    """``ThemeController._restyle_toolbar`` re-applies the button's
    QSS via ``set_css`` on every theme + palette-mode swap. The
    tooltip lives on the widget's ``toolTip`` property, not its
    stylesheet, so the restyle must leave it intact."""
    btn = window._match_mode_btn
    before = btn.toolTip()
    window._theme._restyle_toolbar()
    QApplication.processEvents()
    assert btn.toolTip() == before


def test_tooltip_flips_on_toggle(window) -> None:
    """Toggling the button swaps the tooltip between the two
    relayed constants. Confirms the click handler routes through
    ``_apply_match_mode_btn``."""
    btn = window._match_mode_btn
    assert btn.toolTip() == MATCH_MODE_TOOLTIP_STRICT_ACTIVE
    btn.click()
    QApplication.processEvents()
    assert btn.toolTip() == MATCH_MODE_TOOLTIP_WILDCARD_ACTIVE
    btn.click()
    QApplication.processEvents()
    assert btn.toolTip() == MATCH_MODE_TOOLTIP_STRICT_ACTIVE
