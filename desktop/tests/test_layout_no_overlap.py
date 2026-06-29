"""Pairwise non-overlap invariants for the desktop GUI layout.

The other desktop layout tests (``test_layout_stress.py``,
``test_feature_panel_layout.py``) pin pixel sizes and content-driven
thresholds. None of them assert "widget A's geometry does not
intersect widget B's geometry". This file fills that gap: at a
representative set of window resolutions, every declared pair of
visible regions must not occupy overlapping screen coordinates.

The test resolution matrix mirrors the named breakpoints used in
``shared/tests/test_layout_resolutions.py`` so a future "all my
resolution tests pass but the screen has a button on top of a label"
regression fails here on the same matrix.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QRect, QSettings

from phonology_shared.presentation.constants import (
    SETTINGS_APP,
    SETTINGS_ORG,
)


def _wipe_settings() -> None:
    QSettings(SETTINGS_ORG, SETTINGS_APP).clear()


def _drain(qapp, times: int = 4) -> None:
    for _ in range(times):
        qapp.processEvents()


# Representative resolutions covering the main breakpoint regimes:
# laptop-low, mainstream FHD, ultrawide. Wider than the no-overlap
# claim needs to cover, but mirrors shared/tests/test_layout_resolutions.py
# so a regression at one resolution lights up everywhere.
_RESOLUTIONS = [
    (1366, 768),
    (1920, 1080),
    (2560, 1440),
]


def _shrink(rect: QRect, by: int = 1) -> QRect:
    """Return ``rect`` shrunk by ``by`` pixels on each side so
    sub-pixel boundary touches don't register as overlap. Real
    overlaps (a button sitting on top of a label) survive this; only
    1-px borrow at shared boundaries gets absorbed.
    """
    return QRect(
        rect.left() + by,
        rect.top() + by,
        max(0, rect.width() - 2 * by),
        max(0, rect.height() - 2 * by),
    )


def _assert_no_overlap(
    rect_a: QRect,
    rect_b: QRect,
    label: str,
    tolerance: int = 1,
) -> None:
    a = _shrink(rect_a, tolerance)
    b = _shrink(rect_b, tolerance)
    assert not a.intersects(b), (
        f"{label}: {rect_a} intersects {rect_b}"
        f" (after {tolerance}-px shrink: {a} vs {b})"
    )


def _global_rect(widget) -> QRect:
    """The widget's VISIBLE area mapped to the window's root
    coordinate system. Uses ``visibleRegion()`` (which respects
    parent clipping) rather than ``rect()`` so a widget whose
    ``minimumHeight`` exceeds the parent splitter's slot doesn't
    report intrinsic geometry that overflows past its clipped
    bounds. The intersection check that consumes this rect needs to
    answer "do these two widgets actually visually overlap on
    screen", which is the post-clipping rect.
    """
    visible = widget.visibleRegion().boundingRect()
    top_left = widget.mapTo(widget.window(), visible.topLeft())
    return QRect(top_left, visible.size())


@pytest.fixture()
def window(qapp):
    """A fresh ``MainWindow`` per test so size-policy state from one
    pair check can't shadow another's."""
    _wipe_settings()
    from phonology_features.gui.main_window import MainWindow

    w = MainWindow()
    w.show()
    _drain(qapp)
    yield w
    w.close()
    _drain(qapp)


@pytest.mark.parametrize("width,height", _RESOLUTIONS)
def test_seg_panel_and_feat_panel_do_not_overlap(
    window,
    qapp,
    width: int,
    height: int,
) -> None:
    """The horizontal splitter places these side by side; their
    geometries must not intersect at any representative resolution.
    """
    window.resize(width, height)
    _drain(qapp)
    _assert_no_overlap(
        _global_rect(window.seg_panel),
        _global_rect(window.feat_panel),
        f"seg_panel vs feat_panel @ {width}x{height}",
    )


@pytest.mark.parametrize("width,height", _RESOLUTIONS)
def test_analysis_panel_does_not_overlap_top_split(
    window,
    qapp,
    width: int,
    height: int,
) -> None:
    """The vertical splitter places the analysis pane below the
    seg/feat split. Vertically the analysis-pane top must be at or
    below the top-split's bottom.

    Uses 0-px tolerance because the active panel's 1.5-px accent
    border occupies the panel's bottom edge; any overlap into the
    analysis pane lands a coloured stripe on top of the analysis
    pane's first row of pixels. A previous regression had the top
    panes overflowing their hsplit by ``handleWidth`` (4 px)
    because the budget cap in ``apply_splitter_sizes`` did not
    subtract the handle width; pinning at 0 px catches that class
    of bug immediately.
    """
    window.resize(width, height)
    _drain(qapp)
    _assert_no_overlap(
        _global_rect(window.analysis),
        _global_rect(window.seg_panel),
        f"analysis vs seg_panel @ {width}x{height}",
        tolerance=0,
    )
    _assert_no_overlap(
        _global_rect(window.analysis),
        _global_rect(window.feat_panel),
        f"analysis vs feat_panel @ {width}x{height}",
        tolerance=0,
    )
