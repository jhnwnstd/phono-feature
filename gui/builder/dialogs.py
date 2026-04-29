"""
gui/builder/dialogs.py
Reusable dialog helpers and the InputDialog for inventory setup.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from gui.builder.presets import FEATURE_PRESETS
from gui.palette import C

# ---------------------------------------------------------------------------
# Dialog positioning helpers
# ---------------------------------------------------------------------------


def center_on_parent(dialog, parent):
    """Move *dialog* to the center of *parent*'s screen.

    On multi-monitor setups (especially WSL2/X11), Qt's static dialog
    helpers sometimes place windows on the primary monitor instead of
    the parent's monitor.  This ensures co-location.
    """
    if parent is None:
        return
    screen = parent.screen()
    if screen is None:
        return
    geo = screen.availableGeometry()
    frame = dialog.frameGeometry()
    frame.moveCenter(geo.center())
    dialog.move(frame.topLeft())


def ask_question(parent, title: str, text: str, buttons=None, default=None):
    """Show a question dialog centered on *parent*'s screen."""
    if buttons is None:
        buttons = (
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
    if default is None:
        default = QMessageBox.StandardButton.No
    box = QMessageBox(QMessageBox.Icon.Question, title, text, buttons, parent)
    box.setDefaultButton(default)
    center_on_parent(box, parent)
    return box.exec()


def show_warning(parent, title: str, text: str):
    """Show a warning dialog centered on *parent*'s screen."""
    box = QMessageBox(
        QMessageBox.Icon.Warning,
        title,
        text,
        QMessageBox.StandardButton.Ok,
        parent,
    )
    center_on_parent(box, parent)
    box.exec()


# ---------------------------------------------------------------------------
# InputDialog — segment/feature setup before opening the grid
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
        )  # noqa: RUF001
        self.seg_edit.setFont(QFont("Noto Sans", 12))
        layout.addWidget(self.seg_edit)

        # Feature preset
        feat_preset_lay = QHBoxLayout()
        feat_preset_lay.addWidget(QLabel("Feature set:"))
        self.preset_combo = QComboBox()
        for name in FEATURE_PRESETS:
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
        ok_btn.setStyleSheet(f"""
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
            """)
        ok_btn.clicked.connect(self.accept)
        btn_lay.addWidget(ok_btn)

        layout.addLayout(btn_lay)

    def _on_preset_changed(self, name: str):
        features = FEATURE_PRESETS.get(name, [])
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
        return [
            s.strip() for s in text.replace("\n", " ").split() if s.strip()
        ]

    def get_features(self) -> list:
        text = self.feat_edit.toPlainText().strip()
        if not text:
            return []
        raw = text.replace(",", "\n").split("\n")
        return [f.strip() for f in raw if f.strip()]

    def get_name(self) -> str:
        return self.name_edit.text().strip() or "Untitled Inventory"
