"""Shared GUI constants, geometry, and tiny helpers."""

from enum import StrEnum

from phonology_features.gui.palette import C

SETTINGS_ORG = "features"
SETTINGS_APP = "SegFeatureEngine"

# Unicode minus (U+2212), not ASCII hyphen-minus (U+002D). Used
# wherever we render the negative-feature symbol so it visually
# matches the width and stroke weight of ``+``. Named constant
# rather than ``chr(8722)`` so readers don't have to look it up.
MINUS_SIGN: str = "−"


class TagColor(StrEnum):
    """Semantic name for an analysis-pane chip colour.

    Magic strings were typo-silent before: ``_tag(text, "bleu")``
    fell back to gray with no warning. This enum is exhaustive (mypy
    can verify every consumer), self-documenting (``TagColor.SEGMENT``
    says WHY the chip is blue), and the string values match the
    historical palette keys so existing lookups keep working.
    """

    SEGMENT = "blue"
    PLUS = "green"
    MINUS = "red"
    NEUTRAL = "gray"


# One source of truth for the inline-chip box model. Every chip in
# the analysis pane shares this geometry; the previous magic numbers
# (``border-radius:4px; padding:2px 7px; ...``) were duplicated in
# every f-string in analysis.py and went out of sync at least once
# during the dark-mode work.
CHIP_BORDER_RADIUS_PX: int = 4
CHIP_PADDING_CSS: str = "2px 7px"
CHIP_MARGIN_PX: int = 2
CHIP_FONT_SIZE_PT: int = 10

# Monospace font fallback chain for IPA-heavy text (analysis-pane
# chips, anything rendering segment symbols / feature values). Order:
# most-IPA-coverage first, then per-OS defaults that are usually
# installed, then the system ``monospace`` alias as a last resort.
# Without an explicit chain Qt resolves ``monospace`` to whatever the
# system aliases, which on stripped-down Linux can land on a font with
# poor coverage of combining marks like U+0361 (the tie bar in d͡ʒ).
# Python list -- usable with ``QFont.setFamilies``; ``MONO_FAMILY_CSS``
# is the CSS string form for inline ``font-family:`` rules.
MONO_FAMILIES: list[str] = [
    "Noto Sans Mono",
    "DejaVu Sans Mono",
    "Menlo",
    "Consolas",
    "Liberation Mono",
    "monospace",
]
MONO_FAMILY_CSS: str = ", ".join(
    f"'{f}'" if " " in f else f for f in MONO_FAMILIES
)


def tag_palettes() -> dict[TagColor, tuple[str, str]]:
    """Inline-chip ``(background, foreground)`` palette keyed by
    :class:`TagColor`.

    A function (not a module constant) so it re-reads ``C`` on every
    call; theme swaps would otherwise bake in the import-time palette.
    """
    return {
        TagColor.SEGMENT: (C["tag_blue"], C["tag_blue_text"]),
        TagColor.PLUS: (C["tag_green"], C["tag_green_text"]),
        TagColor.MINUS: (C["tag_red"], C["tag_red_text"]),
        TagColor.NEUTRAL: (C["tag_gray"], C["tag_gray_text"]),
    }


BTN_W = 33
BTN_GAP = 4
# Canonical feature display order. Features absent from this list trail
# at the end in their original order.
FEATURE_ORDER: list = [
    # Major class
    "Syllabic",
    "Consonantal",
    "Sonorant",
    "Approximant",
    # Laryngeal
    "Voice",
    "SpreadGl",
    "ConstrGl",
    # Manner
    "Continuant",
    "Strident",
    "DelRel",
    "Nasal",
    "Lateral",
    "Trill",
    "Tap",
    "Click",
    # Place
    "LABIAL",
    "Round",
    "Labiodental",
    "CORONAL",
    "Anterior",
    "Distributed",
    "DORSAL",
    "High",
    "Low",
    "Back",
    "Front",
    # Pharyngeal and advanced tongue root
    "ConstrPharynx",
    "Pharyngeal",
    "ATR",
    "Tense",
    # Prosodic
    "Long",
    "Stress",
    "Tone",
    "UpperRegister",
]
_FEATURE_ORDER_INDEX: dict = {
    feature: index for index, feature in enumerate(FEATURE_ORDER)
}
# Two-column feature panel layout.
FEATURE_GROUPS: list = [
    (
        "Major Class",
        [
            "Syllabic",
            "Consonantal",
            "Sonorant",
            "Approximant",
        ],
    ),
    (
        "Laryngeal",
        [
            "Voice",
            "SpreadGl",
            "ConstrGl",
        ],
    ),
    (
        "Manner",
        [
            "Continuant",
            "Strident",
            "DelRel",
            "Nasal",
            "Lateral",
            "Trill",
            "Tap",
            "Click",
        ],
    ),
    (
        "Place",
        [
            "LABIAL",
            "Round",
            "Labiodental",
            "CORONAL",
            "Anterior",
            "Distributed",
            "DORSAL",
            "High",
            "Low",
            "Back",
            "Front",
        ],
    ),
    (
        "Tongue-Root / Pharyngeal",
        [
            "ConstrPharynx",
            "Pharyngeal",
            "ATR",
            "Tense",
        ],
    ),
    (
        "Prosodic",
        [
            "Long",
            "Stress",
            "Tone",
            "UpperRegister",
        ],
    ),
]


def sort_features(features: list) -> list:
    """Sort features by ``FEATURE_ORDER``; unknowns trail in original order."""
    unknown_index = len(FEATURE_ORDER)
    return sorted(
        features, key=lambda f: _FEATURE_ORDER_INDEX.get(f, unknown_index)
    )


def sort_spec(spec: dict) -> dict:
    """Reorder a feature-bundle dict into canonical key order."""
    return {
        feature: spec[feature] for feature in sort_features(list(spec.keys()))
    }


def scrollbar_style() -> str:
    """Thin overlay-style scrollbar QSS.

    A function (not a module constant) so theme swaps pick up the new
    palette; an f-string at import time would bake in the old colors.
    """
    return f"""
    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 0;
        border: none;
    }}

    QScrollBar::handle:vertical {{
        background: {C["border"]};
        border-radius: 3px;
        min-height: 24px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: {C["text_dim"]};
    }}

    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{
        height: 0;
        background: none;
        border: none;
    }}

    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {{
        background: none;
    }}

    QScrollBar:horizontal {{
        background: transparent;
        height: 6px;
        margin: 0;
        border: none;
    }}

    QScrollBar::handle:horizontal {{
        background: {C["border"]};
        border-radius: 3px;
        min-width: 24px;
    }}

    QScrollBar::handle:horizontal:hover {{
        background: {C["text_dim"]};
    }}

    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {{
        width: 0;
        background: none;
        border: none;
    }}

    QScrollBar::add-page:horizontal,
    QScrollBar::sub-page:horizontal {{
        background: none;
    }}
"""
