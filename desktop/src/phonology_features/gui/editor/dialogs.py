"""Reusable dialog helpers and the InputDialog for inventory setup."""

from typing import ClassVar

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import QFont, QPainter, QPaintEvent, QTextCursor
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from phonology_features.gui.controllers.theme import ThemeController
from phonology_features.providers import available_providers
from phonology_shared.data.limits import MAX_NAME_LENGTH
from phonology_shared.editor.providers import FeatureProvider
from phonology_shared.editor.setup import (
    DEFAULT_FEATURES,
    DEFAULT_SEGMENTS,
    FEATURE_PRESETS,
    SETUP_DIALOG_TITLE,
    SETUP_NAME_PLACEHOLDER,
    infer_split,
    normalize_setup_name,
    validate_setup,
)
from phonology_shared.presentation.palette import C


class _AutofillTextEdit(QPlainTextEdit):
    """Segment/feature input for the New Inventory dialog, with two
    shared affordances. ``QPlainTextEdit`` (not QTextEdit) is the
    correct base for untrusted text: QTextEdit interprets HTML on
    paste and would briefly render pasted rich text, even though
    ``entries()`` later strips formatting via ``toPlainText``.

    Tab autofill: Tab on an empty box pastes ``DEFAULT_FILL`` (a
    quick-start example); once non-empty, Tab advances focus.
    ``setTabChangesFocus(True)`` routes Tab through ``event()`` to
    ``focusNextPrevChild`` before ``keyPressEvent``, so the autofill
    branch there returns True to consume the event and keep focus.

    ``entries()`` splits the contents on any whitespace, so ``a b c``
    and one-per-line input parse to the same list.

    ``paintEvent`` renders multi-line placeholder text because Qt only
    paints the first line of placeholderText.
    """

    DEFAULT_FILL: str = ""  # subclasses override

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTabChangesFocus(True)
        # Stored separately from Qt's placeholderText so our paintEvent
        # owns the full multi-line render. See setPlaceholderText.
        self._placeholder: str = ""

    def setPlaceholderText(self, text: str) -> None:  # type: ignore[override]
        """Capture the placeholder for our multi-line paint and tell Qt
        its placeholder is empty, so every line comes from the same
        paintEvent path and shades identically."""
        self._placeholder = text
        super().setPlaceholderText("")

    def placeholderText(self) -> str:
        return self._placeholder

    def event(self, e: QEvent | None) -> bool:
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
        """Parse the current text into entries with an inferred
        delimiter (see :py:func:`infer_split`), so pasted input from
        any source works without pre-processing."""
        return infer_split(self.toPlainText())

    def paintEvent(self, e: QPaintEvent | None) -> None:
        super().paintEvent(e)
        if self.toPlainText() or not self.placeholderText():
            return
        lines = self.placeholderText().splitlines()
        if not lines:
            return
        # Paint every placeholder line here, not just the lines past
        # the first. Qt paints only the first line, and when both Qt
        # and we paint the same buffer the alpha-blended lines land at
        # different effective opacities, so adjacent lines show
        # different shades. Owning the whole paint keeps them uniform.
        painter = QPainter(self.viewport())
        painter.setPen(self.palette().placeholderText().color())
        painter.setFont(self.font())
        metrics = painter.fontMetrics()
        doc = self.document()
        margin = int(doc.documentMargin()) if doc is not None else 0
        x = margin
        y = margin + metrics.ascent()
        for line in lines:
            painter.drawText(x, y, line)
            y += metrics.lineSpacing()
        painter.end()


class SegmentTextEdit(_AutofillTextEdit):
    """Tab on empty fills a quick-start segment list. The trailing
    space in DEFAULT_FILL lands the caret ready for the next segment;
    ``entries()`` filters empties, so it adds no phantom entry."""

    # Sourced from the shared setup module so the web setup dialog
    # offers the same Tab-autofill string.
    DEFAULT_FILL = DEFAULT_SEGMENTS


class FeatureTextEdit(_AutofillTextEdit):
    """Tab on empty seeds the two major-class features as a start for
    a custom set (fuller Hayes/PHOIBLE starts are in the preset
    dropdown). The inferred-delimiter parser accepts any consistent
    delimiter, so feature names may contain spaces (e.g. "Long Vowel")
    when the user separates entries with something other than
    whitespace."""

    DEFAULT_FILL = DEFAULT_FEATURES


def center_on_parent(dialog: QWidget, parent: QWidget | None) -> None:
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


def ask_question(
    parent: QWidget | None,
    title: str,
    text: str,
    buttons: QMessageBox.StandardButton | None = None,
    default: QMessageBox.StandardButton | None = None,
) -> int:
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


def show_warning(parent: QWidget | None, title: str, text: str) -> None:
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


