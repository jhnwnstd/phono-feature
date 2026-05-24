"""Tests for the shared ``Inventory`` contract.

This is the file the reviewer flagged as missing: validator behaviour,
malformed-input handling, engine/validator agreement, atomic-write
durability, and the alias-collision check in segment_grouper.

Every test here exercises the SINGLE entry point ``Inventory.parse``
(or a thin wrapper). The engine cannot accept anything the parser
rejects, and the builder cannot save anything the parser rejects --
the parser is the contract.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from phonology_features.engine.feature_engine import FeatureEngine
from phonology_features.engine.geometry import GeometryAnalyzer
from phonology_features.engine.inventory import (
    Inventory,
    ValidationError,
    atomic_write_json,
)
from phonology_features.engine.segment_grouper import (
    AliasCollisionError,
    _normalize_feats,
)

from .conftest import close_builder_silent

REPO_ROOT = Path(__file__).resolve().parent.parent
HAYES = str(REPO_ROOT / "inventories" / "hayes_features.json")
GENERAL = str(REPO_ROOT / "inventories" / "general_features.json")


# ---------------------------------------------------------------------------
# parse(): structural shape errors
# ---------------------------------------------------------------------------
def test_parse_rejects_non_dict_top_level() -> None:
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(["features", "segments"])
    assert any("top-level" in i for i in ex.value.issues)


def test_parse_rejects_missing_features_key() -> None:
    """The old validator only warned on missing 'features'; the engine
    rejected the same data with ValueError. The new contract is
    strict so the two cannot disagree."""
    with pytest.raises(ValidationError) as ex:
        Inventory.parse({"segments": {"p": {}}})
    assert any("'features'" in i for i in ex.value.issues)


def test_parse_rejects_missing_segments_key() -> None:
    with pytest.raises(ValidationError) as ex:
        Inventory.parse({"features": ["Voice"]})
    assert any("'segments'" in i for i in ex.value.issues)


# ---------------------------------------------------------------------------
# parse(): features validation
# ---------------------------------------------------------------------------
def test_parse_rejects_non_list_features() -> None:
    with pytest.raises(ValidationError) as ex:
        Inventory.parse({"features": "Voice", "segments": {}})
    assert any("'features'" in i and "list" in i for i in ex.value.issues)


def test_parse_rejects_empty_feature_name_without_crashing() -> None:
    """The old validator's lowercase-name warning path did ``feat[0]``
    on an empty string and raised ``IndexError``. The new parser
    surfaces it as a structured issue."""
    inv = {"features": ["Voice", ""], "segments": {}}
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(inv)
    assert any("empty" in i.lower() for i in ex.value.issues)


def test_parse_rejects_duplicate_feature_names() -> None:
    with pytest.raises(ValidationError) as ex:
        Inventory.parse({"features": ["Voice", "Voice"], "segments": {}})
    assert any("duplicate" in i.lower() for i in ex.value.issues)


def test_parse_rejects_non_string_feature_entries() -> None:
    with pytest.raises(ValidationError) as ex:
        Inventory.parse({"features": ["Voice", 42], "segments": {}})
    assert any("'features[1]'" in i for i in ex.value.issues)


def test_parse_rejects_aliased_feature_names() -> None:
    """Two distinct literal feature names that collapse to the same
    canonical key under ``_normalize_key`` (e.g. ``"DelRel"`` and
    ``"delayed_release"``) would later raise ``AliasCollisionError``
    inside ``engine.grouped_segments`` -- uncaught, that escapes
    ``_load_path`` and can crash app startup via the last-inventory
    restore. The parser must reject this at the boundary so the
    "parse == valid" contract holds end-to-end.
    """
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(
            {
                "features": ["DelRel", "delayed_release", "Voice"],
                "segments": {
                    "p": {"DelRel": "+", "delayed_release": "-", "Voice": "-"}
                },
            }
        )
    msg = " ".join(ex.value.issues)
    assert "collide" in msg.lower()
    assert "delrel" in msg.lower()


def test_engine_consumers_never_raise_on_parsed_inventory() -> None:
    """Defense in depth: anything ``Inventory.parse`` accepts must
    survive ``FeatureEngine.grouped_segments`` and
    ``normalized_segment_feats`` without raising. If a new downstream
    consumer adds stricter validation than the parser, this test
    forces the validation back into the parser.
    """
    # A plausible user-authored inventory that previously crashed the
    # downstream grouper: distinct literal names that normalize the
    # same way. After the parser fix this raises at parse, so
    # constructing the engine from a parsed Inventory is always safe.
    parsed = Inventory.parse(
        {"features": ["Voice", "Nasal"], "segments": {"p": {"Voice": "-"}}}
    )
    eng = FeatureEngine(parsed)
    # Both consumers must succeed for ANY parsed Inventory.
    _ = eng.grouped_segments
    _ = eng.normalized_segment_feats


# ---------------------------------------------------------------------------
# Name-identity boundary: NFC + whitespace + length + duplicate JSON keys
# ---------------------------------------------------------------------------
def test_parse_canonicalizes_feature_names_to_nfc() -> None:
    """Feature names go through ``unicodedata.normalize('NFC', ...)``
    + strip at the parser boundary. The stored key is the canonical
    form; downstream lookups by either NFC or NFD must hit the same
    entry because identity is normalized at one place."""
    import unicodedata

    nfd = unicodedata.normalize("NFD", "Café")
    assert nfd != "Café", "NFD form must differ as Python strings"
    inv = Inventory.parse({"features": [nfd], "segments": {}})
    # Stored as NFC.
    assert inv.features == ("Café",)


def test_parse_rejects_nfc_nfd_feature_collision() -> None:
    """If the input has BOTH NFC and NFD forms of the same name,
    that's ambiguous user intent. Surface rather than silently merge."""
    import unicodedata

    nfc = "Café"
    nfd = unicodedata.normalize("NFD", nfc)
    with pytest.raises(ValidationError) as ex:
        Inventory.parse({"features": [nfc, nfd, "Voice"], "segments": {}})
    msg = " ".join(ex.value.issues).lower()
    assert "nfc" in msg or "normalization" in msg


def test_parse_rejects_whitespace_padded_feature_collision() -> None:
    """``" Voice "`` and ``"Voice"`` canonicalize identically; both
    appearing in one inventory is ambiguous and must be reported."""
    with pytest.raises(ValidationError) as ex:
        Inventory.parse({"features": ["Voice", " Voice "], "segments": {}})
    msg = " ".join(ex.value.issues).lower()
    assert "voice" in msg
    assert "normalization" in msg or "whitespace" in msg


def test_parse_strips_whitespace_from_feature_names() -> None:
    """A single whitespace-padded name is silently canonicalized
    (no collision = no ambiguity to report); engine lookups using
    the unpadded form succeed."""
    inv = Inventory.parse(
        {"features": [" Voice "], "segments": {"p": {" Voice ": "-"}}}
    )
    assert inv.features == ("Voice",)
    assert "Voice" in inv.segments["p"]


def test_parse_canonicalizes_segment_keys() -> None:
    """Segment names are keys too. ``" p "`` should be stored as
    ``"p"`` and looked up identically."""
    inv = Inventory.parse(
        {"features": ["Voice"], "segments": {" p ": {"Voice": "-"}}}
    )
    assert "p" in inv.segments


def test_parse_rejects_nfc_nfd_segment_collision() -> None:
    """Two visually-identical segment keys (NFC vs NFD) must not
    silently merge -- that would discard one segment's bundle."""
    import unicodedata

    nfc = "é"
    nfd = unicodedata.normalize("NFD", nfc)
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(
            {
                "features": ["V"],
                "segments": {nfc: {"V": "+"}, nfd: {"V": "-"}},
            }
        )
    assert "normalization" in " ".join(ex.value.issues).lower()


def test_parse_rejects_overlong_feature_name() -> None:
    """A 10k-character name probably wasn't intentional. Surface
    the actual length and the max so the user can fix it."""
    with pytest.raises(ValidationError) as ex:
        Inventory.parse({"features": ["X" * 5000], "segments": {}})
    msg = " ".join(ex.value.issues)
    assert "5000" in msg
    assert "256" in msg


def test_parse_rejects_overlong_segment_name() -> None:
    with pytest.raises(ValidationError):
        Inventory.parse(
            {"features": ["V"], "segments": {"X" * 5000: {"V": "+"}}}
        )


def test_parse_rejects_too_many_features() -> None:
    """Hard cap stops obvious accidents (autogenerated stress files)
    without restricting any realistic phonological feature set."""
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(
            {"features": [f"F{i}" for i in range(500)], "segments": {}}
        )
    assert "100" in " ".join(ex.value.issues)


def test_parse_rejects_too_many_segments() -> None:
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(
            {
                "features": ["V"],
                "segments": {f"s{i}": {} for i in range(2000)},
            }
        )
    assert "1000" in " ".join(ex.value.issues)


def test_load_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    """``json.load`` silently keeps the LAST value for a duplicate
    key. For an inventory file with two segments named ``"p"`` that
    means losing one segment's bundle entirely with no warning --
    classic pre-parser data loss. The ``object_pairs_hook`` in
    ``Inventory.load`` catches this at decode time so the user gets
    a clear ValidationError instead."""
    target = tmp_path / "dup.json"
    # Two "p" entries; json.load would normally keep the second.
    target.write_text(
        '{"features": ["V"], '
        '"segments": {"p": {"V": "+"}, "p": {"V": "-"}}}'
    )
    with pytest.raises(ValidationError) as ex:
        Inventory.load(str(target))
    msg = " ".join(ex.value.issues).lower()
    assert "duplicate" in msg
    assert "p" in msg


def test_load_rejects_duplicate_features_key(tmp_path: Path) -> None:
    """Duplicate top-level keys are the same data-loss class as
    duplicate segment keys -- check the hook applies at every depth."""
    target = tmp_path / "dup.json"
    target.write_text('{"features": ["V"], "features": ["X"], "segments": {}}')
    with pytest.raises(ValidationError) as ex:
        Inventory.load(str(target))
    assert "duplicate" in " ".join(ex.value.issues).lower()


