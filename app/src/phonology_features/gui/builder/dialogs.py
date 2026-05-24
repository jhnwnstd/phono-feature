"""Reusable dialog helpers and the InputDialog for inventory setup."""

from phonology_features.gui.builder.presets import FEATURE_PRESETS
from phonology_features.gui.palette import C
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QTextCursor
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


class _AutofillTextEdit(QTextEdit):
    """QTextEdit with two shared affordances used by both the segment
    and feature inputs in the New Inventory dialog:

    1. **Tab autofill**: Tab on an empty box pastes ``DEFAULT_FILL``
       (a quick-start example). Once non-empty, Tab advances focus
       normally via ``setTabChangesFocus``.

       ``setTabChangesFocus(True)`` makes Qt route Tab through
       ``event()`` to ``focusNextPrevChild`` BEFORE ``keyPressEvent``
       runs; the autofill branch returns True to consume the event
       so focus stays.

    2. **``entries()`` parser**: splits the contents on any whitespace
       (spaces, tabs, newlines). Both ``a b c`` and one-per-line input
       parse to the same list.

    Also overrides ``paintEvent`` to render multi-line placeholder text
    (Qt only paints the first line of placeholderText).
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
            self.setPlainText(self.DEFAULT_FILL)
            # Land the caret at the end of the seeded text so the user
            # can type a continuation without having to click first.
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.setTextCursor(cursor)
            return True
        return super().event(e)

    def entries(self) -> list[str]:
        """Parse the current text as a list of entries. Default splits
        on any whitespace -- spaces, tabs, newlines. Subclasses
        override when a different split rule applies (e.g. Features
        only one per line)."""
        return [token for token in self.toPlainText().split() if token]

    def paintEvent(self, e):  # type: ignore[override]
        super().paintEvent(e)
        if self.toPlainText() or not self.placeholderText():
            return
        lines = self.placeholderText().splitlines()
        if len(lines) <= 1:
            return
        painter = QPainter(self.viewport())
        painter.setPen(QColor(C["text_dim"]))
        painter.setFont(self.font())
        metrics = painter.fontMetrics()
        margin = int(self.document().documentMargin())
        x = margin
        # Skip the first line; Qt already painted it.
        y = margin + metrics.ascent() + metrics.lineSpacing()
        for line in lines[1:]:
            painter.drawText(x, y, line)
            y += metrics.lineSpacing()
        painter.end()


class SegmentTextEdit(_AutofillTextEdit):
    """Tab on empty fills a quick-start segment list (IPA voiceless and
    voiced stops)."""

    DEFAULT_FILL = (
        "p b t d k \u0261"  # noqa: RUF001; IPA voiced velar (script g)
    )


class FeatureTextEdit(_AutofillTextEdit):
    """Tab on empty seeds the two major-class features (Syllabic and
    Consonantal) as a starting point for a custom set. The full
    Default (33) preset is in the dropdown.

    Features are one-per-line (overrides the whitespace-split base):
    feature names may legitimately contain spaces or unusual chars
    that a whitespace splitter would shred."""

    DEFAULT_FILL = "Syllabic\nConsonantal"

    def entries(self) -> list[str]:
        return [
            line.strip()
            for line in self.toPlainText().splitlines()
            if line.strip()
        ]


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
        self.setWindowTitle("New Inventory Setup")
        self.setMinimumSize(500, 500)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addLayout(self._build_name_row())
        self._add_segments_section(layout)
        self._add_features_section(layout)
        layout.addLayout(self._build_button_row())

    def _build_name_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Inventory name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. My Language Inventory")
        row.addWidget(self.name_edit)
        return row

    def _add_segments_section(self, parent: QVBoxLayout) -> None:
        label = QLabel("Segments (one per line, or space-separated):")
        label.setFont(QFont("Noto Sans", 10, QFont.Weight.Bold))
        parent.addWidget(label)
        self.seg_edit = SegmentTextEdit()
        # Placeholder = what Tab fills; the grayed text is the hint.
        self.seg_edit.setPlaceholderText(SegmentTextEdit.DEFAULT_FILL)
        self.seg_edit.setFont(QFont("Noto Sans", 12))
        parent.addWidget(self.seg_edit)

    def _add_features_section(self, parent: QVBoxLayout) -> None:
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Feature set:"))
        self.preset_combo = QComboBox()
        # Native combo highlight is white-on-white in some OS themes;
        # mirror MainWindow's inventory dropdown styling so items stay
        # legible when highlighted.
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
        preset_row.addWidget(self.preset_combo)
        parent.addLayout(preset_row)
        feat_label = QLabel("Features (one per line):")
        feat_label.setFont(QFont("Noto Sans", 10, QFont.Weight.Bold))
        parent.addWidget(feat_label)
        self.feat_edit = FeatureTextEdit()
        self.feat_edit.setFont(QFont("Noto Sans", 10))
        self.feat_edit.setPlaceholderText(FeatureTextEdit.DEFAULT_FILL)
        parent.addWidget(self.feat_edit)
        self._on_preset_changed(self.preset_combo.currentText())

    def _build_button_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        row.addWidget(cancel_btn)
        ok_btn = QPushButton("Create Grid")
        ok_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C["btn_primary"]};
                color: {C["btn_primary_text"]};
                border: none;
                border-radius: 6px;
                padding: 6px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {C["btn_primary_hover"]};
                color: {C["btn_primary_hover_text"]};
            }}
            """)
        ok_btn.clicked.connect(self.accept)
        row.addWidget(ok_btn)
        return row

    def _on_preset_changed(self, name: str):
        features = FEATURE_PRESETS.get(name, [])
        if features:
            self.feat_edit.setPlainText("\n".join(features))
            self.feat_edit.setReadOnly(False)
            return
        self.feat_edit.clear()
        self.feat_edit.setReadOnly(False)

    def get_segments(self) -> list:
        return self.seg_edit.entries()

    def get_features(self) -> list:
        return self.feat_edit.entries()

    def get_name(self) -> str:
        name = self.name_edit.text().strip()
        if name:
            return name
        return "Untitled Inventory"

    def accept(self) -> None:  # type: ignore[override]
        """Validate inputs before dismissing. On failure, warn, focus
        the offending field, and keep the dialog open.
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
