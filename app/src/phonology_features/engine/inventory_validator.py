"""Validate phonological inventory data before loading.

Returns (errors, warnings) as human-readable strings so the GUI can
surface them without crashing. A dict that produces no errors is safe
to hand to ``FeatureEngine.load_inventory_data``.
"""

from __future__ import annotations

_VALID_VALUES = {"+", "-", "0"}
_ALLCAPS_ALLOWED = {"CORONAL", "LABIAL", "DORSAL", "ATR"}


def validate_inventory_data(data) -> tuple[list[str], list[str]]:
    """Validate an already-parsed inventory dict.

    The caller opens and parses the JSON so the engine and validator
    can share one parse instead of reading the file twice.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        errors.append(
            f"Top-level JSON value must be an object, not {type(data).__name__}"
        )
        return errors, warnings
    if "segments" not in data:
        errors.append("Missing required key 'segments'")
    if "features" not in data and "segments" in data:
        warnings.append(
            "No 'features' key; feature list will be inferred from segments"
        )
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
            seen: set[str] = set()
            dupes: set[str] = set()
            for f in features:
                if isinstance(f, str):
                    if f in seen:
                        dupes.add(f)
                    seen.add(f)
            if dupes:
                errors.append(
                    f"'features' contains duplicates: {sorted(dupes)}"
                )
    segments = data.get("segments")
    if segments is not None and not isinstance(segments, dict):
        errors.append(
            f"'segments' must be an object, got {type(segments).__name__}"
        )
        return errors, warnings
    if not isinstance(segments, dict) or not segments:
        if isinstance(segments, dict) and not segments:
            errors.append("'segments' is empty")
        return errors, warnings
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
    if declared_features is not None:
        unused = declared_features - all_seg_features
        if unused:
            warnings.append(
                f"Features declared but unused by any segment: {sorted(unused)}"
            )
        undeclared = all_seg_features - declared_features
        if undeclared:
            warnings.append(
                f"Features used by segments but not in 'features' list: "
                f"{sorted(undeclared)}"
            )
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
    sig_to_segs: dict = {}
    for seg_name, seg_feats in segments.items():
        if not isinstance(seg_feats, dict):
            continue
        sig = tuple(sorted((f, v) for f, v in seg_feats.items() if v != "0"))
        sig_to_segs.setdefault(sig, []).append(seg_name)
    warnings.extend(
        f"Featurally identical segments (same specified features): {', '.join(names)}"
        for names in sig_to_segs.values()
        if len(names) > 1
    )
    check_feats = declared_features or all_seg_features
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
    name = data.get("name")
    if name is not None and not isinstance(name, str):
        warnings.append(
            f"'name' should be a string, got {type(name).__name__}"
        )
    return errors, warnings
