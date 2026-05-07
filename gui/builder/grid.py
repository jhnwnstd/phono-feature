"""
gui/builder/grid.py
Grid cell logic: creation, styling, and value cycling for the feature table.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import QTableWidgetItem

from gui.palette import C

# ---------------------------------------------------------------------------
# Cell brushes and fonts (created once at import time)
# ---------------------------------------------------------------------------
_CELL_BRUSH = {
    "+": (QBrush(QColor(C["plus"])), QBrush(QColor(C["plus_bg"]))),
    "-": (QBrush(QColor(C["minus"])), QBrush(QColor(C["minus_bg"]))),
    "\u2212": (QBrush(QColor(C["minus"])), QBrush(QColor(C["minus_bg"]))),
    "0": (QBrush(QColor(C["text_dim"])), QBrush(QColor("#FFFFFF"))),
}
_CELL_FONT_BOLD = QFont("Noto Sans", 10, QFont.Weight.Bold)
_CELL_FONT_NORMAL = QFont("Noto Sans", 10)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def make_cell(value: str = "0") -> QTableWidgetItem:
    """Create a styled table cell with the given feature value."""
    if value == "-":
        value = "\u2212"
    item = QTableWidgetItem(value)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    style_cell(item, value)
    return item


def style_cell(item: QTableWidgetItem, value: str):
    """Apply colour to a cell based on its value."""
    fg, bg = _CELL_BRUSH.get(value, _CELL_BRUSH["0"])
    item.setForeground(fg)
    item.setBackground(bg)
    item.setFont(_CELL_FONT_BOLD if value != "0" else _CELL_FONT_NORMAL)


def cycle_value(current: str) -> str:
    """Cycle: 0 -> + -> minus -> 0.  Any unrecognised value resets to 0."""
    if current == "0":
        return "+"
    if current == "+":
        return "\u2212"
    return "0"  # covers both ASCII "-" and Unicode minus, plus any bad state
