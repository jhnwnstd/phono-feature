"""The PHOIBLE adapter: the single PHOIBLE-aware seam that turns a raw
feature row into canonical per-feature tiers, faithful and round-tripping,
surfacing malformed source rows instead of patching them.
"""

from __future__ import annotations

import pytest

from phonology_shared.editor.phoible_features import (
    partition_tiers,
    phoible_row_to_tiers,
    tiers_to_cells,
)


def test_maps_names_and_splits_contours_verbatim() -> None:
    row = {"syllabic": "-", "continuant": "-,+", "delayedRelease": "+"}
    tiers = phoible_row_to_tiers(row)
    assert tiers["Syllabic"] == ("-",)
    assert tiers["Continuant"] == ("-", "+")  # order preserved
    assert tiers["DelRel"] == ("+",)


def test_source_silence_omitted_but_asserted_zero_kept() -> None:
    """An empty / NA column is source silence (omitted); a stated ``0``
    is an asserted not-applicable and is kept as ``("0",)``."""
    row = {
        "continuant": "-",
        "delayedRelease": "0",
        "tone": "",
        "stress": "NA",
    }
    tiers = phoible_row_to_tiers(row)
    assert tiers["DelRel"] == ("0",)  # asserted N/A, present
    assert "Tone" not in tiers  # source silence
    assert "Stress" not in tiers


def test_round_trip_is_faithful_including_order() -> None:
    row = {"continuant": "-,+", "lateral": "-,+", "delayedRelease": "+"}
    cells = tiers_to_cells(phoible_row_to_tiers(row))
    assert cells["Continuant"] == "-,+"
    assert cells["Lateral"] == "-,+"
    assert cells["DelRel"] == "+"


def test_triphthong_tier_kept_whole_not_reduced() -> None:
    """A three-phase cell is kept verbatim, not reduced to endpoints."""
    tiers = phoible_row_to_tiers({"continuant": "-,-,+"})
    assert tiers["Continuant"] == ("-", "-", "+")
    assert tiers_to_cells(tiers)["Continuant"] == "-,-,+"


def test_rejects_token_outside_alphabet() -> None:
    with pytest.raises(ValueError, match="alphabet"):
        phoible_row_to_tiers({"continuant": "-,x"})


def test_rejects_constant_contour() -> None:
    """PHOIBLE writes a single value for a feature that does not change,
    so a ``+,+`` style constant contour is malformed and surfaces."""
    with pytest.raises(ValueError, match="constant contour"):
        phoible_row_to_tiers({"continuant": "+,+"})


# --------------------------------------------------------------------
# Duration is phase-forming. A ``long`` / ``short`` comma is the source
# stating how long each part of the segment is, not a base plus a
# diacritic, so it must reach the tier layer instead of collapsing onto
# one value. See ``_DURATION_PHASE_FEATURES``.
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,row,expected",
    [
        # PHOIBLE /iːe/: long first element, short second.
        (
            "long-first diphthong",
            {"syllabic": "+", "high": "+,-", "long": "+,-"},
            ("+", "-"),
        ),
        # PHOIBLE /iaː/: short first element, long second.
        (
            "long-last diphthong",
            {"syllabic": "+", "high": "+,-", "long": "-,+"},
            ("-", "+"),
        ),
        # PHOIBLE /mbː/: prenasalized geminate, a CONSONANT contour.
        (
            "geminate prenasalized stop",
            {
                "syllabic": "-",
                "nasal": "+,-",
                "sonorant": "+,-",
                "long": "-,+",
            },
            ("-", "+"),
        ),
        (
            "short contour",
            {"syllabic": "+", "high": "+,-", "short": "-,+"},
            ("-", "+"),
        ),
    ],
)
def test_duration_contour_survives_as_a_timeline(
    label: str, row: dict[str, str], expected: tuple[str, ...]
) -> None:
    """The duration sequence reaches ``genuine`` whole, on either major
    class, whichever phase is the long one."""
    feature = "Short" if "short" in row else "Long"
    _primary, genuine = partition_tiers(phoible_row_to_tiers(row))
    assert genuine[feature] == expected, label


def test_long_first_and_long_last_answer_the_same_way() -> None:
    """The regression this exists for. Both encodings state a long
    phase; collapsing to the LAST value made only the long-last one
    report ``+``, so /iaː/ answered a ``[+long]`` query and /iːe/ did
    not, decided purely by phase order. Reaching is what membership
    reads, so both must reach both polarities.
    """
    long_first = partition_tiers(
        phoible_row_to_tiers({"syllabic": "+", "high": "+,-", "long": "+,-"})
    )[1]["Long"]
    long_last = partition_tiers(
        phoible_row_to_tiers({"syllabic": "+", "high": "+,-", "long": "-,+"})
    )[1]["Long"]
    assert set(long_first) == set(long_last) == {"+", "-"}


def test_secondary_articulation_place_comma_still_collapses() -> None:
    """The duration change must not widen the gate. /kʷ/ has no manner
    contour; its ``labial`` comma is a base plus a ``ʷ`` overlay, so it
    stays single-phase with the stated modified value."""
    primary, genuine = partition_tiers(
        phoible_row_to_tiers(
            {
                "syllabic": "-",
                "consonantal": "+",
                "continuant": "-",
                "labial": "-,+",
            }
        )
    )
    assert genuine == {}
    assert primary["Labial"] == "+"


