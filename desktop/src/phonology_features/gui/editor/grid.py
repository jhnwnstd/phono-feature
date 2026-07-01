"""Grid cell creation, styling, and value cycling for the feature table."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import QTableWidgetItem

from phonology_shared.editor.grid import (
    MINUS_DISPLAY,
    MINUS_SERIALIZED,
    cycle_value,
)
from phonology_shared.presentation import palette
from phonology_shared.presentation.palette import C

# Re-export so existing ``from .grid import cycle_value`` call sites
# in the editor continue to resolve. The canonical home is
# :py:mod:`phonology_shared.editor.grid`.
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
# matters because make_cell is called for every grid cell on load:
# the previous per-call OR showed up as the second-hottest line in
# the editor-load profile (25k+ enum.__or__ calls).
_CELL_FLAGS = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

# QBrush/QColor construction is ~14us per call and ran 4x per cell,
# producing ~16k QColor objects per Hayes editor load. There are only
# three states (+, -, 0), so cache one (fg, bg) tuple per state and
# rebuild all of them only on theme change. Keyed on
# ``palette.theme_version`` (a monotonic counter bumped by
# ``set_theme``) so the cache self-invalidates with no observer wiring.
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
    """Return ``(foreground, background)`` brushes for the cell value
    from the theme-version-keyed cache; hits skip all construction."""
    _ensure_brush_cache()
    if value in _brush_cache:
        return _brush_cache[value]
    # Unicode minus normalizes to '-'; any other unexpected value gets
    # the '0' style (gridlines stay legible).
    if value == "−":
        return _brush_cache["-"]
    return _brush_cache["0"]


def make_cell(value: str = "0") -> QTableWidgetItem:
    if value == MINUS_SERIALIZED:
        value = MINUS_DISPLAY
    item = QTableWidgetItem(value)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    item.setFlags(_CELL_FLAGS)
    style_cell(item, value)
    return item


def style_cell(item: QTableWidgetItem, value: str) -> None:
    fg, bg = _cell_brushes(value)
    item.setForeground(fg)
    item.setBackground(bg)
    item.setFont(_CELL_FONT_BOLD if value != "0" else _CELL_FONT_NORMAL)
