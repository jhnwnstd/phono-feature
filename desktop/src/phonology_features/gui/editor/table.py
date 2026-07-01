"""Custom QTableWidget machinery for the inventory editor.

Three Qt subclasses and one cached-brush helper, all self-contained
so the main editor window does not have to carry the Qt-specific
selection-paint and click-haptic code inline.

* ``_ToggleHeaderView``: a QHeaderView that emits ``sectionClicked``
  on double-click, giving every press the same haptic regardless of
  click timing.
* ``_BulkCycleTable``: a QTableWidget that runs a bulk-cycle callback
  on second-click-into-selection and overpaints the selection
  outline above Qt's gridlines.
* ``_SelectionFillDelegate``: per-cell paint delegate that swaps in a
  theme-aware highlight brush for selected cells.

The InventoryEditor owns instances of all three but does not need
their implementation surfaces. Splitting them here keeps the main
window file focused on state and lifecycle.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from PyQt6.QtCore import QItemSelection, QModelIndex, QRect, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
)
from PyQt6.QtWidgets import (
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from phonology_shared.presentation.palette import C


class _ToggleHeaderView(QHeaderView):
    """QHeaderView with the click semantics of a QPushButton.

    When two presses land within the OS double-click interval, Qt
    routes the second through ``mouseDoubleClickEvent``, which emits
    ``sectionDoubleClicked`` but not ``sectionClicked``, and the
    following release emits neither. So a fast two-click pair fires
    ``sectionClicked`` only once, and every second click drops out of
    the toggle handler (the "clicks not always detecting" symptom).

    Fix: emit ``sectionClicked`` from the ``mouseDoubleClickEvent``
    override so every press maps to one click. Skip the super call so
    ``sectionDoubleClicked`` does not also fire. These headers have no
    double-click gesture (resize is fixed, no edit-on-doubleclick), so
    repurposing that path costs nothing.
    """

    def __init__(
        self,
        orientation: Qt.Orientation,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(orientation, parent)
        # QTableWidget's default header has sectionsClickable=True;
        # a fresh QHeaderView defaults to False. Without this, no
        # sectionClicked signals fire at all.
        self.setSectionsClickable(True)

    def mouseDoubleClickEvent(self, e: QMouseEvent | None) -> None:
        # Coordinate space: x for horizontal headers, y for vertical.
        if e is None:
            return
        if self.orientation() == Qt.Orientation.Horizontal:
            section = self.logicalIndexAt(e.pos().x())
        else:
            section = self.logicalIndexAt(e.pos().y())
        if section >= 0:
            self.sectionClicked.emit(section)


class _BulkCycleTable(QTableWidget):
    """Subclass with two custom behaviours:

    1. ``mousePressEvent``: clicking a cell already in the selection
       runs the editor's bulk-cycle callback and does not forward the
       press. Keeps Qt's selection intact and avoids the orphan-release
       problem an event filter would cause (the base release handler
       would see a press it never processed).

    2. ``paintEvent``: draw the selection outline after the base paints
       cells and gridlines. A cell delegate cannot do this because Qt
       paints gridlines after delegates and would overwrite the
       boundary outline; painting here puts it above everything.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bulk_cycle_cb: Callable[[QTableWidgetItem], None] | None = None
        # General-case selection membership, rebuilt at most once
        # per selection change (see ``selectionChanged``) instead of
        # on every paint pass: during a drag-selection every mouse
        # move repaints, and rebuilding a Hayes-sized rectangle's
        # set per paint did thousands of inserts per tick.
        self._sel_cells_cache: set[tuple[int, int]] | None = None

    def selectionChanged(
        self, selected: QItemSelection, deselected: QItemSelection
    ) -> None:
        self._sel_cells_cache = None
        super().selectionChanged(selected, deselected)

    def set_bulk_cycle_callback(
        self, cb: Callable[[QTableWidgetItem], None]
    ) -> None:
        self._bulk_cycle_cb = cb

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            super().mousePressEvent(event)
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not event.modifiers()
            & (
                Qt.KeyboardModifier.ShiftModifier
                | Qt.KeyboardModifier.ControlModifier
            )
            and self._bulk_cycle_cb is not None
        ):
            idx = self.indexAt(event.position().toPoint())
            sel_model = self.selectionModel()
            if (
                idx.isValid()
                and sel_model is not None
                and sel_model.isSelected(idx)
            ):
                item = self.item(idx.row(), idx.column())
                if item is not None:
                    self._bulk_cycle_cb(item)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def paintEvent(self, event: QPaintEvent | None) -> None:
        super().paintEvent(event)
        sel_model = self.selectionModel()
        model = self.model()
        if sel_model is None or model is None:
            return
        sel_cols = sel_model.selectedColumns()
        sel_rows = sel_model.selectedRows()
        n_rows = self.rowCount()
        n_cols = self.columnCount()
        if n_rows == 0 or n_cols == 0:
            return
        # Fast path 1: exactly one full column.
        if len(sel_cols) == 1 and len(sel_rows) == 0:
            col = sel_cols[0].column()
            top_rect = self.visualRect(model.index(0, col))
            bot_rect = self.visualRect(model.index(n_rows - 1, col))
            self._draw_outline_rect(top_rect.united(bot_rect))
            return
        # Fast path 2: exactly one full row.
        if len(sel_rows) == 1 and len(sel_cols) == 0:
            row = sel_rows[0].row()
            left_rect = self.visualRect(model.index(row, 0))
            right_rect = self.visualRect(model.index(row, n_cols - 1))
            self._draw_outline_rect(left_rect.united(right_rect))
            return
        # Fast path 3: whole table.
        if len(sel_rows) == n_rows and len(sel_cols) == n_cols:
            tl_rect = self.visualRect(model.index(0, 0))
            br_rect = self.visualRect(model.index(n_rows - 1, n_cols - 1))
            self._draw_outline_rect(tl_rect.united(br_rect))
            return
        # General case: arbitrary selection shape (cross, multi-col,
        # rectangle, ctrl+click set). Build a {(row, col)} membership
        # set, then for each cell draw the edges whose neighbour is not
        # also selected. The set is cached across paints and cleared by
        # ``selectionChanged``, so a drag-selection's per-move repaints
        # reuse one build.
        cells = self._sel_cells_cache
        if cells is None:
            cells = set()
            for col_idx in sel_cols:
                c = col_idx.column()
                for ri in range(n_rows):
                    cells.add((ri, c))
            for row_idx in sel_rows:
                ri = row_idx.row()
                for ci in range(n_cols):
                    cells.add((ri, ci))
            for idx in sel_model.selectedIndexes():
                cells.add((idx.row(), idx.column()))
            self._sel_cells_cache = cells
        if not cells:
            return
        painter = QPainter(self.viewport())
        pen = QPen(QColor(C["accent"]))
        pen.setWidth(2)
        painter.setPen(pen)
        for row, col in cells:
            # Skip isolated cells (no selected neighbour). Outlines are
            # reserved for actual groups (row, col, rectangle, cross);
            # a lone cell shows only the light-blue fill. Grouped cells
            # always have a selected neighbour, so only lone ones drop.
            if not (
                (row - 1, col) in cells
                or (row + 1, col) in cells
                or (row, col - 1) in cells
                or (row, col + 1) in cells
            ):
                continue
            cell_rect = self.visualRect(model.index(row, col))
            if not cell_rect.isValid():
                continue
            if (row - 1, col) not in cells:
                painter.drawLine(
                    cell_rect.left(),
                    cell_rect.top(),
                    cell_rect.right(),
                    cell_rect.top(),
                )
            if (row + 1, col) not in cells:
                painter.drawLine(
                    cell_rect.left(),
                    cell_rect.bottom(),
                    cell_rect.right(),
                    cell_rect.bottom(),
                )
            if (row, col - 1) not in cells:
                painter.drawLine(
                    cell_rect.left(),
                    cell_rect.top(),
                    cell_rect.left(),
                    cell_rect.bottom(),
                )
            if (row, col + 1) not in cells:
                painter.drawLine(
                    cell_rect.right(),
                    cell_rect.top(),
                    cell_rect.right(),
                    cell_rect.bottom(),
                )
        painter.end()

    def _draw_outline_rect(self, rect: QRect) -> None:
        """Draw a 2 px outline around ``rect`` on the viewport. Used
        by the full-row / full-column / full-table fast paths."""
        if not rect.isValid():
            return
        painter = QPainter(self.viewport())
        pen = QPen(QColor(C["accent"]))
        pen.setWidth(2)
        painter.setPen(pen)
        # Inset by 1 so the 2-px border lands inside the selection
        # bounds rather than half outside.
        painter.drawRect(rect.adjusted(1, 1, -1, -1))
        painter.end()


