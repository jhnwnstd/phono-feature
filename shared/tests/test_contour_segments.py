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
from phonology_shared.editor.phoible_features import initial_phase_value
from phonology_shared.theory.feature_engine import FeatureEngine, MatchMode


def test_initial_phase_value_reads_the_starting_polarity() -> None:
    """The bake's vowel/obstruent gate reads this to classify a
    segment by the state it STARTS in. A contour returns its initial
    polarity; a plain cell normalizes as usual. This is what keeps a
    falling diphthong (``syllabic="+,-"``) read as a vowel and a
    prenasalized consonant (``sonorant="+,-"``) read as a sonorant,
    instead of the raw ``"+,-" == "+"`` comparison misreading both."""
    assert initial_phase_value("+,-") == "+"
    assert initial_phase_value("-,+") == "-"
    assert initial_phase_value("+") == "+"
    assert initial_phase_value("-") == "-"
    assert initial_phase_value("0") == "0"
    # Not a valid 2-part contour -> falls back to normalize ("0").
    assert initial_phase_value("+,-,+") == "0"
    assert initial_phase_value("NA") == "0"


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


#: Every label a consonant affricate can wear once the sub-class
#: breakouts have run, so a test can ask "is this an affricate" without
#: caring whether the tiny fixture broke a sub-class out.
_AFFRICATE_LABELS = (
    "Affricates",
    "Sibilant Affricates",
    "Lateral Affricates",
    "Ejective Affricates",
)


def _affricates(groups: dict[str, list[str]]) -> set[str]:
    out: set[str] = set()
    for label in _AFFRICATE_LABELS:
        out.update(groups.get(label, []))
    return out


def _obstruent_inv() -> Inventory:
    """Obstruents exercising the phase-union affricate rule.

    An affricate is an obstruent with a ``[-continuant]`` closure phase
    AND a ``[+delrel]`` (fricated release) phase; that conjunction is
    the intersection of the delayed-release-stop and contour analyses,
    so it spans both encodings PHOIBLE uses and, critically, separates
    a fricated release from a sonorant one. The fixture holds one of
    each relevant shape:

    - ``t``  plain stop         (continuant -, delrel -)   -> Plosive
    - ``s``  fricative          (continuant +, delrel +)   -> Fricative
    - ``ts`` collapse affricate (continuant -, delrel +, one phase:
             the shape PHOIBLE's whitelist gives ``ts``)   -> Affricate
    - ``cl`` contour affricate  (continuant / delrel / lateral all
             ``-,+`` across two phases: the shape PHOIBLE gives the
             lateral affricate ``tɬ``)                       -> Affricate
    - ``tr`` stop + sonorant    (continuant ``-,+`` but delrel ``-``:
             a closure releasing into a sonorant, not a fricated
             release, i.e. a cluster like ``tr`` / ``tl``)   -> NOT affricate
    """
    features = [
        "Consonantal",
        "Sonorant",
        "Continuant",
        "DelRel",
        "Nasal",
        "Lateral",
        "Strident",
    ]
    segments = {
        "t": {
            "Consonantal": "+", "Sonorant": "-", "Continuant": "-",
            "DelRel": "-", "Nasal": "-", "Lateral": "-", "Strident": "-",
        },
        "s": {
            "Consonantal": "+", "Sonorant": "-", "Continuant": "+",
            "DelRel": "+", "Nasal": "-", "Lateral": "-", "Strident": "+",
        },
        "ts": {
            "Consonantal": "+", "Sonorant": "-", "Continuant": "-",
            "DelRel": "+", "Nasal": "-", "Lateral": "-", "Strident": "+",
        },
        # Closure phase of the contour affricate / cluster; the fricated
        # (or sonorant) release lives in ``segment_secondary`` below.
        "cl": {
            "Consonantal": "+", "Sonorant": "-", "Continuant": "-",
            "DelRel": "-", "Nasal": "-", "Lateral": "-", "Strident": "-",
        },
        "tr": {
            "Consonantal": "+", "Sonorant": "-", "Continuant": "-",
            "DelRel": "-", "Nasal": "-", "Lateral": "-", "Strident": "-",
        },
    }
    secondary = {
        # Fricated lateral release: +continuant, +delrel, +lateral.
        "cl": {"continuant": "+", "delrel": "+", "lateral": "+"},
        # Sonorant release: +continuant only, NO delayed release.
        "tr": {"continuant": "+"},
    }
    return Inventory.parse(
        {
            "features": features,
            "segments": segments,
            "metadata": {"segment_secondary": secondary},
        }
    )


def test_collapse_affricate_is_classified() -> None:
    """A single-phase ``[-continuant, +delrel]`` obstruent (PHOIBLE's
    ``ts`` shape) is an affricate."""
    groups = FeatureEngine(_obstruent_inv()).grouped_segments
    assert "ts" in _affricates(groups), groups
    assert "ts" not in groups.get("Plosives", []), groups


def test_contour_affricate_is_classified() -> None:
    """A ``continuant`` + ``delrel`` contour obstruent (PHOIBLE's
    ``tɬ`` shape) is an affricate on the phase union, even though its
    closure phase alone looks like a plain stop."""
    groups = FeatureEngine(_obstruent_inv()).grouped_segments
    assert "cl" in _affricates(groups), groups
    assert "cl" not in groups.get("Plosives", []), groups


def test_stop_sonorant_cluster_is_not_affricate() -> None:
    """The robustness guard: a stop that releases into a sonorant
    (``tr`` / ``tl``) contours on ``continuant`` but carries no
    ``[+delrel]`` phase, so it is NOT an affricate. The old
    continuant-contour-alone rule wrongly swept these in."""
    groups = FeatureEngine(_obstruent_inv()).grouped_segments
    assert "tr" not in _affricates(groups), groups


def test_plain_stop_and_fricative_are_not_affricates() -> None:
    """The rule excludes both neighbours of the affricate class: a
    plain stop (no ``+delrel`` phase) and a fricative (no
    ``-continuant`` phase)."""
    groups = FeatureEngine(_obstruent_inv()).grouped_segments
    assert "t" in groups.get("Plosives", []), groups
    assert "t" not in _affricates(groups), groups
    assert "s" not in _affricates(groups), groups
    assert "s" not in groups.get("Plosives", []), groups


def test_secondary_feats_exposes_release_bundle() -> None:
    """The engine's per-segment release map carries the final-phase
    bundle for contour segments and nothing for single-phase ones; the
    grouper unions it with the primary bundle to see the whole
    segment."""
    eng = FeatureEngine(_obstruent_inv())
    sec = eng._secondary_feats_by_seg
    assert sec.get("cl", {}).get("continuant") == "+"
    assert sec.get("cl", {}).get("lateral") == "+"
    assert "ts" not in sec and "t" not in sec and "s" not in sec


def test_diphthong_contour_is_not_an_affricate() -> None:
    """The obstruent gate keeps the affricate rule off vowels: the
    ``ia`` diphthong has a release phase but is ``-consonantal``, so it
    never enters the Affricates class."""
    eng = FeatureEngine(_contour_inv())
    assert (
        "ia" in eng._secondary_feats_by_seg
    ), "diphthong should have a release phase"
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
