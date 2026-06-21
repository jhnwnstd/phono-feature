"""Pins the vowel chart's per-cell diphthong classification.

The two-mode vowel chart (monophthong vs diphthong) filters cell
visibility by ``VowelChartCell.is_diphthong``. The flag must be
set ONLY for cells whose entries include true diphthongs:
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

from phonology_shared.chart.vowel_geometry import build_vowel_chart_geometry
from phonology_shared.chart.vowels import (
    PlacementFlag,
    compute_placements,
    detect_vowel_profile,
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


def test_true_diphthong_does_not_occupy_a_cell() -> None:
    """A segment whose ``vowel_secondary`` puts the secondary at
    a DIFFERENT (row, col) than the primary is a TRUE diphthong
    and renders as an arrow + chip strip entry exclusively. It
    does NOT appear in any chart cell.

    Mirrors PHOIBLE's encoding of e.g. Korean ``/ia/`` (primary
    close-front, secondary open-central). The architectural fix
    keeps /ia/ in ``placements`` (so the arrow build reads its
    endpoints) but NOT in ``occupied``.

    Pre-fix /ia/ landed in /i/'s cell, so the cell stack showed
    /i/ and /ia/ together, visually grouping the singleton
    monophthong with the diphthong, contrary to the user's
    mental model.
    """
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
    assert "ia" not in by_seg, (
        f"diphthong /ia/ must NOT occupy a cell; landed in "
        f"{by_seg.get('ia').entries if 'ia' in by_seg else None!r}"
    )
    # Monophthongs DO occupy cells.
    assert "i" in by_seg, "monophthong /i/ should land in some cell"
    assert "a" in by_seg, "monophthong /a/ should land in some cell"
    # Cells contain only monophthongs, so no cell is flagged.
    for cell in geom.cells:
        assert not cell.is_diphthong, (
            f"cell {cell.entries!r} should not be flagged as "
            f"diphthong (diphthongs no longer occupy cells)"
        )
    # The diphthong is still in the geometry's diphthong list
    # for arrow rendering.
    assert any(d.segment == "ia" for d in geom.diphthongs), (
        "diphthong /ia/ should appear in geometry.diphthongs for "
        "arrow rendering even though it doesn't occupy a cell"
    )


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
def test_korean_phoible_diphthongs_render_as_arrows_not_cells() -> None:
    """Korean PHOIBLE (id=2197) has 12 diphthongs (/io, iu, ia,
    ie, iɛ, iʌ, ɯi, ua, ue, ui, uɛ, uʌ/) plus 16 monophthongs
    (/i, ɯ, u, ɛ, e, əː, a, ʌ, o/ + their long counterparts).

    After the placer architectural fix: diphthongs render as
    ARROWS + chip strip; they don't occupy chart cells. Every
    cell.entries contains only monophthongs. The diphthong
    segments still appear in ``geom.diphthongs`` so the arrow
    overlay can read their endpoint coords.

    Pre-fix the diphthongs landed in the same cell as their
    primary vowel: cell (0,5) packed /u, ua, ue, ui, uɛ, uʌ, uː/
    together; the user complaint "singleton segments are
    grouped as diphthongs" surfaced this. The fix removes
    diphthongs from ``occupied`` so cells hold only true
    monophthongs.

    """
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
        f"diphthongs leaked into chart cells: {leaked!r}. The "
        f"placer's PlacementFlag.DIPHTHONG gate in "
        f"compute_placements should exclude these from ``occupied``."
    )
    # No cell carries the (now vestigial) is_diphthong flag.
    for cell in geom.cells:
        assert not cell.is_diphthong, (
            f"cell {cell.entries!r} flagged as diphthong; "
            f"diphthongs no longer occupy cells, so the flag "
            f"should never be True"
        )
    # Every diphthong segment is represented in geom.diphthongs.
    geom_diph_segs = {d.segment for d in geom.diphthongs}
    missing = diphthong_segments - geom_diph_segs
    assert not missing, (
        f"diphthongs missing from geom.diphthongs: {missing!r}. "
        f"Arrow rendering depends on this list."
    )
    # Cells are non-empty (monophthongs still place).
    assert geom.cells, "Korean monophthongs should populate cells"


@pytest.mark.skipif(
    not _PHOIBLE_AVAILABLE,
    reason="PHOIBLE provider not importable",
)
def test_archi_pharyngeals_not_flagged_as_diphthongs() -> None:
    """Archi (PHOIBLE id=228) contains pharyngealised vowels
    /aˤ/, /iˤ/, /uˤ/, /eˤ/, /oˤ/; these appear in
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
    # Archi has no TRUE diphthongs; every cell should be
    # unflagged regardless of how many vowels appear in
    # ``vowel_secondary``.
    flagged = [c for c in geom.cells if c.is_diphthong]
    assert not flagged, (
        f"Archi PHOIBLE should have zero diphthong-flagged cells; "
        f"got {[c.entries for c in flagged]!r}. Pharyngealised "
        f"monophthongs must be excluded by the placer's "
        f"degeneracy filter."
    )


# ---------------------------------------------------------------------------
# Cell.is_diphthong derivation invariant
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _PHOIBLE_AVAILABLE,
    reason="PHOIBLE provider not importable",
)
def test_cell_is_diphthong_matches_placement_flag_invariant() -> None:
    """INVARIANT: for every populated cell,
    ``cell.is_diphthong == any(PlacementFlag.DIPHTHONG in
    placements[seg].flags for seg in cell.entries)``.

    The cell-level flag is computed in
    ``build_vowel_chart_geometry`` by reading the placement-level
    flags. The two layers are currently independent; this test
    pins their relationship so a future refactor that touches
    either layer can't drift them apart without failing CI.
    """
    p = PhoibleProvider()
    if not getattr(p, "has_data", False):
        pytest.skip("PHOIBLE data snapshot absent")
    # Korean has a mix of diphthong and monophthong cells; ideal
    # for exercising the invariant on both branches.
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
    _occupied, placements = compute_placements(
        vowels,
        profile,
        seg_feats,
        vowel_secondary=(
            vowel_secondary if isinstance(vowel_secondary, dict) else None
        ),
    )
    for cell in geom.cells:
        expected = any(
            seg in placements
            and PlacementFlag.DIPHTHONG in placements[seg].flags
            for seg in cell.entries
        )
        assert cell.is_diphthong == expected, (
            f"is_diphthong invariant broken at cell {cell.entries!r}: "
            f"cell.is_diphthong={cell.is_diphthong} but "
            f"any(placement DIPHTHONG flag)={expected}. The "
            f"cell-level flag derivation in "
            f"build_vowel_chart_geometry drifted from the "
            f"placement-level flag in compute_placements."
        )
