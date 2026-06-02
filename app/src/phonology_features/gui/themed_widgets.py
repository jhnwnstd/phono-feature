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
from PyQt6.QtGui import QColor, QEnterEvent, QFont, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QSplitter,
    QSplitterHandle,
    QStatusBar,
    QWidget,
)

from phonology_features.gui.shared.layout import REGION_CONSTRAINTS
from phonology_features.gui.shared.palette import C
from phonology_features.gui.style_utils import set_css


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
        self._message_label = QLabel("", self)
        self._message_label.setFont(self._FONT)
        self._message_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._brand = QLabel("Language Doodad", self)
        self._brand.setFont(self._FONT)
        self._brand.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.addWidget(self._message_label, 1)
        self.addPermanentWidget(self._brand, 0)
        self.apply_theme()

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

    def showMessage(self, text: str, timeout: int = 0) -> None:  # type: ignore[override]
        """Override that doesn't call super() (which would hide
        left-section widgets). ``timeout`` is ignored; the app never
        uses auto-clear.
        """
        self._message_label.setText(text)

    def clearMessage(self) -> None:
        self._message_label.setText("")

    def currentMessage(self) -> str:
        return self._message_label.text()


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
