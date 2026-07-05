"""Robustness of the segment grouper across feature SYSTEMS and
adversarial inventories, not just PHOIBLE.

The grouper must not over-fit to one source. Its contract:

  1. **Cover (multiset).** Every input segment lands in AT LEAST one
     group; none vanishes, none is invented, and none is listed twice in
     one group. A segment whose tiers reach several manner classes is a
     multi-membership segment and appears in each.
  2. **Graceful degradation.** A segment whose features match no
     manner/place spec (a sparse spec, a contradictory one, or a
     feature system the specs do not recognise) routes to the
     Contoid/Vocoid catch-all rather than crashing, vanishing, or
     being force-fit to a class it has no positive evidence for.
  3. **Encoding-agnostic affrication.** An affricate is classified the
     same whether its source encodes it as a ``[-continuant, +delrel]``
     collapse (the Hayes / PanPhon shape, and PHOIBLE's for ``ts``) or
     as a ``continuant`` / ``delrel`` contour (PHOIBLE ``tɬ``).
  4. **Major-class disjointness.** A vowel-phoneme never lands in a
     consonant manner class.

The whole-PHOIBLE stress test proves PHOIBLE-correctness; this file
guards against PHOIBLE OVER-FIT with hand-built multi-system fixtures,
adversarial edge inventories, and Hypothesis-generated bundles that the
real specs actually engage.
"""

from __future__ import annotations

import pytest

from phonology_shared.chart.consonants import (
    CONTOID_GROUP_NAME,
    DISPLAY_ORDER,
    TONES_GROUP_NAME,
    VOCOID_GROUP_NAME,
    VOWEL_GROUP_NAME,
    group_segments,
)
from phonology_shared.data.inventory import normalize_feature_bundle

#: The catch-alls plus the non-consonant homes. Everything else in
#: ``DISPLAY_ORDER`` is a consonant manner class, derived here so the
#: set stays in sync if the display order gains a class.
_NON_MANNER = frozenset(
    {
        VOWEL_GROUP_NAME,
        TONES_GROUP_NAME,
        CONTOID_GROUP_NAME,
        VOCOID_GROUP_NAME,
    }
)
_MANNER_GROUPS = frozenset(g for g in DISPLAY_ORDER if g not in _NON_MANNER)

_AFFRICATE_LABELS = frozenset(
    {
        "Affricates",
        "Sibilant Affricates",
        "Lateral Affricates",
        "Ejective Affricates",
    }
)


def _flat(groups: dict[str, list[str]]) -> list[str]:
    return [seg for segs in groups.values() for seg in segs]


def _membership(groups: dict[str, list[str]]) -> dict[str, set[str]]:
    """Each segment -> the SET of groups it renders in. group_segments is
    a MULTISET: a segment reaching several manner classes appears in each,
    so membership is a set, not a single label."""
    out: dict[str, set[str]] = {}
    for name, segs in groups.items():
        for seg in segs:
            out.setdefault(seg, set()).add(name)
    return out


def _assert_covers(inv: dict[str, dict[str, str]]) -> dict[str, set[str]]:
    """Grouping must COVER every segment (place each in >= 1 group, none
    invented, none listed twice in one group) and may place a
    multi-membership segment in several groups. Returns the seg -> set of
    groups membership for further per-segment assertions."""
    groups = group_segments(inv)
    flat = _flat(groups)
    assert set(flat) == set(inv), "grouping dropped or invented a segment"
    for name, segs in groups.items():
        assert len(segs) == len(set(segs)), f"{name} lists a segment twice"
    return _membership(groups)


# --------------------------------------------------------------------
# Multi-system fixtures: the same affricate under both encodings.
# --------------------------------------------------------------------

_STOP = {"Consonantal": "+", "Sonorant": "-", "Continuant": "-"}
_FRIC = {"Consonantal": "+", "Sonorant": "-", "Continuant": "+"}


def _hayes_collapse_inv() -> dict[str, dict[str, str]]:
    """Hayes / PanPhon / PHOIBLE-whitelist shape: the affricate is a
    single ``[-continuant, +delrel]`` bundle."""
    return {
        "t": {**_STOP, "DelRel": "-"},
        "s": {**_FRIC, "DelRel": "+"},
        "ts": {**_STOP, "DelRel": "+"},
    }


def test_collapse_encoded_affricate_is_classified() -> None:
    place = _assert_covers(_hayes_collapse_inv())
    assert place["ts"] & _AFFRICATE_LABELS, place
    assert "Plosives" in place["t"], place


def test_contour_encoded_affricate_is_classified() -> None:
    """PHOIBLE ``tɬ`` shape: ``continuant`` and ``delrel`` each carry a
    value SEQUENCE (closure then fricated release). group_segments reads
    a feature's whole sequence, so the affricate rule fires."""
    inv = {
        "t": {**_STOP, "DelRel": "-"},
        "s": {**_FRIC, "DelRel": "+"},
        "aff": {**_STOP, "DelRel": "-"},
    }
    sequences = {"aff": {"continuant": ("-", "+"), "delrel": ("-", "+")}}
    groups = group_segments(inv, sequences=sequences)
    place = _membership(groups)
    assert sorted(_flat(groups)) == sorted(inv)
    assert place["aff"] & _AFFRICATE_LABELS, place
    assert "Plosives" in place["t"], place


