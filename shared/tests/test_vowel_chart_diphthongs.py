"""Pins the vowel chart's diphthong handling.

Diphthongs (PHOIBLE contour vowels: a ``segment_secondary`` whose
secondary placement lands in a DIFFERENT (row, col) from the
primary) are NOT placed in the trapezoid. They are surfaced as a
labelled chip strip below the vowel space, and the geometry lists
their segment names in ``VowelChartGeometry.diphthongs`` (a tuple
of strings).

The placer's degeneracy filter in ``compute_placements`` excludes
contours that collapse to a single cell (pharyngealised
monophthongs like Archi ``/aˤ/``, ``/iˤ/``), so those are not
treated as diphthongs. These tests pin that contract end-to-end
across the geometry build.
"""

from __future__ import annotations

import pytest

from phonology_shared.chart.vowel_geometry import build_vowel_chart_geometry
from phonology_shared.chart.vowels import (
    PlacementFlag,
    compute_placements,
    detect_vowel_profile,
)


def _build_geometry(seg_feats, *, segment_secondary=None):
    vowels = list(seg_feats)
    profile = detect_vowel_profile(vowels, seg_feats)
    return build_vowel_chart_geometry(
        vowels,
        profile,
        seg_feats,
        segment_secondary=segment_secondary,
    )


# ---------------------------------------------------------------------------
# Synthetic case: true diphthong + monophthong split
# ---------------------------------------------------------------------------


def test_true_diphthong_does_not_occupy_a_cell() -> None:
    """A segment whose ``segment_secondary`` puts the secondary at a
    DIFFERENT (row, col) than the primary is a TRUE diphthong: it
    appears in ``geometry.diphthongs`` (the chip list) and NOT in any
    chart cell. Monophthongs do occupy cells."""
    seg_feats = {
        "i": {
            "high": "+",
            "low": "-",
            "front": "+",
            "back": "-",
            "round": "-",
            "tense": "+",
        },
        "a": {
            "high": "-",
            "low": "+",
            "front": "-",
            "back": "-",
            "round": "-",
        },
        # Synthetic diphthong /ia/: primary at /i/ position,
        # secondary at /a/ position.
        "ia": {
            "high": "+",
            "low": "-",
            "front": "+",
            "back": "-",
            "round": "-",
            "tense": "+",
        },
    }
    segment_secondary = {
        "ia": {
            "high": "-",
            "low": "+",
            "front": "-",
            "back": "-",
            "round": "-",
        },
    }
    geom = _build_geometry(seg_feats, segment_secondary=segment_secondary)
    by_seg = {seg: cell for cell in geom.cells for seg in cell.entries}
    assert "ia" not in by_seg, (
        f"diphthong /ia/ must NOT occupy a cell; landed in "
        f"{by_seg.get('ia').entries if 'ia' in by_seg else None!r}"
    )
    # Monophthongs DO occupy cells.
    assert "i" in by_seg, "monophthong /i/ should land in some cell"
    assert "a" in by_seg, "monophthong /a/ should land in some cell"
    # The diphthong is in the geometry's diphthong list (segment names).
    assert "ia" in geom.diphthongs, (
        "diphthong /ia/ should appear in geometry.diphthongs (the "
        "chip list) even though it doesn't occupy a cell"
    )


def test_no_segment_secondary_means_no_diphthongs() -> None:
    """When the inventory carries no ``segment_secondary`` metadata
    (user-created JSON inventory, no PHOIBLE encoding), the diphthong
    list is empty regardless of segment-string length or diacritic
    count."""
    seg_feats = {
        "i": {
            "high": "+",
            "low": "-",
            "front": "+",
            "back": "-",
            "round": "-",
        },
        # Diacritic-heavy monophthongs that LOOK like multi-char
        # segments but aren't diphthongs.
        "ã": {
            "high": "-",
            "low": "+",
            "front": "-",
            "back": "-",
            "round": "-",
            "nasal": "+",
        },
        "aː": {
            "high": "-",
            "low": "+",
            "front": "-",
            "back": "-",
            "round": "-",
            "long": "+",
        },
        "ɚ": {
            "high": "-",
            "low": "-",
            "front": "-",
            "back": "-",
            "round": "-",
            "rhotic": "+",
        },
    }
    geom = _build_geometry(seg_feats, segment_secondary=None)
    assert geom.diphthongs == (), (
        f"no segment_secondary should mean no diphthongs; got "
        f"{geom.diphthongs!r}"
    )


