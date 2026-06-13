"""Inventory data: schema, parsing, and the hard caps that bound it.

Pure data layer. No phonological theory, no display logic. Imports
nothing from the rest of ``phonology_shared``.
"""

from __future__ import annotations

from phonology_shared.data.inventory import (
    VALID_VALUES,
    Inventory,
    ValidationError,
    canonicalize_feature_label,
    canonicalize_segment_label,
    parse_inventory_json_text,
)
from phonology_shared.data.limits import (
    ADVISORY_FEATURE_THRESHOLD,
    ADVISORY_SEGMENT_THRESHOLD,
    MAX_CONSONANTS,
    MAX_FEATURES,
    MAX_INVENTORY_FILE_BYTES,
    MAX_NAME_LENGTH,
    MAX_SEGMENTS,
    MAX_VOWELS,
)

__all__ = [
    "ADVISORY_FEATURE_THRESHOLD",
    "ADVISORY_SEGMENT_THRESHOLD",
    "Inventory",
    "MAX_CONSONANTS",
    "MAX_FEATURES",
    "MAX_INVENTORY_FILE_BYTES",
    "MAX_NAME_LENGTH",
    "MAX_SEGMENTS",
    "MAX_VOWELS",
    "VALID_VALUES",
    "ValidationError",
    "canonicalize_feature_label",
    "canonicalize_segment_label",
    "parse_inventory_json_text",
]
