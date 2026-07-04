"""The PHOIBLE adapter: the single PHOIBLE-aware seam that turns a raw
feature row into canonical per-feature tiers, faithful and round-tripping,
surfacing malformed source rows instead of patching them.
"""

from __future__ import annotations

import pytest

from phonology_shared.editor.phoible_features import (
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
