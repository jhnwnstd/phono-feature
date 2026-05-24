"""Shared color palettes for the GUI.

``C`` is the active palette, mutated in place by ``set_theme`` so
existing imports keep observing the current theme. Per-widget
``apply_theme`` methods do the rest of the live swap.

Neutrals avoid pure black and pure white (less glare, contrast above
WCAG AA on body text); accent and status colors are tuned per theme.
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
    # Neutrals (true dark gray, not deep navy)
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

# Active palette, mutated in place by set_theme.
C: dict = dict(LIGHT)

# Monotonic counter bumped on every theme change. Caches that
# depend on palette colors key on this integer; on miss they
# rebuild from the current ``C`` and store the new version.
# Lets callers cache derived objects (e.g. QBrush triples) without
# wiring observer callbacks into ``set_theme``.
theme_version: int = 0


def set_theme(name: str) -> None:
    """Switch the active palette to "light" or "dark"."""
    global theme_version
    target = DARK if name == "dark" else LIGHT
    C.clear()
    C.update(target)
    theme_version += 1


def get_theme_name() -> str:
    """Return "light" or "dark" for the currently active palette."""
    return "dark" if C.get("bg") == DARK["bg"] else "light"


def detect_system_theme(default: str = "light") -> str:
    """Return "dark" if the OS reports dark mode, else "light".
    Uses Qt's ``styleHints().colorScheme()`` (Qt 6.5+); falls back to
    ``default`` when no QApplication exists, Qt reports Unknown, or
    the running Qt is too old.
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
