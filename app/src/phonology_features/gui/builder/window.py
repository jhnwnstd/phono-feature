"""InventoryBuilder: grid editor for creating or editing inventories."""

import os
import re
from dataclasses import dataclass

from phonology_features.engine.inventory import Inventory, ValidationError
from phonology_features.gui.builder.dialogs import (
    InputDialog,
    ask_question,
    center_on_parent,
    show_warning,
)
from phonology_features.gui.builder.grid import (
    cycle_value,
    make_cell,
    style_cell,
)
from phonology_features.gui.palette import C
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPalette, QPen, QRegion
from PyQt6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class _CellEdit:
    """One cell mutation, captured for undo/redo."""

    row: int
    col: int
    old: str
    new: str


class _ToggleHeaderView(QHeaderView):
    """QHeaderView with the click semantics of a QPushButton.

    Background: when two presses land within the OS double-click
    interval (~400 ms), Qt routes the second press through
    ``mouseDoubleClickEvent`` instead of ``mousePressEvent``. Qt's
    QHeaderView::mouseDoubleClickEvent emits ``sectionDoubleClicked``
    but NOT ``sectionClicked``. The release after the doubleclick
    finds state already cleared and doesn't emit either. Result on
    a real OS: a fast two-click pair fires sectionClicked exactly
    once (from the first release), so every second click silently
    drops out of the toggle handler -- the "clicks not always
    detecting" symptom the user reported.

    Fix: emit ``sectionClicked`` from our ``mouseDoubleClickEvent``
    override so the second press of the pair is represented as a
    normal click event. Skip the super call so ``sectionDoubleClicked``
    doesn't also fire (no consumer wants it, and emitting both would
    double-count if anyone wired both signals).

    Result: every user press = one ``sectionClicked``, same haptic as
    a QPushButton's clicked signal. No dedicated doubleclick gesture
    is used on these headers (resize is fixed, no edit-on-doubleclick),
    so there's nothing to lose by repurposing the doubleclick path.
    """

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        # QTableWidget's default header has sectionsClickable=True;
        # a fresh QHeaderView defaults to False. Without this, no
        # sectionClicked signals fire at all.
        self.setSectionsClickable(True)

    def mouseDoubleClickEvent(self, e):  # type: ignore[override]
        # Coordinate space: x for horizontal headers, y for vertical.
        if self.orientation() == Qt.Orientation.Horizontal:
            section = self.logicalIndexAt(e.pos().x())
        else:
            section = self.logicalIndexAt(e.pos().y())
        if section >= 0:
            self.sectionClicked.emit(section)


