"""Shared colour palette for the GUI.

Two themes are defined: ``LIGHT`` (default) and ``DARK``. ``C`` is the
active palette - mutated in place by ``set_theme`` so existing
``from gui.palette import C`` imports keep working after a swap.
Per-theme style caches on SegmentButton / FeatureRow + MainWindow's
``_apply_theme`` central-widget rebuild make swaps live (no restart).
"""

LIGHT = {
    "bg": "#F0F2F5",
    "panel": "#FFFFFF",
    "border": "#D0D5DD",
    "accent": "#2563EB",
    "accent_light": "#DBEAFE",
    "seg_default": "#F8FAFC",
    "seg_selected": "#2563EB",
    "seg_matched": "#2563EB",
    "seg_unmatched": "#E2E8F0",
    "plus": "#15803D",
    "plus_bg": "#DCFCE7",
    "minus": "#B91C1C",
    "minus_bg": "#FEE2E2",
    "shared_plus": "#DCFCE7",
    "shared_minus": "#FEE2E2",
    "text": "#1E293B",
    "text_dim": "#94A3B8",
    "analysis_bg": "#F8FAFC",
    "tag_blue": "#DBEAFE",
    "tag_blue_text": "#1D4ED8",
    "tag_green": "#DCFCE7",
    "tag_green_text": "#15803D",
    "tag_red": "#FEE2E2",
    "tag_red_text": "#B91C1C",
    "tag_gray": "#F1F5F9",
    "tag_gray_text": "#64748B",
}

DARK = {
    "bg": "#0F172A",
    "panel": "#1E293B",
    "border": "#334155",
    "accent": "#60A5FA",
    "accent_light": "#1E3A8A",
    "seg_default": "#1E293B",
    "seg_selected": "#3B82F6",
    "seg_matched": "#3B82F6",
    "seg_unmatched": "#334155",
    "plus": "#86EFAC",
    "plus_bg": "#14532D",
    "minus": "#FCA5A5",
    "minus_bg": "#7F1D1D",
    "shared_plus": "#14532D",
    "shared_minus": "#7F1D1D",
    "text": "#F1F5F9",
    "text_dim": "#94A3B8",
    "analysis_bg": "#1E293B",
    "tag_blue": "#1E3A8A",
    "tag_blue_text": "#93C5FD",
    "tag_green": "#14532D",
    "tag_green_text": "#86EFAC",
    "tag_red": "#7F1D1D",
    "tag_red_text": "#FCA5A5",
    "tag_gray": "#334155",
    "tag_gray_text": "#94A3B8",
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