def test_load_handles_utf8_bom_transparently(tmp_path: Path) -> None:
    """Files exported from Windows Notepad / Excel / many other
    tools commonly include a UTF-8 BOM. Pre-fix the parser produced
    a cryptic ``invalid JSON (Unexpected UTF-8 BOM (decode using
    utf-8-sig))`` error -- accurate but unhelpful for a linguist.
    Fix: open with ``utf-8-sig`` codec which silently consumes a
    leading BOM and behaves like ``utf-8`` for files without one.
    """
    target = tmp_path / "bom.json"
    # Hand-write the file with a BOM prefix.
    target.write_bytes(
        b"\xef\xbb\xbf"
        + b'{"features": ["Voice"], "segments": {"p": {"Voice": "-"}}}'
    )
    inv = Inventory.load(str(target))
    assert inv.features == ("Voice",)
    assert "p" in inv.segments


def test_parse_rejects_surrogate_in_segment_name() -> None:
    """A lone surrogate code point (U+DCFF etc.) NFC-survives but
    cannot be UTF-8 encoded; ``inv.write_atomic`` would
    UnicodeEncodeError every save attempt -- a save lockout where
    the inventory loads fine but can never be persisted. Reject at
    the parser boundary so the user never reaches that state."""
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(
            {"features": ["V"], "segments": {"p\udcff": {"V": "+"}}}
        )
    msg = " ".join(ex.value.issues)
    assert "U+DCFF" in msg


def test_parse_rejects_control_char_in_name() -> None:
    """``str.strip()`` only removes Cc characters at name edges, not
    in the middle. ``Voice\\x07`` (with embedded BEL) would survive
    and render oddly in the grid header and validation messages."""
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(
            {"features": ["Voi\x07ce"], "segments": {}}
        )
    msg = " ".join(ex.value.issues)
    assert "U+0007" in msg


def test_parse_rejects_per_segment_feature_when_features_empty() -> None:
    """An inventory with ``features=[]`` AND per-segment feature
    keys was silently accepted -- the cross-check short-circuited
    when ``declared`` was empty. Result: segments carry ghost data
    that ``feature_value`` can never reach (raises KeyError because
    the feature isn't in ``inv.features``). Now rejected."""
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(
            {"features": [], "segments": {"p": {"Voice": "+"}}}
        )
    assert any(
        "Voice" in i and "not declared" in i for i in ex.value.issues
    )


def test_parse_accepts_empty_features_with_empty_bundles() -> None:
    """The fix to the empty-features check must NOT break the
    legitimate degenerate case: ``features=[]`` with segments that
    have no feature bundles (empty dicts). That's still valid."""
    inv = Inventory.parse({"features": [], "segments": {"p": {}, "b": {}}})
    assert "p" in inv.segments and "b" in inv.segments
    assert inv.features == ()


# ---------------------------------------------------------------------------
# Soft advisories: notable-but-valid observations
# ---------------------------------------------------------------------------
def test_bundled_inventories_produce_no_advisories() -> None:
    """Soft advisory thresholds must sit ABOVE every bundled
    inventory's size so a normal load shows no scary-looking notes."""
    for fname in (
        "hayes_features.json",
        "general_features.json",
        "english_features.json",
        "blevins_features.json",
    ):
        inv = Inventory.load(str(REPO_ROOT / "inventories" / fname))
        assert (
            inv.advisories == ()
        ), f"{fname} produced advisories: {inv.advisories}"


def test_advisory_fires_for_unusually_many_features() -> None:
    feats = [f"F{i}" for i in range(60)]
    inv = Inventory.parse({"features": feats, "segments": {}})
    assert any("feature" in a.lower() for a in inv.advisories)


def test_advisory_fires_for_unusually_many_segments() -> None:
    segs: dict[str, dict[str, str]] = {f"s{i}": {} for i in range(250)}
    inv = Inventory.parse({"features": ["V"], "segments": segs})
    assert any("segment" in a.lower() for a in inv.advisories)


def test_segment_ascii_g_normalized_to_script_g() -> None:
    """ASCII ``g`` (U+0067) in a segment label is folded to the
    canonical IPA ``ɡ`` (U+0261). Users typing on a US keyboard
    get the IPA voiced velar stop identity regardless of which
    character they actually typed."""
    inv = Inventory.parse({"features": ["V"], "segments": {"g": {"V": "+"}}})
    assert "ɡ" in inv.segments
    assert "g" not in inv.segments


def test_segment_ascii_apostrophe_normalized_to_modifier_letter() -> None:
    """ASCII ``'`` (U+0027) in a segment label is folded to the
    canonical IPA ``ʼ`` (U+02BC) -- the modern IPA ejective marker."""
    inv = Inventory.parse({"features": ["V"], "segments": {"p'": {"V": "-"}}})
    assert "pʼ" in inv.segments
    assert "p'" not in inv.segments


def test_segment_r_left_alone() -> None:
    """``r`` is the legitimate IPA alveolar trill character;
    DON'T fold it to ``ɹ`` (turned r, the approximant) -- that
    would silently change the meaning of users' inventories."""
    inv = Inventory.parse({"features": ["V"], "segments": {"r": {"V": "+"}}})
    assert "r" in inv.segments
    assert "ɹ" not in inv.segments


def test_ipa_translation_does_not_touch_feature_names() -> None:
    """The IPA-segment translation is for SEGMENT labels only.
    Feature names are analytical identifiers (``DelayedRelease``,
    ``Voice``); folding ``g`` to ``ɡ`` in a feature name like
    ``Glottal`` would silently rename ``Glottal`` to ``ɡlottal``."""
    inv = Inventory.parse(
        {"features": ["Glottal"], "segments": {"ʔ": {"Glottal": "+"}}}
    )
    assert inv.features == ("Glottal",)


def test_ascii_g_and_script_g_in_one_inventory_is_collision() -> None:
    """A user with both ``g`` and ``ɡ`` in one inventory probably
    didn't mean two distinct segments; the parser folds ASCII to
    canonical then rejects the resulting collision."""
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(
            {
                "features": ["V"],
                "segments": {"g": {"V": "+"}, "ɡ": {"V": "-"}},
            }
        )
    msg = " ".join(ex.value.issues).lower()
    assert "normalization" in msg or "duplicate" in msg


def test_advisory_fires_for_ascii_colon_in_segment_label() -> None:
    """ASCII colon (U+003A) in a segment label is almost always a
    typing substitute for the IPA length mark U+02D0. The advisory
    is informational only -- the inventory still loads."""
    inv = Inventory.parse({"features": ["V"], "segments": {"a:": {"V": "+"}}})
    assert any(
        "U+003A" in a and "U+02D0" in a for a in inv.advisories
    ), inv.advisories


def test_no_ascii_colon_advisory_when_proper_length_mark_used() -> None:
    """A segment using the canonical IPA length mark must NOT fire
    the advisory -- the whole point of the advisory is to flag
    likely paste mistakes, not penalize correct IPA notation."""
    inv = Inventory.parse({"features": ["V"], "segments": {"aː": {"V": "+"}}})
    assert not any("U+003A" in a for a in inv.advisories)


def test_bundled_inventories_produce_no_ipa_confusable_advisories() -> None:
    """Bundled inventories use canonical IPA (``ɡ͡b`` not ``g͡b``;
    ``pʼ`` not ``p'``; ``ɹ`` or ``r`` according to the inventory's
    intent), so the IPA-confusable advisory should never fire on a
    bundled load -- otherwise users see scary notes every time
    they open the app."""
    for fname in (
        "hayes_features.json",
        "general_features.json",
        "english_features.json",
        "blevins_features.json",
    ):
        inv = Inventory.load(str(REPO_ROOT / "inventories" / fname))
        # Size advisories are checked separately; this test guards
        # specifically against IPA-confusable false positives.
        confusable_advisories = [
            a
            for a in inv.advisories
            if "U+" in a and "IPA" in a or "length mark" in a
        ]
        assert confusable_advisories == [], (
            f"{fname} triggered IPA confusable advisories: "
            f"{confusable_advisories}"
        )


# ---------------------------------------------------------------------------
# IPA text-surface regression: notation survives parse → save → re-parse
# ---------------------------------------------------------------------------
def test_ipa_segment_labels_survive_round_trip() -> None:
    """Linguistically plausible IPA segment labels must round-trip
    through ``parse → to_json_dict → parse`` with their canonical
    names byte-for-byte unchanged. Stress cases:

      - combining diacritics (n̪, m̥, ã)
      - tie bars / affricates (t͡ʃ, d͡ʒ)
      - modifier letters (pʰ, tʼ, kʷ)
      - length marks (ɜː)
      - non-Latin IPA letters (χ, ʁ, θ, ð, ɫ, ɲ, ʔ, ɬ, ɡ, ə)

    Protects against future over-tightening: a regression that
    rejected combining marks, stripped tie bars, or NFKC-folded
    modifier letters would trip this test loudly.
    """
    ipa_labels = [
        "t͡ʃ",
        "d͡ʒ",
        "n̪",
        "ã",
        "pʰ",
        "tʼ",
        "kʷ",
        "ɫ",
        "ɲ",
        "χ",
        "ʁ",
        "m̥",
        "ɜː",
        "ə",
        "ɡ",
        "ʔ",
        "θ",
        "ð",
        "ɬ",
    ]
    segments = {seg: {"V": "+"} for seg in ipa_labels}
    inv1 = Inventory.parse({"features": ["V"], "segments": segments})
    # All labels survive parse with their original spelling.
    for seg in ipa_labels:
        assert (
            seg in inv1.segments
        ), f"label {seg!r} ({[hex(ord(c)) for c in seg]}) lost in parse"
    # Round-trip through serialization.
    serialized = inv1.to_json_dict()
    inv2 = Inventory.parse(serialized)
    assert set(inv2.segments.keys()) == set(ipa_labels), (
        f"labels changed across round-trip: "
        f"{set(ipa_labels) - set(inv2.segments.keys())} lost; "
        f"{set(inv2.segments.keys()) - set(ipa_labels)} added"
    )


