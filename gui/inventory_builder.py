"""
gui/inventory_builder.py
Inventory Builder — create new phonological feature inventories via a grid editor.

Provides a dialog where users can:
  1. Enter segment symbols (IPA Unicode characters)
  2. Enter feature names
  3. Fill in +/−/0 values for each segment × feature cell
  4. Save the result as a JSON file compatible with the main engine
"""

import json
import os
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
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
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from gui.palette import C

# ---------------------------------------------------------------------------
# Standard feature presets
# ---------------------------------------------------------------------------

_FEATURE_PRESETS = {
    "Hayes (28)": [
        "Syllabic",
        "Consonantal",
        "Sonorant",
        "Approximant",
        "Voice",
        "SpreadGl",
        "ConstrGl",
        "Continuant",
        "Strident",
        "DelRel",
        "Nasal",
        "Lateral",
        "Trill",
        "Tap",
        "LABIAL",
        "Round",
        "Labiodental",
        "CORONAL",
        "Anterior",
        "Distributed",
        "DORSAL",
        "High",
        "Low",
        "Back",
        "Front",
        "Tense",
        "Long",
        "Stress",
    ],
    "Custom": [],
}

# Place nodes that should remain all-caps
_ALLCAPS = {"CORONAL", "LABIAL", "DORSAL"}


# ---------------------------------------------------------------------------
# FeatureCell — clickable table cell that cycles through +, −, 0
# ---------------------------------------------------------------------------


def _make_cell(value: str = "0") -> QTableWidgetItem:
    """Create a styled table cell with the given feature value."""
    item = QTableWidgetItem(value)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    _style_cell(item, value)
    return item


def _style_cell(item: QTableWidgetItem, value: str):
    """Apply colour to a cell based on its value."""
    from PyQt6.QtGui import QBrush, QColor

    if value == "+":
        item.setForeground(QBrush(QColor(C["plus"])))
        item.setBackground(QBrush(QColor(C["plus_bg"])))
        item.setFont(QFont("Noto Sans", 10, QFont.Weight.Bold))
    elif value == "−" or value == "-":
        item.setForeground(QBrush(QColor(C["minus"])))
        item.setBackground(QBrush(QColor(C["minus_bg"])))
        item.setFont(QFont("Noto Sans", 10, QFont.Weight.Bold))
    else:
        item.setForeground(QBrush(QColor(C["text_dim"])))
        item.setBackground(QBrush(QColor("#FFFFFF")))
        item.setFont(QFont("Noto Sans", 10))


def _cycle_value(current: str) -> str:
    """Cycle: 0 → + → − → 0."""
    if current == "0":
        return "+"
    elif current == "+":
        return "−"
    else:
        return "0"


# ---------------------------------------------------------------------------
# Segment/Feature input dialog
# ---------------------------------------------------------------------------


