"""Grid cell creation, styling, and value cycling for the feature table."""

from phonology_features.gui.palette import C
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import QTableWidgetItem

# Fonts don't change with the theme so they're safe to cache at import.
# Brushes / colors must NOT be cached: the palette mutates on theme
# toggle and a module-level cache would freeze cells to the palette
# active during first import.
_CELL_FONT_BOLD = QFont("Noto Sans", 10, QFont.Weight.Bold)
_CELL_FONT_NORMAL = QFont("Noto Sans", 10)


def _cell_brushes(value: str) -> tuple[QBrush, QBrush]:
    """Return (foreground, background) brushes for ``value`` against the
    live palette. Called per cell on every style pass; brush creation
    is microsecond-cheap so this is fine."""
    if value == "+":
        return QBrush(QColor(C["plus"])), QBrush(QColor(C["plus_bg"]))
    if value in ("-", "−"):
        return QBrush(QColor(C["minus"])), QBrush(QColor(C["minus_bg"]))
    return QBrush(QColor(C["text_dim"])), QBrush(QColor(C["panel"]))


def make_cell(value: str = "0") -> QTableWidgetItem:
    """Create a styled table cell with the given feature value."""
    if value == "-":
        value = "−"
    item = QTableWidgetItem(value)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    style_cell(item, value)
    return item


def style_cell(item: QTableWidgetItem, value: str):
    """Apply color and font to a cell based on its value."""
    fg, bg = _cell_brushes(value)
    item.setForeground(fg)
    item.setBackground(bg)
    item.setFont(_CELL_FONT_BOLD if value != "0" else _CELL_FONT_NORMAL)


def cycle_value(current: str) -> str:
    """Cycle 0 -> + -> minus -> 0. Unknown values reset to 0."""
    if current == "0":
        return "+"
    if current == "+":
        return "−"
    return "0"