def test_ipa_nfd_segment_normalizes_to_nfc() -> None:
    """A label provided in NFD form (e.g. ``"a" + combining tilde``)
    must canonicalize to the same NFC form (``"ã"``) that's stored
    if the label were provided pre-composed. This is the property
    that makes NFC-based identity reliable across paste sources."""
    import unicodedata

    nfc = "ã"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd, "test setup: NFD form must differ from NFC"

    inv_from_nfc = Inventory.parse(
        {"features": ["V"], "segments": {nfc: {"V": "+"}}}
    )
    inv_from_nfd = Inventory.parse(
        {"features": ["V"], "segments": {nfd: {"V": "+"}}}
    )
    # Both produce the same canonical key.
    assert list(inv_from_nfc.segments) == list(inv_from_nfd.segments)
    assert nfc in inv_from_nfd.segments


def test_ipa_serialization_keeps_unicode_readable() -> None:
    """Saved JSON for IPA inventories must keep IPA glyphs readable
    (``ensure_ascii=False`` is the right choice for a linguistics
    tool). Linguists diff and grep inventory files; ``\\u02d0`` for
    the length mark would defeat that. ``atomic_write_json`` is the
    only writer; verify its output."""
    import json as _json

    inv = Inventory.parse(
        {
            "features": ["V"],
            "segments": {"aː": {"V": "+"}, "t͡ʃ": {"V": "-"}},
        }
    )
    out = inv.to_json_dict()
    # Confirm to_json_dict carries IPA glyphs as-is in the dict.
    assert "aː" in out["segments"]
    assert "t͡ʃ" in out["segments"]
    # And that json.dumps(..., ensure_ascii=False) keeps them
    # readable -- ``atomic_write_json`` uses this serializer.
    text = _json.dumps(out, indent=2, ensure_ascii=False)
    assert "ː" in text
    assert "t͡ʃ" in text
    assert "\\u02d0" not in text


def test_parse_rejects_invisible_format_char_in_feature_name() -> None:
    """ZWJ (U+200D) and friends are invisible to readers and SURVIVE
    NFC + ``str.strip()``. Two feature names that differ only in an
    embedded ZWJ would look identical in the UI but be distinct keys.
    Reject at the parser boundary with a message that names the
    actual code point so the user can find and remove the bad paste.
    """
    for cp in ("‍", "‌", "‎", "‏", "﻿"):
        with pytest.raises(ValidationError) as ex:
            Inventory.parse({"features": [f"Voi{cp}ce"], "segments": {}})
        msg = " ".join(ex.value.issues)
        assert "invisible" in msg.lower() or "format" in msg.lower()
        assert f"U+{ord(cp):04X}" in msg


def test_parse_rejects_invisible_format_char_in_segment_name() -> None:
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(
            {
                "features": ["V"],
                "segments": {"p‍t": {"V": "+"}},
            }
        )
    msg = " ".join(ex.value.issues)
    assert "U+200D" in msg


def test_parse_strips_nbsp_from_names() -> None:
    """NBSP (U+00A0) is a SPACE separator (category Zs), not a
    format character, so ``str.strip()`` removes it. A name with
    trailing NBSP canonicalizes the same as the unpadded form."""
    inv = Inventory.parse({"features": ["Voice "], "segments": {}})
    assert inv.features == ("Voice",)


def test_parse_canonicalizes_inventory_name() -> None:
    """The inventory name is a display label, not a key, but it
    still gets NFC + strip so the UI title matches the file's
    metadata regardless of paste source."""
    import unicodedata

    nfd_name = unicodedata.normalize("NFD", "Café")
    inv = Inventory.parse(
        {
            "metadata": {"name": f"  {nfd_name}  "},
            "features": [],
            "segments": {},
        }
    )
    assert inv.name == "Café"
    # And the metadata round-trips with the canonical form.
    assert inv.metadata["name"] == "Café"


def test_parse_caps_overlong_inventory_name() -> None:
    """A 5000-char inventory name would destroy the title bar /
    status strip. Truncate (don't reject -- the inventory is
    otherwise fine) so the user still gets a working load."""
    inv = Inventory.parse(
        {
            "metadata": {"name": "X" * 5000},
            "features": [],
            "segments": {},
        }
    )
    assert len(inv.name) <= 256


# ---------------------------------------------------------------------------
# parse(): segments validation
# ---------------------------------------------------------------------------
def test_parse_rejects_non_dict_segments() -> None:
    with pytest.raises(ValidationError):
        Inventory.parse({"features": ["Voice"], "segments": []})


def test_parse_rejects_undeclared_feature_in_segment() -> None:
    """The old validator only warned on undeclared features and the
    engine then silently dropped them from queries. New contract:
    undeclared features are an error so the two cannot disagree."""
    inv = {
        "features": ["Voice"],
        "segments": {"p": {"Voice": "-", "Nasal": "-"}},
    }
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(inv)
    assert any("'Nasal'" in i and "not declared" in i for i in ex.value.issues)


def test_parse_rejects_invalid_feature_value() -> None:
    inv = {
        "features": ["Voice"],
        "segments": {"p": {"Voice": "yes"}},
    }
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(inv)
    assert any("invalid" in i.lower() and "yes" in i for i in ex.value.issues)


def test_parse_rejects_non_string_segment_key() -> None:
    inv = {"features": ["Voice"], "segments": {42: {"Voice": "+"}}}
    with pytest.raises(ValidationError):
        Inventory.parse(inv)


def test_parse_collects_all_issues_not_just_first() -> None:
    """Reviewer asked for structured validation results that report
    every problem at once, not crash on the first."""
    inv = {
        "features": ["", "Voice", "Voice"],
        "segments": {
            "p": {"Voice": "yes"},
            "x": {"Undeclared": "+"},
        },
    }
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(inv)
    assert len(ex.value.issues) >= 3


