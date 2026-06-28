"""Tests for :py:mod:`phonology_shared.editor.setup`.

The module is pure-Python and consumed by both the desktop editor
dialog and the web setup modal. These tests exercise its contract
directly so a regression here fails fast in CI, before the desktop
or web smoke would notice.

No Qt imports here; the module under test is Qt-free by design.
"""

from __future__ import annotations

import pytest

from phonology_shared.editor.setup import (
    DEFAULT_FEATURES,
    DEFAULT_SEGMENTS,
    EXPLICIT_DELIMITERS,
    FEATURE_PRESETS,
    SetupIssue,
    SetupResult,
    infer_split,
    normalize_setup_name,
    suggest_filename,
    validate_setup,
)

# infer_split: delimiter inference contract


def test_infer_split_whitespace_fallback():
    """No explicit delimiter present: fall back to whitespace split."""
    assert infer_split("p b t d") == ["p", "b", "t", "d"]


def test_infer_split_newline_separated():
    assert infer_split("Syllabic\nConsonantal\nVoice\n") == [
        "Syllabic",
        "Consonantal",
        "Voice",
    ]


def test_infer_split_comma_separated_preserves_internal_spaces():
    """Comma triggers explicit-delimiter mode; spaces inside an
    entry survive so 'Long Vowel' stays one token."""
    assert infer_split("Long Vowel, Short Vowel, Schwa") == [
        "Long Vowel",
        "Short Vowel",
        "Schwa",
    ]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("a; b; c", ["a", "b", "c"]),
        ("a|b|c", ["a", "b", "c"]),
        ("a\tb\tc", ["a", "b", "c"]),
    ],
)
def test_infer_split_each_explicit_delimiter(text, expected):
    assert infer_split(text) == expected


def test_infer_split_mixes_commas_and_newlines():
    """Both delimiters together yield six tokens, not two strings
    of three. Documents the explicit-delimiter union behaviour."""
    assert infer_split("p, b, t\nd, e, f") == ["p", "b", "t", "d", "e", "f"]


def test_infer_split_empty_returns_empty():
    assert infer_split("") == []
    assert infer_split("   \n\t  ") == []


def test_infer_split_single_token_preserved():
    assert infer_split("Voice") == ["Voice"]


def test_explicit_delimiters_set_documented():
    """The exported tuple is the contract; tests below assume it."""
    assert set(EXPLICIT_DELIMITERS) == {",", ";", "|", "\t", "\n"}


# normalize_setup_name: name canonicalization


def test_normalize_setup_name_strips():
    assert normalize_setup_name("  Hello  ") == "Hello"


def test_normalize_setup_name_empty_falls_back():
    assert normalize_setup_name("") == "Untitled Inventory"
    assert normalize_setup_name("   \t\n") == "Untitled Inventory"


# validate_setup: end-to-end


def test_validate_setup_happy_path():
    result = validate_setup("My Inv", "p b t", "Voice, Nasal")
    assert result.ok
    assert result.issues == ()
    assert result.name == "My Inv"
    assert result.segments == ("p", "b", "t")
    assert result.features == ("Voice", "Nasal")


def test_validate_setup_empty_name_falls_back():
    result = validate_setup("", "p", "Voice")
    assert result.ok
    assert result.name == "Untitled Inventory"


def test_validate_setup_empty_segments_is_issue():
    result = validate_setup("X", "", "Voice")
    assert not result.ok
    fields = {i.field for i in result.issues}
    assert "segments" in fields
    issue = next(i for i in result.issues if i.field == "segments")
    assert issue.code == "empty"
    assert issue.message == "Input segments to build inventory."


def test_validate_setup_empty_features_is_issue():
    result = validate_setup("X", "p", "")
    assert not result.ok
    fields = {i.field for i in result.issues}
    assert "features" in fields


def test_validate_setup_collects_all_problems():
    """Both lists empty: caller gets both issues, not just the first."""
    result = validate_setup("X", "", "")
    assert len(result.issues) == 2
    fields = [i.field for i in result.issues]
    assert fields == ["segments", "features"]


def test_validate_setup_rejects_over_cap_segments():
    """The New Inventory dialog fails immediately on an over-cap
    segment count rather than waiting for the grid build."""
    from phonology_shared.data.limits import MAX_SEGMENTS

    segs = " ".join(f"s{i}" for i in range(MAX_SEGMENTS + 1))
    result = validate_setup("X", segs, "Voice")
    assert not result.ok
    issue = next(i for i in result.issues if i.field == "segments")
    assert issue.code == "over_cap"
    assert str(MAX_SEGMENTS) in issue.message


def test_validate_setup_rejects_over_cap_features():
    from phonology_shared.data.limits import MAX_FEATURES

    feats = " ".join(f"F{i}" for i in range(MAX_FEATURES + 1))
    result = validate_setup("X", "p", feats)
    assert not result.ok
    issue = next(i for i in result.issues if i.field == "features")
    assert issue.code == "over_cap"