def test_duration_never_introduces_a_ragged_segment() -> None:
    """Why phasing duration is safe: PHOIBLE always states the duration
    sequence at the same length as the manner/quality contour beside it,
    so the added tier can never be the one that makes a segment
    Misaligned. Verified corpus-wide when the change landed; this pins
    the property on the shapes the corpus actually contains.
    """
    for row in (
        {"syllabic": "+", "high": "+,-", "long": "+,-"},
        {"syllabic": "-", "nasal": "+,-", "sonorant": "+,-", "long": "-,+"},
        {"syllabic": "+", "high": "+,+,-", "low": "-,-,+", "long": "-,-,+"},
    ):
        _primary, genuine = partition_tiers(phoible_row_to_tiers(row))
        assert len({len(seq) for seq in genuine.values()}) == 1


# --------------------------------------------------------------------
# Length agreement. A contour on a feature that is NOT phase-forming by
# name is still a timeline when the source already fixed a phase count
# without it and the contour states exactly that many values. Nothing
# below reads what a feature MEANS.
# --------------------------------------------------------------------


def test_place_contour_is_admitted_when_it_agrees_with_the_manner_timeline() -> (
    None
):
    """/tx/: `continuant` and `delayedRelease` fix 2 phases, `coronal`
    and `dorsal` state 2 values each, so the closure really is coronal
    and the release really is not. Collapsing stored the RELEASE place
    for both phases, which had the affricate's closure backwards."""
    _primary, genuine = partition_tiers(
        phoible_row_to_tiers(
            {
                "syllabic": "-",
                "consonantal": "+",
                "continuant": "-,+",
                "delayedRelease": "-,+",
                "coronal": "+,-",
                "dorsal": "-,+",
            }
        )
    )
    assert genuine["Coronal"] == ("+", "-")
    assert genuine["Dorsal"] == ("-", "+")


def test_voice_contour_is_admitted_on_a_prenasalized_stop() -> None:
    """/mp/ kept `nasal`/`sonorant` as a timeline while asserting one
    voicing value across BOTH phases, i.e. a voiceless nasal onset."""
    _primary, genuine = partition_tiers(
        phoible_row_to_tiers(
            {
                "syllabic": "-",
                "nasal": "+,-",
                "sonorant": "+,-",
                "periodicGlottalSource": "+,-",
            }
        )
    )
    assert genuine["Voice"] == ("+", "-")


def test_no_independent_phase_count_means_no_admission() -> None:
    """/kʷ/: `labial` is the ONLY contour, so nothing established a
    phase structure for it to agree with. It stays an overlay. This is
    the case the discriminator must NOT widen."""
    primary, genuine = partition_tiers(
        phoible_row_to_tiers(
            {
                "syllabic": "-",
                "consonantal": "+",
                "continuant": "-",
                "labial": "-,+",
            }
        )
    )
    assert genuine == {}
    assert primary["Labial"] == "+"


def test_two_non_core_contours_do_not_bootstrap_each_other() -> None:
    """/ŋm/: `labial` and `dorsal` agree in length with EACH OTHER but
    neither is phase-forming by name, so no phase count is established
    and both collapse. A doubly-articulated segment and a two-phase one
    are indistinguishable by length alone."""
    _primary, genuine = partition_tiers(
        phoible_row_to_tiers(
            {"syllabic": "-", "nasal": "+", "labial": "-,+", "dorsal": "+,-"}
        )
    )
    assert genuine == {}


def test_length_mismatch_is_not_admitted() -> None:
    """A 3-value contour against a 2-phase core states no column of that
    timeline. Admitting it would make the segment Misaligned, turning
    every multi-feature query over it UNDETERMINED."""
    _primary, genuine = partition_tiers(
        phoible_row_to_tiers(
            {
                "syllabic": "-",
                "consonantal": "+",
                "continuant": "-,+",
                "dorsal": "0,-,+",
            }
        )
    )
    assert "Dorsal" not in genuine


def test_ragged_core_licenses_nothing() -> None:
    """When the phase-forming contours THEMSELVES disagree on length the
    source already underdetermines the timeline, so it cannot license an
    admission. (PHOIBLE's lateral-release clicks: `lateral` 3 long,
    `continuant` 2.)"""
    _primary, genuine = partition_tiers(
        phoible_row_to_tiers(
            {
                "syllabic": "-",
                "consonantal": "+",
                "continuant": "-,+",
                "lateral": "-,+,-",
                "coronal": "+,-",
            }
        )
    )
    assert "Coronal" not in genuine


def test_zero_inside_an_admitted_sequence_stays_unvalued() -> None:
    """Partiality is preserved. Where the source declines to value a
    feature in a phase it writes `0` there; admitting the sequence keeps
    that phase unvalued instead of handing it the last phase's value."""
    _primary, genuine = partition_tiers(
        phoible_row_to_tiers(
            {
                "syllabic": "-",
                "consonantal": "+",
                "continuant": "-,+,+",
                "delayedRelease": "-,+,+",
                "distributed": "0,+,-",
            }
        )
    )
    assert genuine["Distributed"] == ("0", "+", "-")
