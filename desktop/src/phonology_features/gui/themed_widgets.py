"""Theme-aware Qt widget subclasses used by MainWindow.

Each class paints itself directly from the live palette rather than
relying on Qt stylesheets. This avoids the polish cascade that
``setStyleSheet`` triggers through every descendant widget, which
was the largest single cost in the theme-toggle profile.

All four classes are module-private (leading underscore) and only
referenced from main_window.py. ``_clear_btn_style`` is a sibling
helper for the Clear buttons that needs the same live-palette
behaviour (function not constant so it re-evaluates after a theme
swap).
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QEnterEvent,
    QFont,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QResizeEvent,
)
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QSplitter,
    QSplitterHandle,
    QStatusBar,
    QWidget,
)

from phonology_features.gui.style_utils import set_css
from phonology_shared.presentation.layout import REGION_CONSTRAINTS
from phonology_shared.presentation.palette import C


def _clear_btn_style() -> str:
    """Stylesheet for the per-panel Clear buttons. Function-not-constant
    so it re-evaluates against the active palette after a theme swap.
    """
    return (
        f"QPushButton {{"
        f" color: {C['text']}; background: transparent;"
        f" border: 1px solid {C['border']};"
        f" border-radius: 5px; padding: 0 10px;"
        f" }}"
        f" QPushButton:hover {{ color: {C['text']};"
        f" background: {C['bg']}; }}"
    )


def _match_mode_btn_style() -> str:
    """Stylesheet for the wildcard / match-mode toggle that sits in
    the Features pane header. Same chrome shape as the Clear button
    so the two siblings read as a matched pair; the ``:checked``
    state pulls the accent fill so the user can see at a glance
    that wildcard matching is active.

    Function-not-constant so it re-evaluates against the active
    palette after a theme or palette-mode swap; the colorblind
    palette redefines ``accent`` / ``accent_light`` and the toggle
    inherits the new hues without an additional restyle hook.
    """
    return (
        f"QPushButton {{"
        f" color: {C['text']}; background: transparent;"
        f" border: 1px solid {C['border']};"
        f" border-radius: 5px; padding: 0 8px;"
        f" }}"
        f" QPushButton:hover {{ color: {C['accent']};"
        f" background: {C['accent_light']};"
        f" border-color: {C['accent']}; }}"
        f" QPushButton:checked {{ color: {C['accent']};"
        f" background: {C['accent_light']};"
        f" border-color: {C['accent']}; }}"
        f" QPushButton:checked:hover {{ color: {C['btn_primary_text']};"
        f" background: {C['accent']};"
        f" border-color: {C['accent']}; }}"
    )


class _BrandedStatusBar(QStatusBar):
    """Status bar with a 'Language Doodad' brand pinned at the right.

    QStatusBar.showMessage() hides addWidget() items while a message is
    shown, which would blink the brand on every status update. This
    subclass routes messages to a managed QLabel on the left so both
    message and brand stay visible.
    """

    _FONT = QFont("Noto Sans", 9)
    # 22 px matches the toolbar baseline; sized so italic ascenders /
    # descenders don't push the bar taller than non-italic text would.
    _BAR_HEIGHT = 22

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizeGripEnabled(False)
        # ``setMinimumHeight`` (not ``setFixedHeight``) so the bar
        # grows with font metrics on a high-DPI display rather than
        # clipping the message glyphs at 200% / 300% scale. The 22-px
        # floor preserves the historic toolbar-baseline alignment.
        self.setMinimumHeight(self._BAR_HEIGHT)
        # Full message text; the label renders an elided view of it
        # sized to the space the brand leaves over (see
        # ``_update_elided_message``).
        self._full_message = ""
        self._message_label = QLabel("", self)
        self._message_label.setFont(self._FONT)
        self._message_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        # ``Ignored`` horizontal policy so a long message can never
        # widen the label past its layout slot: QLabel's minimum
        # size otherwise tracks the text width, and an oversized
        # message pushed the brand out of the bar instead of
        # eliding. The brand keeps its full width (stretch 0); the
        # message takes whatever remains and clips with an ellipsis.
        self._message_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._brand = QLabel("Language Doodad", self)
        self._brand.setFont(self._FONT)
        self._brand.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        # "Source" hyperlink for a loaded PHOIBLE inventory. Sits as
        # a permanent widget to the LEFT of the brand (added first), so
        # it reads as part of the loaded-inventory summary at the
        # right of the bar. Hidden until ``set_source_link`` is given a
        # URL; a non-PHOIBLE inventory clears it.
        self._source_link = QLabel("", self)
        self._source_link.setFont(self._FONT)
        self._source_link.setTextFormat(Qt.TextFormat.RichText)
        self._source_link.setOpenExternalLinks(True)
        self._source_link.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._source_link.hide()
        self.addWidget(self._message_label, 1)
        self.addPermanentWidget(self._source_link, 0)
        self.addPermanentWidget(self._brand, 0)
        self.apply_theme()

    def set_source_link(self, url: str) -> None:
        """Show a ``Source`` hyperlink to ``url`` (a PHOIBLE source or
        inventory page), or hide the link when ``url`` is empty (a
        non-PHOIBLE inventory). Idempotent."""
        url = (url or "").strip()
        if not url:
            self._source_link.clear()
            self._source_link.hide()
            return
        # ``url`` is a baked phoible.org link, not user input; still,
        # only http(s) URLs are ever emitted, so no escaping beyond
        # the quote attribute is needed.
        self._source_link.setText(f'<a href="{url}">Source</a>')
        self._source_link.show()

    def apply_theme(self) -> None:
        """Re-apply palette-dependent styles. Called on theme toggle."""
        self.setStyleSheet(
            f"background: {C['panel']};"
            f" border-top: 1px solid {C['border']};"
        )
        set_css(self._message_label, f"color: {C['text']};")
        self._brand.setStyleSheet(
            f"color: {C['text_dim']}; font-style: italic; padding: 0 4px;"
        )
        # The ``<a>`` tag picks up the accent colour for the link text
        # via the widget's palette link role; padding matches the
        # brand so the two right-pinned items sit on the same rhythm.
        self._source_link.setStyleSheet("padding: 0 4px;")
        link_palette = self._source_link.palette()
        link_palette.setColor(QPalette.ColorRole.Link, QColor(C["accent"]))
        self._source_link.setPalette(link_palette)

    def showMessage(self, text: str, timeout: int = 0) -> None:  # type: ignore[override]
        """Override that doesn't call super() (which would hide
        left-section widgets). ``timeout`` is ignored; the app never
        uses auto-clear. The full text lives in the tooltip; the
        label shows an elided view fitted to the available width.
        """
        self._full_message = text
        self._message_label.setToolTip(text)
        self._update_elided_message()

    def clearMessage(self) -> None:
        self._full_message = ""
        self._message_label.setToolTip("")
        self._message_label.setText("")

    def currentMessage(self) -> str:
        return self._full_message

    def _update_elided_message(self) -> None:
        fm = self._message_label.fontMetrics()
        width = max(0, self._message_label.width() - 4)
        self._message_label.setText(
            fm.elidedText(
                self._full_message, Qt.TextElideMode.ElideRight, width
            )
        )

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        self._update_elided_message()


class _ThemedHandle(QSplitterHandle):
    """Splitter handle that paints itself from the live palette.

    Avoids the prior ``QSplitter::handle`` subcontrol stylesheet,
    which forced a polish cascade through every descendant of the
    splitter on each theme toggle (the biggest cost in
    :py:meth:`ThemeController.apply`).
    Reading ``C`` per paintEvent costs microseconds; the polish
    cascade cost ~65 ms.
    """

    def __init__(self, orientation: Qt.Orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
        self._hover = False

    def enterEvent(self, event: QEnterEvent | None) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent | None) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QPaintEvent | None) -> None:
        # Resting state blends with neighbouring panel chrome via
        # ``border``. Hover state uses ``splitter_hover``, a neutral
        # grey, NOT the accent blue. Accent is reserved for "active /
        # selected" semantics; the drag handle just signals "this
        # surface is interactive", and a darker grey reads as
        # affordance without overloading the selected meaning.
        painter = QPainter(self)
        painter.fillRect(
            self.rect(),
            QColor(C["splitter_hover"] if self._hover else C["border"]),
        )


class _ThemedSplitter(QSplitter):
    """``QSplitter`` whose handles are ``_ThemedHandle`` (live palette,
    no stylesheet). Cursor is still set automatically by the base."""

    def createHandle(self) -> QSplitterHandle | None:
        return _ThemedHandle(self.orientation(), self)


class _ThemedCard(QFrame):
    """Feature-group card that paints its own bg + rounded border from
    the live palette. Replaces a per-card setStyleSheet that previously
    triggered a polish cascade through ~5 FeatureRow children every
    theme toggle (6-7 cards = the cost behind _restyle_feature_cards).

    Min-width pulled from ``REGION_CONSTRAINTS['feature_card']`` so the
    floor that keeps the longest group title on one line is declared
    once and inherited by both the Qt card and the web's
    ``--feature-card-min-w`` rule.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _c = REGION_CONSTRAINTS["feature_card"]
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )
        self.setMinimumWidth(_c.min_w)
        self.setMinimumHeight(_c.min_h)

    def paintEvent(self, event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(C["border"]))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(QColor(C["panel"]))
        # Inset by 0.5 so the 1 px border falls inside the widget rect.
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.drawRoundedRect(rect, 7, 7)