def test_validate_setup_allows_counts_at_cap():
    """At-cap counts are valid; only OVER the cap is refused."""
    from phonology_shared.data.limits import MAX_FEATURES, MAX_SEGMENTS

    segs = " ".join(f"s{i}" for i in range(MAX_SEGMENTS))
    feats = " ".join(f"F{i}" for i in range(MAX_FEATURES))
    result = validate_setup("X", segs, feats)
    assert result.ok


def test_validate_setup_per_entry_length_cap():
    """A pasted wall of prose with no recognized delimiter parses
    to one over-long entry; the cap catches it before it reaches
    the inventory parser. Literal 257 (= 256 + 1) so a change to
    ``MAX_NAME_LENGTH`` trips the test rather than silently
    re-deriving the input length to match."""
    long_seg = "x" * 257
    result = validate_setup("X", long_seg, "Voice")
    assert not result.ok
    issue = next(i for i in result.issues if i.field == "segments")
    assert issue.code == "too_long"
    assert "256" in issue.message  # error mentions the literal cap


def test_validate_setup_length_cap_applies_to_features_too():
    long_feat = "x" * 257  # 1 over the 256-char MAX_NAME_LENGTH
    result = validate_setup("X", "p", long_feat)
    assert not result.ok
    issue = next(i for i in result.issues if i.field == "features")
    assert issue.code == "too_long"


def test_validate_setup_exact_cap_is_accepted():
    """The cap is inclusive: MAX_NAME_LENGTH-long (256-char)
    entries pass. Literal 256 pins the cap so a bump trips here."""
    at_cap = "x" * 256
    result = validate_setup("X", at_cap, "Voice")
    assert result.ok


# Defaults and presets


def test_default_segments_uses_ipa_script_g():
    """The seed is the IPA voiced velar (U+0261), not ASCII g, so
    the placeholder display matches the canonical form the
    inventory parser would fold ASCII g to.
    """
    assert "ɡ" in DEFAULT_SEGMENTS


def test_default_features_seeds_two_major_class_features():
    tokens = infer_split(DEFAULT_FEATURES)
    assert tokens == ["Syllabic", "Consonantal"]


def test_preset_keys_in_dropdown_order():
    """Keys in ``FEATURE_PRESETS`` are the dropdown labels; their
    insertion order is the contract for the picker render order.
    PanPhon comes from a separate provider registry and renders
    above these in the dialog, but Hayes -> PHOIBLE -> Custom is
    pinned here."""
    assert tuple(FEATURE_PRESETS.keys()) == ("Hayes", "PHOIBLE", "Custom")


def test_presets_default33_removed():
    """The legacy ``Default (33)`` preset is gone. New dialogs
    should never default-select it again."""
    assert "Default (33)" not in FEATURE_PRESETS


def test_hayes_preset_matches_bundled_inventory():
    """The inline Hayes preset must equal the ``features`` array in
    ``desktop/inventories/hayes_features.json`` so the two cannot
    drift; the JSON is the authoritative source."""
    import json
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    hayes_path = repo_root / "desktop" / "inventories" / "hayes_features.json"
    bundled = json.loads(hayes_path.read_text(encoding="utf-8-sig"))
    assert FEATURE_PRESETS["Hayes"] == bundled["features"]


def test_phoible_preset_matches_phoible_to_app_feature_values():
    """PHOIBLE preset mirrors ``PHOIBLE_TO_APP_FEATURE.values()``
    so the picker and the bake stay in lock-step. A future bake
    refresh that adds or renames features flows through here
    automatically."""
    from phonology_shared.editor.phoible_features import (
        PHOIBLE_TO_APP_FEATURE,
    )

    assert FEATURE_PRESETS["PHOIBLE"] == list(PHOIBLE_TO_APP_FEATURE.values())


def test_presets_custom_is_empty_list():
    assert FEATURE_PRESETS["Custom"] == []


# SetupResult contract


# suggest_filename: download/save-as slug


def test_suggest_filename_lowercases_and_underscores_inventory_name():
    """Lowercase, non-alphanumeric runs collapse to ``_``,
    ``_features`` suffix appended, ``.json`` extension."""
    assert suggest_filename("My Language") == "my_language_features.json"


def test_suggest_filename_preserves_existing_features_suffix():
    """An already-slugged name does not get a doubled suffix."""
    assert suggest_filename("hayes_features") == "hayes_features.json"


def test_suggest_filename_strips_punctuation_and_parens():
    """Realistic bundled-style: parens, year, mixed case all fold."""
    out = suggest_filename("Hayes 2009 (Universal)")
    assert out == "hayes_2009_universal_features.json"


def test_suggest_filename_empty_falls_back():
    assert suggest_filename("") == "untitled_features.json"
    assert suggest_filename("   ") == "untitled_features.json"


def test_suggest_filename_non_ascii_collapses():
    """Non-ASCII (and any character outside ``[a-z0-9]``) becomes a
    single underscore. Avoids producing filenames the OS may render
    inconsistently across platforms."""
    assert suggest_filename("Énglish") == "nglish_features.json"


def test_setup_result_ok_property():
    assert SetupResult(
        issues=(), name="X", segments=("a",), features=("V",)
    ).ok
    bad = SetupResult(
        issues=(SetupIssue("segments", "empty", "msg"),),
        name="X",
        segments=(),
        features=("V",),
    )
    assert not bad.ok
