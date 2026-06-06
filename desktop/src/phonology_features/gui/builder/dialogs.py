"""Reusable dialog helpers and the InputDialog for inventory setup."""

from typing import ClassVar

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import QFont, QPainter, QPaintEvent, QTextCursor
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

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
    """Plain-text editor (NOT QTextEdit) with two shared affordances
    used by both the segment and feature inputs in the New Inventory
    dialog. ``QPlainTextEdit`` is the correct base for untrusted text
    input: it cannot render pasted rich text from word processors or
    browsers (Qt's QTextEdit interprets HTML on paste; the styled
    fragment would display briefly even though ``entries()`` later
    strips formatting via ``toPlainText``).

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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTabChangesFocus(True)
        # Stored separately from Qt's placeholderText so our paintEvent
        # owns the full multi-line render. See setPlaceholderText.
        self._placeholder: str = ""

    def setPlaceholderText(self, text: str) -> None:  # type: ignore[override]
        """Capture the placeholder text for our own multi-line paint
        and tell Qt the placeholder is empty so its built-in single
        line render stays out of our way. Both lines of a multi-line
        placeholder then come from the same paintEvent code path,
        guaranteeing identical shading."""
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
        """Parse the current text as a list of entries by inferring
        the delimiter. See :py:func:`infer_split` for the rule. Same
        shape for segments and features so pasted input from any
        source (CSV exports, spreadsheet columns, one-per-line
        lists, space-separated jottings) works without pre-processing.
        """
        return infer_split(self.toPlainText())

    def paintEvent(self, e: QPaintEvent | None) -> None:
        super().paintEvent(e)
        if self.toPlainText() or not self.placeholderText():
            return
        lines = self.placeholderText().splitlines()
        if not lines:
            return
        # Paint EVERY placeholder line ourselves rather than letting
        # Qt's built-in placeholder paint the first line and us paint
        # the rest. Two reasons: (1) Qt only paints the first line of
        # a multi-line placeholderText, so we have to paint the others
        # anyway; (2) when both Qt and we paint the same buffer, the
        # alpha-blended lines end up at different effective opacities
        # (Qt's first-line render and our subsequent-line renders
        # composite slightly differently across paint frames), giving
        # the user visibly different shades for adjacent lines.
        # Owning the whole multi-line paint here keeps every line at
        # the same colour.
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
    """Tab on empty fills a quick-start segment list (IPA voiceless and
    voiced stops). Trailing space so the caret lands ready for the
    user to type the next segment without first having to add a
    separator. ``entries()`` splits on whitespace and filters empties,
    so the trailer does not introduce a phantom entry.
    """

    # Sourced from the shared setup module so the web setup dialog
    # offers the same Tab-autofill string. The \u0261 inside
    # DEFAULT_SEGMENTS is U+0261 (IPA voiced velar script g).
    DEFAULT_FILL = DEFAULT_SEGMENTS


class FeatureTextEdit(_AutofillTextEdit):
    """Tab on empty seeds the two major-class features (Syllabic and
    Consonantal) as a starting point for a custom set. Fuller
    starting points (Hayes, PHOIBLE) are in the preset dropdown.

    Trailing newline so the caret lands on a fresh line ready for
    the user to type the next feature; ``_infer_split`` filters empty
    lines so the trailer doesn't introduce a phantom feature. The
    inferred-delimiter parser inherited from the base accepts any
    consistent delimiter (newline, comma, tab, etc.) so a pasted
    list from any source works without pre-processing, AND lets
    feature names contain spaces (e.g. "Long Vowel") as long as the
    user separates with something other than whitespace."""

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


class InputDialog(QDialog):
    """Dialog for entering segments and features before opening the grid."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(SETUP_DIALOG_TITLE)
        self.setMinimumSize(500, 500)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        # Provider chosen via the preset dropdown. ``None`` means the
        # user picked a static features-only preset (Default / Custom)
        # so the builder takes the user-typed feature list verbatim
        # and produces an empty grid. A non-None value means the
        # builder calls ``provider.generate(segments)`` after the
        # dialog accepts and pre-populates grid cells.
        self._chosen_provider: FeatureProvider | None = None
        # Provider-labelled entries in the preset combo are routed
        # through this map. Keys are the combo's display label
        # (``provider.display_label()``), values are the provider
        # instance. Populated once at construction.
        self._provider_by_label: dict[str, FeatureProvider] = {}
        # Debounced re-generation of the features preview while a
        # provider is chosen and the user is editing the segments
        # textarea. ``generate`` is fast (~ms per segment via PanPhon)
        # but spamming it on every keystroke would be noisy; 250 ms
        # of idle is enough to feel responsive without flashing the
        # textarea as the user types out a segment list.
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
        # UI cap mirrors the parser cap (Inventory.MAX_NAME_LENGTH).
        # Without it, the user could type/paste 10k chars, see them
        # accepted in the field, and only get the error at save. With
        # it, the field itself stops accepting input at the limit.
        self.name_edit.setMaxLength(MAX_NAME_LENGTH)
        self.name_edit.setPlaceholderText(SETUP_NAME_PLACEHOLDER)
        row.addWidget(self.name_edit)
        return row

    def _add_segments_section(self, parent: QVBoxLayout) -> None:
        label = QLabel("Segments (delimited):")
        label.setFont(QFont("Noto Sans", 10, QFont.Weight.Bold))
        parent.addWidget(label)
        self.seg_edit = SegmentTextEdit()
        # Placeholder = what Tab fills; the grayed text doubles as a
        # format hint for the inferred-delimiter parser.
        self.seg_edit.setPlaceholderText(SegmentTextEdit.DEFAULT_FILL)
        self.seg_edit.setFont(QFont("Noto Sans", 12))
        # Live-trim the features preview while a provider is active.
        # Each edit re-arms the debounce timer so the textarea catches
        # up after the user pauses typing; the handler no-ops when no
        # provider is selected.
        self.seg_edit.textChanged.connect(self._on_segments_changed)
        # Stretch 1 here vs 4 on the features edit below: segments
        # are typically a short list (~10-40 symbols) while features
        # are routinely 30+ entries, often pasted from a spreadsheet.
        # Giving features the lion's share of vertical room matches
        # the common shape of pasted input.
        parent.addWidget(self.seg_edit, stretch=1)

    def _add_features_section(self, parent: QVBoxLayout) -> None:
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
        # Display order: providers FIRST (today PanPhon, the
        # auto-fill recommended default), then the static presets
        # (Hayes, PHOIBLE, Custom). Providers are bolded so the
        # auto-generating option reads as the recommended path
        # even at a glance; the static presets just populate the
        # textarea with a column scaffold the user fills in.
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
        # Features header row: bold label on the left, preset combo
        # flush to the RIGHT edge (separated by stretch). The combo
        # doubles as the section's "set" control, so it sits in the
        # header rather than under its own "Feature set:" label.
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
        # See the segments edit for why features get the larger
        # stretch factor: feature sets are routinely 30+ entries,
        # often pasted from a spreadsheet column.
        parent.addWidget(self.feat_edit, stretch=4)
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

    def _on_preset_changed(self, name: str) -> None:
        provider = self._provider_by_label.get(name)
        if provider is not None:
            self._chosen_provider = provider
            self.feat_edit.setReadOnly(False)
            # Run the same refresh path the textChanged handler uses,
            # so a provider pick with already-typed segments lands
            # immediately on the trimmed feature set instead of
            # flashing the full 24-name canonical list first.
            self._refresh_provider_features()
            return
        self._chosen_provider = None
        # Drop any pending provider-driven refresh: switching to a
        # static preset means the user opted out of auto-generation.
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
        """Replace the features textarea with the actual feature
        list the active provider would emit for the current segment
        text. Empty / all-unresolved segment input falls back to
        the provider's full canonical feature set so the user has
        a preview of what is available before they enter any IPA.

        Idempotent: callers (textChanged debounce, ``_on_preset_changed``,
        and the test fixture) can invoke it freely.
        """
        if self._chosen_provider is None:
            return
        segments = infer_split(self.seg_edit.toPlainText())
        if not segments:
            features = self._chosen_provider.feature_names()
        else:
            features = self._chosen_provider.generate(segments).features
            if not features:
                # All inputs unresolved: ``generate`` already falls
                # back to the full set so the user has columns to
                # edit. Defensive guard in case a future provider
                # returns an empty tuple instead.
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
        Custom) and the builder should produce an empty grid.
        Otherwise the builder calls ``provider.generate(segments)``
        after validation to pre-populate cells.
        """
        return self._chosen_provider

    # Field name (from :py:class:`SetupIssue`) to (title, focus widget).
    # Drives the warning box title and where focus lands on rejection;
    # keeps the Qt UI vocabulary local to this class while the shared
    # :py:func:`validate_setup` owns the rules.
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

        Provider-driven presets (PanPhon today) need at least one
        segment to derive bundles from; this branch surfaces a
        provider-specific message so the user understands why the
        generic "no segments" hint is showing up. It also routes
        the features-side validation against the provider's
        canonical feature names so a user who cleared the
        auto-filled textarea does not get a misleading "no
        features" error: the builder uses the provider's features
        regardless.
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
