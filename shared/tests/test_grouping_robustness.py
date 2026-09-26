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
guards against PHOIBLE OVER-FIT with hand-built multi-system fixtures
and adversarial edge inventories. The Hypothesis-generated counterpart
lives in :py:mod:`test_grouping_properties`, which asserts the same
cover contract via :py:mod:`_grouping_asserts`; it is a separate module
so a venv without ``hypothesis`` skips the properties WITHOUT taking
the fixtures below with it.
"""

from __future__ import annotations

from _grouping_asserts import (
    AFFRICATE_LABELS,
    assert_covers,
    flat,
    membership,
)

from phonology_shared.chart.consonants import (
    CONTOID_GROUP_NAME,
    VOCOID_GROUP_NAME,
    group_segments,
)

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
    place = assert_covers(_hayes_collapse_inv())
    assert place["ts"] & AFFRICATE_LABELS, place
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
    place = membership(groups)
    assert sorted(flat(groups)) == sorted(inv)
    assert place["aff"] & AFFRICATE_LABELS, place
    assert "Plosives" in place["t"], place


def test_stop_sonorant_cluster_is_not_an_affricate_by_contour() -> None:
    """A closure that releases into a sonorant (``tr`` / ``tl``)
    contours on ``continuant`` but never reaches ``[+delrel]``, so it is
    a Plosive, not an affricate. Guards the over-generation the old
    contour-alone rule committed."""
    inv = {"t": {**_STOP, "DelRel": "-"}, "tr": {**_STOP, "DelRel": "-"}}
    # sonorant release: continuant contours but delrel stays "-"
    sequences = {"tr": {"continuant": ("-", "+")}}
    place = membership(group_segments(inv, sequences=sequences))
    assert not (place["tr"] & AFFRICATE_LABELS), place


def test_grouping_reads_the_whole_sequence_including_interior() -> None:
    """A distinguishing ``+delrel`` in an INTERIOR position of the
    sequence (neither first nor last) is still seen, because membership
    is per-feature over the whole value sequence, not just endpoints."""
    inv = {"t": {**_STOP, "DelRel": "-"}, "x": {**_STOP, "DelRel": "-"}}
    # delrel reaches "+" only in the middle; continuant closes then opens
    sequences = {
        "x": {"continuant": ("-", "-", "+"), "delrel": ("-", "+", "-")}
    }
    place = membership(group_segments(inv, sequences=sequences))
    assert place["x"] & AFFRICATE_LABELS, place


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
    place = assert_covers(inv)
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
    assert_covers(inv)  # asserts partition + no exception


def test_empty_inventory_is_empty() -> None:
    assert group_segments({}) == {}
