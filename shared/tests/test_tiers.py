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
    bundle_bits,
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


# --------------------------------------------------------------------
# A requested "0" is a CONSTRAINT, not a waiver. ``bundle_bits`` used to
# drop it, so ``Phase.satisfies`` never checked it while
# ``feature_reaches`` did: a multi-feature existential could report a
# co-occurrence no phase actually had.
# --------------------------------------------------------------------


def test_nil_request_constrains_multi_feature_exists() -> None:
    """``f`` is ``0`` only in phase 0 and ``g`` is ``+`` only in phase 1,
    so no single phase satisfies both. Each conjunct is individually
    reached, which is exactly what made the old per-feature pre-filter
    wave the bundle through."""
    tiers = {"cont": ("0", "+"), "nas": ("-", "+")}
    attrs = Attrs(sorted(tiers))
    alignment = align(attrs, tiers)
    assert feature_reaches(tiers, "cont", "0")
    assert feature_reaches(tiers, "nas", "+")
    assert (
        member_exists(attrs, tiers, alignment, {"cont": "0", "nas": "+"})
        is False
    )


def test_nil_request_still_matches_where_it_truly_cooccurs() -> None:
    """The other side of the guard: phase 0 really does have ``cont``
    at ``0`` and ``nas`` at ``-``, so that bundle must still match."""
    tiers = {"cont": ("0", "+"), "nas": ("-", "+")}
    attrs = Attrs(sorted(tiers))
    alignment = align(attrs, tiers)
    assert (
        member_exists(attrs, tiers, alignment, {"cont": "0", "nas": "-"})
        is True
    )
    assert (
        member_exists(attrs, tiers, alignment, {"cont": "+", "nas": "+"})
        is True
    )


def test_nil_mask_is_absence_of_both_polarities() -> None:
    """``Phase.satisfies``' nil arm at the bit level: an attribute
    valued either way in this phase fails a ``"0"`` request."""
    phase = phase_of(_A, {"cont": "-", "nas": "+"})
    assert phase.satisfies(*bundle_bits(_A, {"strid": "0"}))
    assert not phase.satisfies(*bundle_bits(_A, {"cont": "0"}))
    assert not phase.satisfies(*bundle_bits(_A, {"nas": "0"}))


# --------------------------------------------------------------------
# Parse-boundary invariant. Every tier the system can hand out is
# non-empty and over the +/-/0 alphabet, because the parser refuses
# anything else. ``align`` and the grouper's phase reconstruction index
# position 0 unguarded, which is correct GIVEN this invariant.
# --------------------------------------------------------------------


def test_parse_rejects_the_empty_tier_before_any_consumer_sees_it() -> None:
    """The architectural guard, not a crash reproduction. An empty
    sequence next to a real contour used to parse cleanly and then
    raise IndexError deep in the grouper. The assertion is that
    ``Inventory.parse`` refuses it, so no consumer is ever handed one.
    """
    from phonology_shared.data.inventory import Inventory, ValidationError

    raw = {
        "features": ["Consonantal", "Continuant", "Voice"],
        "segments": {
            "p": {"Consonantal": "+", "Continuant": "-", "Voice": "-"}
        },
        "metadata": {
            "segment_sequences": {"p": {"Continuant": ["-", "+"], "Voice": []}}
        },
    }
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(raw)
    codes = {vi.code for vi in ex.value.validation_issues}
    assert "sequences.empty" in codes, codes


def test_every_bundled_tier_is_nonempty_and_in_alphabet(
    bundled_inventory,
) -> None:
    """The invariant stated positively over real data: for every
    inventory that DOES parse, every tier is non-empty and every value
    is in the alphabet. This is the precondition ``align`` relies on.
    """
    from _inventory_names import BUNDLED_INVENTORY_NAMES

    checked = 0
    for name in BUNDLED_INVENTORY_NAMES:
        inv = bundled_inventory(name)
        for seg in inv.segments:
            for feat, tier in inv.sequences(seg).items():
                assert tier, f"{name}/{seg}/{feat} has an empty tier"
                assert set(tier) <= {
                    "+",
                    "-",
                    "0",
                }, f"{name}/{seg}/{feat} = {tier}"
                checked += 1
    assert checked > 1000, f"only {checked} tiers checked; too few to pin"