# ---------------------------------------------------------------------------
# Real-world PHOIBLE corpora
# ---------------------------------------------------------------------------


_PHOIBLE_AVAILABLE = True
try:
    from phonology_shared.editor.phoible_provider import (
        PhoibleProvider,
        materialize_phoible_inventory,
    )
    from phonology_shared.theory.feature_engine import FeatureEngine
except Exception:
    _PHOIBLE_AVAILABLE = False


@pytest.mark.skipif(
    not _PHOIBLE_AVAILABLE,
    reason="PHOIBLE provider not importable",
)
def test_korean_phoible_diphthongs_are_chips_not_cells() -> None:
    """Korean PHOIBLE (id=2197) has 12 diphthongs plus its
    monophthongs. The diphthongs are listed in ``geom.diphthongs``
    (the chip list) and never leak into chart cells; every
    ``cell.entries`` holds only monophthongs."""
    p = PhoibleProvider()
    if not getattr(p, "has_data", False):
        pytest.skip("PHOIBLE data snapshot absent")
    inv = materialize_phoible_inventory(p, "2197")
    engine = FeatureEngine(inv)
    vowels = list(engine.grouped_segments.get("Vowels", []))
    if not vowels:
        pytest.skip("Korean PHOIBLE has no vowels (unexpected)")
    seg_feats = {s: dict(engine.normalized_segment_feats[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    segment_secondary = inv.metadata.get("segment_secondary")
    vsec = segment_secondary if isinstance(segment_secondary, dict) else None
    geom = build_vowel_chart_geometry(
        vowels, profile, seg_feats, segment_secondary=vsec
    )
    _occupied, placements = compute_placements(
        vowels, profile, seg_feats, segment_secondary=vsec
    )
    diphthong_segments = {
        seg
        for seg, pl in placements.items()
        if PlacementFlag.DIPHTHONG in pl.flags
    }
    assert diphthong_segments, (
        "Korean PHOIBLE should have at least one diphthong; "
        "test fixture or PHOIBLE snapshot may have changed"
    )
    # No diphthong-flagged segment may appear in any cell.entries.
    cells_segs = {seg for cell in geom.cells for seg in cell.entries}
    leaked = diphthong_segments & cells_segs
    assert not leaked, (
        f"diphthongs leaked into chart cells: {leaked!r}. The placer's "
        f"PlacementFlag.DIPHTHONG gate should exclude these from "
        f"``occupied``."
    )
    # Every diphthong segment is represented in geom.diphthongs.
    missing = diphthong_segments - set(geom.diphthongs)
    assert not missing, (
        f"diphthongs missing from geom.diphthongs: {missing!r}. "
        f"The chip list depends on this."
    )
    assert geom.cells, "Korean monophthongs should populate cells"


@pytest.mark.skipif(
    not _PHOIBLE_AVAILABLE,
    reason="PHOIBLE provider not importable",
)
def test_archi_pharyngeals_not_treated_as_diphthongs() -> None:
    """Archi (PHOIBLE id=228) contains pharyngealised vowels that
    appear in ``segment_secondary`` but whose secondary collapses to
    the primary cell, so the placer's degeneracy filter excludes
    them. The diphthong list must be empty."""
    p = PhoibleProvider()
    if not getattr(p, "has_data", False):
        pytest.skip("PHOIBLE data snapshot absent")
    inv = materialize_phoible_inventory(p, "228")
    engine = FeatureEngine(inv)
    vowels = list(engine.grouped_segments.get("Vowels", []))
    if not vowels:
        pytest.skip("Archi PHOIBLE has no vowels (unexpected)")
    seg_feats = {s: dict(engine.normalized_segment_feats[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    segment_secondary = inv.metadata.get("segment_secondary")
    vsec = segment_secondary if isinstance(segment_secondary, dict) else None
    geom = build_vowel_chart_geometry(
        vowels, profile, seg_feats, segment_secondary=vsec
    )
    assert geom.diphthongs == (), (
        f"Archi PHOIBLE should have zero diphthongs (pharyngealised "
        f"monophthongs are filtered); got {geom.diphthongs!r}"
    )
