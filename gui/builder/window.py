"""
gui/builder/window.py
InventoryBuilder — main grid editor window for creating/editing inventories.
"""

import json
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHeaderView,
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

from gui.builder.dialogs import (
    InputDialog,
    ask_question,
    center_on_parent,
    show_warning,
)
from gui.builder.grid import cycle_value, make_cell, style_cell
from gui.builder.presets import VALID_VALUES
from gui.palette import C


class InventoryBuilder(QMainWindow):
    """Grid editor for creating phonological feature inventories."""

    def __init__(self, parent=None, load_path: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Inventory Builder — A Language Doodad")
        self.setMinimumSize(800, 500)
        self._segments: list = []
        self._features: list = []
        self._inv_name: str = "Untitled Inventory"
        self._current_path: str | None = None
        self._dirty: bool = False
        self._selected_remove_col: int | None = None
        self._selected_remove_row: int | None = None

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

        new_btn = QPushButton("New")
        new_btn.setFont(QFont("Noto Sans", 10))
        new_btn.setFixedHeight(32)
        new_btn.setStyleSheet(btn_style)
        new_btn.clicked.connect(self._show_setup_dialog)
        toolbar.addWidget(new_btn)

        open_btn = QPushButton("Open\u2026")
        open_btn.setFont(QFont("Noto Sans", 10))
        open_btn.setFixedHeight(32)
        open_btn.setStyleSheet(btn_style)
        open_btn.clicked.connect(self._open_file)
        toolbar.addWidget(open_btn)

        save_btn = QPushButton("Save")
        save_btn.setFont(QFont("Noto Sans", 10))
        save_btn.setFixedHeight(32)
        save_btn.setStyleSheet(f"""
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
            """)
        save_btn.clicked.connect(self._save)
        toolbar.addWidget(save_btn)

        saveas_btn = QPushButton("Save As\u2026")
        saveas_btn.setFont(QFont("Noto Sans", 10))
        saveas_btn.setFixedHeight(32)
        saveas_btn.setStyleSheet(btn_style)
        saveas_btn.clicked.connect(self._save_as)
        toolbar.addWidget(saveas_btn)

        # Add segment button
        toolbar.addSeparator()
        add_seg_btn = QPushButton("+ Segment")
        add_seg_btn.setFont(QFont("Noto Sans", 10))
        add_seg_btn.setFixedHeight(32)
        add_seg_btn.setStyleSheet(btn_style)
        add_seg_btn.clicked.connect(self._add_segment)
        toolbar.addWidget(add_seg_btn)

        add_feat_btn = QPushButton("+ Feature")
        add_feat_btn.setFont(QFont("Noto Sans", 10))
        add_feat_btn.setFixedHeight(32)
        add_feat_btn.setStyleSheet(btn_style)
        add_feat_btn.clicked.connect(self._add_feature)
        toolbar.addWidget(add_feat_btn)

        toolbar.addSeparator()

        self._rm_seg_btn = QPushButton("\u2212 Segment")
        self._rm_seg_btn.setFont(QFont("Noto Sans", 10))
        self._rm_seg_btn.setFixedHeight(32)
        self._rm_seg_btn.setEnabled(False)
        self._rm_seg_btn.clicked.connect(self._remove_segment)
        toolbar.addWidget(self._rm_seg_btn)

        self._rm_feat_btn = QPushButton("\u2212 Feature")
        self._rm_feat_btn.setFont(QFont("Noto Sans", 10))
        self._rm_feat_btn.setFixedHeight(32)
        self._rm_feat_btn.setEnabled(False)
        self._rm_feat_btn.clicked.connect(self._remove_feature)
        toolbar.addWidget(self._rm_feat_btn)

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
        self._rm_seg_btn.setStyleSheet(self._btn_style_disabled)
        self._rm_feat_btn.setStyleSheet(self._btn_style_disabled)

        # Central table
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

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

        h_header = self._table.horizontalHeader()
        v_header = self._table.verticalHeader()
        if h_header:
            h_header.sectionClicked.connect(self._on_col_header_clicked)
        if v_header:
            v_header.sectionClicked.connect(self._on_row_header_clicked)
        layout.addWidget(self._table)

        # Status bar
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

    def _show_setup_dialog(self) -> bool:
        """Show the new-inventory setup dialog. Returns True if the user
        committed and a fresh grid was built; False if they cancelled or
        the unsaved-changes check refused.

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

    def eventFilter(self, obj, event):
        if (
            obj is self._table
            and event.type() == event.Type.KeyPress
            and event.key() == Qt.Key.Key_Space
        ):
            row = self._table.currentRow()
            col = self._table.currentColumn()
            if row >= 0 and col >= 0:
                self._on_cell_clicked(row, col)
                return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # Header selection / remove button state
    # ------------------------------------------------------------------

    def _on_col_header_clicked(self, col: int):
        """A segment column header was clicked — enable segment removal only."""
        self._selected_remove_col = col
        self._selected_remove_row = None
        self._table.selectColumn(col)
        self._rm_seg_btn.setEnabled(True)
        self._rm_seg_btn.setStyleSheet(self._btn_style_enabled)
        self._rm_feat_btn.setEnabled(False)
        self._rm_feat_btn.setStyleSheet(self._btn_style_disabled)

    def _on_row_header_clicked(self, row: int):
        """A feature row header was clicked — enable feature removal only."""
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
        current = item.text()
        new_val = cycle_value(current)
        item.setText(new_val)
        style_cell(item, new_val)
        self._dirty = True
        self._disable_remove_btns()

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
        config_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config")
        )
        dlg = QFileDialog(
            self, "Save Inventory", config_dir, "JSON Files (*.json)"
        )
        dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
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

    def _open_file(self) -> None:
        if not self._check_unsaved():
            return
        config_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config")
        )
        dlg = QFileDialog(
            self, "Open Inventory", config_dir, "JSON Files (*.json)"
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
        if self._current_path:
            fname = os.path.basename(self._current_path)
            self.setWindowTitle(f"{name} ({fname}) \u2014 Inventory Builder")
        else:
            self.setWindowTitle(f"{name} \u2014 Inventory Builder")
