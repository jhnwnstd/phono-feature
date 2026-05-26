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
    # Primary-action and destructive-action buttons (Save / Delete /
    # Create-Grid). Hover is slightly DEEPER than default in light
    # mode so "pressing in" reads as a darker version of the same hue.
    # In dark mode these flip (see DARK) because the dark-mode accent
    # is pale; using it as the default makes the button look washed
    # out and the hover then has to swing to a vivid saturated state
    # for distinction. Both directions should read as "press == more
    # contrast against background".
    "btn_primary": "#2563EB",
    "btn_primary_text": "#FFFFFF",
    # One Tailwind shade past the default (blue-700 to blue-800,
    # red-800 to red-900). Reads as a subtle "press". The original
    # hovers were essentially the default colour, which made the
    # hover state hard to feel.
    "btn_primary_hover": "#1E40AF",
    "btn_primary_hover_text": "#FFFFFF",
    "btn_danger": "#B91C1C",
    "btn_danger_text": "#FFFFFF",
    "btn_danger_hover": "#7F1D1D",
    "btn_danger_hover_text": "#FFFFFF",
    # Disabled-button palette: darker bg than ``tag_gray`` and a
    # heavily muted text colour so the button recedes from the
    # active toolbar buttons. The border matches the bg (no rim)
    # so the disabled state reads as "flat tile, not interactive".
    "btn_disabled_bg": "#E2E4E7",
    "btn_disabled_text": "#9AA0A6",
    "btn_disabled_border": "#E2E4E7",
    # Splitter handle hover: a neutral grey, NOT the accent blue.
    # Accent is reserved for "active / selected" semantics; the
    # drag handle is an "interactive surface" cue, which a darker
    # grey communicates without overloading the selected meaning.
    "splitter_hover": "#9AA0A6",
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
    # See LIGHT.btn_primary comment: in dark mode the saturated deep
    # blue / deep red is the DEFAULT (reads boldly on dark bg), and
    # the pale tint becomes the hover (reads as a "lift"). Hover text
    # switches to dark because white on pale pink / pale blue would
    # smear; everything else stays white on the saturated default.
    "btn_primary": "#1D4ED8",
    "btn_primary_text": "#FFFFFF",
    "btn_primary_hover": "#60A5FA",
    "btn_primary_hover_text": "#181818",
    "btn_danger": "#991B1B",
    "btn_danger_text": "#FFFFFF",
    "btn_danger_hover": "#FCA5A5",
    "btn_danger_hover_text": "#181818",
    # Dark-mode disabled: bg darker than the panel chrome (sinks BELOW
    # the toolbar surface so it reads as "carved out, inactive"), text
    # heavily muted so it is barely legible. The visible cue is the
    # darker tile; the label is just a hint.
    "btn_disabled_bg": "#161616",
    "btn_disabled_text": "#555555",
    "btn_disabled_border": "#161616",
    # See LIGHT.splitter_hover comment. Dark mode wants the hover
    # cue LIGHTER than the resting border so it pops against the
    # dark background; same "neutral, not accent" rule applies.
    "splitter_hover": "#6A6A6A",
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
# Lets callers cache derived objects (for example QBrush triples)
# without wiring observer callbacks into ``set_theme``.
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