class _BulkCycleTable(QTableWidget):
    """Subclass with two custom behaviours:

    1. ``mousePressEvent``: when the user clicks a cell that's
       already in the selection, run the builder's bulk-cycle
       callback without forwarding the press to the base class.
       Keeps Qt's selection intact AND avoids the orphan-release
       problem where consuming via an event filter let the base
       release handler see a press it didn't process.

    2. ``paintEvent``: after the base class paints cells +
       gridlines, draw the selection outline ON TOP. Doing this in
       the cell delegate doesn't work -- Qt paints gridlines AFTER
       delegates, so any outline drawn at cell boundaries gets
       overwritten by the gridline. Drawing here puts the outline
       above everything.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bulk_cycle_cb = None

    def set_bulk_cycle_callback(self, cb):
        """Builder hands us a function ``(QTableWidgetItem) -> None``."""
        self._bulk_cycle_cb = cb

    def mousePressEvent(self, event):  # type: ignore[override]
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

    def paintEvent(self, event):  # type: ignore[override]
        super().paintEvent(event)
        sel_model = self.selectionModel()
        if sel_model is None:
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
            top_rect = self.visualRect(self.model().index(0, col))
            bot_rect = self.visualRect(self.model().index(n_rows - 1, col))
            self._draw_outline_rect(top_rect.united(bot_rect))
            return
        # Fast path 2: exactly one full row.
        if len(sel_rows) == 1 and len(sel_cols) == 0:
            row = sel_rows[0].row()
            left_rect = self.visualRect(self.model().index(row, 0))
            right_rect = self.visualRect(self.model().index(row, n_cols - 1))
            self._draw_outline_rect(left_rect.united(right_rect))
            return
        # Fast path 3: whole table.
        if len(sel_rows) == n_rows and len(sel_cols) == n_cols:
            tl_rect = self.visualRect(self.model().index(0, 0))
            br_rect = self.visualRect(
                self.model().index(n_rows - 1, n_cols - 1)
            )
            self._draw_outline_rect(tl_rect.united(br_rect))
            return
        # General case: arbitrary selection shape (cross, multi-col,
        # rectangle, ctrl+click set). Build a {(row, col)} membership
        # set, then for each selected cell draw its edges on sides
        # whose neighbour isn't also selected. Drawing happens AFTER
        # super().paintEvent so the border lands above Qt's gridlines.
        cells: set[tuple[int, int]] = set()
        for col_idx in sel_cols:
            c = col_idx.column()
            for r in range(n_rows):
                cells.add((r, c))
        for row_idx in sel_rows:
            r = row_idx.row()
            for c in range(n_cols):
                cells.add((r, c))
        for idx in sel_model.selectedIndexes():
            cells.add((idx.row(), idx.column()))
        if not cells:
            return
        from PyQt6.QtGui import QPainter

        painter = QPainter(self.viewport())
        pen = QPen(QColor(C["accent"]))
        pen.setWidth(2)
        painter.setPen(pen)
        for row, col in cells:
            # Skip isolated cells (no neighbour also selected). Otherwise
            # a single-cell selection would get a 4-sided border per
            # cell -- user wants only the light-blue fill in that case,
            # reserving outlines for actual GROUPS (row, col, rectangle,
            # cross). Cells inside a group always have at least one
            # selected neighbour, so this only suppresses lone cells.
            if not (
                (row - 1, col) in cells
                or (row + 1, col) in cells
                or (row, col - 1) in cells
                or (row, col + 1) in cells
            ):
                continue
            r = self.visualRect(self.model().index(row, col))
            if not r.isValid():
                continue
            if (row - 1, col) not in cells:
                painter.drawLine(r.left(), r.top(), r.right(), r.top())
            if (row + 1, col) not in cells:
                painter.drawLine(r.left(), r.bottom(), r.right(), r.bottom())
            if (row, col - 1) not in cells:
                painter.drawLine(r.left(), r.top(), r.left(), r.bottom())
            if (row, col + 1) not in cells:
                painter.drawLine(r.right(), r.top(), r.right(), r.bottom())
        painter.end()

    def _draw_outline_rect(self, rect):
        """Draw a 2 px outline around ``rect`` on the viewport. Used
        by the full-row / full-column / full-table fast paths."""
        if not rect.isValid():
            return
        from PyQt6.QtGui import QPainter

        painter = QPainter(self.viewport())
        pen = QPen(QColor(C["accent"]))
        pen.setWidth(2)
        painter.setPen(pen)
        # Inset by 1 so the 2-px border lands inside the selection
        # bounds rather than half outside.
        painter.drawRect(rect.adjusted(1, 1, -1, -1))
        painter.end()


class _SelectionFillDelegate(QStyledItemDelegate):
    """Selected cells render as light-blue fill + the cell's own text
    colour. The outline around the whole selection region is drawn by
    ``_BulkCycleTable.paintEvent`` so it sits ON TOP of Qt's
    gridlines instead of being overwritten by them.

    Hot path: this ``paint`` runs once per visible cell on every
    selection change. Two micro-optimisations vs the obvious version:
      - State_Selected check is done against a cached ``int`` to skip
        Python's slow ``enum.__and__`` (was 60 ms / 15k calls on the
        row-toggle profile).
      - The highlight QBrush is module-level cached and theme-version
        keyed (see ``_get_highlight_brush``) so we don't allocate a
        QColor on every selected-cell paint.
    """

    # Pre-extracted int value so the per-cell hot path is an int AND
    # rather than an enum.__and__ call. The Flag value never changes
    # at runtime so caching at class load is safe.
    _SELECTED_FLAG = QStyle.StateFlag.State_Selected

    def paint(self, painter, option, index):  # type: ignore[override]
        if option.state & self._SELECTED_FLAG:
            view = self.parent()
            item = (
                view.item(index.row(), index.column())
                if view is not None
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
# the cell-brush cache uses in builder/grid.py.
_highlight_brush_version: int = -1
_highlight_brush: QBrush | None = None


def _get_highlight_brush() -> QBrush:
    """Return the cached highlight QBrush, rebuilding if theme changed."""
    global _highlight_brush, _highlight_brush_version
    from phonology_features.gui import palette as _palette

    if (
        _highlight_brush is None
        or _highlight_brush_version != _palette.theme_version
    ):
        _highlight_brush_version = _palette.theme_version
        _highlight_brush = QBrush(QColor(C["accent_light"]))
    return _highlight_brush


# Undo-history depth cap. ~200 batches of at-most all cells covers a
# normal editing session without unbounded growth.
_MAX_UNDO_DEPTH = 200


def _suggest_filename(inv_name: str) -> str:
    """Slugify an inventory name into a bundled-style filename.
    Mirrors ``hayes_features.json`` / ``english_features.json``:
    lowercase, non-alphanumeric runs to ``_``, ``_features`` suffix
    appended unless already present.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", inv_name.lower()).strip("_")
    if not slug:
        slug = "untitled"
    if not slug.endswith("_features"):
        slug = f"{slug}_features"
    return f"{slug}.json"


