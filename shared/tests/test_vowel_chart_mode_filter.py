"""Pins the vowel chart's per-cell diphthong classification.

The two-mode vowel chart (monophthong vs diphthong) filters cell
visibility by ``VowelChartCell.is_diphthong``. The flag must be
set ONLY for cells whose entries include true diphthongs --
segments whose secondary placement lands in a different (row,
col) from the primary.

The placer already enforces this via the degeneracy filter in
``compute_placements``: pharyngealised monophthongs like Archi
``/aˤ/``, ``/iˤ/`` appear in PHOIBLE's ``vowel_secondary``
metadata but their secondary collapses back to the primary cell,
so the ``PlacementFlag.DIPHTHONG`` flag is NOT set. The cell
classifier reads this flag, so false positives are excluded by
construction.

These tests pin that contract end-to-end across the geometry
build so the renderer-side filter (``cell.is_diphthong ==
(mode == DIPHTHONG)``) gets a trustworthy signal.
"""

from __future__ import annotations

import pytest

from phonology_shared.chart.vowels import (
    PlacementFlag,
    compute_placements,
    detect_vowel_profile,
)
from phonology_shared.chart.vowels_layout import (
    build_vowel_chart_geometry,
)


def _build_geometry(seg_feats, *, vowel_secondary=None):
    vowels = list(seg_feats)
    profile = detect_vowel_profile(vowels, seg_feats)
    return build_vowel_chart_geometry(
        vowels,
        profile,
        seg_feats,
        vowel_secondary=vowel_secondary,
    )


# ---------------------------------------------------------------------------
# Synthetic case: true diphthong + monophthong split
# ---------------------------------------------------------------------------


def test_true_diphthong_cell_is_flagged() -> None:
    """A cell containing a segment whose ``vowel_secondary`` puts
    the secondary at a DIFFERENT (row, col) than the primary
    must have ``is_diphthong=True``. Mirrors PHOIBLE's encoding
    of e.g. Korean ``/ia/`` (primary close-front, secondary
    open-central)."""
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
    vowel_secondary = {
        "ia": {
            "high": "-",
            "low": "+",
            "front": "-",
            "back": "-",
            "round": "-",
        },
    }
    geom = _build_geometry(seg_feats, vowel_secondary=vowel_secondary)
    by_seg = {seg: cell for cell in geom.cells for seg in cell.entries}
    assert "ia" in by_seg, "diphthong segment should land in some cell"
    diphthong_cell = by_seg["ia"]
    assert diphthong_cell.is_diphthong, (
        f"cell with /ia/ should be flagged as diphthong; "
        f"entries={diphthong_cell.entries}"
    )
    # Monophthong cells stay unflagged.
    if "i" in by_seg and by_seg["i"] is not diphthong_cell:
        assert not by_seg["i"].is_diphthong
    if "a" in by_seg and by_seg["a"] is not diphthong_cell:
        assert not by_seg["a"].is_diphthong


def test_no_vowel_secondary_means_no_diphthongs() -> None:
    """When the inventory carries no ``vowel_secondary`` metadata
    (user-created JSON inventory, no PHOIBLE encoding), zero
    cells get the diphthong flag regardless of segment-string
    length or diacritic count."""
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
    geom = _build_geometry(seg_feats, vowel_secondary=None)
    for cell in geom.cells:
        assert not cell.is_diphthong, (
            f"cell {cell.entries!r} flagged as diphthong without "
            f"any vowel_secondary metadata"
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
def test_korean_phoible_partitions_cleanly() -> None:
    """Korean PHOIBLE (id=2197) has both monophthongs and
    diphthongs. After the geometry builds, the cell list must
    partition: every diphthong-flagged cell should hold segments
    whose placements carry the DIPHTHONG flag; every unflagged
    cell should NOT."""
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
    vowel_secondary = inv.metadata.get("vowel_secondary")
    geom = build_vowel_chart_geometry(
        vowels,
        profile,
        seg_feats,
        vowel_secondary=(
            vowel_secondary if isinstance(vowel_secondary, dict) else None
        ),
    )
    # Cross-check against compute_placements: any segment with
    # ``PlacementFlag.DIPHTHONG`` should sit in a cell flagged
    # ``is_diphthong``.
    _occupied, placements = compute_placements(
        vowels,
        profile,
        seg_feats,
        vowel_secondary=(
            vowel_secondary if isinstance(vowel_secondary, dict) else None
        ),
    )
    diphthong_segments = {
        seg
        for seg, p in placements.items()
        if PlacementFlag.DIPHTHONG in p.flags
    }
    assert diphthong_segments, (
        "Korean PHOIBLE should have at least one diphthong; "
        "test fixture or PHOIBLE snapshot may have changed"
    )
    for cell in geom.cells:
        cell_has_diphthong = any(
            seg in diphthong_segments for seg in cell.entries
        )
        assert cell.is_diphthong == cell_has_diphthong, (
            f"cell {cell.entries!r} is_diphthong={cell.is_diphthong} "
            f"but contains diphthong-flagged segments? "
            f"{cell_has_diphthong}"
        )
    # The partition should be non-trivial: both flagged and
    # unflagged cells exist (Korean has both vowel classes).
    flagged = [c for c in geom.cells if c.is_diphthong]
    unflagged = [c for c in geom.cells if not c.is_diphthong]
    assert flagged, "expected at least one diphthong cell in Korean"
    assert unflagged, "expected at least one monophthong cell in Korean"


@pytest.mark.skipif(
    not _PHOIBLE_AVAILABLE,
    reason="PHOIBLE provider not importable",
)
def test_archi_pharyngeals_not_flagged_as_diphthongs() -> None:
    """Archi (PHOIBLE id=228) contains pharyngealised vowels
    /aˤ/, /iˤ/, /uˤ/, /eˤ/, /oˤ/ -- these appear in
    ``vowel_secondary`` but their secondary collapses to the
    primary cell, so the placer's degeneracy filter excludes
    them from ``PlacementFlag.DIPHTHONG``. The cell classifier
    must not flag them either."""
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
    vowel_secondary = inv.metadata.get("vowel_secondary")
    geom = build_vowel_chart_geometry(
        vowels,
        profile,
        seg_feats,
        vowel_secondary=(
            vowel_secondary if isinstance(vowel_secondary, dict) else None
        ),
    )
    # Archi has no TRUE diphthongs -- every cell should be
    # unflagged regardless of how many vowels appear in
    # ``vowel_secondary``.
    flagged = [c for c in geom.cells if c.is_diphthong]
    assert not flagged, (
        f"Archi PHOIBLE should have zero diphthong-flagged cells; "
        f"got {[c.entries for c in flagged]!r}. Pharyngealised "
        f"monophthongs must be excluded by the placer's "
        f"degeneracy filter."
    )
