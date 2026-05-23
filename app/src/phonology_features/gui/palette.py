"""Shared colour palette for the GUI.

Two themes are defined: ``LIGHT`` and ``DARK``. ``C`` is the active
palette - mutated in place by ``set_theme`` so existing
``from gui.palette import C`` imports keep working after a swap.
Per-theme style caches on SegmentButton / FeatureRow + MainWindow's
``_apply_theme`` central-widget rebuild make swaps live (no restart).

Neutral values (bg/panel/text/border) intentionally avoid pure black
or pure white and lean on Google's Material defaults: comfortable
contrast (WCAG AA on body text) without the glare of #000 / #FFF.
The accent + status colors (plus/minus, tags) are tuned per theme to
stay readable against those neutrals.
"""

LIGHT = {
    # Neutrals (Material-ish: warm light gray, not blueish)
    "bg": "#F7F7F7",
    "panel": "#FFFFFF",
    "border": "#DADCE0",
    "text": "#202124",
    "text_dim": "#5F6368",
    # Accent + selection
    "accent": "#2563EB",
    "accent_light": "#D6E8FF",
    # Segment-button states
    "seg_default": "#F2F3F5",
    "seg_selected": "#2563EB",
    "seg_matched": "#2563EB",
    "seg_unmatched": "#E2E8F0",
    # Feature value semantics
    "plus": "#15803D",
    "plus_bg": "#DCFCE7",
    "minus": "#B91C1C",
    "minus_bg": "#FEE2E2",
    "shared_plus": "#DCFCE7",
    "shared_minus": "#FEE2E2",
    # Analysis panel + tag chips
    "analysis_bg": "#F2F3F5",
    "tag_blue": "#DBEAFE",
    "tag_blue_text": "#1D4ED8",
    "tag_green": "#DCFCE7",
    "tag_green_text": "#15803D",
    "tag_red": "#FEE2E2",
    "tag_red_text": "#B91C1C",
    "tag_gray": "#F1F3F4",
    "tag_gray_text": "#5F6368",
}

DARK = {
    # Neutrals (true dark gray instead of deep navy; reduces glare while
    # keeping body-text contrast comfortably above WCAG AA)
    "bg": "#181818",
    "panel": "#202020",
    "border": "#3A3A3A",
    "text": "#E8EAED",
    "text_dim": "#B8B8B8",
    # Accent + selection
    "accent": "#60A5FA",
    "accent_light": "#2F4F6F",
    # Segment-button states
    "seg_default": "#262626",
    "seg_selected": "#3B82F6",
    "seg_matched": "#3B82F6",
    "seg_unmatched": "#3A3A3A",
    # Feature value semantics
    "plus": "#86EFAC",
    "plus_bg": "#14532D",
    "minus": "#FCA5A5",
    "minus_bg": "#7F1D1D",
    "shared_plus": "#14532D",
    "shared_minus": "#7F1D1D",
    # Analysis panel + tag chips
    "analysis_bg": "#262626",
    "tag_blue": "#1E3A8A",
    "tag_blue_text": "#93C5FD",
    "tag_green": "#14532D",
    "tag_green_text": "#86EFAC",
    "tag_red": "#7F1D1D",
    "tag_red_text": "#FCA5A5",
    "tag_gray": "#2A2A2A",
    "tag_gray_text": "#B8B8B8",
}

# Active palette. Mutated in place by ``set_theme`` so existing imports
# keep observing the current theme.
C: dict = dict(LIGHT)


def set_theme(name: str) -> None:
    """Switch the active palette to ``light`` or ``dark``."""
    target = DARK if name == "dark" else LIGHT
    C.clear()
    C.update(target)


def get_theme_name() -> str:
    """Return ``'light'`` or ``'dark'`` for the currently-active palette."""
    return "dark" if C.get("bg") == DARK["bg"] else "light"


def detect_system_theme(default: str = "light") -> str:
    """Return ``'dark'`` if the OS is in dark mode, else ``'light'``.

    Uses Qt's ``styleHints().colorScheme()`` (added in Qt 6.5). Falls
    back to ``default`` when no QApplication exists yet, when Qt
    reports ColorScheme.Unknown, or when the running Qt is too old.
    """
    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        return default
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return default
    hints = app.styleHints()
    if hints is None or not hasattr(hints, "colorScheme"):
        return default
    scheme = hints.colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        return "dark"
    if scheme == Qt.ColorScheme.Light:
        return "light"
    return default
