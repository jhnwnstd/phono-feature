"""Shared GUI constants, geometry, and tiny helpers."""

from phonology_features.gui.palette import C

SETTINGS_ORG = "features"
SETTINGS_APP = "SegFeatureEngine"


def tag_palettes() -> dict:
    """Inline-chip palette keyed by colour name.

    A function (not a module constant) so it re-reads ``C`` on every
    call; theme swaps would otherwise bake in the import-time palette.
    """
    return {
        "blue": (C["tag_blue"], C["tag_blue_text"]),
        "green": (C["tag_green"], C["tag_green_text"]),
        "red": (C["tag_red"], C["tag_red_text"]),
        "gray": (C["tag_gray"], C["tag_gray_text"]),
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
