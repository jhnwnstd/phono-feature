"""Issue-code coverage: every validation path emits a stable
:py:class:`ValidationIssue` code. Tests pin the codes (the
contract), not the wording (the UI surface). When a new check is
added, the matching ``_IssueCodes`` entry is added to the
parametrise table here.

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


# Each row pins one validation path: the issue code that MUST
# appear in the raised ValidationError when ``Inventory.parse``
# runs on ``raw``. Add a new row whenever a new ``_IssueCodes``
# entry is added; consolidates the prior 17 single-assert tests
# into one table whose maintenance is a single line per check.
_CASES: tuple[tuple[str, Any], ...] = (
    # Top-level shape
    (_IssueCodes.TOP_LEVEL_NOT_OBJECT, []),
    (_IssueCodes.TOP_LEVEL_NOT_OBJECT, "not an object"),
    # Schema version
    (
        _IssueCodes.SCHEMA_VERSION_TYPE,
        {"schema_version": "1", "features": [], "segments": {}},
    ),
    # bool is a subclass of int; rejected explicitly.
    (
        _IssueCodes.SCHEMA_VERSION_TYPE,
        {"schema_version": True, "features": [], "segments": {}},
    ),
    (
        _IssueCodes.SCHEMA_VERSION_UNSUPPORTED,
        {"schema_version": 9999, "features": [], "segments": {}},
    ),
    # Required-field presence
    (_IssueCodes.MISSING_FEATURES, {"segments": {}}),
    (_IssueCodes.MISSING_SEGMENTS, {"features": []}),
    # Features container shape
    (
        _IssueCodes.FEATURES_NOT_LIST,
        {"features": "not a list", "segments": {}},
    ),
    (
        _IssueCodes.FEATURE_NOT_STRING,
        {"features": ["Voice", 123], "segments": {}},
    ),
    (
        _IssueCodes.FEATURE_DUPLICATE,
        {"features": ["Voice", "Voice"], "segments": {}},
    ),
    # Two distinct spellings that collapse to the same canonical
    # identity (NFC-stripping ' Voice ' equals 'Voice').
    (
        _IssueCodes.FEATURE_CANONICAL_COLLISION,
        {"features": ["Voice", " Voice "], "segments": {}},
    ),
    # ``DelRel`` and ``delayed_release`` are distinct canonical
    # names but ``normalize_feature_key`` folds both to ``delrel``.
    (
        _IssueCodes.FEATURE_ALIAS_COLLISION,
        {"features": ["DelRel", "delayed_release"], "segments": {}},
    ),
    # Segments container shape
    (
        _IssueCodes.SEGMENTS_NOT_OBJECT,
        {"features": ["Voice"], "segments": []},
    ),
    # ASCII ``g`` folds to IPA ``ɡ`` during canonicalisation;
    # both keys at the top level are the same segment.
    (
        _IssueCodes.SEGMENT_KEY_COLLISION,
        {
            "features": ["Voice"],
            "segments": {"g": {"Voice": "+"}, "ɡ": {"Voice": "+"}},
        },
    ),
    (
        _IssueCodes.BUNDLE_NOT_OBJECT,
        {"features": ["Voice"], "segments": {"p": "not an object"}},
    ),
    # A bundle key that does not match any declared feature
    # (neither by canonical name nor by alias) is rejected.
    (
        _IssueCodes.BUNDLE_FEATURE_NOT_DECLARED,
        {"features": ["Voice"], "segments": {"p": {"Nasal": "+"}}},
    ),
    # Two bundle keys that resolve to the same declared feature
    # (one direct, one via alias folding) are reported as a
    # collision so neither value silently overwrites the other.
    (
        _IssueCodes.BUNDLE_FEATURE_KEY_COLLISION,
        {
            "features": ["Rhotic"],
            "segments": {"p": {"Rhotic": "+", "r-colored": "-"}},
        },
    ),
    (
        _IssueCodes.BUNDLE_VALUE_TYPE,
        {"features": ["Voice"], "segments": {"p": {"Voice": 1}}},
    ),
    (
        _IssueCodes.BUNDLE_VALUE_INVALID,
        {"features": ["Voice"], "segments": {"p": {"Voice": "yes"}}},
    ),
)


@pytest.mark.parametrize(
    "expected_code,raw",
    _CASES,
    ids=[code for code, _ in _CASES],
)
def test_validation_issue_codes_emit(expected_code: str, raw: Any) -> None:
    """Each row in ``_CASES`` pins one validation path: the named
    issue code must appear in the codes the parser emits for the
    raw input. Consolidates 17 prior single-assertion tests into
    one parametrise table; adding a new check is one row."""
    assert expected_code in _codes(raw)


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