class InputDialog(QDialog):
    """Dialog for entering segments and features before opening the grid."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Inventory — Setup")
        self.setMinimumSize(500, 500)
        self.setWindowModality(Qt.WindowModality.WindowModal)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Inventory name
        name_lay = QHBoxLayout()
        name_lay.addWidget(QLabel("Inventory name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. My Language Inventory")
        name_lay.addWidget(self.name_edit)
        layout.addLayout(name_lay)

        # Segments input
        seg_label = QLabel("Segments (one per line, or space-separated):")
        seg_label.setFont(QFont("Noto Sans", 10, QFont.Weight.Bold))
        layout.addWidget(seg_label)

        self.seg_edit = QTextEdit()
        self.seg_edit.setPlaceholderText(
            "p b t d k ɡ\nm n ŋ\nf v s z ʃ ʒ\n..."
        )
        self.seg_edit.setFont(QFont("Noto Sans", 12))
        layout.addWidget(self.seg_edit)

        # Feature preset
        feat_preset_lay = QHBoxLayout()
        feat_preset_lay.addWidget(QLabel("Feature set:"))
        self.preset_combo = QComboBox()
        for name in _FEATURE_PRESETS:
            self.preset_combo.addItem(name)
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        feat_preset_lay.addWidget(self.preset_combo)
        layout.addLayout(feat_preset_lay)

        # Features input
        feat_label = QLabel("Features (one per line, or comma-separated):")
        feat_label.setFont(QFont("Noto Sans", 10, QFont.Weight.Bold))
        layout.addWidget(feat_label)

        self.feat_edit = QTextEdit()
        self.feat_edit.setFont(QFont("Noto Sans", 10))
        layout.addWidget(self.feat_edit)

        # Pre-fill with first preset
        self._on_preset_changed(self.preset_combo.currentText())

        # Buttons
        btn_lay = QHBoxLayout()
        btn_lay.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_lay.addWidget(cancel_btn)

        ok_btn = QPushButton("Create Grid")
        ok_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: {C["accent"]};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: #1D4ED8;
            }}
            """
        )
        ok_btn.clicked.connect(self.accept)
        btn_lay.addWidget(ok_btn)

        layout.addLayout(btn_lay)

    def _on_preset_changed(self, name: str):
        features = _FEATURE_PRESETS.get(name, [])
        if features:
            self.feat_edit.setPlainText("\n".join(features))
            self.feat_edit.setReadOnly(False)
        else:
            self.feat_edit.clear()
            self.feat_edit.setReadOnly(False)
            self.feat_edit.setPlaceholderText(
                "Syllabic\nConsonantal\nSonorant\n..."
            )

    def get_segments(self) -> list:
        text = self.seg_edit.toPlainText().strip()
        if not text:
            return []
        # Split on whitespace and newlines, filter empty
        return [
            s.strip() for s in text.replace("\n", " ").split() if s.strip()
        ]

    def get_features(self) -> list:
        text = self.feat_edit.toPlainText().strip()
        if not text:
            return []
        # Split on newlines or commas
        raw = text.replace(",", "\n").split("\n")
        return [f.strip() for f in raw if f.strip()]

    def get_name(self) -> str:
        return self.name_edit.text().strip() or "Untitled Inventory"


# ---------------------------------------------------------------------------
# InventoryBuilder — main grid editor window
# ---------------------------------------------------------------------------


