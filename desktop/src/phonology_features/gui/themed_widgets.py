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

from PyQt6.QtCore import QEvent, QRectF, Qt, QTimer
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
    QHBoxLayout,
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


def toolbar_chrome_qss() -> str:
    """QSS for a toolbar container: panel background, bottom border,
    and padding. Shared by the main window's theme restyle
    (:py:meth:`ThemeController._restyle_toolbar`) and the editor's
    toolbar so the chrome lives in one place. Function-not-constant so
    it re-evaluates against the active palette after a theme swap.
    """
    return f"""
        QToolBar {{
            background: {C["panel"]};
            border-bottom: 1px solid {C["border"]};
            padding: 4px 8px;
            spacing: 6px;
        }}
    """


def statusbar_chrome_qss() -> str:
    """QSS for a status bar's chrome: panel background and top border.
    Shared by the main window's branded status bar
    (:py:meth:`_BrandedStatusBar.apply_theme`) and the editor's status
    bar so the two windows cannot drift. Function-not-constant for the
    same re-evaluate-after-swap reason as the button helpers.
    """
    return (
        f"background: {C['panel']};" f" border-top: 1px solid {C['border']};"
    )


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
        # The persistent inventory summary: the one line the bar shows
        # by default. Transient messages (clipboard feedback, errors,
        # and Qt ``StatusTip`` hover events) float above it and revert
        # back to it, so the summary is the single source of truth for
        # the bottom-border text and can never be left stranded blank.
        self._summary = ""
        # Single-shot timer that reverts a timed transient message to
        # the summary once it elapses.
        self._revert_timer = QTimer(self)
        self._revert_timer.setSingleShot(True)
        self._revert_timer.timeout.connect(self._revert_to_summary)
        self._message_label = QLabel("", self)
        self._message_label.setFont(self._FONT)
        self._message_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        # The message sizes to its (elided) content; the elide pass
        # below sets a fixed width capped to the room the source link
        # and brand leave over, so a long message can never push the
        # brand off the bar. Fixed width also decouples width from the
        # text so setting the elided string can't feed back into the
        # layout.
        self._message_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        # "Source" hyperlink for a loaded PHOIBLE inventory. Sits in
        # the LEFT group, immediately after the inventory-summary
        # message (mirrors the web's ``.statusbar-left`` row). Hidden
        # until ``set_source_link`` is given a URL; a non-PHOIBLE
        # inventory clears it.
        self._source_link = QLabel("", self)
        self._source_link.setFont(self._FONT)
        self._source_link.setTextFormat(Qt.TextFormat.RichText)
        self._source_link.setOpenExternalLinks(True)
        self._source_link.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._source_link.hide()
        # Spacer absorbs the slack between the left group and the brand
        # so the message + source stay left-aligned and the brand stays
        # pinned right.
        self._spacer = QWidget(self)
        self._spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._brand = QLabel("Language Doodad", self)
        self._brand.setFont(self._FONT)
        self._brand.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        # Message + Source share one tight container so the gap between
        # the inventory summary and the Source link is small and under
        # our control. QStatusBar.addWidget keeps a fixed ~6 px between
        # separate items that cannot be reduced via the status bar's own
        # layout, which left a wide gap after "features"; a private
        # QHBoxLayout here closes it without overlap.
        self._left_group = QWidget(self)
        left_layout = QHBoxLayout(self._left_group)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(self._message_label)
        left_layout.addWidget(self._source_link)
        self.addWidget(self._left_group, 0)
        self.addWidget(self._spacer, 1)
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
            self._update_elided_message()
            return
        # ``url`` is a baked phoible.org link, not user input; still,
        # only http(s) URLs are ever emitted, so no escaping beyond
        # the quote attribute is needed.
        self._source_link.setText(f'<a href="{url}">Source</a>')
        self._source_link.show()
        self._update_elided_message()

    def apply_theme(self) -> None:
        """Re-apply palette-dependent styles. Called on theme toggle."""
        self.setStyleSheet(statusbar_chrome_qss())
        set_css(self._message_label, f"color: {C['text']};")
        self._brand.setStyleSheet(
            f"color: {C['text_dim']}; font-style: italic; padding: 0 4px;"
        )
        # The ``<a>`` tag picks up the accent colour for the link text
        # via the widget's palette link role; a small left pad sets the
        # gap from the inventory-summary message it follows.
        self._source_link.setStyleSheet("padding: 0 4px;")
        link_palette = self._source_link.palette()
        link_palette.setColor(QPalette.ColorRole.Link, QColor(C["accent"]))
        self._source_link.setPalette(link_palette)

    def set_summary(self, text: str) -> None:
        """Set the persistent inventory summary, the bar's default
        line. It survives mode toggles, focus changes, hover, and
        transient messages, all of which fall back to it. This is the
        only method that writes a lasting bottom-border message; a
        successful load calls it and immediately cancels any transient
        message still on screen.
        """
        self._summary = text or ""
        self._revert_timer.stop()
        self._show(self._summary)

    def showMessage(  # type: ignore[override]
        self, text: str = "", timeout: int = 0
    ) -> None:
        """Show a TRANSIENT message over the persistent summary.

        Deliberately does not call ``super()`` (which would hide the
        brand + source widgets). Empty ``text`` reverts to the summary,
        so a Qt ``StatusTip`` (posted with an empty string when the
        pointer leaves a widget, and the historic cause of the bar
        going blank on a pane toggle) or an explicit clear can never
        strand the bar. A positive ``timeout`` (ms) auto-reverts to the
        summary; ``timeout == 0`` keeps the message until the next
        summary set or empty call (sticky load errors use this).
        """
        text = text or ""
        if not text:
            self._revert_timer.stop()
            self._show(self._summary)
            return
        self._show(text)
        if timeout > 0:
            self._revert_timer.start(timeout)
        else:
            self._revert_timer.stop()

    def _revert_to_summary(self) -> None:
        self._show(self._summary)

    def _show(self, text: str) -> None:
        """Render ``text`` into the managed label (elided to fit). The
        full text lives in the tooltip; the label shows an elided view
        fitted to the available width."""
        self._full_message = text
        self._message_label.setToolTip(text)
        self._update_elided_message()

    def _update_elided_message(self) -> None:
        # Size the message to its content, capped to the room the
        # source link + brand leave over, so the source sits right
        # beside the (short) summary yet a long transient message
        # still elides instead of shoving the brand off the bar.
        fm = self._message_label.fontMetrics()
        source_w = (
            self._source_link.sizeHint().width()
            if self._source_link.isVisible()
            else 0
        )
        brand_w = self._brand.sizeHint().width()
        # Reserve the source + brand widths plus a margin allowance for
        # item spacing and the bar's content margins.
        avail = max(0, self.width() - source_w - brand_w - 32)
        # Drive the box from the label's natural sizeHint, not the raw
        # pen advance. The advance omits the QLabel render slack (the
        # trailing glyph's right bearing and the widget's text padding),
        # so a box sized to the advance clipped the final glyph (the
        # "s" of "features"), which read as the Source link covering it.
        self._message_label.setText(self._full_message)
        natural_w = self._message_label.sizeHint().width()
        if natural_w <= avail:
            # The whole summary fits: show it in full, unclipped.
            self._message_label.setFixedWidth(natural_w)
            return
        # Too long for the room left over: elide. Keep the same render
        # slack out of the elide budget so the elided string plus its
        # ellipsis stays inside the box and never spills toward Source.
        slack = natural_w - fm.horizontalAdvance(self._full_message)
        elided = fm.elidedText(
            self._full_message,
            Qt.TextElideMode.ElideRight,
            max(0, avail - slack),
        )
        self._message_label.setText(elided)
        self._message_label.setFixedWidth(avail)

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
