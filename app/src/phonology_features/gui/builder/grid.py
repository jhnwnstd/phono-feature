"""Grid cell creation, styling, and value cycling for the feature table."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import QTableWidgetItem

from phonology_features.gui import palette
from phonology_features.gui.grid_logic import (
    MINUS_DISPLAY,
    MINUS_SERIALIZED,
    cycle_value,
)
from phonology_features.gui.palette import C

# Re-export so existing ``from .grid import cycle_value`` call sites
# in the builder continue to resolve. The canonical home is
# :py:mod:`phonology_features.gui.grid_logic`.
__all__ = [
    "MINUS_DISPLAY",
    "MINUS_SERIALIZED",
    "cycle_value",
    "make_cell",
    "style_cell",
]

# Fonts don't change with the theme so they're safe to cache at import.
_CELL_FONT_BOLD = QFont("Noto Sans", 10, QFont.Weight.Bold)
_CELL_FONT_NORMAL = QFont("Noto Sans", 10)

# Item flags don't depend on value either. Hoisting the bitwise OR
# matters because make_cell is called for every grid cell on load --
# the previous per-call OR showed up as the second-hottest line in
# the builder-load profile (25k+ enum.__or__ calls).
_CELL_FLAGS = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

# QBrush/QColor construction is ~14us per call and ran 4x per cell on
# the old code path. On the Hayes inventory that produced ~16k QColor
# objects per builder load. The brush set has exactly three states
# (+, -, 0), so cache one (fg, bg) tuple per state and rebuild ALL of
# them only when the theme changes. Keyed on ``palette.theme_version``
# (a monotonic counter bumped by ``set_theme``) so the cache is
# self-invalidating; no observer wiring needed.
_brush_cache_version: int = -1
_brush_cache: dict[str, tuple[QBrush, QBrush]] = {}


def _ensure_brush_cache() -> None:
    global _brush_cache_version
    if _brush_cache_version == palette.theme_version:
        return
    _brush_cache_version = palette.theme_version
    _brush_cache.clear()
    _brush_cache["+"] = (
        QBrush(QColor(C["plus"])),
        QBrush(QColor(C["plus_bg"])),
    )
    _brush_cache["-"] = (
        QBrush(QColor(C["minus"])),
        QBrush(QColor(C["minus_bg"])),
    )
    _brush_cache["0"] = (
        QBrush(QColor(C["text_dim"])),
        QBrush(QColor(C["panel"])),
    )


def _cell_brushes(value: str) -> tuple[QBrush, QBrush]:
    """Return ``(foreground, background)`` brushes for the cell value.
    Theme-version-keyed cache: hits avoid all QBrush/QColor construction."""
    _ensure_brush_cache()
    if value in _brush_cache:
        return _brush_cache[value]
    # Unicode minus normalizes to '-'; any other unexpected value gets
    # the '0' style (gridlines stay legible).
    if value == "−":
        return _brush_cache["-"]
    return _brush_cache["0"]


def make_cell(value: str = "0") -> QTableWidgetItem:
    """Create a styled table cell with the given feature value."""
    if value == MINUS_SERIALIZED:
        value = MINUS_DISPLAY
    item = QTableWidgetItem(value)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    item.setFlags(_CELL_FLAGS)
    style_cell(item, value)
    return item


def style_cell(item: QTableWidgetItem, value: str):
    """Apply color and font to a cell based on its value."""
    fg, bg = _cell_brushes(value)
    item.setForeground(fg)
    item.setBackground(bg)
    item.setFont(_CELL_FONT_BOLD if value != "0" else _CELL_FONT_NORMAL)