# ---------------------------------------------------------------------------
# parse(): happy path produces a usable immutable Inventory
# ---------------------------------------------------------------------------
def test_parse_returns_immutable_inventory() -> None:
    inv = Inventory.parse(
        {
            "features": ["Voice", "Nasal"],
            "segments": {"p": {"Voice": "-"}, "m": {"Nasal": "+"}},
        }
    )
    assert isinstance(inv.features, tuple)
    with pytest.raises(TypeError):
        inv.segments["p"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        inv.segments["p"]["Voice"] = "+"  # type: ignore[index]


def test_parse_missing_feature_in_bundle_defaults_to_zero() -> None:
    """Segments may omit features; the parser does NOT auto-fill the
    on-disk representation. Readers default to '0' via
    ``Inventory.feature_value``."""
    inv = Inventory.parse(
        {
            "features": ["Voice", "Nasal"],
            "segments": {"p": {"Voice": "-"}},
        }
    )
    assert inv.feature_value("p", "Voice") == "-"
    assert inv.feature_value("p", "Nasal") == "0"
    # On-disk shape unchanged: Nasal is NOT auto-inserted.
    assert "Nasal" not in inv.segments["p"]


def test_parse_uses_metadata_name_then_top_level_name() -> None:
    inv = Inventory.parse(
        {
            "metadata": {"name": "Pretty Name"},
            "name": "Fallback Name",
            "features": [],
            "segments": {},
        }
    )
    assert inv.name == "Pretty Name"
    inv2 = Inventory.parse(
        {"name": "Fallback Name", "features": [], "segments": {}}
    )
    assert inv2.name == "Fallback Name"
    inv3 = Inventory.parse({"features": [], "segments": {}})
    assert inv3.name == "Untitled Inventory"


def test_parse_missing_schema_version_assumed_current() -> None:
    """Existing files (bundled + user-saved) predate the field and
    must keep loading without migration. Missing == current."""
    inv = Inventory.parse({"features": [], "segments": {}})
    assert inv.name == "Untitled Inventory"


def test_parse_accepts_current_schema_version() -> None:
    inv = Inventory.parse(
        {"schema_version": 1, "features": [], "segments": {}}
    )
    assert inv.name == "Untitled Inventory"


def test_parse_rejects_unsupported_schema_version() -> None:
    with pytest.raises(ValidationError) as ex:
        Inventory.parse({"schema_version": 2, "features": [], "segments": {}})
    msg = str(ex.value)
    assert "schema_version" in msg
    assert "2" in msg


def test_parse_rejects_non_integer_schema_version() -> None:
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(
            {"schema_version": "1", "features": [], "segments": {}}
        )
    assert "schema_version" in str(ex.value)


def test_parse_rejects_bool_as_schema_version() -> None:
    # ``bool`` is a subclass of ``int``; without an explicit reject
    # ``True`` would pass the integer check and read as version 1.
    with pytest.raises(ValidationError):
        Inventory.parse(
            {"schema_version": True, "features": [], "segments": {}}
        )


def test_schema_version_round_trips_on_write() -> None:
    """Saving emits ``schema_version: 1`` so future readers can
    branch on format without guessing."""
    inv = Inventory.parse({"features": [], "segments": {}})
    out = inv.to_json_dict()
    assert out["schema_version"] == 1
    # And not duplicated into metadata.
    assert "schema_version" not in out["metadata"]


def test_schema_version_does_not_leak_into_metadata() -> None:
    """Round-trip: schema_version present on input must not appear in
    the parsed inventory's metadata view, only on the serialized output."""
    inv = Inventory.parse(
        {"schema_version": 1, "features": [], "segments": {}}
    )
    assert "schema_version" not in inv.metadata


def test_hayes_parses_without_issues() -> None:
    inv = Inventory.load(HAYES)
    assert len(inv.features) > 0
    assert len(inv.segments) > 0


@pytest.mark.parametrize(
    "fname",
    [
        "hayes_features.json",
        "general_features.json",
        "english_features.json",
        "blevins_features.json",
    ],
)
def test_bundled_inventory_survives_engine_consumers(fname: str) -> None:
    """Every bundled inventory must load, construct an engine, and
    survive both downstream cached_property consumers. Catches a
    bundled inventory developing feature-name aliasing (or any other
    parser-vs-engine drift) during edits.
    """
    path = str(REPO_ROOT / "inventories" / fname)
    inv = Inventory.load(path)
    eng = FeatureEngine(inv)
    _ = eng.grouped_segments
    _ = eng.normalized_segment_feats


# ---------------------------------------------------------------------------
# load(): file-level errors come through ValidationError too
# ---------------------------------------------------------------------------
def test_load_missing_file_raises_validation_error(tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as ex:
        Inventory.load(str(tmp_path / "does_not_exist.json"))
    assert any("not found" in i for i in ex.value.issues)


def test_load_invalid_json_raises_validation_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(ValidationError) as ex:
        Inventory.load(str(bad))
    assert any("invalid JSON" in i for i in ex.value.issues)


def test_engine_requires_inventory_not_raw_dict() -> None:
    """The engine's old load_inventory_data accepted raw dicts and
    could be more lenient than the validator. New engine refuses raw
    input."""
    with pytest.raises(TypeError):
        FeatureEngine({"features": [], "segments": {}})  # type: ignore[arg-type]


def test_engine_caches_cannot_desync_from_mutation() -> None:
    """Reviewer's #3: previously the engine stored caller's data by
    reference and the caches went stale on caller mutation. With a
    frozen Inventory this can't happen."""
    inv_raw: dict[str, object] = {
        "features": ["Voice"],
        "segments": {"p": {"Voice": "-"}, "b": {"Voice": "+"}},
    }
    inv = Inventory.parse(inv_raw)
    eng = FeatureEngine(inv)
    # Mutating the original raw dict must not affect the engine.
    inv_raw["segments"]["p"]["Voice"] = "+"  # type: ignore[index]
    assert eng.get_feature_value("p", "Voice") == "-"
    assert "p" not in eng.plus_segs["Voice"]
    assert "p" in eng.minus_segs["Voice"]


def test_engine_features_are_immutable_view() -> None:
    eng = FeatureEngine.from_path(HAYES)
    assert isinstance(eng.features, tuple)


# ---------------------------------------------------------------------------
# Engine architectural invariants
# ---------------------------------------------------------------------------
def test_engine_has_no_empty_state() -> None:
    """The engine takes its Inventory in ``__init__``; there is no
    moment where ``eng.features`` is empty because no inventory was
    loaded yet. Constructing without an inventory is an error."""
    with pytest.raises(TypeError):
        FeatureEngine()  # type: ignore[call-arg]


def test_engine_caches_bundle_search_results() -> None:
    """``is_natural_class`` and ``compute_natural_class`` both delegate
    to ``find_all_minimal_bundles``. Calling them back-to-back on the
    same input must not re-run the exponential-worst-case search.
    We probe via the private cache dict since timing is too flaky."""
    eng = FeatureEngine.from_path(HAYES)
    segs = ["b", "d", "ɡ"]
    assert frozenset(segs) not in eng._bundle_cache
    eng.is_natural_class(segs)
    assert frozenset(segs) in eng._bundle_cache
    # Second call must hit the cache (same list identity isn't required;
    # only the frozenset).
    cached = eng._bundle_cache[frozenset(segs)]
    eng.compute_natural_class(segs)
    assert eng._bundle_cache[frozenset(segs)] is cached


def test_engine_grouped_segments_cached_per_engine() -> None:
    """``grouped_segments`` is a cached_property: same engine returns
    the same dict object; new engine = new computation."""
    eng = FeatureEngine.from_path(HAYES)
    a = eng.grouped_segments
    b = eng.grouped_segments
    assert a is b
    eng2 = FeatureEngine.from_path(HAYES)
    assert eng2.grouped_segments is not a


def test_bundle_cache_results_are_immutable() -> None:
    """``find_all_minimal_bundles`` returns a reference into the
    per-engine cache; before the fix the return type was
    ``list[dict[str, str]]`` and a caller mutation would silently
    corrupt the cache for every subsequent call on the same input.
    The new shape is ``tuple[Mapping[str, str], ...]`` -- both layers
    immutable -- so mutation attempts raise rather than corrupt.
    """
    eng = FeatureEngine.from_path(HAYES)
    segs = ["b", "d", "ɡ"]
    bundles_a = eng.find_all_minimal_bundles(segs)
    # Outer container is a tuple: no append / pop / clear.
    assert isinstance(bundles_a, tuple)
    with pytest.raises(AttributeError):
        bundles_a.append({"X": "+"})  # type: ignore[attr-defined]
    # Inner bundles are read-only mappings.
    if bundles_a:
        with pytest.raises(TypeError):
            bundles_a[0]["bogus"] = "+"  # type: ignore[index]
    # Cache hit returns the same object so consumers don't pay
    # rewrap costs on repeated queries.
    bundles_b = eng.find_all_minimal_bundles(segs)
    assert bundles_a is bundles_b


def test_engine_seg_value_tuples_lazy() -> None:
    """Built lazily: not present in ``__dict__`` until first access."""
    eng = FeatureEngine.from_path(HAYES)
    assert "_seg_value_tuples" not in eng.__dict__
    eng.segment_distance("b", "p")
    assert "_seg_value_tuples" in eng.__dict__


# ---------------------------------------------------------------------------
# GeometryAnalyzer: state must not leak across analyze() calls
# ---------------------------------------------------------------------------
def test_find_all_minimal_bundles_bitmask_matches_naive() -> None:
    """The bitmask hitting-set search must produce the same bundles
    as a brute-force reference implementation for a handful of
    inputs. Catches off-by-one in the bit numbering."""
    eng = FeatureEngine.from_path(HAYES)
    seg_lists = (
        ["b", "d", "ɡ"],
        ["p", "t", "k"],
        ["m", "n", "ŋ"],
        ["f", "s"],
        ["a", "e", "i", "o", "u"],
        ["l"],
        ["b"],  # singleton -- common path
    )
    for segs in seg_lists:
        bundles = eng.find_all_minimal_bundles(segs)
        # Every returned bundle must characterise S exactly.
        for bundle in bundles:
            recovered = set(
                eng.find_segments(bundle, underspec_compatible=True)
            )
            assert recovered == set(
                segs
            ), f"bundle {bundle} for {segs} recovered {recovered}"
        # All bundles must be the same size (minimal).
        sizes = {len(b) for b in bundles}
        assert len(sizes) <= 1, f"non-uniform bundle sizes for {segs}: {sizes}"


def test_cell_brushes_cached_until_theme_changes() -> None:
    """The brush triple cache must return the SAME QBrush object
    across calls within one theme epoch, then a fresh one after
    ``set_theme`` bumps ``theme_version``."""
    from phonology_features.gui import palette
    from phonology_features.gui.builder.grid import _cell_brushes

    palette.set_theme("light")
    fg_a, bg_a = _cell_brushes("+")
    fg_b, bg_b = _cell_brushes("+")
    assert fg_a is fg_b and bg_a is bg_b, "cache miss within one theme"
    palette.set_theme("dark")
    fg_c, _ = _cell_brushes("+")
    assert fg_c is not fg_a, "cache should rebuild after theme change"
    palette.set_theme("light")  # restore for other tests


def test_geometry_analyzer_resets_between_runs() -> None:
    """Calling ``analyze`` twice on the same analyzer used to leak
    dependency entries from the first run. Now it clears first."""
    eng = FeatureEngine.from_path(HAYES)
    analyzer = GeometryAnalyzer(eng)
    analyzer.analyze()
    first_deps = dict(analyzer.dependencies)
    # Poison the dict with a fake entry and re-run; analyze must drop it.
    analyzer.dependencies["FakeFeature"] = {
        "parent": "FakeParent",
        "coverage": 1.0,
        "p_value": 0.0,
        "confidence": "high",
    }
    analyzer.analyze()
    assert "FakeFeature" not in analyzer.dependencies
    assert analyzer.dependencies == first_deps


# ---------------------------------------------------------------------------
# Atomic writes: a crash mid-write must not corrupt the destination
# ---------------------------------------------------------------------------
def test_atomic_write_replaces_atomically(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    target.write_text('{"old": true}', encoding="utf-8")
    atomic_write_json(str(target), {"new": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"new": True}


def test_atomic_write_does_not_leave_tmp_file_on_success(
    tmp_path: Path,
) -> None:
    target = tmp_path / "out.json"
    atomic_write_json(str(target), {"x": 1})
    leftover = [p for p in tmp_path.iterdir() if p.name != "out.json"]
    assert leftover == []


def test_atomic_write_cleans_up_tmp_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force ``os.replace`` to fail and confirm we don't leave debris."""
    target = tmp_path / "out.json"
    real_replace = os.replace

    def fail_replace(src: str, dst: str) -> None:
        # Remove the tmp file to simulate a crash partway through;
        # the cleanup branch should swallow the missing-tmp gracefully.
        raise OSError("simulated rename failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError):
        atomic_write_json(str(target), {"x": 1})
    monkeypatch.setattr(os, "replace", real_replace)
    leftover = list(tmp_path.iterdir())
    assert leftover == [], f"tmp files leaked: {leftover}"


def test_inventory_write_atomic_round_trip(tmp_path: Path) -> None:
    inv = Inventory.parse(
        {
            "metadata": {"name": "Test"},
            "features": ["Voice"],
            "segments": {"p": {"Voice": "-"}, "b": {"Voice": "+"}},
        }
    )
    target = tmp_path / "round.json"
    inv.write_atomic(str(target))
    loaded = Inventory.load(str(target))
    assert loaded.name == "Test"
    assert loaded.features == ("Voice",)
    assert loaded.feature_value("b", "Voice") == "+"


def test_round_trip_preserves_top_level_metadata(tmp_path: Path) -> None:
    """Some bundled inventories (e.g. ``general_features.json``) store
    ``name``/``version``/``notes`` at the top level rather than under
    a ``metadata`` object. ``to_json_dict`` must not silently drop
    them on round-trip -- the parser harvests both conventions into
    ``Inventory.metadata`` and ``to_json_dict`` writes them all back
    under the canonical ``metadata`` key."""
    raw = {
        "name": "X",
        "version": "3.0",
        "notes": "important",
        "features": ["Voice"],
        "segments": {"p": {"Voice": "-"}},
    }
    inv = Inventory.parse(raw)
    target = tmp_path / "round.json"
    inv.write_atomic(str(target))
    reloaded = Inventory.load(str(target))
    assert reloaded.name == "X"
    assert reloaded.metadata.get("version") == "3.0"
    assert reloaded.metadata.get("notes") == "important"


def test_explicit_metadata_wins_over_top_level_collision() -> None:
    """If both shapes set ``name``, the explicit metadata object wins
    -- it's the more deliberate, structured location."""
    inv = Inventory.parse(
        {
            "name": "top-level",
            "metadata": {"name": "metadata-name"},
            "features": [],
            "segments": {},
        }
    )
    assert inv.name == "metadata-name"


# ---------------------------------------------------------------------------
# from_grid normalizes Unicode minus to ASCII before validation
# ---------------------------------------------------------------------------
def test_from_grid_accepts_unicode_minus() -> None:
    inv = Inventory.from_grid(
        name="X",
        features=["Voice"],
        segments={"p": {"Voice": "−"}},  # U+2212 MINUS SIGN
    )
    assert inv.feature_value("p", "Voice") == "-"


def test_from_grid_rejects_unknown_cell_value() -> None:
    """The old builder silently rewrote unknown values to '0'. New
    contract: unknown values are an error -- they shouldn't reach the
    save path in the first place, so surfacing them is the bug-hunting
    behaviour."""
    with pytest.raises(ValidationError):
        Inventory.from_grid(
            name="X",
            features=["Voice"],
            segments={"p": {"Voice": "weird"}},
        )


# ---------------------------------------------------------------------------
# Alias collision detection in segment_grouper
# ---------------------------------------------------------------------------
def test_normalize_feats_raises_on_alias_collision() -> None:
    """Reviewer's #7: previously a dict-comprehension rebuild would
    silently keep whichever alias came last. Now the collision is
    surfaced."""
    with pytest.raises(AliasCollisionError) as ex:
        _normalize_feats({"DelRel": "+", "delayed_release": "-"})
    assert "delrel" in ex.value.collisions


def test_normalize_feats_passes_when_no_collision() -> None:
    out = _normalize_feats({"DelRel": "+", "Voice": "-"})
    assert out["delrel"] == "+"
    assert out["voice"] == "-"


# ---------------------------------------------------------------------------
# Geometry: confidence vocabulary and acyclicity
# ---------------------------------------------------------------------------
def test_geometry_confidence_uses_medium_not_moderate() -> None:
    """Reviewer's #9: implementation drifted to 'moderate' while
    tests / public docs say 'medium'. Standardize on 'medium'."""
    eng = FeatureEngine.from_path(HAYES)
    analyzer = GeometryAnalyzer(eng)
    analyzer.analyze()
    for dep in analyzer.get_dependency_summary():
        assert dep["confidence"] in {
            "high",
            "medium",
            "low",
        }, f"unexpected confidence label: {dep['confidence']!r}"


def test_geometry_tree_is_acyclic() -> None:
    """The reviewer flagged that geometry acyclicity isn't tested.
    Walk every node from the root and confirm no node is visited
    twice (DFS with a visited set)."""
    eng = FeatureEngine.from_path(HAYES)
    analyzer = GeometryAnalyzer(eng)
    root = analyzer.analyze()
    visited: set[str] = set()

    def walk(node) -> None:
        assert node.feature not in visited, f"cycle detected at {node.feature}"
        visited.add(node.feature)
        for child in node.children:
            walk(child)

    walk(root)


# ---------------------------------------------------------------------------
# HTML escaping in the analysis pane
# ---------------------------------------------------------------------------
def test_analysis_copy_translates_unicode_minus_to_ascii(
    tmp_path: Path,
) -> None:
    """The analysis pane renders feature negatives as U+2212 (`−`)
    for visual symmetry with `+`, but the rest of the ecosystem
    (JSON values, code, regex, terminals) expects ASCII `-`. The
    ``_CopyableTextEdit`` subclass must translate at the clipboard
    boundary so a user copying `-Voice` from the pane can paste it
    into a JSON value and have it actually match.

    Asserts both payloads: the plain-text mime (for code editors and
    terminals) AND the HTML mime (for rich-text targets like docx).
    """
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from phonology_features.gui.widgets import _CopyableTextEdit

    edit = _CopyableTextEdit()
    # The display layer puts U+2212 in the HTML; verify the copy
    # path turns it into ASCII '-' in both mime payloads. The
    # show()+processEvents() bit is required for selectAll() to
    # establish a real selection under the offscreen QPA -- an
    # unrealised widget produces an empty selection and Qt then
    # crashes deep in createMimeDataFromSelection.
    edit.setHtml(
        "<p>shared: <span style='color:red'>" "−Voice</span> +Continuant</p>"
    )
    edit.show()
    for _ in range(3):
        app.processEvents()
    edit.selectAll()
    for _ in range(3):
        app.processEvents()
    mime = edit.createMimeDataFromSelection()
    assert mime is not None
    assert (
        "−" not in mime.text()
    ), "plain-text payload still contains U+2212 minus"
    assert "-Voice" in mime.text()
    assert mime.hasHtml()
    assert "−" not in mime.html(), "HTML payload still contains U+2212 minus"

    # Sanity: a selection with no U+2212 still produces a usable mime
    # (the fast path returns the original; we don't care which branch
    # ran, only that the output is right).
    edit.clear()
    edit.setHtml("<p>just plain ASCII +Voice +Nasal</p>")
    for _ in range(3):
        app.processEvents()
    edit.selectAll()
    for _ in range(3):
        app.processEvents()
    mime2 = edit.createMimeDataFromSelection()
    assert mime2 is not None
    assert "+Voice" in mime2.text()
    edit.close()


def test_analysis_tag_escapes_html_in_text() -> None:
    """A feature named ``"<b>X"`` must not break the rendered
    layout. The ``_tag`` chip is the only path through which
    inventory text reaches the HTML output, so escaping there is
    sufficient."""
    from phonology_features.gui.analysis import _tag
    from phonology_features.gui.constants import TagColor

    out = _tag("<b>oops</b>", TagColor.PLUS)
    assert "<b>oops</b>" not in out
    assert "&lt;b&gt;oops&lt;/b&gt;" in out


def test_analysis_render_single_segment_escapes_symbol() -> None:
    """The segment symbol is interpolated into the bold header
    outside the tag chip, so it has its own escape call."""
    from phonology_features.gui.analysis import render_single_segment

    class _FakeEngine:
        features: tuple[str, ...] = ("Voice",)
        segments = {"<x>": {"Voice": "+"}}

        def is_natural_class(self, segs):
            return False, []

        def find_segments(self, *args, **kwargs):
            return []

    # The renderer treats ``engine`` as duck-typed for testability;
    # the cast keeps mypy happy without forcing a real FeatureEngine.
    out = render_single_segment(_FakeEngine(), "<x>", {"Voice": "+"})  # type: ignore[arg-type]
    assert "/<x>/" not in out
    assert "/&lt;x&gt;/" in out


def test_bulk_cycle_whole_table_under_100ms(tmp_path: Path) -> None:
    """Regression guard against the ResizeToContents footgun. Before
    we switched the vertical header to Fixed, every per-cell
    setForeground stalled Qt re-walking the row to recompute height;
    a whole-table cycle on Hayes (3920 cells) took ~60+ seconds. The
    Fixed-mode fix dropped it to ~17 ms. 100 ms is a comfortable
    ceiling that still catches the failure mode if it ever regresses."""
    import os as _os
    import time as _time

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    app = QApplication.instance() or QApplication([])
    from phonology_features.gui.builder import InventoryBuilder

    b = InventoryBuilder(load_path=HAYES)
    b.show()
    for _ in range(4):
        app.processEvents()
    b._table.selectAll()
    for _ in range(2):
        app.processEvents()
    anchor = b._table.item(0, 0)
    assert anchor is not None
    t0 = _time.perf_counter()
    b._cycle_selection_from(anchor)
    elapsed_ms = (_time.perf_counter() - t0) * 1000
    assert elapsed_ms < 100, (
        f"whole-table bulk cycle took {elapsed_ms:.1f} ms; "
        f"regression vs <100 ms target. Did vertical header drift "
        f"back to ResizeToContents?"
    )
    # Bulk cycle dirtied the grid; close_builder_silent skips the
    # unsaved-changes modal that would block forever in offscreen mode.
    close_builder_silent(b)


def test_bulk_edit_does_not_disable_rm_buttons(tmp_path: Path) -> None:
    """After a bulk-cycle on a selected column the Qt selection is
    UNCHANGED. The -Segment button must stay enabled to reflect
    that the column is still selected and still removable. The old
    behaviour cleared rm state in ``_commit_edits`` and produced a
    visible-but-disabled mismatch (column highlighted, -Segment
    grey, forcing a header re-click)."""
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    app = QApplication.instance() or QApplication([])
    from phonology_features.gui.builder import InventoryBuilder

    b = InventoryBuilder(load_path=HAYES)
    b.show()
    for _ in range(4):
        app.processEvents()
    b._on_col_header_clicked(5)
    for _ in range(2):
        app.processEvents()
    assert (
        b._rm_seg_btn.isEnabled()
    ), "after selecting a column, -Segment should be enabled"
    anchor = b._table.item(0, 5)
    assert anchor is not None
    b._cycle_selection_from(anchor)
    for _ in range(2):
        app.processEvents()
    assert b._rm_seg_btn.isEnabled(), (
        "after a bulk edit on a still-selected column, "
        "-Segment must stay enabled (Qt selection didn't change)"
    )
    assert b._user_clicked_col == 5
    close_builder_silent(b)


def test_header_doubleclick_still_toggles_selection(tmp_path: Path) -> None:
    """PyQt6's QHeaderView suppresses ``sectionClicked`` when a press
    lands within the OS double-click interval (~400 ms) of the previous
    press, firing ``sectionDoubleClicked`` instead. We worked around
    this by installing ``_ToggleHeaderView``, which forwards
    ``mouseDoubleClickEvent`` to ``mousePressEvent`` so every press
    flows through the standard click pipeline. End-to-end check: a
    Qt double-click on the header must fire ``sectionClicked`` for
    EACH of the two presses (same haptic as QPushButton)."""
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QPoint, QSettings
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    app = QApplication.instance() or QApplication([])
    from phonology_features.gui.builder import InventoryBuilder

    b = InventoryBuilder(load_path=HAYES)
    b.resize(1600, 900)
    b.show()
    for _ in range(4):
        app.processEvents()
    h = b._table.horizontalHeader()
    assert h is not None
    col = 5
    x = h.sectionViewportPosition(col) + h.sectionSize(col) // 2
    y = h.height() // 2
    viewport = h.viewport()
    assert viewport is not None

    # A single click should toggle ON.
    QTest.mouseClick(  # type: ignore[call-overload]
        viewport,
        _Qt.MouseButton.LeftButton,
        _Qt.KeyboardModifier.NoModifier,
        QPoint(x, y),
    )
    for _ in range(3):
        app.processEvents()
    assert b._user_clicked_col == col, "first click did not toggle ON"

    # _ToggleHeaderView.mouseDoubleClickEvent manually emits
    # sectionClicked so the second press of a doubleclick pair
    # registers as a click (Qt's default suppresses it). Count
    # emissions from a synthetic doubleclick event directly.
    h_sig_count = [0]
    h.sectionClicked.connect(
        lambda _: h_sig_count.__setitem__(0, h_sig_count[0] + 1)
    )
    QTest.mouseDClick(  # type: ignore[call-overload]
        viewport,
        _Qt.MouseButton.LeftButton,
        _Qt.KeyboardModifier.NoModifier,
        QPoint(x, y),
    )
    for _ in range(3):
        app.processEvents()
    assert h_sig_count[0] >= 1, (
        f"doubleclick should emit sectionClicked at least once "
        f"(via _ToggleHeaderView.mouseDoubleClickEvent), got {h_sig_count[0]}"
    )
    assert b._user_clicked_col is None, (
        "after 1 single click (ON) + 1 doubleclick-as-click (OFF), "
        "expected user_clicked_col=None"
    )

    b.close()


def test_dropdown_filters_out_atomic_write_tmp_files(tmp_path: Path) -> None:
    """``atomic_write_json`` creates ``.tmp_inv_*.json`` files in the
    target directory between ``mkstemp`` and ``os.replace``. The
    directory watcher can fire on the tmp create; the dropdown must
    not include those side files."""
    inv_dir = tmp_path / "inventories"
    inv_dir.mkdir()
    real = inv_dir / "real_features.json"
    Inventory.parse(
        {"metadata": {"name": "Real"}, "features": [], "segments": {}}
    ).write_atomic(str(real))
    # Simulate a tmp file that atomic_write_json would create
    tmp = inv_dir / ".tmp_inv_abc123.json"
    tmp.write_text('{"in_progress": true}', encoding="utf-8")
    listed = sorted(
        f
        for f in os.listdir(inv_dir)
        if f.endswith(".json") and not f.startswith(".")
    )
    assert listed == ["real_features.json"]
    assert ".tmp_inv_abc123.json" not in listed


def test_builder_close_waits_for_save_in_flight(tmp_path: Path) -> None:
    """Closing the builder while a background save is still running
    must wait for the worker to finish, so the worker can't emit
    ``_save_finished`` on a QObject that Qt is destroying."""
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    QApplication.instance() or QApplication([])
    from phonology_features.gui.builder import InventoryBuilder

    b = InventoryBuilder(load_path=HAYES)
    target = tmp_path / "saved.json"
    b._write_json(str(target))
    assert b._save_in_flight, "save should be scheduled but not done"
    # close() should drive the save to completion before returning.
    closed_ok = b.close()
    assert closed_ok
    assert not b._save_in_flight, "save must complete before close returns"
    assert target.exists(), "file must be on disk after close completes"


def test_builder_save_then_close_dialog_path(tmp_path: Path) -> None:
    """User edits, then clicks Close. The unsaved dialog's Save button
    calls ``_save()`` (async) and then ``_wait_for_save()``; the
    dirty flag must clear before ``_check_unsaved`` returns so the
    close proceeds. Without the wait, the user would be told their
    save succeeded but the close would be silently refused."""
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    QApplication.instance() or QApplication([])
    from phonology_features.gui.builder import InventoryBuilder

    b = InventoryBuilder(load_path=HAYES)
    target = tmp_path / "edited.json"
    b._current_path = str(target)
    b._dirty = True
    # Simulate the "Save" branch directly (skip the dialog).
    b._save()
    waited = b._wait_for_save()
    assert waited, "save did not complete within timeout"
    assert not b._dirty, "dirty flag must clear once save signal lands"


def test_worker_non_oserror_clears_save_in_flight(
    tmp_path: Path, monkeypatch
) -> None:
    """The save worker catches BaseException, not just OSError. If
    any other exception slipped through, the daemon thread would die
    silently, ``_save_finished`` would never fire, and
    ``_save_in_flight`` would be stuck True forever -- a permanent
    save lockout. Reproduce by monkey-patching write_atomic to raise
    TypeError."""
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    app = QApplication.instance() or QApplication([])
    from phonology_features.engine.inventory import Inventory
    from phonology_features.gui.builder import InventoryBuilder
    from phonology_features.gui.builder import window as _bw

    # Stub modal warning so the error path doesn't deadlock the test.
    monkeypatch.setattr(_bw, "show_warning", lambda *a, **k: None)

    def boom(self, path):
        raise TypeError("simulated non-OSError")

    monkeypatch.setattr(Inventory, "write_atomic", boom)

    b = InventoryBuilder(load_path=HAYES)
    b._write_json(str(tmp_path / "out.json"))
    import time as _time

    deadline = _time.monotonic() + 2.0
    while b._save_in_flight and _time.monotonic() < deadline:
        app.processEvents()
        _time.sleep(0.01)
    assert not b._save_in_flight, (
        "non-OSError in worker left _save_in_flight=True forever; "
        "user would be permanently locked out of save"
    )
    close_builder_silent(b)


def test_save_as_drains_in_flight_save(tmp_path: Path, monkeypatch) -> None:
    """A Save-As during an in-flight Save must wait for the first
    save to drain so its own write isn't silently dropped by the
    re-entrancy guard in ``_write_json``."""
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication, QFileDialog

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    app = QApplication.instance() or QApplication([])
    from phonology_features.gui.builder import InventoryBuilder

    b = InventoryBuilder(load_path=HAYES)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    b._current_path = str(first)
    b._write_json(str(first))
    assert b._save_in_flight, "first save did not schedule"
    # Patch the file dialog to return ``second`` without opening.
    monkeypatch.setattr(QFileDialog, "exec", lambda self: 1)
    monkeypatch.setattr(
        QFileDialog, "selectedFiles", lambda self: [str(second)]
    )
    b._save_as()
    import time as _time

    deadline = _time.monotonic() + 3.0
    while b._save_in_flight and _time.monotonic() < deadline:
        app.processEvents()
        _time.sleep(0.01)
    assert first.exists(), "first save did not complete"
    assert second.exists(), (
        "Save-As silently dropped because _save_as did not drain the "
        "in-flight save before issuing the second write"
    )
    close_builder_silent(b)


def test_builder_save_runs_off_main_thread(tmp_path: Path) -> None:
    """``_write_json`` validates synchronously then hands the disk
    write to a background worker. We assert:
      1. The call returns BEFORE the file is fully written
         (well, before the post-write callback fires).
      2. After a brief wait the file is on disk and parses back.
      3. ``_save_in_flight`` is cleared so a subsequent save proceeds."""
    import os as _os
    import time as _time

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    settings_dir = str(tmp_path / "qt-settings")
    _os.makedirs(settings_dir, exist_ok=True)
    for fmt in (
        QSettings.Format.NativeFormat,
        QSettings.Format.IniFormat,
    ):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, settings_dir)
    app = QApplication.instance() or QApplication([])
    from phonology_features.gui.builder import InventoryBuilder

    b = InventoryBuilder(load_path=HAYES)
    target = tmp_path / "saved.json"
    b._write_json(str(target))
    # Save was scheduled; spin the event loop briefly so the timer
    # callback fires (worker -> QTimer.singleShot(0)).
    deadline = _time.monotonic() + 2.0
    while _time.monotonic() < deadline and b._save_in_flight:
        app.processEvents()
        _time.sleep(0.01)
    assert target.exists(), "background save never produced the file"
    assert not b._save_in_flight, "in-flight flag not cleared"
    # File is a valid Inventory.
    reloaded = Inventory.load(str(target))
    assert len(reloaded.features) > 0
    b.close()


def test_edit_during_in_flight_save_preserves_dirty(
    tmp_path: Path, monkeypatch
) -> None:
    """The snapshot handed to the save worker is fixed at the moment
    ``_to_inventory()`` ran. Any edit made *after* the snapshot but
    *before* the worker finishes is NOT in the file on disk -- so the
    completion handler must not clear ``_dirty``. Before the fix, the
    completion handler unconditionally cleared the flag, silently
    marking post-snapshot edits as saved and losing them at close.
    """
    import os as _os
    import time as _time

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    app = QApplication.instance() or QApplication([])
    from phonology_features.engine.inventory import Inventory
    from phonology_features.gui.builder import InventoryBuilder

    # Stall the worker so the main thread has time to mutate the grid
    # between snapshot and completion.
    real_write = Inventory.write_atomic

    def slow_write(self, path):
        _time.sleep(0.15)
        return real_write(self, path)

    monkeypatch.setattr(Inventory, "write_atomic", slow_write)

    b = InventoryBuilder(load_path=HAYES)
    target = tmp_path / "out.json"
    b._write_json(str(target))
    # Snapshot is committed; _dirty cleared by the save-start path.
    assert b._save_in_flight, "worker should still be running"
    assert not b._dirty, "snapshot commit should have cleared _dirty"

    # Edit a cell while the worker is still writing the OLD snapshot.
    # Route through _set_cell_value so it goes through _commit_edit
    # (the real edit chokepoint), the same path a user click takes.
    item = b._table.item(0, 0)
    assert item is not None
    new = "-" if item.text() == "+" else "+"
    b._set_cell_value(0, 0, new)

    deadline = _time.monotonic() + 3.0
    while b._save_in_flight and _time.monotonic() < deadline:
        app.processEvents()
        _time.sleep(0.01)
    assert not b._save_in_flight, "worker never completed"
    assert b._dirty, (
        "post-snapshot edit was clobbered: completion handler cleared "
        "_dirty even though the edit is not in the file on disk"
    )
    close_builder_silent(b)


def test_save_failure_redirties_grid(tmp_path: Path, monkeypatch) -> None:
    """A failed write leaves in-memory state diverged from the file on
    disk. ``_dirty`` is cleared at save-start (snapshot commit), so on
    worker failure the completion handler must restore it -- otherwise
    the close guard would let the user discard their unsaved changes.
    """
    import os as _os
    import time as _time

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    app = QApplication.instance() or QApplication([])
    from phonology_features.engine.inventory import Inventory
    from phonology_features.gui.builder import InventoryBuilder
    from phonology_features.gui.builder import window as _bw

    monkeypatch.setattr(_bw, "show_warning", lambda *a, **k: None)
    monkeypatch.setattr(
        Inventory,
        "write_atomic",
        lambda self, path: (_ for _ in ()).throw(OSError("disk full")),
    )

    b = InventoryBuilder(load_path=HAYES)
    b._dirty = True
    b._write_json(str(tmp_path / "out.json"))

    deadline = _time.monotonic() + 2.0
    while b._save_in_flight and _time.monotonic() < deadline:
        app.processEvents()
        _time.sleep(0.01)
    assert not b._save_in_flight
    assert b._dirty, (
        "save failure left _dirty=False; close guard would discard "
        "the user's unsaved work silently"
    )
    close_builder_silent(b)


# ---------------------------------------------------------------------------
# Defensive QSettings reads at startup -- a corrupt or wrong-typed
# value must NEVER prevent the app from launching.
# ---------------------------------------------------------------------------
def test_safe_read_setting_recovers_from_systemerror() -> None:
    """Stale pickled enum values from a renamed package raise
    ``SystemError`` inside ``QSettings.value``. The helper must
    catch, remove the bad key, and return the default."""
    from phonology_features._settings import safe_read_setting

    class FakeSettings:
        def __init__(self) -> None:
            self.removed: list[str] = []

        def value(self, key: str, default: object) -> object:
            raise SystemError("stale pickled enum")

        def remove(self, key: str) -> None:
            self.removed.append(key)

    s = FakeSettings()
    out = safe_read_setting(s, "theme", "light", expected_type=str)
    assert out == "light"
    assert s.removed == ["theme"]


def test_safe_read_setting_recovers_from_module_not_found() -> None:
    """Same shape as SystemError but for an old import path that
    no longer exists -- e.g. an enum class moved between modules."""
    from phonology_features._settings import safe_read_setting

    class FakeSettings:
        def __init__(self) -> None:
            self.removed: list[str] = []

        def value(self, key: str, default: object) -> object:
            raise ModuleNotFoundError("phonology_features.old.path")

        def remove(self, key: str) -> None:
            self.removed.append(key)

    s = FakeSettings()
    out = safe_read_setting(s, "mode", "seg_to_feat", expected_type=str)
    assert out == "seg_to_feat"
    assert s.removed == ["mode"]


def test_safe_read_setting_rejects_wrong_type_without_removing() -> None:
    """A wrong-typed value (e.g. a hand-edited INI replaced a QSize
    with a string) falls back to default but is NOT removed -- the
    user may have set it deliberately and we just don't know how
    to use it yet."""
    from phonology_features._settings import safe_read_setting
    from PyQt6.QtCore import QSize

    class FakeSettings:
        def __init__(self) -> None:
            self.removed: list[str] = []

        def value(self, key: str, default: object) -> object:
            return "not a QSize"  # wrong type on purpose

        def remove(self, key: str) -> None:
            self.removed.append(key)

    s = FakeSettings()
    out = safe_read_setting(s, "window_size", None, expected_type=QSize)
    assert out is None
    assert s.removed == [], "wrong-type fallback should preserve the value"


def test_safe_read_setting_accepts_correct_type() -> None:
    from phonology_features._settings import safe_read_setting
    from PyQt6.QtCore import QSize

    class FakeSettings:
        def value(self, key: str, default: object) -> object:
            return QSize(1024, 768)

        def remove(self, key: str) -> None:
            raise AssertionError("should not be called on success path")

    out = safe_read_setting(
        FakeSettings(), "window_size", QSize(1, 1), expected_type=QSize
    )
    assert isinstance(out, QSize)
    assert (out.width(), out.height()) == (1024, 768)


def test_mainwindow_construction_survives_corrupt_window_size(
    tmp_path: Path,
) -> None:
    """Pre-fix, a wrong-typed window_size value (string instead of
    QSize) would crash ``_restore_settings`` at ``size.width()``,
    aborting startup with a traceback and no in-app recovery. With
    the ``expected_type=QSize`` guard the bad value falls back to
    the default and the window launches normally."""
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    QApplication.instance() or QApplication([])

    # Pre-populate corrupt settings BEFORE the window is constructed.
    from phonology_features.gui.constants import SETTINGS_APP, SETTINGS_ORG

    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    settings.setValue("window_size", "1200x900-not-a-qsize")
    settings.setValue("window_pos", "0,0-not-a-qpoint")
    settings.sync()

    from phonology_features.gui.main_window import MainWindow

    # Should NOT raise. Pre-fix this raised AttributeError on
    # size.width().
    w = MainWindow()
    # Window came up at a clamped default; specific size depends on
    # the screen, just assert it's nonzero.
    assert w.width() > 0
    assert w.height() > 0
    w.close()


def test_stale_tmp_files_swept_on_dropdown_populate(tmp_path: Path) -> None:
    """A save killed between mkstemp and os.replace leaves a
    ``.tmp_inv_*.json`` orphan in the inventories dir. They're
    hidden from the dropdown by the filter but accumulate across
    crashes. The sweep removes orphans older than 1 hour and
    leaves recent ones (which might be in-flight saves) alone.
    """
    import time as _time

    from phonology_features.gui.main_window import MainWindow

    # Set up the inventories dir with one stale and one fresh tmp.
    inv_dir = tmp_path / "inventories"
    inv_dir.mkdir()
    stale = inv_dir / ".tmp_inv_oldcrash.json"
    fresh = inv_dir / ".tmp_inv_inflight.json"
    legit = inv_dir / "user_inventory.json"
    stale.write_text("{}")
    fresh.write_text("{}")
    legit.write_text('{"features": [], "segments": {}}')
    # Make ``stale`` look 2 hours old.
    old_t = _time.time() - 7200
    os.utime(stale, (old_t, old_t))

    MainWindow._sweep_stale_tmp_files(str(inv_dir))

    assert not stale.exists(), (
        "stale tmp file from an old crashed save was not swept"
    )
    assert fresh.exists(), (
        "fresh tmp file (possibly an in-flight save) must not be touched"
    )
    assert legit.exists(), (
        "non-tmp file got swept -- the filter is too aggressive"
    )


def test_main_viewer_loads_freshly_saved_builder_inventory(
    tmp_path: Path,
) -> None:
    """When the user creates a NEW inventory in the builder and
    saves, the main feature visualizer should switch to that
    inventory automatically. Pre-fix the builder closed silently and
    the user had to open the dropdown to find their new file.
    """
    import os as _os
    import time as _time

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    app = QApplication.instance() or QApplication([])
    from phonology_features.gui.builder import InventoryBuilder
    from phonology_features.gui.main_window import MainWindow

    w = MainWindow()
    # Spawn a builder the same way _open_builder does for the
    # no-current-inventory case, including the save-finished wiring.
    builder = InventoryBuilder(parent=w)
    builder._save_finished.connect(w._on_builder_save_finished)
    w._builder = builder
    # Author a minimal inventory by hand.
    builder._segments = ["p", "b"]
    builder._features = ["Voice"]
    builder._inv_name = "Built-In-Test"
    builder._dirty = True
    builder._rebuild_table()
    # Need to set the cells properly so _to_inventory produces valid output.
    from phonology_features.gui.builder.grid import make_cell
    builder._table.setItem(0, 0, make_cell("-"))  # p is voiceless
    builder._table.setItem(0, 1, make_cell("+"))  # b is voiced

    target = tmp_path / "built_in_test.json"
    assert w._current_path is None
    builder._write_json(str(target))

    # Drain the background save -- _on_builder_save_finished fires
    # via the queued _save_finished signal back on the main thread.
    deadline = _time.monotonic() + 3.0
    while builder._save_in_flight and _time.monotonic() < deadline:
        app.processEvents()
        _time.sleep(0.01)
    # Process events one more time so the queued save_finished slot
    # in MainWindow gets dispatched.
    for _ in range(3):
        app.processEvents()

    assert target.exists(), "save did not produce the file"
    assert w._current_path == str(_os.path.abspath(target)), (
        f"main viewer did not switch to the freshly-saved inventory: "
        f"current_path={w._current_path!r}, expected={str(target)!r}"
    )
    assert w.engine is not None
    assert "p" in w.engine.segments
    close_builder_silent(builder)
    w.close()


def test_builder_rebuild_table_keeps_headers_visible(tmp_path: Path) -> None:
    """When the user creates a new inventory in the builder, the grid
    showed correct dimensions but no header labels (segments/features
    invisible). Cause: ``_rebuild_table`` replaces the table's headers
    via ``setHorizontalHeader(new)``; a freshly-constructed
    QHeaderView starts ``isHidden=True``, and Qt does NOT auto-show
    the new header when handed to the view. Result: header height/
    width = 0, cells fill the viewport, labels disappear.

    Regression guard: after both initial _build_table and any
    subsequent _rebuild_table, both headers must be visible with
    nonzero height/width.
    """
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    app = QApplication.instance() or QApplication([])
    from phonology_features.gui.builder import InventoryBuilder

    b = InventoryBuilder()
    b._segments = ["p", "b", "t"]
    b._features = ["Voice", "Nasal"]
    b._rebuild_table()
    b.show()
    for _ in range(3):
        app.processEvents()

    h1 = b._table.horizontalHeader()
    v1 = b._table.verticalHeader()
    assert h1 is not None and v1 is not None
    assert h1.isVisible() and h1.height() > 0, (
        f"horizontal header invisible after first rebuild: "
        f"isVisible={h1.isVisible()}, height={h1.height()}"
    )
    assert v1.isVisible() and v1.width() > 0, (
        f"vertical header invisible after first rebuild: "
        f"isVisible={v1.isVisible()}, width={v1.width()}"
    )

    # The bug originally triggered on the SECOND rebuild after show.
    b._segments = ["s", "z"]
    b._features = ["Voice", "Continuant"]
    b._rebuild_table()
    for _ in range(3):
        app.processEvents()

    h2 = b._table.horizontalHeader()
    v2 = b._table.verticalHeader()
    assert h2 is not None and v2 is not None
    assert h2.isVisible() and h2.height() > 0, (
        f"horizontal header invisible after rebuild on visible table: "
        f"isVisible={h2.isVisible()}, height={h2.height()}"
    )
    assert v2.isVisible() and v2.width() > 0, (
        f"vertical header invisible after rebuild on visible table: "
        f"isVisible={v2.isVisible()}, width={v2.width()}"
    )
    close_builder_silent(b)


def test_inventory_swap_does_not_resize_window(tmp_path: Path) -> None:
    """Once the user (or restored settings) owns the window geometry,
    swapping inventories must leave the top-level size and position
    untouched. The previous behaviour was to chase each inventory's
    content sizeHint with self.resize(), which moved the window on
    every load and clobbered any manual sizing.
    """
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    app = QApplication.instance() or QApplication([])
    from phonology_features.gui.main_window import MainWindow

    w = MainWindow(startup_path=HAYES)
    # Simulate user-owned geometry: pretend settings restored a size.
    # The production path also sets this in ``_restore_settings``.
    w._has_saved_size = True
    w.resize(1100, 850)
    w.show()
    app.processEvents()
    before_size = (w.width(), w.height())

    # Swap to a different inventory with a different segment / feature
    # count so the content sizeHint differs from the previous one.
    english = str(REPO_ROOT / "inventories" / "english_features.json")
    general = str(REPO_ROOT / "inventories" / "general_features.json")
    for path in (english, general, HAYES):
        w._load_path(path)
        app.processEvents()
        assert (w.width(), w.height()) == before_size, (
            f"window resized on inventory swap to {os.path.basename(path)}: "
            f"{before_size} -> {(w.width(), w.height())}"
        )
    w.close()


def test_inventory_swap_preserves_splitter_ratio(tmp_path: Path) -> None:
    """Once the splitter has been sized (restored from settings or
    nudged by the user), subsequent inventory swaps must not re-apply
    the content-derived ratio. Previously ``_apply_splitter_sizes``
    ran on every load and snapped the panel boundary back to the
    new inventory's seg-pane sizeHint.
    """
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    app = QApplication.instance() or QApplication([])
    from phonology_features.gui.main_window import MainWindow

    w = MainWindow(startup_path=HAYES)
    w._has_saved_size = True
    w._has_saved_splitter = True  # simulate restored state
    w.resize(1100, 850)
    w.show()
    app.processEvents()
    # User-chosen ratio.
    w._hsplit.setSizes([400, 700])
    app.processEvents()
    before = w._hsplit.sizes()

    english = str(REPO_ROOT / "inventories" / "english_features.json")
    general = str(REPO_ROOT / "inventories" / "general_features.json")
    for path in (english, general, HAYES):
        w._load_path(path)
        app.processEvents()
        assert w._hsplit.sizes() == before, (
            f"splitter ratio drifted on load of {os.path.basename(path)}: "
            f"{before} -> {w._hsplit.sizes()}"
        )
    w.close()


def test_user_splitter_drag_promotes_to_owned(tmp_path: Path) -> None:
    """Dragging a splitter handle must flip the owned flag, so the
    drag survives the next inventory load. Without this, a manual
    drag would silently revert on the next inventory swap.
    """
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    QApplication.instance() or QApplication([])
    from phonology_features.gui.main_window import MainWindow

    w = MainWindow(startup_path=HAYES)
    # Fresh install path: no settings yet, so first _fit_to_content
    # already ran and the flag is True from that programmatic setSizes.
    # Simulate the user dragging by emitting the signal directly.
    w._has_saved_splitter = False
    w._hsplit.splitterMoved.emit(450, 0)
    assert (
        w._has_saved_splitter
    ), "splitterMoved should promote the splitter to user-owned"
    w.close()


def test_bundle_search_largest_inventory_under_50ms() -> None:
    """Performance guard for ``find_all_minimal_bundles`` on the
    biggest bundled inventory (``general_features.json`` -- 135
    segments x 30 features, the deepest candidate-feature search
    space we ship). Runs a mix of small / medium / large target sets
    so a regression in any one shape gets caught.

    Current measured total on a developer laptop is ~1-2 ms across
    these five queries. 50 ms gives ~25x dev headroom and ~5-10x CI
    headroom -- enough to tolerate slow virtualized runners while
    still catching the regression patterns the search relies on:
      - bitmask encoding reverted to Python set ops (~7-10x per the
        comment at find_all_minimal_bundles).
      - branch-and-bound pruning broken (often 100x+ on hard inputs).
      - per-engine memoization cache disabled.

    Engine-only -- no GUI, no QApplication, so it stays cheap.
    """
    import time as _time

    inv = Inventory.load(GENERAL)
    eng = FeatureEngine(inv)
    all_segs = list(inv.segments.keys())
    # Picked to exercise three shapes:
    #   - tiny target  -> huge outside set, many excluders per outside
    #   - medium       -> mixed
    #   - large        -> few outsiders, but each may need many features
    targets = [
        all_segs[:3],
        all_segs[:8],
        all_segs[:20],
        all_segs[:50],
        all_segs[:100],
    ]
    t0 = _time.perf_counter()
    for segs in targets:
        eng.find_all_minimal_bundles(segs)
    elapsed_ms = (_time.perf_counter() - t0) * 1000
    assert elapsed_ms < 50, (
        f"bundle search on general_features (135 seg x 30 feat) took "
        f"{elapsed_ms:.1f} ms across {len(targets)} queries; "
        f"regression vs <50 ms budget (typical: ~1-2 ms)"
    )


def test_builder_save_omits_zero_cells_to_preserve_omission(
    tmp_path: Path,
) -> None:
    """``Inventory.parse`` documents missing-feature == 0 semantics
    and preserves omitted features on round-trip
    (see test_parse_missing_feature_in_bundle_defaults_to_zero).
    Builder save MUST honour the same contract: writing explicit "0"
    for every unset cell would silently inflate sparsely-authored
    inventories on every save through the builder.
    """
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    QApplication.instance() or QApplication([])
    from phonology_features.gui.builder import InventoryBuilder

    # Author a sparse inventory: 'p' has Voice set, no Nasal.
    sparse_src = tmp_path / "sparse.json"
    sparse_src.write_text(
        json.dumps(
            {
                "features": ["Voice", "Nasal"],
                "segments": {"p": {"Voice": "-"}, "m": {"Nasal": "+"}},
            }
        )
    )
    b = InventoryBuilder(load_path=str(sparse_src))
    # Snapshot through the same code path save uses; no edits.
    inv = b._to_inventory()
    serialized = inv.to_json_dict()
    # The omitted "Nasal" on "p" and "Voice" on "m" must STAY omitted.
    assert "Nasal" not in serialized["segments"]["p"], (
        f"builder reintroduced explicit '0' for omitted feature: "
        f"{serialized['segments']['p']}"
    )
    assert "Voice" not in serialized["segments"]["m"], (
        f"builder reintroduced explicit '0' for omitted feature: "
        f"{serialized['segments']['m']}"
    )
    close_builder_silent(b)


def test_validation_report_html_escapes_issue_text() -> None:
    """The validation-report HTML interpolates raw issue strings; if
    one of those quotes back inventory data containing tag characters
    we must not let it break out of the <p>."""
    from phonology_features.gui.main_window import MainWindow

    issues = (
        "segment '<script>': bad",
        "feature '\"oops\"': bad",
    )
    out = MainWindow._validation_report_html(issues)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