def test_stop_sonorant_cluster_is_not_an_affricate_by_contour() -> None:
    """A closure that releases into a sonorant (``tr`` / ``tl``)
    contours on ``continuant`` but never reaches ``[+delrel]``, so it is
    a Plosive, not an affricate. Guards the over-generation the old
    contour-alone rule committed."""
    inv = {"t": {**_STOP, "DelRel": "-"}, "tr": {**_STOP, "DelRel": "-"}}
    # sonorant release: continuant contours but delrel stays "-"
    sequences = {"tr": {"continuant": ("-", "+")}}
    place = _membership(group_segments(inv, sequences=sequences))
    assert not (place["tr"] & _AFFRICATE_LABELS), place


def test_grouping_reads_the_whole_sequence_including_interior() -> None:
    """A distinguishing ``+delrel`` in an INTERIOR position of the
    sequence (neither first nor last) is still seen, because membership
    is per-feature over the whole value sequence, not just endpoints."""
    inv = {"t": {**_STOP, "DelRel": "-"}, "x": {**_STOP, "DelRel": "-"}}
    # delrel reaches "+" only in the middle; continuant closes then opens
    sequences = {
        "x": {"continuant": ("-", "-", "+"), "delrel": ("-", "+", "-")}
    }
    place = _membership(group_segments(inv, sequences=sequences))
    assert place["x"] & _AFFRICATE_LABELS, place


# --------------------------------------------------------------------
# Adversarial inventories: the grouper must degrade, not break.
# --------------------------------------------------------------------


def test_novel_feature_system_degrades_to_catch_alls() -> None:
    """An inventory whose feature names the specs do not recognise must
    not crash or drop segments: with no manner/place evidence every
    segment routes to a Contoid/Vocoid catch-all."""
    inv = {
        "x1": {"Blorp": "+", "Zizz": "-"},
        "x2": {"Blorp": "-", "Zizz": "+"},
        "x3": {"Quux": "0"},
    }
    place = _assert_covers(inv)
    assert all(
        m <= {CONTOID_GROUP_NAME, VOCOID_GROUP_NAME} for m in place.values()
    ), place


def test_sparse_and_contradictory_segments_do_not_vanish() -> None:
    """Barely-specified and internally-contradictory segments still get
    a home (partition holds) and never raise."""
    inv = {
        "sparse": {"Consonantal": "+"},  # one feature only
        "empty": {},  # no features at all
        "contradiction": {  # vowel-ish AND obstruent-ish at once
            "Syllabic": "+",
            "Consonantal": "+",
            "Continuant": "-",
            "Sonorant": "-",
        },
    }
    _assert_covers(inv)  # asserts partition + no exception


def test_empty_inventory_is_empty() -> None:
    assert group_segments({}) == {}


# --------------------------------------------------------------------
# Hypothesis: fuzz over canonical features so the real specs engage.
# --------------------------------------------------------------------

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

#: A pool of real feature names so generated inventories actually reach
#: the manner/place specs (a purely random alphabet would only ever
#: exercise the catch-all path).
_CANONICAL_FEATURES = [
    "Consonantal",
    "Sonorant",
    "Syllabic",
    "Continuant",
    "DelRel",
    "Nasal",
    "Lateral",
    "Trill",
    "Tap",
    "Approximant",
    "Strident",
    "Coronal",
    "Voice",
    "Click",
    "Tone",
]
_VALUES = st.sampled_from(["+", "-", "0"])


@st.composite
def _random_inventory(draw: st.DrawFn) -> dict[str, dict[str, str]]:
    feats = draw(
        st.lists(
            st.sampled_from(_CANONICAL_FEATURES),
            min_size=1,
            max_size=8,
            unique=True,
        )
    )
    count = draw(st.integers(min_value=1, max_value=10))
    return {f"s{i}": {f: draw(_VALUES) for f in feats} for i in range(count)}


@given(_random_inventory())
@settings(max_examples=200, deadline=None)
def test_grouping_always_partitions(inv: dict[str, dict[str, str]]) -> None:
    """No generated inventory makes a segment vanish, duplicate, or
    raise: the grouper always returns a clean partition."""
    _assert_covers(inv)


@given(_random_inventory())
@settings(max_examples=200, deadline=None)
def test_vowel_phonemes_never_in_a_consonant_class(
    inv: dict[str, dict[str, str]],
) -> None:
    """A vowel-phoneme (``Syllabic=+``, not ``Consonantal=+``, not a
    click) is barred from every consonant manner class; it lands in
    Vowels or the Vocoid catch-all."""
    place = _assert_covers(inv)
    for seg, bundle in inv.items():
        nb = normalize_feature_bundle(bundle)
        is_vowel_phoneme = (
            nb.get("syllabic") == "+"
            and nb.get("consonantal") != "+"
            and nb.get("click") != "+"
        )
        if is_vowel_phoneme:
            assert place[seg].isdisjoint(_MANNER_GROUPS), (seg, place[seg])
