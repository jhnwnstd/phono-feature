"""Click-to-open help windows for the Segments pane (desktop).

Two labels open a small help dialog: the pane's ``SEGMENTS`` title and
the ``Vowels`` chart title. Both share :class:`ClickableLabel` (a QLabel
that emits ``clicked``) and :func:`show_help_dialog`, which renders the
shared HTML copy from
:mod:`phonology_shared.presentation.help_text` in a read-only
``QTextBrowser`` so the desktop and web windows show identical wording.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QShowEvent
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from phonology_shared.presentation.palette import C

from .style_utils import set_css


def help_hint_html(text: str) -> str:
    """Wrap ``text`` with a trailing superscript "?" (Qt rich text) so a
    help-opening :class:`ClickableLabel` shows a visible click-for-help
    affordance. The "?" carries no colour of its own, so it inherits the
    label's colour and tracks the theme + active/dim state. Mirrors the
    web ``#seg-title::after`` / ``.vowel-chart-title::after`` badge."""
    return f"{text} <sup>?</sup>"


class ClickableLabel(QLabel):
    """A QLabel that emits :attr:`clicked` on a left-button press.

    Used for the two help-opening pane labels; a pointing-hand cursor,
    a tooltip, and a trailing "?" (see :func:`help_hint_html`) advertise
    that clicking opens a help window.
    """

    clicked = pyqtSignal()

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is not None and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class _HelpDialog(QDialog):
    """Non-modal help window that closes when it loses focus (the user
    clicks outside it), in addition to the title-bar close button and
    Escape. Mirrors the web dialog's backdrop-click + Escape dismissal.
    The ``_armed`` flag suppresses the close until after the first show
    so the window doesn't dismiss itself during construction / initial
    activation.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._armed = False

    def showEvent(self, event: QShowEvent | None) -> None:
        super().showEvent(event)
        self._armed = True

    def changeEvent(self, event: QEvent | None) -> None:
        super().changeEvent(event)
        if (
            self._armed
            and event is not None
            and event.type() == QEvent.Type.ActivationChange
            and not self.isActiveWindow()
        ):
            self.close()


def show_help_dialog(parent: QWidget | None, title: str, html: str) -> None:
    """Open a help window showing ``html`` under ``title``.

    Non-modal so the user can read it alongside the chart; it closes on
    the title-bar close button (top-right), on Escape, or when it loses
    focus (a click anywhere outside it). The body is a borderless,
    read-only :class:`QTextBrowser` so long copy scrolls inside the
    window instead of stretching it off-screen.
    """
    dlg = _HelpDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(20, 20, 20, 20)

    body = QTextBrowser(dlg)
    body.setOpenExternalLinks(True)
    # No context menu: its popup would deactivate the window and trip
    # the click-outside-to-close handler.
    body.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
    body.setHtml(html)
    set_css(
        body,
        f"QTextBrowser {{ border: none; background: transparent;"
        f" color: {C['text']}; }}",
    )
    layout.addWidget(body)

    dlg.resize(560, 480)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
