"""Public API for the :py:mod:`phonology_engine` package.

Consumers (desktop GUI, web Pyodide bridge, tests) import from this
module rather than from submodules so the public surface is one
explicit list. Anything not re-exported here is considered internal
and may move without notice across patch releases.

The submodule imports the engine itself uses (``feature_engine``
importing from ``inventory`` and ``segment_grouper``) keep working;
this barrel-export layer is for downstream consumers only.
"""

from __future__ import annotations

from phonology_engine.feature_engine import FeatureEngine
from phonology_engine.inventory import (
    VALID_VALUES,
    Inventory,
    ValidationError,
    canonicalize_feature_label,
    canonicalize_segment_label,
    parse_inventory_json_text,
)
from phonology_engine.limits import (
    ADVISORY_FEATURE_THRESHOLD,
    ADVISORY_SEGMENT_THRESHOLD,
    MAX_FEATURES,
    MAX_FILE_BYTES,
    MAX_INVENTORY_FILE_BYTES,
    MAX_NAME_LENGTH,
    MAX_SEGMENTS,
)

__all__ = [
    # Core types
    "FeatureEngine",
    "Inventory",
    "ValidationError",
    "VALID_VALUES",
    # Parsing + canonicalisation helpers shared with the GUI
    # validators (NFC + IPA fold for segments, NFC only for
    # features) so add-time and save-time use the same identity
    # rule.
    "canonicalize_feature_label",
    "canonicalize_segment_label",
    "parse_inventory_json_text",
    # Hard caps + soft advisory thresholds.
    "MAX_FEATURES",
    "MAX_FILE_BYTES",
    "MAX_INVENTORY_FILE_BYTES",
    "MAX_NAME_LENGTH",
    "MAX_SEGMENTS",
    "ADVISORY_FEATURE_THRESHOLD",
    "ADVISORY_SEGMENT_THRESHOLD",
]