class InventoryBuilder(QMainWindow):
    """Grid editor for creating phonological feature inventories."""

    # Emitted from the save worker thread with (path, error_message).
    # Qt picks QueuedConnection automatically for cross-thread emit,
    # so the slot runs on the main thread.
    _save_finished = pyqtSignal(str, str)

    def __init__(self, parent=None, load_path: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Inventory Builder")
        self.setMinimumSize(800, 500)
        self._save_finished.connect(self._on_save_finished)
        self._save_in_flight: bool = False
        self._segments: list = []
        self._features: list = []
        self._inv_name: str = "Untitled Inventory"
        self._current_path: str | None = None
        self._dirty: bool = False
        self._selected_remove_col: int | None = None
        self._selected_remove_row: int | None = None
        # Bounded invalidation: track the previous selection's region so
        # the next selection change can repaint only (old | new) rather
        # than the entire viewport. Held as a QRegion so the union
        # works for arbitrary shapes (single column, cross, rectangle).
        self._last_selection_region: "QRegion | None" = None
        # User-click stickies, distinct from the Qt-selection-derived
        # ``_selected_remove_*`` above. Qt auto-selects the column /
        # row on header PRESS (before sectionClicked fires on
        # RELEASE), so the toggle decision can't be based on Qt's
        # selection state -- it'd always look "already selected".
        # These mutate ONLY in the header click handlers.
        self._user_clicked_col: int | None = None
        self._user_clicked_row: int | None = None
        # Last applied enabled-state for each rm button. Lets the
        # selection handler short-circuit when nothing changed, so
        # spamming a header click doesn't pay the setStyleSheet polish
        # cost on every event.
        self._rm_seg_enabled_state: bool | None = None
        self._rm_feat_enabled_state: bool | None = None
        # Undo / redo: each entry is one batch (the cell edits produced
        # by a single user action). Cleared on table rebuild.
        self._undo_stack: list[list[_CellEdit]] = []
        self._redo_stack: list[list[_CellEdit]] = []
        self._build_ui()
        if parent is not None:
            parent_screen = parent.screen()
            if parent_screen is not None:
                avail = parent_screen.availableGeometry()
                self.resize(
                    min(1000, avail.width() - 80),
                    min(700, avail.height() - 80),
                )
                frame = self.frameGeometry()
                frame.moveCenter(avail.center())
                self.move(frame.topLeft())
        if load_path:
            self._load_existing(load_path)

    def _build_ui(self) -> None:
        self._build_toolbar()
        self._build_central()
        self._build_status_bar()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setStyleSheet(f"""
            QToolBar {{
                background: {C["panel"]};
                border-bottom: 1px solid {C["border"]};
                padding: 4px 8px;
                spacing: 6px;
            }}
            """)
        self.addToolBar(toolbar)
        btn_style = f"""
            QPushButton {{
                background: {C["bg"]};
                color: {C["text"]};
                border: 1.5px solid {C["border"]};
                border-radius: 6px;
                padding: 0 12px;
            }}
            QPushButton:hover {{
                background: {C["accent_light"]};
                border: 1.5px solid {C["accent"]};
                color: {C["accent"]};
            }}
        """
        save_style = f"""
            QPushButton {{
                background: {C["btn_primary"]};
                color: {C["btn_primary_text"]};
                border: none;
                border-radius: 6px;
                padding: 0 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {C["btn_primary_hover"]};
                color: {C["btn_primary_hover_text"]};
            }}
            """
        # Destructive action: red fill so it reads as "danger" against
        # the rest of the toolbar's neutral buttons.
        self._delete_style_enabled = f"""
            QPushButton {{
                background: {C["btn_danger"]};
                color: {C["btn_danger_text"]};
                border: none;
                border-radius: 6px;
                padding: 0 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {C["btn_danger_hover"]};
                color: {C["btn_danger_hover_text"]};
            }}
        """
        self._btn_style_enabled = btn_style
        # Disabled state: subtly greyer background so the button reads
        # as "inactive" instead of blending into the toolbar.
        self._btn_style_disabled = f"""
            QPushButton {{
                background: {C["tag_gray"]};
                color: {C["text_dim"]};
                border: 1.5px solid {C["border"]};
                border-radius: 6px;
                padding: 0 12px;
            }}
        """

        def make_btn(label: str, slot, *, style: str = btn_style):
            """Add a 32 px Noto Sans 10 button to the toolbar with the
            given label, slot, and style.
            """
            btn = QPushButton(label)
            btn.setFont(QFont("Noto Sans", 10))
            btn.setFixedHeight(32)
            btn.setStyleSheet(style)
            btn.clicked.connect(slot)
            toolbar.addWidget(btn)
            return btn

        make_btn("New", self.show_setup_dialog)
        make_btn("Open", self._open_file)
        make_btn("Save", self._save, style=save_style)
        make_btn("Save As", self._save_as)
        toolbar.addSeparator()
        make_btn("+ Segment", self._add_segment)
        make_btn("+ Feature", self._add_feature)
        self._rm_seg_btn = make_btn("\u2212 Segment", self._remove_segment)
        self._rm_feat_btn = make_btn("\u2212 Feature", self._remove_feature)
        # Initial state: nothing selected => both greyed out. Use the
        # cache-aware setters so the initial assignment also fills the
        # ``_rm_*_enabled_state`` cache.
        self._set_rm_seg_enabled(False)
        self._set_rm_feat_enabled(False)
        toolbar.addSeparator()
        # Two stretches sandwich Delete in the middle of the empty
        # space: away from the edit cluster on the left AND away from
        # the window's close button on the right.
        left_stretch = QWidget()
        left_stretch.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        toolbar.addWidget(left_stretch)
        # Delete is only valid when an existing file is loaded; enabled
        # by _update_title whenever _current_path changes.
        self._delete_btn = make_btn("Delete", self._delete_inventory)
        self._delete_btn.setEnabled(False)
        self._delete_btn.setStyleSheet(self._btn_style_disabled)
        right_stretch = QWidget()
        right_stretch.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        toolbar.addWidget(right_stretch)

    def _build_central(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_meta_strip())
        layout.addWidget(self._build_table())

    def _build_meta_strip(self) -> QWidget:
        """Editable inventory-name field + current-file indicator.

        Sits above the grid so it's clear what you'll be saving and
        where, before any cell edit. Editing the name marks the
        inventory dirty; Save / Save As pick up the new name on write.
        """
        strip = QWidget()
        strip.setStyleSheet(
            f"background: {C['bg']};"
            f" border-bottom: 1px solid {C['border']};"
        )
        lay = QHBoxLayout(strip)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(8)
        name_label = QLabel("Name:")
        name_label.setFont(QFont("Noto Sans", 9, QFont.Weight.Bold))
        name_label.setStyleSheet(f"color: {C['text_dim']};")
        lay.addWidget(name_label)
        self._name_edit = QLineEdit(self._inv_name)
        self._name_edit.setFont(QFont("Noto Sans", 10))
        self._name_edit.setStyleSheet(f"""
            QLineEdit {{
                background: {C["panel"]};
                color: {C["text"]};
                border: 1px solid {C["border"]};
                border-radius: 4px;
                padding: 2px 8px;
            }}
            QLineEdit:focus {{
                border: 1.5px solid {C["accent"]};
            }}
        """)
        self._name_edit.editingFinished.connect(self._on_name_edited)
        lay.addWidget(self._name_edit, stretch=1)
        self._file_label = QLabel("(unsaved)")
        self._file_label.setFont(QFont("Noto Sans", 9))
        self._file_label.setStyleSheet(
            f"color: {C['text_dim']}; padding: 0 4px;"
        )
        lay.addWidget(self._file_label)
        return strip

    def _build_table(self) -> QTableWidget:
        self._table = _BulkCycleTable()
        # Install QPushButton-haptic headers BEFORE any signal wiring;
        # see _ToggleHeaderView for why.
        self._table.setHorizontalHeader(
            _ToggleHeaderView(Qt.Orientation.Horizontal, self._table)
        )
        self._table.setVerticalHeader(
            _ToggleHeaderView(Qt.Orientation.Vertical, self._table)
        )
        self._table.set_bulk_cycle_callback(self._cycle_selection_from)
        self._table.setFont(QFont("Noto Sans", 10))
        self._table.setStyleSheet(f"""
            QTableWidget {{
                background: {C["panel"]};
                gridline-color: {C["border"]};
                border: none;
            }}
            QTableWidget::item {{
                padding: 2px 4px;
            }}
            QHeaderView::section {{
                background: {C["bg"]};
                color: {C["text"]};
                border: 1px solid {C["border"]};
                padding: 4px;
                font-weight: bold;
            }}
            """)
        # Selected cells get a light-blue fill + outer outline (delegate).
        self._table.setItemDelegate(_SelectionFillDelegate(self._table))
        # Key-handling event filter only -- the click-to-select /
        # click-to-cycle UX lives in _BulkCycleTable.mousePressEvent.
        self._table.installEventFilter(self)
        h_header = self._table.horizontalHeader()
        v_header = self._table.verticalHeader()
        if h_header:
            # _ToggleHeaderView forwards doubleclick -> press, so every
            # user click fires sectionClicked exactly once. Same haptic
            # as a QPushButton; no need to wire sectionDoubleClicked.
            h_header.sectionClicked.connect(self._on_col_header_clicked)
        if v_header:
            v_header.sectionClicked.connect(self._on_row_header_clicked)
        # Single source of truth for rm-button enabled/disabled state:
        # fires for every selection change regardless of source (header
        # click, ctrl+A, corner click, drag-select). Setters inside
        # short-circuit when nothing changed.
        sel_model = self._table.selectionModel()
        if sel_model is not None:
            sel_model.selectionChanged.connect(self._on_selection_changed)
        # Corner button (top-left of headers) drives select-all by
        # default; intercept so a second click clears the selection.
        corner = self._table.findChild(QAbstractButton)
        if corner is not None:
            try:
                corner.clicked.disconnect()
            except TypeError:
                pass
            corner.clicked.connect(self._on_corner_clicked)
        return self._table

    def _build_status_bar(self) -> None:
        self._status = QStatusBar()
        self._status.setStyleSheet(
            f"background: {C['panel']}; border-top: 1px solid {C['border']};"
        )
        self.setStatusBar(self._status)
        self._status.showMessage(
            "Create a new inventory or open an existing one."
        )

    # Setup dialog
    def show_setup_dialog(self) -> bool:
        """Show the new-inventory setup dialog. Returns True if the user
        committed and a grid was built; False if they cancelled or the
        unsaved-changes check refused.

        The dialog validates its own input (see InputDialog.accept), so on
        a True return the segments/features lists are guaranteed non-empty.
        """
        if not self._check_unsaved():
            return False
        dlg = InputDialog(self)
        center_on_parent(dlg, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        # Dedupe (preserving order). InputDialog.accept already guaranteed
        # both lists are non-empty.
        segments = list(dict.fromkeys(dlg.get_segments()))
        features = list(dict.fromkeys(dlg.get_features()))
        self._segments = segments
        self._features = features
        self._inv_name = dlg.get_name()
        self._current_path = None
        self._dirty = True
        self._rebuild_table()
        self._update_title()
        self._status.showMessage(
            f"Created grid: {len(segments)} segments \u00d7 {len(features)} features. "
            "Click cells to cycle through +/\u2212/0."
        )
        return True

    # Table management
    def _rebuild_table(self) -> None:
        """Build the table: rows=features, cols=segments."""
        # Edits captured against the previous table refer to row/col
        # indices that may no longer match the new table; drop them.
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._table.clear()
        self._table.setRowCount(len(self._features))
        self._table.setColumnCount(len(self._segments))
        # clear() can replace header objects with default QHeaderView,
        # destroying our _ToggleHeaderView's doubleclick-as-press
        # override. Re-install our custom headers BEFORE setting labels
        # or wiring signals so the per-click haptic survives a reload.
        self._table.setHorizontalHeader(
            _ToggleHeaderView(Qt.Orientation.Horizontal, self._table)
        )
        self._table.setVerticalHeader(
            _ToggleHeaderView(Qt.Orientation.Vertical, self._table)
        )
        self._table.setVerticalHeaderLabels(self._features)
        self._table.setHorizontalHeaderLabels(self._segments)
        v_header = self._table.verticalHeader()
        if v_header:
            v_header.setFont(QFont("Noto Sans", 9))
            v_header.setSectionResizeMode(
                QHeaderView.ResizeMode.ResizeToContents
            )
            v_header.setMinimumSectionSize(24)
            v_header.sectionClicked.connect(self._on_row_header_clicked)
        h_header = self._table.horizontalHeader()
        if h_header:
            h_header.setFont(QFont("Noto Sans", 11))
            h_header.setDefaultSectionSize(36)
            h_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
            h_header.setMinimumSectionSize(32)
            h_header.sectionClicked.connect(self._on_col_header_clicked)
        # clear() can replace the selectionModel too; re-wire it here.
        sel_model = self._table.selectionModel()
        if sel_model is not None:
            try:
                sel_model.selectionChanged.disconnect(
                    self._on_selection_changed
                )
            except TypeError:
                pass
            sel_model.selectionChanged.connect(self._on_selection_changed)
        for r in range(len(self._features)):
            for c in range(len(self._segments)):
                self._table.setItem(r, c, make_cell("0"))

    # Number / numpad keys set the cell directly to a specific value.
    # 0 is also accepted alongside 3 because that's where "zero" sits on
    # most keyboards (and it's the most natural press for "underspecified").
    _VALUE_KEYS = {
        Qt.Key.Key_1: "+",
        Qt.Key.Key_2: "\u2212",  # Unicode minus, matches cycle_value()
        Qt.Key.Key_3: "0",
        Qt.Key.Key_0: "0",
    }
    # Numpad-style + Vim-style cell navigation. dr, dc as relative steps.
    _MOVE_KEYS = {
        Qt.Key.Key_8: (-1, 0),
        Qt.Key.Key_K: (-1, 0),
        Qt.Key.Key_5: (1, 0),
        Qt.Key.Key_J: (1, 0),
        Qt.Key.Key_4: (0, -1),
        Qt.Key.Key_H: (0, -1),
        Qt.Key.Key_6: (0, 1),
        Qt.Key.Key_L: (0, 1),
    }

    def eventFilter(self, obj, event):
        if obj is self._table and event.type() == event.Type.KeyPress:
            if self._handle_table_key(event):
                return True
        return super().eventFilter(obj, event)

    def _handle_table_key(self, event) -> bool:
        """Keyboard shortcuts on the table. Returns True if consumed.

        Ctrl+Z / Ctrl+Shift+Z = undo, Ctrl+Y = redo. Scoped to the
        table so the metadata-strip name field's Qt-built-in text-undo
        is left alone when it has focus. Space cycles the current cell
        (multi-cell when there's a selection); 1/2/3/0 set the value;
        h/j/k/l + 4/5/6/8 move the cursor.
        """
        row = self._table.currentRow()
        col = self._table.currentColumn()
        key = event.key()
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_Z:
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    self._redo()
                else:
                    self._undo()
                return True
            if key == Qt.Key.Key_Y:
                self._redo()
                return True
        if row >= 0 and col >= 0:
            if key == Qt.Key.Key_Space:
                cur_item = self._table.item(row, col)
                if cur_item is not None:
                    self._cycle_selection_from(cur_item)
                return True
            value = self._VALUE_KEYS.get(key)
            if value is not None:
                self._apply_value_to_selection(value, row, col)
                return True
        move = self._MOVE_KEYS.get(key)
        if move is not None and self._table.rowCount() > 0:
            dr, dc = move
            start_row = row if row >= 0 else 0
            start_col = col if col >= 0 else 0
            new_row = max(0, min(start_row + dr, self._table.rowCount() - 1))
            new_col = max(
                0, min(start_col + dc, self._table.columnCount() - 1)
            )
            self._table.setCurrentCell(new_row, new_col)
            return True
        return False

    def _set_cell_value(self, row: int, col: int, value: str) -> None:
        """Write ``value`` to the cell and record the change for undo."""
        item = self._table.item(row, col)
        if item is None or item.text() == value:
            return
        edits = [_CellEdit(row, col, item.text(), value)]
        item.setText(value)
        style_cell(item, value)
        self._commit_edits(edits)

    def _cycle_selection_from(self, anchor_item: QTableWidgetItem) -> None:
        """Cycle every selected cell to the value ``anchor_item`` would
        cycle to. The anchor is whichever cell the user clicked or is
        currently focused on; its current value picks the destination
        for the whole batch so the selection stays uniform."""
        items = self._table.selectedItems()
        if not items:
            items = [anchor_item]
        new_val = cycle_value(anchor_item.text())
        self._apply_value_to_items(items, new_val)

    def _apply_value_to_selection(
        self, value: str, fallback_row: int, fallback_col: int
    ) -> None:
        """Set ``value`` on every selected cell. Falls back to the cell
        at ``(fallback_row, fallback_col)`` when there is no multi-cell
        selection; typical case where the user has just navigated to a
        single cell with the keyboard."""
        items = self._table.selectedItems()
        if len(items) > 1:
            self._apply_value_to_items(items, value)
            return
        self._set_cell_value(fallback_row, fallback_col, value)

    def _apply_value_to_items(self, items: list, value: str) -> None:
        """Bulk-write ``value`` to ``items``, skipping any that already
        match. Records the whole batch as one undoable edit."""
        edits: list[_CellEdit] = []
        for item in items:
            if item is None or item.text() == value:
                continue
            edits.append(
                _CellEdit(item.row(), item.column(), item.text(), value)
            )
            item.setText(value)
            style_cell(item, value)
        self._commit_edits(edits)

    def _commit_edits(self, edits: list[_CellEdit]) -> None:
        """Push a non-empty edit batch onto the undo stack and update
        dirty + remove-button state. Empty batches are ignored so
        no-op operations don't pollute the history."""
        if not edits:
            return
        self._undo_stack.append(edits)
        # A new edit invalidates any redo history; same convention as
        # most editors (you can't redo into a divergent timeline).
        self._redo_stack.clear()
        if len(self._undo_stack) > _MAX_UNDO_DEPTH:
            self._undo_stack.pop(0)
        self._dirty = True
        self._clear_remove_selection()

    def _undo(self) -> None:
        """Reverse the most recent batch and move it to the redo stack."""
        if not self._undo_stack:
            self._status.showMessage("Nothing to undo.")
            return
        edits = self._undo_stack.pop()
        for e in edits:
            item = self._table.item(e.row, e.col)
            if item is not None:
                item.setText(e.old)
                style_cell(item, e.old)
        self._redo_stack.append(edits)
        self._dirty = True
        self._clear_remove_selection()
        self._status.showMessage(
            f"Undid {len(edits)} cell change{'s' if len(edits) != 1 else ''}."
        )

    def _redo(self) -> None:
        """Re-apply the most recently undone batch."""
        if not self._redo_stack:
            self._status.showMessage("Nothing to redo.")
            return
        edits = self._redo_stack.pop()
        for e in edits:
            item = self._table.item(e.row, e.col)
            if item is not None:
                item.setText(e.new)
                style_cell(item, e.new)
        self._undo_stack.append(edits)
        self._dirty = True
        self._clear_remove_selection()
        self._status.showMessage(
            f"Redid {len(edits)} cell change{'s' if len(edits) != 1 else ''}."
        )

    # Header selection / remove button state
    def _on_col_header_clicked(self, col: int):
        """Toggle segment-column highlight; second click clears it.

        Compares against ``_user_clicked_col`` (a separate sticky
        owned by THIS handler) rather than the Qt-derived
        ``_selected_remove_col`` -- Qt auto-selects the column on
        press, so by the time this handler fires on release the
        Qt-derived sticky already shows ``col``, which would make
        every first click look like a toggle-off.
        """
        if self._user_clicked_col == col:
            self._user_clicked_col = None
            self._user_clicked_row = None
            self._table.clearSelection()
        else:
            # First click on this column: Qt has already auto-selected
            # on press, so just record the click for the next toggle.
            self._user_clicked_col = col
            self._user_clicked_row = None
            # Defensive: re-issue selectColumn in case the press path
            # didn't actually set it (e.g. clicked-while-modifier).
            self._table.selectColumn(col)

    def _on_row_header_clicked(self, row: int):
        """Toggle feature-row highlight; second click clears it."""
        if self._user_clicked_row == row:
            self._user_clicked_row = None
            self._user_clicked_col = None
            self._table.clearSelection()
        else:
            self._user_clicked_row = row
            self._user_clicked_col = None
            self._table.selectRow(row)

    def _on_corner_clicked(self):
        """Toggle select-all when the table corner is clicked."""
        rows = self._table.rowCount()
        cols = self._table.columnCount()
        total = rows * cols
        if total > 0 and len(self._table.selectedItems()) == total:
            self._table.clearSelection()
        else:
            self._table.selectAll()

    def _clear_remove_selection(self) -> None:
        """Reset which header is currently selected for removal."""
        self._selected_remove_col = None
        self._selected_remove_row = None
        self._set_rm_seg_enabled(False)
        self._set_rm_feat_enabled(False)

    def _set_rm_seg_enabled(self, enabled: bool) -> None:
        """Toggle the − Segment button's enabled state, skipping the
        setStyleSheet polish if nothing actually changed."""
        if self._rm_seg_enabled_state == enabled:
            return
        self._rm_seg_enabled_state = enabled
        self._rm_seg_btn.setEnabled(enabled)
        self._rm_seg_btn.setStyleSheet(
            self._btn_style_enabled if enabled else self._btn_style_disabled
        )

    def _set_rm_feat_enabled(self, enabled: bool) -> None:
        """Toggle the − Feature button's enabled state, skipping the
        setStyleSheet polish if nothing actually changed."""
        if self._rm_feat_enabled_state == enabled:
            return
        self._rm_feat_enabled_state = enabled
        self._rm_feat_btn.setEnabled(enabled)
        self._rm_feat_btn.setStyleSheet(
            self._btn_style_enabled if enabled else self._btn_style_disabled
        )

    def _on_selection_changed(self):
        """Single source of truth for everything that derives from the
        current Qt selection: sticky vars, rm-button enabled state,
        and the targeted viewport invalidation.

        Uses ``selectedColumns()`` / ``selectedRows()`` -- microsecond
        cost even on select-all (vs walking ~4000 indexes).
        """
        sel_model = self._table.selectionModel()
        if sel_model is None:
            return
        # Invalidate ONLY the union of the previous and current
        # selection regions. The old "viewport().update()" repainted
        # every visible cell on every toggle (~768 cells on Hayes ->
        # ~38 ms per click); switching to a bounded region cuts that
        # to just the cells that actually change selection state OR
        # sit at the intersection. Profile saw the delegate paint
        # dominator drop from 541 ms / 15360 paints to <20 ms / ~250
        # paints for a row toggle.
        old_region = self._last_selection_region
        new_region = self._table.visualRegionForSelection(
            sel_model.selection()
        )
        invalid = (
            old_region.united(new_region)
            if old_region is not None
            else new_region
        )
        # ``repaint(region)`` is synchronous; bypasses Qt's paint-event
        # coalescing. update() would let Qt merge a rapid sequence of
        # clicks into ONE paint at the end, so the user sees nothing
        # change between clicks -- the "sticky" / "click didn't
        # register" symptom. With bounded invalidation each repaint
        # is ~3 ms on Hayes, so we can afford 300+ clicks/sec before
        # paint becomes the bottleneck.
        self._table.viewport().repaint(invalid)
        self._last_selection_region = new_region
        sel_cols = sel_model.selectedColumns()
        sel_rows = sel_model.selectedRows()
        if len(sel_cols) == 1 and len(sel_rows) == 0:
            self._selected_remove_col = sel_cols[0].column()
            self._selected_remove_row = None
            self._set_rm_seg_enabled(True)
            self._set_rm_feat_enabled(False)
        elif len(sel_rows) == 1 and len(sel_cols) == 0:
            self._selected_remove_row = sel_rows[0].row()
            self._selected_remove_col = None
            self._set_rm_seg_enabled(False)
            self._set_rm_feat_enabled(True)
        else:
            self._selected_remove_col = None
            self._selected_remove_row = None
            self._set_rm_seg_enabled(False)
            self._set_rm_feat_enabled(False)

    # Add / remove segments and features
    def _add_segment(self) -> None:
        """Prompt for a new segment and add a column."""
        from PyQt6.QtWidgets import QInputDialog

        dlg = QInputDialog(self)
        dlg.setWindowTitle("Add Segment")
        dlg.setLabelText("Segment symbol (IPA):")
        center_on_parent(dlg, self)
        ok = dlg.exec() == QDialog.DialogCode.Accepted
        text = dlg.textValue()
        if not ok or not text.strip():
            return
        seg = text.strip()
        if seg in self._segments:
            self._status.showMessage(f"Segment '{seg}' already exists.")
            return
        self._segments.append(seg)
        col = self._table.columnCount()
        self._table.insertColumn(col)
        self._table.setHorizontalHeaderItem(col, QTableWidgetItem(seg))
        for r in range(len(self._features)):
            self._table.setItem(r, col, make_cell("0"))
        self._dirty = True
        self._status.showMessage(f"Added segment '{seg}'.")

    def _add_feature(self) -> None:
        """Prompt for a new feature and add a row."""
        from PyQt6.QtWidgets import QInputDialog

        dlg = QInputDialog(self)
        dlg.setWindowTitle("Add Feature")
        dlg.setLabelText("Feature name:")
        center_on_parent(dlg, self)
        ok = dlg.exec() == QDialog.DialogCode.Accepted
        text = dlg.textValue()
        if not ok or not text.strip():
            return
        feat = text.strip()
        if feat in self._features:
            self._status.showMessage(f"Feature '{feat}' already exists.")
            return
        self._features.append(feat)
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setVerticalHeaderItem(row, QTableWidgetItem(feat))
        for c in range(len(self._segments)):
            self._table.setItem(row, c, make_cell("0"))
        self._dirty = True
        self._status.showMessage(f"Added feature '{feat}'.")

    def _remove_segment(self) -> None:
        """Remove the header-selected column (segment)."""
        col = self._selected_remove_col
        if col is None or col < 0 or col >= len(self._segments):
            self._status.showMessage(
                "Click a segment column header to choose which to remove."
            )
            return
        seg = self._segments[col]
        reply = ask_question(
            self, "Remove segment", f"Remove segment '{seg}'?"
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._segments.pop(col)
        self._table.removeColumn(col)
        self._dirty = True
        self._clear_remove_selection()
        self._status.showMessage(f"Removed segment '{seg}'.")

    def _remove_feature(self) -> None:
        """Remove the header-selected row (feature)."""
        row = self._selected_remove_row
        if row is None or row < 0 or row >= len(self._features):
            self._status.showMessage(
                "Click a feature row header to choose which to remove."
            )
            return
        feat = self._features[row]
        reply = ask_question(
            self, "Remove feature", f"Remove feature '{feat}'?"
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._features.pop(row)
        self._table.removeRow(row)
        self._dirty = True
        self._clear_remove_selection()
        self._status.showMessage(f"Removed feature '{feat}'.")

    # Serialization (save / load)
    def _to_inventory(self) -> Inventory:
        """Snapshot the current grid as a validated ``Inventory``.

        Routes through ``Inventory.from_grid`` which funnels into
        ``Inventory.parse`` -- so save uses the same contract as load.
        Raises ``ValidationError`` if the grid is somehow inconsistent
        (which would be a bug in the builder, not user input). No
        silent normalization of unknown cell values: the cycle ladder
        only produces '+'/'-'/'0'/'\u2212', so anything else is a
        contract violation worth surfacing.
        """
        assert self._table.columnCount() == len(self._segments)
        assert self._table.rowCount() == len(self._features)
        segments: dict[str, dict[str, str]] = {}
        for c, seg in enumerate(self._segments):
            feats: dict[str, str] = {}
            for r, feat in enumerate(self._features):
                item = self._table.item(r, c)
                val = item.text() if item else "0"
                feats[feat] = val
            segments[seg] = feats
        return Inventory.from_grid(
            name=self._inv_name,
            features=list(self._features),
            segments=segments,
        )

    def _save(self) -> None:
        if self._current_path:
            self._write_json(self._current_path)
        else:
            self._save_as()

    def _save_as(self) -> None:
        inventories_dir = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "..",
                "..",
                "inventories",
            )
        )
        dlg = QFileDialog(
            self, "Save Inventory", inventories_dir, "JSON Files (*.json)"
        )
        dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        # Pre-fill the filename from the inventory name, slugified to
        # match the existing inventories/ naming convention. The user can
        # still override it in the dialog.
        dlg.selectFile(_suggest_filename(self._inv_name))
        center_on_parent(dlg, self)
        if not dlg.exec():
            return
        path = dlg.selectedFiles()[0] if dlg.selectedFiles() else ""
        if not path:
            return
        if not path.endswith(".json"):
            path += ".json"
        self._write_json(path)
        self._current_path = path
        self._update_title()

    def _write_json(self, path: str):
        """Save the grid via the shared Inventory contract.

        Validation + Inventory construction run on the main thread
        (they touch grid widgets); the actual disk write runs on a
        worker thread. Atomic write means an external reader sees
        either the old file or the new file, never a half-written
        one, regardless of how long the background write takes.

        On a slow / network disk this keeps the UI responsive: a
        ``json.dump`` + ``fsync`` on a remote share can freeze the
        window for hundreds of milliseconds. Re-entrancy guard
        (``_save_in_flight``) drops a second click rather than
        racing two writers on the same path.

        Completion hops back to the main thread via the
        ``_save_finished`` signal (QueuedConnection by default for
        cross-thread emit), so the worker never touches GUI state
        directly and the dirty flag / status text mutate only on
        the main thread.
        """
        if getattr(self, "_save_in_flight", False):
            self._status.showMessage("Save already in progress; ignored.")
            return
        try:
            inventory = self._to_inventory()
        except ValidationError as e:
            show_warning(
                self,
                "Cannot save inventory",
                "The grid does not satisfy the inventory contract:\n\n"
                + "\n".join(f"• {issue}" for issue in e.issues),
            )
            return

        import threading

        self._save_in_flight = True
        self._status.showMessage(f"Saving {os.path.basename(path)}...")

        def worker() -> None:
            try:
                inventory.write_atomic(path)
                err: str = ""
            except OSError as e:
                err = str(e)
            self._save_finished.emit(path, err)

        threading.Thread(target=worker, daemon=True).start()

    def _on_save_finished(self, path: str, error: str) -> None:
        """Main-thread completion handler for the background save.
        ``error`` is empty on success, the ``str(OSError)`` otherwise."""
        self._save_in_flight = False
        if error:
            show_warning(
                self, "Save failed", f"Could not write '{path}':\n{error}"
            )
            return
        self._dirty = False
        self._status.showMessage(f"Saved to {os.path.basename(path)}")

    def _delete_inventory(self) -> None:
        """Delete the on-disk file for the currently-loaded inventory.

        The grid contents stay in memory and are marked dirty so the
        user can immediately Save As to a new name if the deletion was
        a refactor rather than a discard. The main window's directory
        watcher picks up the removal and refreshes its dropdown.
        """
        path = self._current_path
        if not path:
            return
        fname = os.path.basename(path)
        reply = ask_question(
            self,
            "Delete inventory",
            f"Permanently delete '{fname}' from disk?\n\n"
            "The current grid stays open; Save As to keep a copy.",
            buttons=(
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.Cancel
            ),
            default=QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            os.remove(path)
        except OSError as e:
            show_warning(
                self, "Delete failed", f"Could not delete '{fname}':\n{e}"
            )
            return
        self._current_path = None
        # In-memory grid is now unsaved (no file backs it).
        self._dirty = True
        self._update_title()
        self._status.showMessage(
            f"Deleted '{fname}'. The grid is unsaved; Save As to keep it."
        )

    def _open_file(self) -> None:
        if not self._check_unsaved():
            return
        inventories_dir = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "..",
                "..",
                "inventories",
            )
        )
        dlg = QFileDialog(
            self, "Open Inventory", inventories_dir, "JSON Files (*.json)"
        )
        dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
        dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
        center_on_parent(dlg, self)
        if not dlg.exec():
            return
        path = dlg.selectedFiles()[0] if dlg.selectedFiles() else ""
        if path:
            self._load_existing(path)

    def _load_existing(self, path: str):
        """Load an existing JSON inventory into the grid for editing.

        Routes through ``Inventory.load`` so the builder enforces the
        same contract as the engine: invalid files refuse to load with
        a human-readable error rather than producing a partially-
        normalized grid that gets silently rewritten on save.
        """
        try:
            inventory = Inventory.load(path)
        except ValidationError as e:
            show_warning(
                self,
                "Cannot load inventory",
                "This file does not satisfy the inventory contract:\n\n"
                + "\n".join(f"• {issue}" for issue in e.issues),
            )
            return
        self._inv_name = inventory.name
        self._features = list(inventory.features)
        self._segments = list(inventory.segments.keys())
        self._current_path = path
        self._rebuild_table()
        for c, seg in enumerate(self._segments):
            seg_feats = inventory.segments[seg]
            for r, feat in enumerate(self._features):
                val = seg_feats.get(feat, "0")
                self._table.setItem(r, c, make_cell(val))
        self._dirty = False
        self._update_title()
        self._status.showMessage(
            f"{len(self._segments)} segments \u00d7 "
            f"{len(self._features)} features."
        )

    # Unsaved changes guard
    def _wait_for_save(self, timeout_ms: int = 5000) -> bool:
        """Pump the event loop until the background save completes or
        ``timeout_ms`` elapses. Returns True if the save finished,
        False on timeout.

        Used by ``_check_unsaved`` (Save+Close flow) and ``closeEvent``
        (post-close cleanup): without this, a window close while the
        save thread is still running would let the worker emit
        ``_save_finished`` on a QObject that's being destroyed by Qt.
        """
        if not self._save_in_flight:
            return True
        from PyQt6.QtCore import QElapsedTimer
        from PyQt6.QtWidgets import QApplication

        elapsed = QElapsedTimer()
        elapsed.start()
        while self._save_in_flight and elapsed.elapsed() < timeout_ms:
            # Process pending events so the queued ``_save_finished``
            # signal can deliver; AllEvents (default) is fine here
            # because the user already chose to close -- new input
            # events just queue.
            QApplication.processEvents()
        return not self._save_in_flight

    def _check_unsaved(self) -> bool:
        """Return True if it's OK to discard changes (or there are none)."""
        if not self._dirty:
            return True
        reply = ask_question(
            self,
            "Unsaved changes",
            "You have unsaved changes. Discard them?",
            buttons=(
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel
            ),
            default=QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Save:
            self._save()
            # _save is async (background thread + signal). Block until
            # the worker finishes so ``not self._dirty`` reflects the
            # ACTUAL outcome -- without the wait, _dirty is still True
            # at this point and Close would get refused even though
            # the user asked for Save+Close.
            self._wait_for_save()
            return not self._dirty
        return reply == QMessageBox.StandardButton.Discard

    def closeEvent(self, event):
        if not self._check_unsaved():
            event.ignore()
            return
        # Wait for any background save before letting Qt destroy the
        # window. If the worker thread emits ``_save_finished`` after
        # the QObject is destroyed, PyQt raises ``RuntimeError:
        # wrapped C/C++ object has been deleted`` on the worker
        # thread -- harmless but noisy in logs, and a clean wait is
        # cheap (atomic write on a healthy disk is sub-ms).
        self._wait_for_save()
        event.accept()

    def _update_title(self) -> None:
        # Window title stays plain; the inventory name and filename
        # already appear in the meta strip below the toolbar, so
        # repeating them in the title bar is noise.
        path = self._current_path
        has_file = bool(path)
        self.setWindowTitle("Inventory Builder")
        # Delete only makes sense when there's an on-disk file backing
        # the current grid; toggle the visual + interactive state.
        self._delete_btn.setEnabled(has_file)
        self._delete_btn.setStyleSheet(
            self._delete_style_enabled
            if has_file
            else self._btn_style_disabled
        )
        self._refresh_meta_strip()

    def _refresh_meta_strip(self) -> None:
        """Sync the name field and file-indicator label with the current
        ``_inv_name`` / ``_current_path``. Used after every load, save,
        or programmatic rename so the visible UI matches the data."""
        if self._name_edit.text() != self._inv_name:
            self._name_edit.setText(self._inv_name)
        if self._current_path:
            self._file_label.setText(os.path.basename(self._current_path))
        else:
            self._file_label.setText("(unsaved)")

    def _on_name_edited(self) -> None:
        """Commit the name field's text to ``_inv_name`` once the user
        finishes editing (focus lost or Enter). Marks dirty if the name
        actually changed; refreshes the title bar."""
        new_name = self._name_edit.text().strip() or "Untitled Inventory"
        if new_name == self._inv_name:
            return
        self._inv_name = new_name
        self._dirty = True
        self._update_title()
