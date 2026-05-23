"""
gui/builder/window.py
InventoryBuilder; main grid editor window for creating/editing inventories.
"""

import json
import os
import re
from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

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
from phonology_features.gui.builder.presets import VALID_VALUES
from phonology_features.gui.palette import C


@dataclass(frozen=True)
class _CellEdit:
    """One cell mutation, captured for undo/redo."""

    row: int
    col: int
    old: str
    new: str


# Cap on the undo history depth. ~200 batches x at-most all cells per
# batch easily covers a normal editing session without unbounded growth.
_MAX_UNDO_DEPTH = 200


def _suggest_filename(inv_name: str) -> str:
    """Slugify an inventory name into a bundled-inventory-style filename.

    Mirrors the convention used by the bundled inventories
    (``hayes_features.json``, ``english_features.json``, ...): lowercase,
    runs of non-alphanumeric replaced with ``_``, suffix ``_features``
    appended unless the name already ends with it.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", inv_name.lower()).strip("_")
    if not slug:
        slug = "untitled"
    if not slug.endswith("_features"):
        slug = f"{slug}_features"
    return f"{slug}.json"


class InventoryBuilder(QMainWindow):
    """Grid editor for creating phonological feature inventories."""

    def __init__(self, parent=None, load_path: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Inventory Builder")
        self.setMinimumSize(800, 500)
        self._segments: list = []
        self._features: list = []
        self._inv_name: str = "Untitled Inventory"
        self._current_path: str | None = None
        self._dirty: bool = False
        self._selected_remove_col: int | None = None
        self._selected_remove_row: int | None = None
        # Undo / redo: each entry is a batch; the list of cell edits
        # produced by one user action (cycle, set, bulk apply). Cleared
        # whenever the table is rebuilt (new inventory or load).
        self._undo_stack: list[list[_CellEdit]] = []
        self._redo_stack: list[list[_CellEdit]] = []
        self._build_ui()
        # Position on the same screen as the parent window
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

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
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
                background: {C["accent"]};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: #1D4ED8;
            }}
            """
        self._btn_style_enabled = btn_style
        self._btn_style_disabled = f"""
            QPushButton {{
                background: {C["bg"]};
                color: {C["text_dim"]};
                border: 1.5px solid {C["border"]};
                border-radius: 6px;
                padding: 0 12px;
            }}
        """

        def make_btn(label: str, slot, *, style: str = btn_style):
            """Add a fixed-height 32 px Noto Sans 10 button to the toolbar.
            Centralizes the create + font + style + connect + addWidget
            pattern that was duplicated nine times before this refactor.
            """
            btn = QPushButton(label)
            btn.setFont(QFont("Noto Sans", 10))
            btn.setFixedHeight(32)
            btn.setStyleSheet(style)
            btn.clicked.connect(slot)
            toolbar.addWidget(btn)
            return btn

        make_btn("New", self.show_setup_dialog)
        make_btn("Open\u2026", self._open_file)
        make_btn("Save", self._save, style=save_style)
        make_btn("Save As\u2026", self._save_as)
        # Delete: only meaningful when an existing file is loaded; the
        # enable state is updated from ``_update_title`` whenever
        # ``_current_path`` changes.
        self._delete_btn = make_btn("Delete\u2026", self._delete_inventory)
        self._delete_btn.setEnabled(False)
        self._delete_btn.setStyleSheet(self._btn_style_disabled)
        toolbar.addSeparator()
        make_btn("+ Segment", self._add_segment)
        make_btn("+ Feature", self._add_feature)
        toolbar.addSeparator()
        self._rm_seg_btn = make_btn("\u2212 Segment", self._remove_segment)
        self._rm_seg_btn.setEnabled(False)
        self._rm_seg_btn.setStyleSheet(self._btn_style_disabled)
        self._rm_feat_btn = make_btn("\u2212 Feature", self._remove_feature)
        self._rm_feat_btn.setEnabled(False)
        self._rm_feat_btn.setStyleSheet(self._btn_style_disabled)

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
        self._table = QTableWidget()
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
        self._table.cellClicked.connect(self._on_cell_clicked)
        self._table.installEventFilter(self)
        # Filter mouse events on the viewport too so we can detect a
        # plain-click inside a multi-cell selection BEFORE Qt collapses
        # that selection back to the single clicked cell.
        viewport = self._table.viewport()
        if viewport is not None:
            viewport.installEventFilter(self)
        h_header = self._table.horizontalHeader()
        v_header = self._table.verticalHeader()
        if h_header:
            h_header.sectionClicked.connect(self._on_col_header_clicked)
        if v_header:
            v_header.sectionClicked.connect(self._on_row_header_clicked)
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

    # ------------------------------------------------------------------
    # Setup dialog
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Table management
    # ------------------------------------------------------------------
    def _rebuild_table(self) -> None:
        """Build the table: rows=features, cols=segments."""
        # Edits captured against the previous table refer to row/col
        # indices that may no longer match the new table; drop them.
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._table.clear()
        self._table.setRowCount(len(self._features))
        self._table.setColumnCount(len(self._segments))
        self._table.setVerticalHeaderLabels(self._features)
        self._table.setHorizontalHeaderLabels(self._segments)
        # clear() may replace header objects, so reconnect signals each time.
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
        if obj is self._table.viewport():
            if self._handle_viewport_press(event):
                return True
        elif obj is self._table and event.type() == event.Type.KeyPress:
            if self._handle_table_key(event):
                return True
        return super().eventFilter(obj, event)

    def _handle_viewport_press(self, event) -> bool:
        """Bulk-cycle every selected cell when the user plain-clicks
        inside an existing multi-cell selection (header-click row/col,
        shift-click range, or ctrl-click set). Catching the mouse
        PRESS on the viewport lets us see the selection before Qt
        collapses it to the clicked cell. Shift / Ctrl clicks are the
        user EXTENDING the selection; let Qt handle those normally.
        """
        if event.type() != event.Type.MouseButtonPress:
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        modifiers = event.modifiers()
        if modifiers & (
            Qt.KeyboardModifier.ShiftModifier
            | Qt.KeyboardModifier.ControlModifier
        ):
            return False
        items = self._table.selectedItems()
        if len(items) <= 1:
            return False
        idx = self._table.indexAt(event.position().toPoint())
        if not idx.isValid():
            return False
        clicked_item = self._table.item(idx.row(), idx.column())
        if clicked_item not in items:
            return False
        self._cycle_selection_from(clicked_item)
        return True

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
        self._disable_remove_btns()

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
        self._disable_remove_btns()
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
        self._disable_remove_btns()
        self._status.showMessage(
            f"Redid {len(edits)} cell change{'s' if len(edits) != 1 else ''}."
        )

    # ------------------------------------------------------------------
    # Header selection / remove button state
    # ------------------------------------------------------------------
    def _on_col_header_clicked(self, col: int):
        """A segment column header was clicked; enable segment removal only."""
        self._selected_remove_col = col
        self._selected_remove_row = None
        self._table.selectColumn(col)
        self._rm_seg_btn.setEnabled(True)
        self._rm_seg_btn.setStyleSheet(self._btn_style_enabled)
        self._rm_feat_btn.setEnabled(False)
        self._rm_feat_btn.setStyleSheet(self._btn_style_disabled)

    def _on_row_header_clicked(self, row: int):
        """A feature row header was clicked; enable feature removal only."""
        self._selected_remove_row = row
        self._selected_remove_col = None
        self._table.selectRow(row)
        self._rm_feat_btn.setEnabled(True)
        self._rm_feat_btn.setStyleSheet(self._btn_style_enabled)
        self._rm_seg_btn.setEnabled(False)
        self._rm_seg_btn.setStyleSheet(self._btn_style_disabled)

    def _disable_remove_btns(self) -> None:
        self._selected_remove_col = None
        self._selected_remove_row = None
        self._rm_seg_btn.setEnabled(False)
        self._rm_seg_btn.setStyleSheet(self._btn_style_disabled)
        self._rm_feat_btn.setEnabled(False)
        self._rm_feat_btn.setStyleSheet(self._btn_style_disabled)

    def _on_cell_clicked(self, row: int, col: int):
        item = self._table.item(row, col)
        if item is None:
            return
        # Cycle: 0 -> + -> minus -> 0. cycle_value always produces a different
        # value (or resets to "0" from a bad state), so this always
        # records an edit.
        new_val = cycle_value(item.text())
        edits = [_CellEdit(row, col, item.text(), new_val)]
        item.setText(new_val)
        style_cell(item, new_val)
        self._commit_edits(edits)

    # ------------------------------------------------------------------
    # Add / remove segments and features
    # ------------------------------------------------------------------
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
        self._disable_remove_btns()
        self._status.showMessage(f"Removed segment '{seg}'.")

    def _remove_feature(self) -> None:
        """Remove the header-selected row (feature)."""
        row = self._selected_remove_row
        if row is None or row < 0 or row >= len(self._features):
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
        self._disable_remove_btns()
        self._status.showMessage(f"Removed feature '{feat}'.")

    # ------------------------------------------------------------------
    # Serialization (save / load)
    # ------------------------------------------------------------------
    def _to_dict(self) -> dict:
        """Convert the current grid to the JSON-compatible dict format."""
        assert self._table.columnCount() == len(self._segments)
        assert self._table.rowCount() == len(self._features)
        segments = {}
        for c, seg in enumerate(self._segments):
            feats = {}
            for r, feat in enumerate(self._features):
                item = self._table.item(r, c)
                val = item.text() if item else "0"
                if val == "\u2212":
                    val = "-"
                if val not in VALID_VALUES:
                    val = "0"
                feats[feat] = val
            segments[seg] = feats
        return {
            "name": self._inv_name,
            "metadata": {"name": self._inv_name},
            "features": list(self._features),
            "segments": segments,
        }

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
        data = self._to_dict()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
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
        """Load an existing JSON inventory into the grid for editing."""
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            show_warning(self, "Load error", str(e))
            return
        self._inv_name = (
            data.get("metadata", {}).get("name")
            or data.get("name")
            or os.path.basename(path)
        )
        segments_dict = data.get("segments", {})
        declared = data.get("features", [])
        if declared:
            self._features = list(declared)
        else:
            all_feats: set = set()
            for feats in segments_dict.values():
                if isinstance(feats, dict):
                    all_feats.update(feats.keys())
            self._features = sorted(all_feats)
        self._segments = list(segments_dict.keys())
        # Dedup (preserving order)
        self._segments = list(dict.fromkeys(self._segments))
        self._features = list(dict.fromkeys(self._features))
        self._current_path = path
        self._rebuild_table()
        for c, seg in enumerate(self._segments):
            seg_feats = segments_dict.get(seg, {})
            for r, feat in enumerate(self._features):
                val = seg_feats.get(feat, "0")
                self._table.setItem(r, c, make_cell(val))
        self._dirty = False
        self._update_title()
        self._status.showMessage(
            f"Loaded {os.path.basename(path)}: "
            f"{len(self._segments)} segments \u00d7 {len(self._features)} features."
        )

    # ------------------------------------------------------------------
    # Unsaved changes guard
    # ------------------------------------------------------------------
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
            return not self._dirty
        return reply == QMessageBox.StandardButton.Discard

    def closeEvent(self, event):
        if self._check_unsaved():
            event.accept()
        else:
            event.ignore()

    def _update_title(self) -> None:
        name = self._inv_name or "Untitled"
        path = self._current_path
        has_file = bool(path)
        if path:
            fname = os.path.basename(path)
            self.setWindowTitle(f"Inventory Builder: {name} ({fname})")
        else:
            self.setWindowTitle(f"Inventory Builder: {name}")
        # Delete only makes sense when there's an on-disk file backing
        # the current grid; toggle the visual + interactive state.
        self._delete_btn.setEnabled(has_file)
        self._delete_btn.setStyleSheet(
            self._btn_style_enabled if has_file else self._btn_style_disabled
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
