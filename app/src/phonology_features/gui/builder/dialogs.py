"""Reusable dialog helpers and the InputDialog for inventory setup."""

import re

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QFont, QPainter, QTextCursor
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
)

from phonology_engine.inventory import MAX_NAME_LENGTH
from phonology_features.gui.builder.presets import FEATURE_PRESETS
from phonology_features.gui.palette import C

# Candidate delimiters _infer_split tries, in no particular order.
# Whitespace is the FALLBACK (used only when none of these appear);
# kept separate because feature names may legitimately contain spaces
# (e.g. "Long Vowel") and the whole point of supporting explicit
# delimiters is to let those names survive paste.
_EXPLICIT_DELIMITERS: tuple[str, ...] = (",", ";", "|", "\t", "\n")


def _infer_split(text: str) -> list[str]:
    """Split ``text`` on whichever of the candidate delimiters appears.

    Lets the user paste any consistently-delimited list (CSV, TSV,
    semicolons, pipes, one-per-line, plain whitespace) without
    pre-processing. The rule:

    * If any of ``,``, ``;``, ``|``, ``\\t``, ``\\n`` appears in the
      text, split on EVERY explicit delimiter that's present.
      Handles mixed cases like ``"p, b, t\\nd, e, f"`` (commas and
      newlines together) which should yield six tokens, not two
      strings of three.
    * Otherwise fall back to any-whitespace split (the legacy
      behaviour for ``"p b t d"``).

    Each token is whitespace-stripped; empties are filtered. Order
    is preserved.
    """
    used = [d for d in _EXPLICIT_DELIMITERS if d in text]
    if not used:
        return [tok for tok in text.split() if tok]
    pattern = "|".join(re.escape(d) for d in used)
    return [tok.strip() for tok in re.split(pattern, text) if tok.strip()]


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

    def __init__(self, parent=None):
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
        the delimiter. See ``_infer_split`` for the rule. Same shape
        for segments and features so pasted input from any source
        (CSV exports, spreadsheet columns, one-per-line lists,
        space-separated jottings) works without pre-processing."""
        return _infer_split(self.toPlainText())

    def paintEvent(self, e):
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

    # The \u0261 here is U+0261 (IPA voiced velar script g), not ASCII g.
    DEFAULT_FILL = "p b t d k \u0261 "


class FeatureTextEdit(_AutofillTextEdit):
    """Tab on empty seeds the two major-class features (Syllabic and
    Consonantal) as a starting point for a custom set. The full
    Default (33) preset is in the dropdown.

    Trailing newline so the caret lands on a fresh line ready for
    the user to type the next feature; ``_infer_split`` filters empty
    lines so the trailer doesn't introduce a phantom feature. The
    inferred-delimiter parser inherited from the base accepts any
    consistent delimiter (newline, comma, tab, etc.) so a pasted
    list from any source works without pre-processing, AND lets
    feature names contain spaces (e.g. "Long Vowel") as long as the
    user separates with something other than whitespace."""

    DEFAULT_FILL = "Syllabic\nConsonantal\n"


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
        # UI cap mirrors the parser cap (Inventory.MAX_NAME_LENGTH).
        # Without it, the user could type/paste 10k chars, see them
        # accepted in the field, and only get the error at save. With
        # it, the field itself stops accepting input at the limit.
        self.name_edit.setMaxLength(MAX_NAME_LENGTH)
        self.name_edit.setPlaceholderText("e.g. My Language Inventory")
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

    def accept(self) -> None:
        """Validate inputs before dismissing. On failure, warn, focus
        the offending field, and keep the dialog open.

        The "no items" branches double as the surface for "couldn't
        infer the delimiter": ``_infer_split`` only returns an empty
        list when the input is empty or whitespace-only. The message
        names every accepted delimiter so a user who pasted something
        the parser couldn't tokenize can see what to try.
        """
        if not self.get_segments():
            QMessageBox.warning(
                self,
                "No segments found",
                "The segments box is empty, or none of the recognized "
                "delimiters were found. Separate segments with any of: "
                "newline, space, tab, comma, semicolon, or pipe. "
                "Press Tab in an empty box for a quick-start set.",
            )
            self.seg_edit.setFocus()
            return
        if not self.get_features():
            QMessageBox.warning(
                self,
                "No features found",
                "The features box is empty, or none of the recognized "
                "delimiters were found. Separate features with any of: "
                "newline, comma, semicolon, tab, or pipe. (Whitespace "
                "is allowed but only as a fallback, so feature names "
                "that contain spaces survive when you use a non-space "
                "delimiter.) Or pick a feature set from the dropdown.",
            )
            self.feat_edit.setFocus()
            return
        # Per-entry length cap. Catches the "pasted a wall of prose
        # into the segments box and didn't notice it has no delimiter
        # the inferrer recognizes" case: ``_infer_split`` would return
        # the whole paragraph as one giant "segment", which would then
        # crawl through json.dump and balloon the saved file. Reject
        # at the dialog boundary, where we can still surface a
        # focusable error, instead of letting it land in the parser.
        for label, edit, entries in (
            ("segments", self.seg_edit, self.get_segments()),
            ("features", self.feat_edit, self.get_features()),
        ):
            offender = next(
                (e for e in entries if len(e) > MAX_NAME_LENGTH), None
            )
            if offender is not None:
                QMessageBox.warning(
                    self,
                    f"{label.capitalize()} entry too long",
                    f"One of the {label} is {len(offender)} characters "
                    f"long, longer than the {MAX_NAME_LENGTH}-character "
                    f"limit. This usually means the delimiter wasn't "
                    f"recognized and the whole input was treated as a "
                    f"single entry. Check the delimiter and try again.",
                )
                edit.setFocus()
                return
        super().accept()