class InventoryBuilder(QMainWindow):
    """Grid editor for creating phonological feature inventories."""

    def __init__(self, parent=None, load_path: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle("Inventory Builder — A Language Doodad")
        self.setMinimumSize(800, 500)
        self._segments: list = []
        self._features: list = []
        self._inv_name: str = "Untitled Inventory"
        self._current_path: Optional[str] = None

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

    def _build_ui(self):
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setStyleSheet(
            f"""
            QToolBar {{
                background: {C["panel"]};
                border-bottom: 1px solid {C["border"]};
                padding: 4px 8px;
                spacing: 6px;
            }}
            """
        )
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
        save_btn.setStyleSheet(
            f"""
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
        )
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

        # Central table
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget()
        self._table.setFont(QFont("Noto Sans", 10))
        self._table.setStyleSheet(
            f"""
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
            """
        )
        self._table.cellClicked.connect(self._on_cell_clicked)
        self._table.installEventFilter(self)
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

    def _show_setup_dialog(self):
        dlg = InputDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        segments = dlg.get_segments()
        features = dlg.get_features()
        name = dlg.get_name()

        if not segments:
            QMessageBox.warning(
                self, "No segments", "Please enter at least one segment."
            )
            return
        if not features:
            QMessageBox.warning(
                self, "No features", "Please enter at least one feature."
            )
            return

        # Check for duplicate segments
        seen = set()
        unique = []
        for s in segments:
            if s not in seen:
                seen.add(s)
                unique.append(s)
        segments = unique

        self._segments = segments
        self._features = features
        self._inv_name = name
        self._current_path = None
        self._rebuild_table()
        self._update_title()
        self._status.showMessage(
            f"Created grid: {len(segments)} segments \u00d7 {len(features)} features. "
            "Click cells to cycle through +/\u2212/0."
        )

    def _rebuild_table(self):
        """Build the table: rows=features, cols=segments."""
        self._table.clear()
        self._table.setRowCount(len(self._features))
        self._table.setColumnCount(len(self._segments))

        # Headers: features down the left, segments across the top
        self._table.setVerticalHeaderLabels(self._features)
        self._table.setHorizontalHeaderLabels(self._segments)

        v_header = self._table.verticalHeader()
        if v_header:
            v_header.setFont(QFont("Noto Sans", 9))
            v_header.setSectionResizeMode(
                QHeaderView.ResizeMode.ResizeToContents
            )
            v_header.setMinimumSectionSize(24)

        h_header = self._table.horizontalHeader()
        if h_header:
            h_header.setFont(QFont("Noto Sans", 11))
            h_header.setDefaultSectionSize(36)
            h_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
            h_header.setMinimumSectionSize(32)

        # Fill with default "0" cells
        for r in range(len(self._features)):
            for c in range(len(self._segments)):
                self._table.setItem(r, c, _make_cell("0"))

    def eventFilter(self, obj, event):
        if obj is self._table and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Space:
                row = self._table.currentRow()
                col = self._table.currentColumn()
                if row >= 0 and col >= 0:
                    self._on_cell_clicked(row, col)
                    return True
        return super().eventFilter(obj, event)

    def _on_cell_clicked(self, row: int, col: int):
        item = self._table.item(row, col)
        if item is None:
            return
        current = item.text()
        new_val = _cycle_value(current)
        item.setText(new_val)
        _style_cell(item, new_val)

    def _add_segment(self):
        """Prompt for a new segment and add a column."""
        from PyQt6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(
            self, "Add Segment", "Segment symbol (IPA):"
        )
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
            self._table.setItem(r, col, _make_cell("0"))
        self._status.showMessage(f"Added segment '{seg}'.")

    def _add_feature(self):
        """Prompt for a new feature and add a row."""
        from PyQt6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(self, "Add Feature", "Feature name:")
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
            self._table.setItem(row, c, _make_cell("0"))
        self._status.showMessage(f"Added feature '{feat}'.")

    def _to_dict(self) -> dict:
        """Convert the current grid to the JSON-compatible dict format.

        Table layout: rows=features, cols=segments.
        """
        segments = {}
        for c, seg in enumerate(self._segments):
            feats = {}
            for r, feat in enumerate(self._features):
                item = self._table.item(r, c)
                val = item.text() if item else "0"
                if val == "\u2212":
                    val = "-"
                feats[feat] = val
            segments[seg] = feats

        return {
            "name": self._inv_name,
            "features": list(self._features),
            "segments": segments,
        }

    def _save(self):
        if self._current_path:
            self._write_json(self._current_path)
        else:
            self._save_as()

    def _save_as(self):
        config_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "config")
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Inventory", config_dir, "JSON Files (*.json)"
        )
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
        self._status.showMessage(f"Saved to {os.path.basename(path)}")

    def _open_file(self):
        config_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "config")
        )
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Inventory", config_dir, "JSON Files (*.json)"
        )
        if path:
            self._load_existing(path)

    def _load_existing(self, path: str):
        """Load an existing JSON inventory into the grid for editing."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            QMessageBox.warning(self, "Load error", str(e))
            return

        self._inv_name = data.get("name", os.path.basename(path))
        segments_dict = data.get("segments", {})

        # Extract features: prefer declared list, fall back to union of all segment keys
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
        self._current_path = path

        self._rebuild_table()

        # Fill in the values (rows=features, cols=segments)
        for c, seg in enumerate(self._segments):
            seg_feats = segments_dict.get(seg, {})
            for r, feat in enumerate(self._features):
                val = seg_feats.get(feat, "0")
                self._table.setItem(r, c, _make_cell(val))

        self._update_title()
        self._status.showMessage(
            f"Loaded {os.path.basename(path)}: "
            f"{len(self._segments)} segments \u00d7 {len(self._features)} features."
        )

    def _update_title(self):
        name = self._inv_name or "Untitled"
        if self._current_path:
            fname = os.path.basename(self._current_path)
            self.setWindowTitle(f"{name} ({fname}) — Inventory Builder")
        else:
            self.setWindowTitle(f"{name} — Inventory Builder")
