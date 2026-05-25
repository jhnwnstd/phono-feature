"""Style application helpers.

``set_css`` exists because ``QWidget.setStyleSheet`` always re-parses
the CSS string and rebuilds the widget's style tree, even when the
new string is byte-identical to the old one. On theme toggle the
window sets ~1500 stylesheets and ~95% of them duplicate strings
applied moments earlier on widget pool entries; profiling showed
~580 ms spent inside ``setStyleSheet`` for one toggle on Hayes.
A one-line guard against identical strings turns most of those into
a no-op.

The same trick applies to ``setHtml`` in the analysis pane: a theme
toggle re-renders the same HTML if the selection hasn't changed but
the embedded palette colors are identical, so the QTextDocument
rebuild is wasted. ``set_html`` short-circuits the common case.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QTextEdit, QWidget

from phonology_features.gui.palette import C


def set_css(widget: QWidget, css: str) -> bool:
    """Apply ``css`` to ``widget`` only when it differs from the
    currently-applied stylesheet. Returns True if a re-parse
    actually happened, False on cache hit -- useful for tests."""
    if widget.styleSheet() == css:
        return False
    widget.setStyleSheet(css)
    return True


def app_qss() -> str:
    """QSS rules applied at the QApplication level once, at startup.

    Do NOT re-apply on theme toggle: ``QApplication.setStyleSheet``
    re-polishes every widget in the tree (Qt re-parses the QSS,
    rebuilds selector matches, and walks the whole tree), which on
    a populated inventory is hundreds of milliseconds of jank.
    Theme-dependent tooltip COLORS are refreshed via
    ``apply_tooltip_palette`` instead, which only touches
    ``QToolTip``'s shared palette and skips the global re-polish.

    Shape rules (border, radius, padding) belong here because they
    don't change with the theme. Colors are deliberately omitted
    so the palette can drive them without QSS overriding.
    """
    return (
        f"QMainWindow {{ background: {C['bg']}; }}"
        f" QToolTip {{"
        f" border: 1px solid {C['border']};"
        f" border-radius: 4px;"
        f" padding: 4px 7px;"
        f" }}"
    )


def apply_tooltip_palette() -> None:
    """Refresh ``QToolTip``'s shared palette from the active ``C``
    palette. Cheap enough to call on every theme toggle; does not
    trigger an app-wide re-polish the way
    ``QApplication.setStyleSheet`` would.
    """
    from PyQt6.QtGui import QColor, QPalette
    from PyQt6.QtWidgets import QToolTip

    pal = QToolTip.palette()
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(C["panel"]))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(C["text"]))
    QToolTip.setPalette(pal)


_LAST_HTML_ATTR = "_set_html_last"


def set_html(view: QTextEdit, html: str) -> bool:
    """Apply ``html`` to ``view`` only when it differs from the
    last value we applied via this helper. We stash the input string
    on the widget as ``_set_html_last`` -- comparing against the
    input avoids Qt's expensive ``toHtml()`` round-trip serializer.
    Useful when the same HTML gets re-applied (e.g. theme toggle
    with no selection change)."""
    last = getattr(view, _LAST_HTML_ATTR, None)
    if last == html:
        return False
    view.setHtml(html)
    setattr(view, _LAST_HTML_ATTR, html)
    return True
