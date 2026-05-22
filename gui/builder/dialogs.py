"""
gui/builder/dialogs.py

Reusable dialog helpers and the InputDialog for inventory setup.
"""

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QColor, QFont, QPainter
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
    DEFAULT_FILL value. Subsequent Tab presses (with the box non-empty)
    advance focus normally via ``setTabChangesFocus``.

    Implementation note: ``setTabChangesFocus(True)`` makes Qt route
    Tab through ``event()`` to ``focusNextPrevChild`` BEFORE
    ``keyPressEvent`` is called. The autofill branch returns ``True``
    to consume the event so the very same press doesn't also advance
    focus to the next widget; that's separately reachable with a
    second Tab press once the box has content.

    Also overrides ``paintEvent`` to render multi-line placeholder text:
    QTextEdit's built-in placeholder paints only the first line, which
    hides the rest of the hint. We bypass it by painting the lines
    ourselves; callers should set the multi-line text via
    ``setPlaceholderText`` as usual.
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
            # Empty + Tab: fill the seed text and consume the event so
            # focus stays here. The user can hit Tab a second time to
            # advance to the next widget once they're satisfied with
            # what got filled.
            self.setPlainText(self.DEFAULT_FILL)
            return True
        return super().event(e)

    def paintEvent(self, e):  # type: ignore[override]
        super().paintEvent(e)
        # Qt only renders the first line of placeholderText. When the box
        # is empty, draw the remaining lines ourselves so multi-line
        # hints (e.g. "Syllabic / Consonantal / (Tab fills these two)")
        # are fully visible.
        if self.toPlainText() or not self.placeholderText():
            return
        lines = self.placeholderText().splitlines()
        if len(lines) <= 1:
            return
        painter = QPainter(self.viewport())
        painter.setPen(QColor(C["text_dim"]))
        painter.setFont(self.font())
        metrics = painter.fontMetrics()
        # Match Qt's first-line origin: top-left of the document margin.
        # ``documentMargin`` is the inset Qt uses when laying out text.
        margin = int(self.document().documentMargin())
        x = margin
        y = margin + metrics.ascent()
        # Skip the first line; Qt already painted it.
        y += metrics.lineSpacing()
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
    """Tab on empty seeds just the two major-class features (Syllabic and
    Consonantal) so the user has a starting point to build a custom set
    from. The full Default (33) preset is available directly from the
    dropdown; no point dumping it here too."""

    DEFAULT_FILL = "Syllabic\nConsonantal"


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
        # Placeholder = exactly what Tab fills. The grayed text IS the hint.
        self.seg_edit.setPlaceholderText(SegmentTextEdit.DEFAULT_FILL)
        self.seg_edit.setFont(QFont("Noto Sans", 12))
        parent.addWidget(self.seg_edit)

    def _add_features_section(self, parent: QVBoxLayout) -> None:
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Feature set:"))
        self.preset_combo = QComboBox()
        # Native combo highlight is white-on-white in some OS themes,
        # making the focused/selected item invisible. Use the same
        # accent-light + accent-text scheme MainWindow's config dropdown
        # uses so both "Default (33)" and "Custom" stay legible when
        # highlighted.
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
        feat_label = QLabel("Features (one per line, or comma-separated):")
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
        row.addWidget(ok_btn)
        return row

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
