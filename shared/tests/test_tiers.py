"""Source-agnostic tier core: ground-truth per-feature sequences, total
onset/offset anchors, derived alignment with an honest UNDETERMINED for
ragged segments, and single-feature reads that answer for every segment.
"""

from __future__ import annotations

import pytest

from phonology_shared.data.tiers import (
    UNDETERMINED,
    Aligned,
    Attrs,
    Misaligned,
    align,
    contour_on,
    feature_reaches,
    feature_throughout,
    member_exists,
    member_forall,
    offset,
    onset,
    phase_of,
)

_NAMES = ["cons", "son", "cont", "delrel", "strid", "lat", "nas", "lab"]
_A = Attrs(_NAMES)


def _tiers(**spec: str) -> dict[str, tuple[str, ...]]:
    return {f: tuple(v.split(",")) for f, v in spec.items()}


#: The worked inventory. ``ts`` is SIMPLEX (PHOIBLE's whitelist shape:
#: [-cont, +delrel]); ``tsh`` (=tɬ) SPLITS closure -> fricated release;
#: ``tl`` is a stop+sonorant cluster; ``n`` carries an asserted-N/A
#: ``0delrel``; ``mbw`` is ragged (2-part nasal beside a 3-part labial).
_INV = {
    "t": _tiers(cons="+", son="-", cont="-", delrel="-", strid="-", lat="-"),
    "s": _tiers(cons="+", son="-", cont="+", delrel="-", strid="+", lat="-"),
    "ts": _tiers(cons="+", son="-", cont="-", delrel="+", strid="+", lat="-"),
    "tS": _tiers(
        cons="+", son="-", cont="-,+", delrel="+", strid="-", lat="-,+"
    ),
    "tl": _tiers(
        cons="+", son="-", cont="-,+", delrel="-", strid="-,+", lat="-,+"
    ),
    "n": _tiers(cons="+", son="+", cont="-", delrel="0", strid="-", nas="+"),
    "mbw": _tiers(cons="+", son="+,-", nas="+,-", cont="-", lab="-,+,+"),
}


def test_ts_is_simplex_no_contour() -> None:
    """A plain affricate is stored simplex; nothing contours."""
    assert not contour_on(_INV["ts"], "cont")
    assert contour_on(_INV["tS"], "cont")
    assert contour_on(_INV["tl"], "cont")


def test_single_feature_reads_are_order_blind_and_total() -> None:
    """∃ / ∀ over one feature answer for every segment including the
    ragged one, and never need an alignment."""
    assert feature_reaches(_INV["tS"], "cont", "+")
    assert feature_reaches(_INV["tS"], "cont", "-")
    assert feature_throughout(_INV["ts"], "cont", "-")
    assert not feature_throughout(_INV["tS"], "cont", "-")
    # ragged mbw still answers single-feature reads:
    assert feature_reaches(_INV["mbw"], "nas", "+")
    assert feature_reaches(_INV["mbw"], "lab", "+")
    assert contour_on(_INV["mbw"], "nas")


def test_absent_feature_is_source_silence() -> None:
    """A feature absent from the map reaches nothing (distinct from an
    asserted ``0``, which is present-and-``0``)."""
    assert not feature_reaches(_INV["t"], "nas", "+")
    assert not feature_reaches(_INV["t"], "nas", "-")
    # n asserts 0delrel: present but neither + nor -
    assert not feature_reaches(_INV["n"], "delrel", "+")
    assert not feature_reaches(_INV["n"], "delrel", "-")
    assert _INV["n"]["delrel"] == ("0",)


def test_onset_offset_total_for_every_segment() -> None:
    """Endpoints read index 0 / -1 of every tier, so they are total even
    for a ragged segment."""
    for seg, tiers in _INV.items():
        assert set(onset(tiers)) == set(tiers), seg
        assert set(offset(tiers)) == set(tiers), seg
    # mbw onset is the nasal-voiced start; offset the labial release
    assert onset(_INV["mbw"])["nas"] == "+"
    assert offset(_INV["mbw"])["nas"] == "-"
    assert onset(_INV["mbw"])["lab"] == "-"
    assert offset(_INV["mbw"])["lab"] == "+"


def test_alignment_and_misalignment() -> None:
    """Segments whose varying tiers share a length align; the ragged one
    reports Misaligned naming the conflict."""
    assert isinstance(align(_A, _INV["ts"]), Aligned)
    tS = align(_A, _INV["tS"])
    assert isinstance(tS, Aligned) and len(tS.phases) == 2
    mis = align(_A, _INV["mbw"])
    assert isinstance(mis, Misaligned)
    assert mis.lengths == (2, 3)
    assert set(mis.features) == {"nas", "son", "lab"}


def test_phases_disjoint() -> None:
    for tiers in _INV.values():
        a = align(_A, tiers)
        if isinstance(a, Aligned):
            assert all(p.disjoint() for p in a.phases)


def test_affricate_uniformity_from_delrel_not_phase_count() -> None:
    """ts (1 phase) and tS (2 phases) both group under ∀[+delrel]; the
    class comes from a shared feature, not from phase count."""
    delrel_plus = {"delrel": "+"}
    grouped = {
        seg for seg, tiers in _INV.items() if member_forall(tiers, delrel_plus)
    }
    assert grouped == {"ts", "tS"}
    # [-cont] is NOT the discriminator: it holds every -continuant-
    # throughout segment (simplex ts, plain t, nasal n, and the ragged
    # prenasalized mbw whose cont is constant "-") but not the split tS.
    cont_minus = {"cont": "-"}
    stops = {
        seg for seg, tiers in _INV.items() if member_forall(tiers, cont_minus)
    }
    assert stops == {"t", "ts", "n", "mbw"}


def test_forall_is_total_even_for_ragged_segments() -> None:
    """∀ decomposes over features, so it is decidable for the ragged
    mbw: it is [-cont] throughout (cont is constant), never UNDETERMINED,
    and it is NOT [+lab] throughout (lab contours)."""
    assert member_forall(_INV["mbw"], {"cont": "-"}) is True
    assert member_forall(_INV["mbw"], {"lab": "+"}) is False
    assert member_forall(_INV["mbw"], {"cons": "+", "cont": "-"}) is True


def test_multi_feature_exists_undetermined_only_when_all_reached() -> None:
    """∃ co-occurrence over the ragged mbw is UNDETERMINED only when both
    features are individually reached; a feature it never reaches rules
    it out definitively, even Misaligned."""
    mbw, a = _INV["mbw"], align(_A, _INV["mbw"])
    # +lab is reached (offset), +son is reached (onset): co-occurrence
    # across the ragged tiers is the fact the source withholds.
    assert member_exists(_A, mbw, a, {"lab": "+", "son": "+"}) is UNDETERMINED
    # +cont is NEVER reached (cont is constant "-"): definitively out.
    assert member_exists(_A, mbw, a, {"cont": "+", "lab": "+"}) is False
    # single-feature stays decidable
    assert member_exists(_A, mbw, a, {"lab": "+"}) is True


def test_undetermined_is_not_boolean() -> None:
    with pytest.raises(TypeError):
        bool(UNDETERMINED)


def test_phase_satisfies_strict_zero_excluded() -> None:
    """A ``0`` attribute satisfies neither polarity."""
    ph = phase_of(_A, {"cont": "-", "delrel": "0"})
    from phonology_shared.data.tiers import bundle_bits

    assert ph.satisfies(*bundle_bits(_A, {"cont": "-"}))
    assert not ph.satisfies(*bundle_bits(_A, {"delrel": "+"}))
    assert not ph.satisfies(*bundle_bits(_A, {"delrel": "-"}))