def prompt_text(
    parent: QWidget | None,
    title: str,
    label: str,
    initial: str = "",
) -> str | None:
    """Show a single-line text prompt centered on parent's screen.

    Returns the entered text, or None if the user cancelled. Callers
    own any trimming or validation of the returned value.
    """
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    if initial:
        dlg.setTextValue(initial)
    center_on_parent(dlg, parent)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return dlg.textValue()


class InputDialog(QDialog):
    """Dialog for entering segments and features before opening the grid."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(SETUP_DIALOG_TITLE)
        self.setMinimumSize(500, 500)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        # Provider chosen via the preset dropdown. ``None`` means a
        # static features-only preset (Default/Custom): the editor
        # takes the typed feature list verbatim and makes an empty
        # grid. Non-None means it calls ``provider.generate(segments)``
        # on accept and pre-populates cells.
        self._chosen_provider: FeatureProvider | None = None
        # Maps each provider's combo display label to its instance.
        self._provider_by_label: dict[str, FeatureProvider] = {}
        # Debounce the features-preview regeneration while a provider
        # is chosen and the user edits the segments textarea.
        # ``generate`` is fast, but running it per keystroke flashes
        # the textarea; 250 ms of idle feels responsive without it.
        self._provider_refresh_timer = QTimer(self)
        self._provider_refresh_timer.setSingleShot(True)
        self._provider_refresh_timer.setInterval(250)
        self._provider_refresh_timer.timeout.connect(
            self._refresh_provider_features
        )
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
        # UI cap mirrors the parser cap (Inventory.MAX_NAME_LENGTH) so
        # the field stops accepting input at the limit instead of
        # deferring the error to save.
        self.name_edit.setMaxLength(MAX_NAME_LENGTH)
        self.name_edit.setPlaceholderText(SETUP_NAME_PLACEHOLDER)
        row.addWidget(self.name_edit)
        return row

    def _add_segments_section(self, parent: QVBoxLayout) -> None:
        label = QLabel("Segments (delimited):")
        label.setFont(QFont("Noto Sans", 10, QFont.Weight.Bold))
        parent.addWidget(label)
        self.seg_edit = SegmentTextEdit()
        # Placeholder equals what Tab fills; the grayed text doubles as
        # a format hint for the inferred-delimiter parser.
        self.seg_edit.setPlaceholderText(SegmentTextEdit.DEFAULT_FILL)
        self.seg_edit.setFont(QFont("Noto Sans", 12))
        self.seg_edit.textChanged.connect(self._on_segments_changed)
        # Stretch 1 here vs 4 on the features edit below: segments are
        # a short list while features run to 30+ entries, so features
        # get most of the vertical room.
        parent.addWidget(self.seg_edit, stretch=1)

    def _add_features_section(self, parent: QVBoxLayout) -> None:
        self.preset_combo = QComboBox()
        # Native combo highlight is white-on-white in some OS themes;
        # mirror MainWindow's inventory dropdown styling so highlighted
        # items stay legible.
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
        # Display order: providers first (PanPhon today, the
        # recommended auto-fill default), then static presets. Providers
        # are bolded so the auto-generating option reads as the
        # recommended path; static presets only scaffold the textarea.
        bold = QFont("Noto Sans", 10, QFont.Weight.Bold)
        for provider in available_providers():
            base_label = provider.display_label()
            label = f"{base_label} (auto-fill)"
            self._provider_by_label[label] = provider
            self.preset_combo.addItem(label)
            self.preset_combo.setItemData(
                self.preset_combo.count() - 1,
                bold,
                Qt.ItemDataRole.FontRole,
            )
        for name in FEATURE_PRESETS:
            self.preset_combo.addItem(name)
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        # Features header row: bold label left, preset combo flush
        # right. The combo doubles as the section's "set" control, so
        # it lives in the header rather than under its own label.
        feat_header_row = QHBoxLayout()
        feat_label = QLabel("Features (delimited):")
        feat_label.setFont(QFont("Noto Sans", 10, QFont.Weight.Bold))
        feat_header_row.addWidget(feat_label)
        feat_header_row.addStretch()
        feat_header_row.addWidget(self.preset_combo)
        parent.addLayout(feat_header_row)
        self.feat_edit = FeatureTextEdit()
        self.feat_edit.setFont(QFont("Noto Sans", 10))
        self.feat_edit.setPlaceholderText(FeatureTextEdit.DEFAULT_FILL)
        # See the segments edit for why features get the larger stretch.
        parent.addWidget(self.feat_edit, stretch=4)
        self._on_preset_changed(self.preset_combo.currentText())

    def _build_button_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        row.addWidget(cancel_btn)
        ok_btn = QPushButton("Create Grid")
        ok_btn.setStyleSheet(
            ThemeController.filled_btn_style("btn_primary", "6px 20px")
        )
        ok_btn.clicked.connect(self.accept)
        row.addWidget(ok_btn)
        return row

    def _on_preset_changed(self, name: str) -> None:
        provider = self._provider_by_label.get(name)
        if provider is not None:
            self._chosen_provider = provider
            self.feat_edit.setReadOnly(False)
            # Run the same refresh path textChanged uses, so a provider
            # pick with already-typed segments lands on the trimmed
            # feature set instead of flashing the full canonical list.
            self._refresh_provider_features()
            return
        self._chosen_provider = None
        # Switching to a static preset opts out of auto-generation, so
        # drop any pending provider-driven refresh.
        self._provider_refresh_timer.stop()
        features = FEATURE_PRESETS.get(name, [])
        if features:
            self.feat_edit.setPlainText("\n".join(features))
            self.feat_edit.setReadOnly(False)
            return
        self.feat_edit.clear()
        self.feat_edit.setReadOnly(False)

    def _on_segments_changed(self) -> None:
        """Trigger a debounced features-preview refresh while a
        provider is active. No-op for static presets so typing
        segments does not clobber the user's hand-edited features
        list.
        """
        if self._chosen_provider is None:
            return
        self._provider_refresh_timer.start()

    def _refresh_provider_features(self) -> None:
        """Replace the features textarea with the list the active
        provider would emit for the current segment text. Empty or
        all-unresolved input falls back to the provider's full
        canonical set so the user sees a preview before entering IPA.

        Idempotent, so any caller can invoke it freely.
        """
        if self._chosen_provider is None:
            return
        segments = infer_split(self.seg_edit.toPlainText())
        if not segments:
            features = self._chosen_provider.feature_names()
        else:
            features = self._chosen_provider.generate(segments).features
            if not features:
                # Defensive guard: ``generate`` already falls back to
                # the full set, but a future provider might return an
                # empty tuple, and the user needs columns to edit.
                features = self._chosen_provider.feature_names()
        self.feat_edit.setPlainText("\n".join(features))

    def get_segments(self) -> list[str]:
        return self.seg_edit.entries()

    def get_features(self) -> list[str]:
        return self.feat_edit.entries()

    def get_name(self) -> str:
        return normalize_setup_name(self.name_edit.text())

    def get_chosen_provider(self) -> FeatureProvider | None:
        """Return the bootstrap provider the user picked, if any.

        ``None`` when the user picked a static preset (Default /
        Custom) and the editor should produce an empty grid.
        Otherwise the editor calls ``provider.generate(segments)``
        after validation to pre-populate cells.
        """
        return self._chosen_provider

    # (field, code) to warning-box title. Keeps the Qt UI vocabulary
    # local while the shared :py:func:`validate_setup` owns the rules.
    _ISSUE_TITLES: ClassVar[dict[tuple[str, str], str]] = {
        ("segments", "empty"): "No segments found",
        ("features", "empty"): "No features found",
        ("segments", "too_long"): "Segments entry too long",
        ("features", "too_long"): "Features entry too long",
    }

    def accept(self) -> None:
        """Validate inputs before dismissing.

        On failure, surface the first issue via QMessageBox, focus
        the offending field, and keep the dialog open. The rules and
        messages are owned by :py:func:`validate_setup` so the web
        setup modal produces identical wording.

        Provider-driven presets need at least one segment to derive
        bundles from, so this branch surfaces a provider-specific
        message. It also validates features against the provider's
        canonical names, so clearing the auto-filled textarea does not
        raise a misleading "no features" error; the editor uses the
        provider's features regardless.
        """
        provider = self._chosen_provider
        if provider is not None:
            if not infer_split(self.seg_edit.toPlainText()):
                QMessageBox.warning(
                    self,
                    "No segments found",
                    f"{provider.name} needs at least one IPA segment "
                    "to generate features from. Enter segments above "
                    "(or press Tab in the empty box for a quick-start "
                    "set), then click Create Grid.",
                )
                self.seg_edit.setFocus()
                return
            features_text = "\n".join(provider.feature_names())
        else:
            features_text = self.feat_edit.toPlainText()
        result = validate_setup(
            self.name_edit.text(),
            self.seg_edit.toPlainText(),
            features_text,
        )
        if not result.issues:
            super().accept()
            return
        first = result.issues[0]
        title = self._ISSUE_TITLES.get(
            (first.field, first.code), "Cannot create grid"
        )
        QMessageBox.warning(self, title, first.message)
        focus_widget = (
            self.seg_edit if first.field == "segments" else self.feat_edit
        )
        focus_widget.setFocus()
