"""Formal (substance-free) membership for contour segments.

A genuinely multi-phase segment reaches several class specifications
across its phases. The engine answers membership as the QUANTIFIED
relations over those phases (existential / universal) read straight off
the tiers, and never by electing a "characteristic" phase to label the
segment by. These assertions name only quantifiers and specs, never a
privileged onset or offset, which is how they stay inside the
substance-free commitment (Bale & Reiss 2018; Reiss 2021).

The display grouper's ``Contour Consonants`` tag is a separate,
presentation-only convention: it must NOT leak into the engine's
membership relations, which keep answering from the tiers.
"""

from __future__ import annotations

from phonology_shared.chart.consonants import CONTOUR_GROUP_NAME
from phonology_shared.data.inventory import Inventory
from phonology_shared.data.tiers import (
    Attrs,
    align,
    member_exists,
    member_forall,
)
from phonology_shared.editor.phoible_features import partition_tiers
from phonology_shared.theory.feature_engine import FeatureEngine

# Class specs as bare feature bundles (no phase named anywhere).
_STOP = {"consonantal": "+", "sonorant": "-", "continuant": "-"}
_NASAL = {"sonorant": "+", "nasal": "+"}


def _quantified(tiers: dict[str, tuple[str, ...]], spec: dict[str, str]):
    """Return ``(exists, forall)`` for ``spec`` over ``tiers``."""
    attrs = Attrs(sorted(set(tiers) | set(spec)))
    alignment = align(attrs, tiers)
    return (
        member_exists(attrs, tiers, alignment, spec),
        member_forall(tiers, spec),
    )


def test_prenasalized_stop_is_existentially_stop_and_nasal_never_forall():
    """``mb`` reaches an oral-stop specification in one phase and a nasal
    specification in another. It is existentially a stop, existentially a
    nasal, and universally NEITHER: no single label is faithful, and the
    set theory refuses to pick one."""
    mb = {
        "consonantal": ("+",),
        "sonorant": ("+", "-"),
        "continuant": ("-",),
        "nasal": ("+", "-"),
    }
    stop_exists, stop_forall = _quantified(mb, _STOP)
    nasal_exists, nasal_forall = _quantified(mb, _NASAL)
    assert stop_exists is True
    assert nasal_exists is True
    assert stop_forall is False
    assert nasal_forall is False


def test_falling_diphthong_is_existentially_syllabic_and_not_never_forall():
    """A falling diphthong glides from ``[+syllabic]`` to
    ``[-syllabic]``: existentially syllabic, existentially non-syllabic,
    universally neither. Same one rule as the prenasalized stop, no
    onset/offset split."""
    diph = {
        "syllabic": ("+", "-"),
        "consonantal": ("-",),
        "high": ("-", "+"),
    }
    syll_plus_exists, syll_plus_forall = _quantified(diph, {"syllabic": "+"})
    syll_minus_exists, syll_minus_forall = _quantified(diph, {"syllabic": "-"})
    assert syll_plus_exists is True
    assert syll_minus_exists is True
    assert syll_plus_forall is False
    assert syll_minus_forall is False


def test_secondary_articulations_stay_single_phase():
    """``kʷ`` / ``kʲ`` / ``lʲ`` carry a lone PLACE-feature comma the
    source composed from a base plus a diacritic; it is not a timeline.
    ``partition_tiers`` creates no genuine contour and resolves the
    feature to the source's stated (last) value, so the segment stays
    single-phase and a query does not see a spurious base polarity."""
    # kʷ: labialized velar stop (labial -,+ is the only comma)
    primary, genuine = partition_tiers(
        {"Consonantal": ("+",), "Dorsal": ("+",), "Labial": ("-", "+")}
    )
    assert genuine == {}, genuine
    assert primary["Labial"] == "+"  # the ʷ articulation, not the base
    # kʲ / lʲ: palatalization writes a lone Dorsal comma
    for base in ("Consonantal", "Approximant"):
        _p, g = partition_tiers({base: ("+",), "Dorsal": ("-", "+")})
        assert g == {}, (base, g)


def test_prenasalized_stop_keeps_the_manner_comma_multiphase():
    """The SAME row that leaves ``kʷ`` single-phase keeps ``mb`` multi-
    phase, because its comma is on manner features (nasal / sonorant),
    which the source uses for a genuine temporal contour."""
    _primary, genuine = partition_tiers(
        {
            "Consonantal": ("+",),
            "Sonorant": ("+", "-"),
            "Continuant": ("-",),
            "Nasal": ("+", "-"),
        }
    )
    assert set(genuine) == {"Sonorant", "Nasal"}


def _mb_inventory() -> Inventory:
    feats = ["Consonantal", "Sonorant", "Continuant", "Nasal", "Syllabic"]
    segs = {
        "mb": {
            "Consonantal": "+",
            "Sonorant": "+",
            "Continuant": "-",
            "Nasal": "+",
            "Syllabic": "-",
        },
        "b": {
            "Consonantal": "+",
            "Sonorant": "-",
            "Continuant": "-",
            "Nasal": "-",
            "Syllabic": "-",
        },
        "m": {
            "Consonantal": "+",
            "Sonorant": "+",
            "Continuant": "-",
            "Nasal": "+",
            "Syllabic": "-",
        },
        "a": {
            "Consonantal": "-",
            "Sonorant": "+",
            "Continuant": "+",
            "Nasal": "-",
            "Syllabic": "+",
        },
    }
    return Inventory.from_grid(
        name="t",
        features=feats,
        segments=segs,
        metadata={
            "segment_sequences": {
                "mb": {"Sonorant": ["+", "-"], "Nasal": ["+", "-"]}
            }
        },
    )


def test_display_tag_does_not_leak_into_engine_membership():
    """The display grouper tags ``mb`` as a Contour Consonant, but that
    is a presentation label: the engine's ∃ query still returns ``mb``
    for BOTH the nasal feature and the oral-stop feature, answered from
    the tiers, never from the tag."""
    eng = FeatureEngine(_mb_inventory())
    place = {s: n for n, segs in eng.grouped_segments.items() for s in segs}
    assert place["mb"] == CONTOUR_GROUP_NAME
    # ∃ over the tiers: mb reaches +nasal (closure) AND -continuant, so
    # both queries return it; the tag never enters this computation.
    assert "mb" in eng.find_segments({"Nasal": "+"})
    assert "mb" in eng.find_segments({"Continuant": "-"})
    assert "mb" in eng.find_segments({"Sonorant": "-"})  # oral release
    # The tag is not a feature the engine can be queried on.
    assert CONTOUR_GROUP_NAME not in eng.grouped_segments.get("Nasals", [])