class _SelectionFillDelegate(QStyledItemDelegate):
    """Selected cells render as light-blue fill plus the cell's own
    text colour. The outline around the whole region is drawn by
    ``_BulkCycleTable.paintEvent`` so it sits above Qt's gridlines.

    ``paint`` runs once per visible cell on every selection change, so
    two hot-path shortcuts: the State_Selected check runs against a
    cached ``int`` to skip Python's slow ``enum.__and__`` (was 60 ms /
    15k calls on the row-toggle profile), and the highlight QBrush is
    module-cached and theme-version keyed (see ``_get_highlight_brush``).
    """

    # Pre-extracted int value so the per-cell hot path is an int AND
    # rather than an enum.__and__ call. The Flag value never changes
    # at runtime so caching at class load is safe.
    _SELECTED_FLAG: ClassVar = QStyle.StateFlag.State_Selected

    def paint(
        self,
        painter: QPainter | None,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        if option.state & self._SELECTED_FLAG:
            # parent() is typed QObject | None but is the owning
            # QTableWidget in practice. ``hasattr`` satisfies mypy
            # without a cast and is cheap on the hot path.
            view = self.parent()
            item = (
                view.item(index.row(), index.column())
                if view is not None and hasattr(view, "item")
                else None
            )
            if item is not None:
                option.palette.setBrush(
                    QPalette.ColorRole.HighlightedText, item.foreground()
                )
            option.palette.setBrush(
                QPalette.ColorRole.Highlight, _get_highlight_brush()
            )
        super().paint(painter, option, index)


# Module-level highlight brush cache. Theme-version keyed so a theme
# toggle invalidates it transparently (no observer wiring), same trick
# the cell-brush cache uses in editor/grid.py.
_highlight_brush_version: int = -1
_highlight_brush: QBrush | None = None


def _get_highlight_brush() -> QBrush:
    """Return the cached highlight QBrush, rebuilding if theme changed."""
    global _highlight_brush, _highlight_brush_version
    from phonology_shared.presentation import palette as _palette

    if (
        _highlight_brush is None
        or _highlight_brush_version != _palette.theme_version
    ):
        _highlight_brush_version = _palette.theme_version
        _highlight_brush = QBrush(QColor(C["accent_light"]))
    return _highlight_brush
