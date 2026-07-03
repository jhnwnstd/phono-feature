"""Click-to-open help windows for the Segments pane (desktop).

Two labels open a small help dialog: the pane's ``SEGMENTS`` title and
the ``Vowels`` chart title. Both share :class:`ClickableLabel` (a QLabel
that emits ``clicked``) and :func:`show_help_dialog`, which renders the
shared HTML copy from
:mod:`phonology_shared.presentation.help_text` in a read-only
``QTextBrowser`` so the desktop and web windows show identical wording.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from phonology_shared.presentation.palette import C

from .style_utils import set_css


class ClickableLabel(QLabel):
    """A QLabel that emits :attr:`clicked` on a left-button press.

    Used for the two help-opening pane labels; a pointing-hand cursor
    plus a tooltip are the only affordance so the labels keep their
    quiet look.
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


def show_help_dialog(parent: QWidget | None, title: str, html: str) -> None:
    """Open a small modal help window showing ``html`` under ``title``.

    The dialog inherits the app's themed chrome; the body is a
    borderless, read-only :class:`QTextBrowser` so long copy scrolls
    inside the window instead of stretching it off-screen.
    """
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setModal(True)
    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(20, 20, 20, 16)
    layout.setSpacing(12)

    body = QTextBrowser(dlg)
    body.setOpenExternalLinks(True)
    body.setHtml(html)
    set_css(
        body,
        f"QTextBrowser {{ border: none; background: transparent;"
        f" color: {C['text']}; }}",
    )
    layout.addWidget(body)

    close = QPushButton("Close", dlg)
    close.clicked.connect(dlg.accept)
    close.setDefault(True)
    layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)

    dlg.resize(480, 460)
    dlg.exec()
