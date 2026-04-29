"""
gui/builder/dialogs.py

Reusable dialog helpers and the InputDialog for inventory setup.
"""

from PyQt6.QtCore import QEvent, Qt
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


class _AutofillTextEdit(QTextEdit):
    """QTextEdit shared base: on Tab while empty, fill a class-defined
    DEFAULT_FILL value, then move focus to the next dialog widget.

    Implementation note: when ``setTabChangesFocus`` is True, Qt routes
    Tab through ``event()`` to ``focusNextPrevChild`` BEFORE
    ``keyPressEvent`` is called. The autofill branch lives in
    ``event()`` so it can run *before* that focus routing kicks in.
    """

    DEFAULT_FILL: str = ""  # subclasses override

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabChangesFocus(True)

    def event(self, e: QEvent | None) -> bool:  # type: ignore[override]
        if (
            e is not None
            and e.type() == QEvent.Type.KeyPress
            and e.key() == Qt.Key.Key_Tab  # type: ignore[attr-defined]
            and self.DEFAULT_FILL
            and not self.toPlainText().strip()
        ):
            # Empty + Tab: fill quick-start, then fall through so Qt's
            # tabChangesFocus handler does the focus advance.
            self.setPlainText(self.DEFAULT_FILL)
        return super().event(e)


class SegmentTextEdit(_AutofillTextEdit):
    """Tab on empty fills a quick-start segment list (IPA voiceless and
    voiced stops)."""

    DEFAULT_FILL = "p b t d k ɡ"  # noqa: RUF001 — IPA voiced velar (script g)


class FeatureTextEdit(_AutofillTextEdit):
    """Tab on empty fills the Default (33) feature preset, mirroring the
    quick-start behavior of SegmentTextEdit. Useful when the user picks
    'Custom' from the preset combo (which clears the box) and then
    decides they actually want the standard set after all."""

    DEFAULT_FILL = "\n".join(FEATURE_PRESETS["Default (33)"])


def center_on_parent(dialog, parent):
    """Move dialog to the center of parent's screen."""
    if parent is None:
        return

    screen = parent.screen()
    if screen is None:
        return

    screen_geometry = screen.availableGeometry()
    dialog_frame = dialog.frameGeometry()

    dialog_frame.moveCenter(screen_geometry.center())
    dialog.move(dialog_frame.topLeft())


def ask_question(parent, title: str, text: str, buttons=None, default=None):
    """Show a question dialog centered on parent's screen."""
    if buttons is None:
        buttons = (
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

    if default is None:
        default = QMessageBox.StandardButton.No

    box = QMessageBox(
        QMessageBox.Icon.Question,
        title,
        text,
        buttons,
        parent,
    )

    box.setDefaultButton(default)
    center_on_parent(box, parent)

    return box.exec()


def show_warning(parent, title: str, text: str):
    """Show a warning dialog centered on parent's screen."""
    box = QMessageBox(
        QMessageBox.Icon.Warning,
        title,
        text,
        QMessageBox.StandardButton.Ok,
        parent,
    )

    center_on_parent(box, parent)
    box.exec()


class InputDialog(QDialog):
    """Dialog for entering segments and features before opening the grid."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("New Inventory — Setup")
        self.setMinimumSize(500, 500)
        self.setWindowModality(Qt.WindowModality.WindowModal)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        name_lay = QHBoxLayout()
        name_label = QLabel("Inventory name:")

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. My Language Inventory")

        name_lay.addWidget(name_label)
        name_lay.addWidget(self.name_edit)
        layout.addLayout(name_lay)

        seg_label = QLabel("Segments (one per line, or space-separated):")
        seg_label.setFont(QFont("Noto Sans", 10, QFont.Weight.Bold))
        layout.addWidget(seg_label)

        self.seg_edit = SegmentTextEdit()
        self.seg_edit.setPlaceholderText(
            "p b t d k ɡ\nm n ŋ\nf v s z ʃ ʒ\n…\n"
            "(Tab on an empty box fills in a quick-start set)"
        )  # noqa: RUF001
        self.seg_edit.setFont(QFont("Noto Sans", 12))
        layout.addWidget(self.seg_edit)

        feat_preset_lay = QHBoxLayout()
        feat_preset_label = QLabel("Feature set:")

        self.preset_combo = QComboBox()
        # Native combo highlight is white-on-white in some OS themes,
        # making the focused/selected item invisible. Use the same accent-
        # light + accent-text scheme MainWindow's config dropdown uses so
        # both "Default (33)" and "Custom" stay legible when highlighted.
        self.preset_combo.setStyleSheet(f"""
            QComboBox {{
                background: {C["panel"]};
                color: {C["text"]};
                border: 1.5px solid {C["border"]};
                border-radius: 4px;
                padding: 2px 8px;
            }}
            QComboBox:hover {{
                border: 1.5px solid {C["accent"]};
            }}
            QComboBox QAbstractItemView {{
                background: {C["panel"]};
                color: {C["text"]};
                border: 1px solid {C["border"]};
                selection-background-color: {C["accent_light"]};
                selection-color: {C["accent"]};
                outline: none;
            }}
        """)

        for name in FEATURE_PRESETS:
            self.preset_combo.addItem(name)

        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)

        feat_preset_lay.addWidget(feat_preset_label)
        feat_preset_lay.addWidget(self.preset_combo)
        layout.addLayout(feat_preset_lay)

        feat_label = QLabel("Features (one per line, or comma-separated):")
        feat_label.setFont(QFont("Noto Sans", 10, QFont.Weight.Bold))
        layout.addWidget(feat_label)

        self.feat_edit = FeatureTextEdit()
        self.feat_edit.setFont(QFont("Noto Sans", 10))
        # Mirror the segment-box hint so the Tab-autofill is discoverable.
        self.feat_edit.setPlaceholderText(
            "Syllabic\nConsonantal\nSonorant\n…\n"
            "(Tab on an empty box fills the Default (33) preset)"
        )
        layout.addWidget(self.feat_edit)

        selected_preset = self.preset_combo.currentText()
        self._on_preset_changed(selected_preset)

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
            feature_text = "\n".join(features)
            self.feat_edit.setPlainText(feature_text)
            self.feat_edit.setReadOnly(False)
            return

        self.feat_edit.clear()
        self.feat_edit.setReadOnly(False)
        # Placeholder set once at construction; no need to overwrite it.

    def get_segments(self) -> list:
        text = self.seg_edit.toPlainText().strip()

        if not text:
            return []

        text = text.replace("\n", " ")
        raw_segments = text.split()

        return [segment.strip() for segment in raw_segments if segment.strip()]

    def get_features(self) -> list:
        text = self.feat_edit.toPlainText().strip()

        if not text:
            return []

        text = text.replace(",", "\n")
        raw_features = text.split("\n")

        return [feature.strip() for feature in raw_features if feature.strip()]

    def get_name(self) -> str:
        name = self.name_edit.text().strip()

        if name:
            return name

        return "Untitled Inventory"

    def accept(self) -> None:  # type: ignore[override]
        """Validate inputs before dismissing. If validation fails, show a
        warning, focus the offending field, and keep the dialog open so the
        user can fix it without losing what they typed.
        """
        if not self.get_segments():
            QMessageBox.warning(
                self,
                "No segments",
                "Please enter at least one segment "
                "(or press Tab in the segment box for a quick-start set).",
            )
            self.seg_edit.setFocus()
            return
        if not self.get_features():
            QMessageBox.warning(
                self,
                "No features",
                "Please enter at least one feature, "
                "or pick a feature set from the dropdown.",
            )
            self.feat_edit.setFocus()
            return
        super().accept()
