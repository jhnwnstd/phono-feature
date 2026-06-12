"""Compatibility facade for the vowel-chart geometry.

The implementation moved to the layered package
:py:mod:`phonology_shared.chart.vowel_geometry` (see its package
docstring for the layer table and dependency rules). This module is
a pure re-export mirror of the old single-module namespace so the
historical import paths (and :py:mod:`phonology_shared.chart.vowels`'
lazy re-export shim) keep working unchanged. New code should import
from ``phonology_shared.chart.vowel_geometry`` directly.

Pure facade contract: nothing but this docstring, import statements,
and ``__all__`` may live here, pinned by
``shared/tests/test_vowel_geometry_boundaries.py``.
"""

from phonology_shared.chart.vowel_geometry.cell_boxes import (
    _VOWEL_CELL_STACK_GAP_PX,
    _VOWEL_DATA_AREA_VERTICAL_PADDING_PX,
    _VOWEL_ROW_GAP_PX,
    DENSITY_TIER_DENSE_BTN_H,
    DENSITY_TIER_DENSE_THRESHOLD,
    DENSITY_TIER_ULTRA_BTN_H,
    DENSITY_TIER_ULTRA_THRESHOLD,
    _cell_box_px,
    _cell_horizontal_button_count,
    _cell_vertical_depth,
    _effective_button_height_px,
    _natural_data_area_size,
    _resolve_pair_shift_conflicts,
    effective_button_height_px,
)
from phonology_shared.chart.vowel_geometry.display_slots import (
    _BACKNESS_SLOT_ORDER,
    _COL_TO_ANCHOR,
    _COL_TO_SLOT,
    _NEUTRAL_TO_PAIRED,
    PAIR_DISPLAY_KINDS,
    _assign_pair_sides,
    _classify_vowel_cell_display,
    _order_pair_entries,
)
from phonology_shared.chart.vowel_geometry.model import (
    VOWEL_CHART_TITLE,
    VowelChartBand,
    VowelChartCell,
    VowelChartColHeader,
    VowelChartDiphthong,
    VowelChartGeometry,
    VowelChartRow,
    VowelChartSilhouette,
)
from phonology_shared.chart.vowel_geometry.outline import (
    _VOWEL_CONTENT_W_PX,
    _VOWEL_MIN_CELL_GAP_NORM,
    _VOWEL_SHRINK_FACTOR,
    _VOWEL_SLANT_CHANGE_CAP_FRAC,
    _compute_shrunken_widths,
    _min_row_width_for_meta,
    _silhouette_with_widths,
    _stage1_uniform_shrink,
    _stage2_slant_tweak,
    rounded_silhouette_polygon_points,
    silhouette_for_data_width,
    silhouette_left_at_y,
    silhouette_right_at_y,
    vowel_silhouette,
)
from phonology_shared.chart.vowel_geometry.pipeline import (
    _CONFINE_MARGIN_PX,
    _CONFINE_MAX_PASSES,
    _confine_cells_to_outline,
    _grow_outline_extent,
    build_vowel_chart_geometry,
)
from phonology_shared.chart.vowels import VowelCellDisplayKind

__all__ = [
    "DENSITY_TIER_DENSE_BTN_H",
    "DENSITY_TIER_DENSE_THRESHOLD",
    "DENSITY_TIER_ULTRA_BTN_H",
    "DENSITY_TIER_ULTRA_THRESHOLD",
    "PAIR_DISPLAY_KINDS",
    "VOWEL_CHART_TITLE",
    "VowelCellDisplayKind",
    "VowelChartBand",
    "VowelChartCell",
    "VowelChartColHeader",
    "VowelChartDiphthong",
    "VowelChartGeometry",
    "VowelChartRow",
    "VowelChartSilhouette",
    "_BACKNESS_SLOT_ORDER",
    "_COL_TO_ANCHOR",
    "_COL_TO_SLOT",
    "_CONFINE_MARGIN_PX",
    "_CONFINE_MAX_PASSES",
    "_NEUTRAL_TO_PAIRED",
    "_VOWEL_CELL_STACK_GAP_PX",
    "_VOWEL_CONTENT_W_PX",
    "_VOWEL_DATA_AREA_VERTICAL_PADDING_PX",
    "_VOWEL_MIN_CELL_GAP_NORM",
    "_VOWEL_ROW_GAP_PX",
    "_VOWEL_SHRINK_FACTOR",
    "_VOWEL_SLANT_CHANGE_CAP_FRAC",
    "_assign_pair_sides",
    "_cell_box_px",
    "_cell_horizontal_button_count",
    "_cell_vertical_depth",
    "_classify_vowel_cell_display",
    "_compute_shrunken_widths",
    "_confine_cells_to_outline",
    "_effective_button_height_px",
    "_grow_outline_extent",
    "_min_row_width_for_meta",
    "_natural_data_area_size",
    "_order_pair_entries",
    "_resolve_pair_shift_conflicts",
    "_silhouette_with_widths",
    "_stage1_uniform_shrink",
    "_stage2_slant_tweak",
    "build_vowel_chart_geometry",
    "effective_button_height_px",
    "rounded_silhouette_polygon_points",
    "silhouette_for_data_width",
    "silhouette_left_at_y",
    "silhouette_right_at_y",
    "vowel_silhouette",
]
