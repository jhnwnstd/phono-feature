"""PanPhon lookup-form normalization (``to_panphon_form``).

A user segment is preserved verbatim for storage/display; PanPhon is
run on an equivalence-mapped form so it can resolve segments written
with non-PanPhon conventions (under-tiebar / ASCII-hyphen / bare
affricates, smart-quote ejectives, an ASCII length colon) and NFC
diacritics. The mapping is explicit and conservative: only the
listed affricate cores fuse, real clusters are left intact.
"""

from __future__ import annotations

import unicodedata

import pytest

from phonology_shared.editor.panphon_features import to_panphon_form

TIEBAR = "͡"  # COMBINING DOUBLE INVERTED BREVE (over-tiebar)


def _nfd(s: str) -> str:
    return unicodedata.normalize("NFD", s)


@pytest.mark.parametrize(
    "original, expected",
    [
        # Under-tiebar -> over-tiebar.
        ("t͜ʃ", "t" + TIEBAR + "ʃ"),
        ("d͜ʒ", "d" + TIEBAR + "ʒ"),
        # ASCII-hyphen convention -> over-tiebar (the user's examples).
        ("t-ʃ", "t" + TIEBAR + "ʃ"),
        ("d-ʒ", "d" + TIEBAR + "ʒ"),
        ("t-s", "t" + TIEBAR + "s"),
        ("d-z", "d" + TIEBAR + "z"),
        ("t-ɕ", "t" + TIEBAR + "ɕ"),
        ("d-ʑ", "d" + TIEBAR + "ʑ"),
        ("t-ɬ", "t" + TIEBAR + "ɬ"),
        # Bare digraph -> over-tiebar.
        ("tʃ", "t" + TIEBAR + "ʃ"),
        ("ts", "t" + TIEBAR + "s"),
        # Already correct -> unchanged (idempotent).
        ("t" + TIEBAR + "ʃ", "t" + TIEBAR + "ʃ"),
        # Affricate carrying a trailing diacritic keeps it.
        ("t-ʃʰ", "t" + TIEBAR + "ʃʰ"),
        # ASCII g folds to script g (shared inventory canonicalisation).
        ("gb", "ɡ" + TIEBAR + "b"),
    ],
)
def test_affricate_forms_map_to_over_tiebar(
    original: str, expected: str
) -> None:
    assert to_panphon_form(original) == _nfd(expected)


@pytest.mark.parametrize(
    "original, expected",
    [
        ("t’", "tʼ"),  # right single quote -> ʼ ejective
        ("t′", "tʼ"),  # prime -> ʼ ejective
        ("t'", "tʼ"),  # ASCII apostrophe (via canonicalize) -> ʼ
        ("a:", "aː"),  # ASCII colon -> ː long
    ],
)
def test_diacritic_variants_fold_to_panphon_codepoints(
    original: str, expected: str
) -> None:
    assert to_panphon_form(original) == _nfd(expected)


def test_output_is_nfd() -> None:
    """The lookup form matches PanPhon's own NFD table/keys, so a
    precomposed vowel decomposes."""
    out = to_panphon_form("ã")  # U+00E3
    assert out == "ã"
    assert out == unicodedata.normalize("NFD", out)


@pytest.mark.parametrize("cluster", ["sp", "st", "ps", "kt", "mn", "ʃt"])
def test_non_affricate_clusters_are_not_fused(cluster: str) -> None:
    """Conservative: a consonant pair that is NOT an explicit affricate
    core never gets a tiebar, so a real cluster the user intends is
    preserved."""
    assert TIEBAR not in to_panphon_form(cluster)


def test_idempotent() -> None:
    for s in ["t-ʃ", "t͜ʒ", "tʃ", "a:", "t’", "ã", "kʷ"]:
        once = to_panphon_form(s)
        assert to_panphon_form(once) == once, s


def test_original_input_is_not_mutated() -> None:
    """The mapping returns a NEW string; the caller keeps the original
    as the inventory key (strings are immutable, but pin the contract
    that the function does not require/return the same object)."""
    original = "t-ʃ"
    mapped = to_panphon_form(original)
    assert original == "t-ʃ"
    assert mapped != original


# End-to-end against the real PanPhon table when it is installed. Skips
# cleanly on web-only environments that do not ship panphon.
panphon = pytest.importorskip("panphon")


@pytest.fixture(scope="module")
def feature_table():
    return panphon.FeatureTable()


@pytest.mark.parametrize(
    "original",
    ["t-ʃ", "t͜ʃ", "tʃ", "d-ʒ", "t-s", "t-ɕ", "t-ɬ", "t’", "a:"],
)
def test_mapped_form_resolves_in_panphon_when_original_does_not(
    feature_table, original: str
) -> None:
    """The mapped form is a single PanPhon segment; the bare original
    is not (it splits, is dropped, or fails)."""
    mapped = to_panphon_form(original)
    assert len(feature_table.word_fts(mapped)) == 1, mapped
