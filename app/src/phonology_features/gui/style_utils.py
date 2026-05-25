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


def apply_app_palette() -> None:
    """Refresh the ``QApplication`` palette from the active ``C`` palette.

    Qt widgets that don't go through our ``set_css`` / ``apply_theme``
    discipline (QDialog, QFileDialog, QInputDialog, QMessageBox,
    QLineEdit, QLabel, default QPushButton chrome) read their colors
    from this palette. Without refreshing it on theme toggle, dark
    mode gets the window background right but leaves text fields with
    black text on a dark background.

    Sets every palette role that any widget in the tree might read.
    Cheaper than ``QApplication.setStyleSheet`` (which re-parses QSS
    and re-polishes every widget); a palette change just fires
    PaletteChange events that widgets queue a repaint for.
    """
    from PyQt6.QtGui import QColor, QPalette
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return
    bg = QColor(C["bg"])
    panel = QColor(C["panel"])
    text = QColor(C["text"])
    text_dim = QColor(C["text_dim"])
    accent = QColor(C["accent"])
    accent_light = QColor(C["accent_light"])
    border = QColor(C["border"])

    pal = app.palette()
    # Window-level chrome (QMainWindow body, QDialog body, etc.)
    pal.setColor(QPalette.ColorRole.Window, bg)
    pal.setColor(QPalette.ColorRole.WindowText, text)
    # Input-widget surfaces (QLineEdit, QTextEdit, QPlainTextEdit,
    # QListView item background, etc.)
    pal.setColor(QPalette.ColorRole.Base, panel)
    pal.setColor(QPalette.ColorRole.AlternateBase, bg)
    pal.setColor(QPalette.ColorRole.Text, text)
    pal.setColor(QPalette.ColorRole.PlaceholderText, text_dim)
    # Default QPushButton chrome. App-specific buttons set their own
    # QSS and ignore palette; system dialogs (QInputDialog OK/Cancel,
    # QFileDialog buttons, QMessageBox buttons) use palette.
    pal.setColor(QPalette.ColorRole.Button, panel)
    pal.setColor(QPalette.ColorRole.ButtonText, text)
    pal.setColor(QPalette.ColorRole.BrightText, text)
    # Selection (highlighted item in a QListView, selected text in a
    # QLineEdit, etc.)
    pal.setColor(QPalette.ColorRole.Highlight, accent_light)
    pal.setColor(QPalette.ColorRole.HighlightedText, accent)
    # Frames / dividers / etched borders
    pal.setColor(QPalette.ColorRole.Mid, border)
    pal.setColor(QPalette.ColorRole.Dark, border)
    pal.setColor(QPalette.ColorRole.Shadow, border)
    # Tooltip is handled separately by apply_tooltip_palette() so
    # both stay in sync.
    app.setPalette(pal)


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
