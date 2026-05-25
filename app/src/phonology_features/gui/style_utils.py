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
    """QSS rules applied at the QApplication level, so they cascade
    to every widget. Read the current ``C`` palette at call time;
    re-invoke after ``set_theme`` to refresh.

    The QToolTip block exists because Qt's default tooltip palette
    on Linux paints a near-black rectangle with no padding that
    clashes against the app's lighter chips and panels. Vowel
    buttons set tooltips with placement metadata, so this is
    visible on hover.
    """
    return (
        f"QMainWindow {{ background: {C['bg']}; }}"
        f" QToolTip {{"
        f" background: {C['panel']};"
        f" color: {C['text']};"
        f" border: 1px solid {C['border']};"
        f" border-radius: 4px;"
        f" padding: 4px 7px;"
        f" }}"
    )


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
