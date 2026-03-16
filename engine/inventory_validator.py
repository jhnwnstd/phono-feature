"""Validate phonological inventory JSON files before loading.

Returns a list of human-readable error/warning strings so the GUI can
display them without crashing.  A file that passes with no errors is
safe to hand to FeatureEngine.load_inventory().
"""

from __future__ import annotations

import json
import os
from typing import List, Tuple

_VALID_VALUES = {"+", "-", "0"}


def validate_inventory(filepath: str) -> Tuple[List[str], List[str]]:
    """Validate an inventory JSON file.

    Returns:
        (errors, warnings) — both are lists of human-readable strings.
        If errors is non-empty the file should not be loaded.
    """
    errors: List[str] = []
    warnings: List[str] = []

    # -- File-level checks --

    if not os.path.isfile(filepath):
        errors.append(f"File not found: {filepath}")
        return errors, warnings

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        errors.append(f"Cannot read file: {e}")
        return errors, warnings

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        errors.append(
            f"Invalid JSON: {e.msg} (line {e.lineno}, col {e.colno})"
        )
        return errors, warnings

    if not isinstance(data, dict):
        errors.append(
            "Top-level JSON value must be an object, not "
            f"{type(data).__name__}"
        )
        return errors, warnings

    # -- Required keys --

    if "segments" not in data:
        errors.append("Missing required key 'segments'")
    if "features" not in data and "segments" in data:
        # Features list is optional — can be inferred from segments
        warnings.append(
            "No 'features' key; feature list will be inferred from segments"
        )

    # -- Features list --

    features = data.get("features")
    if features is not None:
        if not isinstance(features, list):
            errors.append(
                f"'features' must be a list of strings, got {type(features).__name__}"
            )
        else:
            non_str = [f for f in features if not isinstance(f, str)]
            if non_str:
                errors.append(
                    f"'features' contains non-string entries: {non_str[:5]}"
                )
            dupes = [f for f in features if features.count(f) > 1]
            if dupes:
                errors.append(
                    f"'features' contains duplicates: {sorted(set(dupes))}"
                )

    # -- Segments dict --

    segments = data.get("segments")
    if segments is not None and not isinstance(segments, dict):
        errors.append(
            f"'segments' must be an object, got {type(segments).__name__}"
        )
        return errors, warnings

    if not isinstance(segments, dict) or not segments:
        if isinstance(segments, dict) and not segments:
            errors.append("'segments' is empty — no segments defined")
        return errors, warnings

    # -- Per-segment checks --

    declared_features = set(features) if isinstance(features, list) else None
    all_seg_features: set = set()
    bad_value_count = 0
    max_bad_examples = 5

    for seg_name, seg_feats in segments.items():
        if not isinstance(seg_name, str):
            errors.append(f"Segment key {seg_name!r} is not a string")
            continue

        if not isinstance(seg_feats, dict):
            errors.append(
                f"Segment '{seg_name}': feature bundle must be an object, "
                f"got {type(seg_feats).__name__}"
            )
            continue

        for feat_name, feat_val in seg_feats.items():
            all_seg_features.add(feat_name)

            if not isinstance(feat_val, str):
                if bad_value_count < max_bad_examples:
                    errors.append(
                        f"'{seg_name}'.'{feat_name}': value must be a string, "
                        f"got {type(feat_val).__name__} ({feat_val!r})"
                    )
                bad_value_count += 1
                continue

            if feat_val not in _VALID_VALUES:
                if bad_value_count < max_bad_examples:
                    errors.append(
                        f"'{seg_name}'.'{feat_name}': invalid value '{feat_val}' "
                        f"(expected '+', '-', or '0')"
                    )
                bad_value_count += 1

    if bad_value_count > max_bad_examples:
        errors.append(
            f"... and {bad_value_count - max_bad_examples} more invalid values"
        )

    # -- Cross-checks between features list and segment data --

    if declared_features is not None:
        # Features declared but never used by any segment
        unused = declared_features - all_seg_features
        if unused:
            warnings.append(
                f"Features declared but unused by any segment: "
                f"{sorted(unused)}"
            )

        # Features used by segments but not declared
        undeclared = all_seg_features - declared_features
        if undeclared:
            warnings.append(
                f"Features used by segments but not in 'features' list: "
                f"{sorted(undeclared)}"
            )

    # -- Consistency: do all segments specify the same features? --

    seg_names = list(segments.keys())
    if seg_names:
        first_feats = (
            set(segments[seg_names[0]].keys())
            if isinstance(segments[seg_names[0]], dict)
            else set()
        )
        inconsistent = []
        for seg_name in seg_names[1:]:
            seg_feats = segments[seg_name]
            if not isinstance(seg_feats, dict):
                continue
            seg_feat_set = set(seg_feats.keys())
            if seg_feat_set != first_feats:
                missing = first_feats - seg_feat_set
                extra = seg_feat_set - first_feats
                parts = []
                if missing:
                    parts.append(f"missing {sorted(missing)}")
                if extra:
                    parts.append(f"extra {sorted(extra)}")
                inconsistent.append(f"'{seg_name}': {', '.join(parts)}")

        if inconsistent:
            warnings.append(
                f"Segments have inconsistent feature sets "
                f"(vs '{seg_names[0]}'): {'; '.join(inconsistent[:3])}"
            )
            if len(inconsistent) > 3:
                warnings.append(
                    f"... and {len(inconsistent) - 3} more inconsistent segments"
                )

    # -- Duplicate segments: same specified (non-0) features and values --

    sig_to_segs: dict = {}
    for seg_name, seg_feats in segments.items():
        if not isinstance(seg_feats, dict):
            continue
        # Signature = only the specified features (ignore "0" / underspecified)
        sig = tuple(sorted(
            (f, v) for f, v in seg_feats.items() if v != "0"
        ))
        sig_to_segs.setdefault(sig, []).append(seg_name)

    dupes = {
        tuple(names): names
        for names in sig_to_segs.values()
        if len(names) > 1
    }
    if dupes:
        for names in dupes.values():
            warnings.append(
                f"Featurally identical segments (same specified features): "
                f"{', '.join(names)}"
            )

    # -- Feature naming convention --
    # Only place nodes (CORONAL, LABIAL, DORSAL) should be all-caps.
    # All other features should start with a capital letter (title case).

    _ALLCAPS_ALLOWED = {"CORONAL", "LABIAL", "DORSAL", "ATR"}
    check_feats = declared_features if declared_features else all_seg_features
    for feat in sorted(check_feats):
        if feat.isupper() and feat not in _ALLCAPS_ALLOWED:
            warnings.append(
                f"Feature '{feat}' is all-caps but only place nodes "
                f"(CORONAL, LABIAL, DORSAL) should be. "
                f"Consider renaming to '{feat.title()}'"
            )
        elif feat[0].islower():
            warnings.append(
                f"Feature '{feat}' starts with a lowercase letter. "
                f"Consider renaming to '{feat[0].upper() + feat[1:]}'"
            )

    # -- Optional metadata checks --

    name = data.get("name")
    if name is not None and not isinstance(name, str):
        warnings.append(
            f"'name' should be a string, got {type(name).__name__}"
        )

    return errors, warnings
