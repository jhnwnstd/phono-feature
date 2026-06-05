"""Reusable GUI widgets: SegmentButton, FeatureRow, AnalysisPanel,
SegmentGridWidget.

Originally one large module; now split per-widget for navigability.
The four widget classes plus the two enums / helpers that callers
import are re-exported here so the historical import path
``from phonology_features.gui.widgets import SegmentButton``
continues to work without consumer changes.
"""

from __future__ import annotations

from phonology_features.gui.widgets.analysis_panel import (
    AnalysisPanel,
    _class_state_stylesheet,
    _CopyableTextEdit,
)
from phonology_features.gui.widgets.feature_row import FeatureRow
from phonology_features.gui.widgets.segment_button import (
    SegmentButton,
    SegmentState,
)
from phonology_features.gui.widgets.segment_grid import SegmentGridWidget

__all__ = [
    "AnalysisPanel",
    "FeatureRow",
    "SegmentButton",
    "SegmentGridWidget",
    "SegmentState",
    # Test-internal helpers kept exported because at least one test
    # imports them directly. ``_class_state_stylesheet`` is also
    # used by future analysis-popup callers per its docstring.
    "_CopyableTextEdit",
    "_class_state_stylesheet",
]
