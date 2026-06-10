"""Pin the explicit ``setSizePolicy`` declarations added in Phase C.

Each ``QWidget`` subclass under ``desktop/src/phonology_features/gui/``
that the constraint table covers must declare an explicit size
policy aligned to its stretch role and inherit its width / height
floors from ``REGION_CONSTRAINTS``. The previous state relied on Qt
defaults; a future refactor that changes a parent widget would have
silently shifted child sizing behaviour. These tests catch that.

Each assertion checks both the policy enum AND the minimum-size
floor, so a constraint-table edit that bumps ``MIN_FEAT_CARD_W``
propagates without a parallel widget edit failing here.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QSizePolicy

from phonology_features.gui.themed_widgets import _ThemedCard
from phonology_features.gui.vowel_chart import VowelChartWidget
from phonology_features.gui.widgets import (
    AnalysisPanel,
    SegmentButton,
    SegmentGridWidget,
)
from phonology_shared.presentation.layout import REGION_CONSTRAINTS


@pytest.fixture()
def app(qapp: QApplication) -> QApplication:
    return qapp


def test_segment_button_is_fixed_size_and_policy(app: QApplication) -> None:
    """``SegmentButton`` declares Fixed/Fixed and its fixed size
    equals the constraint table's ``seg_btn`` entry. ``setFixedSize``
    implies Fixed/Fixed internally; the explicit ``setSizePolicy``
    call documents the contract in code.
    """
    btn = SegmentButton("p")
    constraint = REGION_CONSTRAINTS["seg_btn"]
    policy = btn.sizePolicy()
    assert policy.horizontalPolicy() == QSizePolicy.Policy.Fixed
    assert policy.verticalPolicy() == QSizePolicy.Policy.Fixed
    assert btn.size().width() == (constraint.pref_w or constraint.min_w)
    assert btn.size().height() == (constraint.pref_h or constraint.min_h)


def test_segment_grid_widget_is_preferred_minimum_expanding(
    app: QApplication,
) -> None:
    """``SegmentGridWidget`` declares Preferred horizontally (the
    parent splitter sets the bound) and MinimumExpanding vertically
    so the widget claims left_wrap's full available height; the
    height beyond the natural consonant content becomes the spillover
    policy's budget instead of stranded space.
    """
    grid = SegmentGridWidget()
    policy = grid.sizePolicy()
    assert policy.horizontalPolicy() == QSizePolicy.Policy.Preferred
    assert policy.verticalPolicy() == QSizePolicy.Policy.MinimumExpanding


def test_vowel_chart_is_fixed_horizontal(app: QApplication) -> None:
    """``VowelChartWidget`` is Fixed-horizontal (width externally
    clamped) and Preferred-vertical (height grows with row count).
    Its minimum height comes from the constraint table.
    """
    chart = VowelChartWidget()
    constraint = REGION_CONSTRAINTS["vowel_chart"]
    policy = chart.sizePolicy()
    assert policy.horizontalPolicy() == QSizePolicy.Policy.Fixed
    assert policy.verticalPolicy() == QSizePolicy.Policy.Preferred
    assert chart.minimumHeight() == constraint.min_h


def test_analysis_panel_is_expanding_with_minimum_size_hint(
    app: QApplication,
) -> None:
    """``AnalysisPanel`` declares Expanding/Expanding so the vsplit
    can grow it to fill leftover height; its ``minimumSizeHint``
    returns the constraint table's ``analysis_panel`` min entry.
    """
    panel = AnalysisPanel()
    constraint = REGION_CONSTRAINTS["analysis_panel"]
    policy = panel.sizePolicy()
    assert policy.horizontalPolicy() == QSizePolicy.Policy.Expanding
    assert policy.verticalPolicy() == QSizePolicy.Policy.Expanding
    hint = panel.minimumSizeHint()
    assert hint.width() == constraint.min_w
    assert hint.height() == constraint.min_h


def test_themed_card_min_width_from_constraint(app: QApplication) -> None:
    """``_ThemedCard`` inherits its width / height floor from the
    constraint table's ``feature_card`` entry. Catches "I bumped
    MIN_FEAT_CARD_W in layout.py but forgot themed_widgets".
    """
    card = _ThemedCard()
    constraint = REGION_CONSTRAINTS["feature_card"]
    policy = card.sizePolicy()
    assert policy.horizontalPolicy() == QSizePolicy.Policy.Preferred
    assert policy.verticalPolicy() == QSizePolicy.Policy.Preferred
    assert card.minimumWidth() == constraint.min_w
    assert card.minimumHeight() == constraint.min_h
