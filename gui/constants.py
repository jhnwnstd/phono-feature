"""
gui/constants.py
Shared constants, layout geometry, and helper functions for the GUI.
"""

from gui.palette import C

# ---------------------------------------------------------------------------
# Settings keys
# ---------------------------------------------------------------------------

SETTINGS_ORG = "features"
SETTINGS_APP = "SegFeatureEngine"

# ---------------------------------------------------------------------------
# Tag palettes for inline HTML chips
# ---------------------------------------------------------------------------

TAG_PALETTES = {
    "blue": (C["tag_blue"], C["tag_blue_text"]),
    "green": (C["tag_green"], C["tag_green_text"]),
    "red": (C["tag_red"], C["tag_red_text"]),
    "gray": (C["tag_gray"], C["tag_gray_text"]),
}

# ---------------------------------------------------------------------------
# Segment button geometry
# ---------------------------------------------------------------------------

BTN_W = 33  # SegmentButton fixed width  (must match setFixedSize in __init__)
BTN_H = 26  # SegmentButton fixed height
BTN_GAP = 4  # QGridLayout spacing

# ---------------------------------------------------------------------------
# Canonical feature display order (linguistically motivated hierarchy)
# Features absent from this list appear at the end in their original order.
# ---------------------------------------------------------------------------

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
    # Place — LABIAL node + dependents
    "LABIAL",
    "Round",
    "Labiodental",
    # Place — CORONAL node + dependents
    "CORONAL",
    "Anterior",
    "Distributed",
    # Place — DORSAL node + dependents
    "DORSAL",
    "High",
    "Low",
    "Back",
    "Front",
    # Pharyngeal / advanced tongue root
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

_FEATURE_ORDER_INDEX: dict = {f: i for i, f in enumerate(FEATURE_ORDER)}

# Feature groups for the two-column panel layout.
FEATURE_GROUPS: list = [
    ("Major Class", ["Syllabic", "Consonantal", "Sonorant", "Approximant"]),
    ("Laryngeal", ["Voice", "SpreadGl", "ConstrGl"]),
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
        ["ConstrPharynx", "Pharyngeal", "ATR", "Tense"],
    ),
    ("Prosodic", ["Long", "Stress", "Tone", "UpperRegister"]),
]


def sort_features(features: list) -> list:
    """Return features in canonical order; unknowns trail in original order."""
    n = len(FEATURE_ORDER)
    return sorted(features, key=lambda f: _FEATURE_ORDER_INDEX.get(f, n))


def sort_spec(spec: dict) -> dict:
    """Return a feature bundle dict with keys in canonical phonological order."""
    return {f: spec[f] for f in sort_features(list(spec.keys()))}


# ---------------------------------------------------------------------------
# Shared scrollbar style — thin, unobtrusive overlay track
# ---------------------------------------------------------------------------

SCROLLBAR_STYLE = f"""
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
