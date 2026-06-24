"""Contour (multi-phase) segments: a diphthong/affricate is modelled
as a sequence of ordinary +/-/0 phases, and the feature engine unions
membership over those phases so a contour segment belongs to BOTH the
[+f] and [-f] natural class for any feature its phases disagree on.

This pins the interim phase model (the final phase comes from the
``segment_secondary`` metadata) and the engine's union + wildcard
behaviour. PHOIBLE encodes the contour as ``"+,-"``; before this, the
engine saw only the initial polarity, so a diphthong gliding into
``[+low]`` never answered a ``[+low]`` query.
"""

from __future__ import annotations

from phonology_shared.data import Inventory
from phonology_shared.theory.feature_engine import FeatureEngine, MatchMode


def _contour_inv() -> Inventory:
    """``i`` (+high -low), ``a`` (-high +low), and a diphthong ``ia``
    whose primary phase is the /i/ state and whose final phase (in
    ``segment_secondary``, folded keys) is the /a/ state."""
    return Inventory.parse(
        {
            "features": ["High", "Low"],
            "segments": {
                "i": {"High": "+", "Low": "-"},
                "a": {"High": "-", "Low": "+"},
                "ia": {"High": "+", "Low": "-"},
            },
            "metadata": {
                "segment_secondary": {"ia": {"high": "-", "low": "+"}}
            },
        }
    )


def test_segment_phases_single_for_simple_segment() -> None:
    inv = _contour_inv()
    phases = inv.segment_phases("i")
    assert len(phases) == 1
    assert dict(phases[0]) == {"High": "+", "Low": "-"}


def test_segment_phases_two_for_contour_with_canonical_keys() -> None:
    inv = _contour_inv()
    phases = inv.segment_phases("ia")
    assert len(phases) == 2
    # Primary (initial) phase = /i/; final phase = /a/, remapped from
    # the folded ``segment_secondary`` keys to canonical feature names.
    assert dict(phases[0]) == {"High": "+", "Low": "-"}
    assert dict(phases[1]) == {"High": "-", "Low": "+"}


def test_contour_segment_is_member_of_both_classes() -> None:
    """The core fix: a diphthong that glides -low -> +low answers BOTH
    a [+Low] and a [-Low] query, in strict AND wildcard mode."""
    eng = FeatureEngine(_contour_inv())
    for mode in (MatchMode.STRICT, MatchMode.WILDCARD):
        plus_low = set(eng.find_segments({"Low": "+"}, mode=mode))
        minus_low = set(eng.find_segments({"Low": "-"}, mode=mode))
        assert "ia" in plus_low, (mode, "diphthong missing from [+Low]")
        assert "ia" in minus_low, (mode, "diphthong missing from [-Low]")
        # And on High, where /ia/ starts +high and ends -high.
        assert "ia" in set(eng.find_segments({"High": "+"}, mode=mode))
        assert "ia" in set(eng.find_segments({"High": "-"}, mode=mode))


def test_monophthongs_stay_in_exactly_one_class() -> None:
    """The phase union must not pollute single-phase segments: /a/ is
    only [+Low], /i/ only [-Low]."""
    eng = FeatureEngine(_contour_inv())
    for mode in (MatchMode.STRICT, MatchMode.WILDCARD):
        plus_low = set(eng.find_segments({"Low": "+"}, mode=mode))
        minus_low = set(eng.find_segments({"Low": "-"}, mode=mode))
        assert "a" in plus_low and "a" not in minus_low, mode
        assert "i" in minus_low and "i" not in plus_low, mode


