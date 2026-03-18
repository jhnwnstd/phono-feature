"""
gui/builder/presets.py
Feature preset definitions and validation constants for the inventory builder.
"""

FEATURE_PRESETS = {
    "Default (33)": [
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
        "Pharyngeal",
        "ATR",
        "Tense",
        # Prosodic
        "Long",
        "Stress",
        "Tone",
        "UpperRegister",
    ],
    "Custom": [],
}

VALID_VALUES = {"+", "-", "0"}
