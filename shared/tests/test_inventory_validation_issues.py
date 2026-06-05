"""Issue-code coverage: every validation path emits a stable
:py:class:`ValidationIssue` code. Tests pin the codes (the
contract), not the wording (the UI surface). When a new check is
added, the matching ``_IssueCodes`` entry is added here too.

The legacy ``ValidationError.issues`` string tuple is still
populated from the messages, so existing UI code keeps working;
this file is the new structural contract that future test
maintenance follows.
"""

from __future__ import annotations

from typing import Any

import pytest

from phonology_shared.data.inventory import (
    Inventory,
    ValidationError,
    _IssueCodes,
)


def _codes(raw: Any) -> set[str]:
    """Run ``Inventory.parse`` on ``raw`` and return the set of
    issue codes from the resulting :py:class:`ValidationError`.
    Fails the test if parsing unexpectedly succeeds."""
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(raw)
    return {vi.code for vi in ex.value.validation_issues}


def test_top_level_not_object_code() -> None:
    """A non-object top-level value raises immediately with the
    matching code; downstream checks are skipped because no per-field
    validation makes sense on a non-dict."""
    assert _IssueCodes.TOP_LEVEL_NOT_OBJECT in _codes([])
    assert _IssueCodes.TOP_LEVEL_NOT_OBJECT in _codes("not an object")


def test_schema_version_type_code() -> None:
    assert _IssueCodes.SCHEMA_VERSION_TYPE in _codes(
        {"schema_version": "1", "features": [], "segments": {}}
    )
    # bool is a subclass of int; rejected explicitly.
    assert _IssueCodes.SCHEMA_VERSION_TYPE in _codes(
        {"schema_version": True, "features": [], "segments": {}}
    )


def test_schema_version_unsupported_code() -> None:
    assert _IssueCodes.SCHEMA_VERSION_UNSUPPORTED in _codes(
        {"schema_version": 9999, "features": [], "segments": {}}
    )


def test_missing_features_code() -> None:
    assert _IssueCodes.MISSING_FEATURES in _codes({"segments": {}})


def test_missing_segments_code() -> None:
    assert _IssueCodes.MISSING_SEGMENTS in _codes({"features": []})


def test_features_not_list_code() -> None:
    assert _IssueCodes.FEATURES_NOT_LIST in _codes(
        {"features": "not a list", "segments": {}}
    )


def test_feature_not_string_code() -> None:
    assert _IssueCodes.FEATURE_NOT_STRING in _codes(
        {"features": ["Voice", 123], "segments": {}}
    )


def test_feature_duplicate_code() -> None:
    assert _IssueCodes.FEATURE_DUPLICATE in _codes(
        {"features": ["Voice", "Voice"], "segments": {}}
    )


def test_feature_canonical_collision_code() -> None:
    """Two distinct spellings collapse to the same canonical
    identity (here NFC-stripping ' Voice ' equals 'Voice')."""
    assert _IssueCodes.FEATURE_CANONICAL_COLLISION in _codes(
        {"features": ["Voice", " Voice "], "segments": {}}
    )


def test_feature_alias_collision_code() -> None:
    """`DelRel` and `delayed_release` are distinct canonical names
    but the engine's normalize_feature_key folds both to `delrel`.
    Caught at the feature-table boundary."""
    assert _IssueCodes.FEATURE_ALIAS_COLLISION in _codes(
        {"features": ["DelRel", "delayed_release"], "segments": {}}
    )


def test_segments_not_object_code() -> None:
    assert _IssueCodes.SEGMENTS_NOT_OBJECT in _codes(
        {"features": ["Voice"], "segments": []}
    )


def test_segment_key_collision_code() -> None:
    """ASCII ``g`` folds to IPA ``ɡ`` during canonicalisation;
    both keys at the top level are the same segment."""
    assert _IssueCodes.SEGMENT_KEY_COLLISION in _codes(
        {
            "features": ["Voice"],
            "segments": {"g": {"Voice": "+"}, "ɡ": {"Voice": "+"}},
        }
    )


def test_bundle_not_object_code() -> None:
    assert _IssueCodes.BUNDLE_NOT_OBJECT in _codes(
        {"features": ["Voice"], "segments": {"p": "not an object"}}
    )


def test_bundle_feature_not_declared_code() -> None:
    """A bundle key that does not match any declared feature
    (neither by canonical name nor by alias) is rejected."""
    assert _IssueCodes.BUNDLE_FEATURE_NOT_DECLARED in _codes(
        {
            "features": ["Voice"],
            "segments": {"p": {"Nasal": "+"}},
        }
    )


def test_bundle_feature_key_collision_code() -> None:
    """Two bundle keys that resolve to the same declared feature
    (one direct, one via alias folding) are reported as a
    collision so neither value silently overwrites the other."""
    assert _IssueCodes.BUNDLE_FEATURE_KEY_COLLISION in _codes(
        {
            "features": ["Rhotic"],
            "segments": {"p": {"Rhotic": "+", "r-colored": "-"}},
        }
    )


def test_bundle_value_type_code() -> None:
    assert _IssueCodes.BUNDLE_VALUE_TYPE in _codes(
        {"features": ["Voice"], "segments": {"p": {"Voice": 1}}}
    )


def test_bundle_value_invalid_code() -> None:
    assert _IssueCodes.BUNDLE_VALUE_INVALID in _codes(
        {
            "features": ["Voice"],
            "segments": {"p": {"Voice": "yes"}},
        }
    )


def test_validation_error_carries_both_shapes() -> None:
    """``validation_issues`` is the new structured contract;
    ``issues`` stays the legacy string tuple. Both must be populated
    from the same set of records, in the same order."""
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(
            {
                "features": ["Voice", "Voice"],
                "segments": {"p": {"Voice": "yes"}},
            }
        )
    err = ex.value
    assert len(err.validation_issues) == len(err.issues)
    for vi, msg in zip(err.validation_issues, err.issues):
        assert vi.message == msg
    # str(err) is the first issue (the status-bar fallback used by
    # the desktop UI).
    assert str(err) == err.issues[0]


def test_issue_paths_are_specific() -> None:
    """Issue ``path`` carries the JSON location so a future UI can
    point at the offending field rather than the whole file."""
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(
            {
                "features": ["Voice", "Voice"],
                "segments": {},
            }
        )
    paths = {vi.path for vi in ex.value.validation_issues}
    assert ("features", 1) in paths