def _affricate_inv(*, with_delrel: bool) -> Inventory:
    """A 3-obstruent inventory: a plain stop ``t``, a fricative ``s``,
    and ``ts`` whose ``continuant`` contours ``- -> +`` (the affricate,
    encoded as a second phase). ``with_delrel`` toggles whether the
    inventory even has a ``DelRel`` column, modelling the two regimes
    the grouper must handle."""
    feats = ["Consonantal", "Sonorant", "Continuant"]
    t = {"Consonantal": "+", "Sonorant": "-", "Continuant": "-"}
    s = {"Consonantal": "+", "Sonorant": "-", "Continuant": "+"}
    ts = {"Consonantal": "+", "Sonorant": "-", "Continuant": "-"}
    if with_delrel:
        feats.append("DelRel")
        t["DelRel"] = "-"
        s["DelRel"] = "-"
        ts["DelRel"] = "+"
    return Inventory.parse(
        {
            "features": feats,
            "segments": {"t": t, "s": s, "ts": ts},
            "metadata": {"segment_secondary": {"ts": {"continuant": "+"}}},
        }
    )


def test_continuant_contour_is_affricate_without_delrel() -> None:
    """The note's case: with no ``DelRel`` feature, a ``continuant``
    contour is what names an affricate. ``ts`` lands in Affricates;
    the plain stop ``t`` stays a Plosive and ``s`` a Fricative."""
    eng = FeatureEngine(_affricate_inv(with_delrel=False))
    groups = eng.grouped_segments
    assert "ts" in groups.get("Affricates", []), groups
    assert "t" in groups.get("Plosives", []), groups
    assert "s" in groups.get("Fricatives", []), groups
    # The contour segment must not also linger in Plosives.
    assert "ts" not in groups.get("Plosives", []), groups


def test_plain_stop_not_affricate_without_delrel() -> None:
    """Guard against the degenerate path: with ``DelRel`` absent the
    Affricates spec must not claim plain stops by tie-break. Only the
    contour segment is an affricate; ``t`` is a Plosive."""
    eng = FeatureEngine(_affricate_inv(with_delrel=False))
    assert "t" not in eng.grouped_segments.get("Affricates", [])


def test_delrel_affricate_still_classified_when_present() -> None:
    """Regression: when ``DelRel`` IS present the existing spec path is
    untouched. ``ts`` (delrel +) is an affricate, ``t`` (delrel -) a
    plosive, independent of any contour metadata."""
    eng = FeatureEngine(_affricate_inv(with_delrel=True))
    groups = eng.grouped_segments
    assert "ts" in groups.get("Affricates", []), groups
    assert "t" in groups.get("Plosives", []), groups


def test_contour_feats_exposes_only_contouring_features() -> None:
    """The engine's contour map names exactly the features that flip
    polarity across phases: ``continuant`` for ``ts`` and nothing for
    the single-phase obstruents."""
    eng = FeatureEngine(_affricate_inv(with_delrel=False))
    cmap = eng._contour_feats_by_seg
    assert cmap.get("ts") == frozenset({"continuant"})
    assert "t" not in cmap and "s" not in cmap


def test_diphthong_contour_is_not_an_affricate() -> None:
    """The obstruent gate keeps the affricate rule off vowels: the
    ``ia`` diphthong contours (it is in the engine's contour map) but
    is ``-consonantal``, so ``affricate_by_contour`` refuses it and it
    never enters the Affricates class."""
    eng = FeatureEngine(_contour_inv())
    assert "ia" in eng._contour_feats_by_seg, "diphthong should contour"
    assert "ia" not in eng.grouped_segments.get("Affricates", [])


def test_single_phase_inventory_matching_unchanged() -> None:
    """An inventory with no contour segments indexes exactly as a
    plain +/-/0 inventory: plus and minus stay disjoint, so wildcard
    subtraction is identical to subtracting the full opposite set."""
    inv = Inventory.parse(
        {
            "features": ["Low"],
            "segments": {"a": {"Low": "+"}, "i": {"Low": "-"}},
        }
    )
    eng = FeatureEngine(inv)
    assert eng._plus_excl["Low"] == eng.plus_segs["Low"]
    assert eng._minus_excl["Low"] == eng.minus_segs["Low"]
    for mode in (MatchMode.STRICT, MatchMode.WILDCARD):
        assert set(eng.find_segments({"Low": "+"}, mode=mode)) == {"a"}
        assert set(eng.find_segments({"Low": "-"}, mode=mode)) == {"i"}
