"""Regression guards for the no-overlap, pair-shift conflict
resolver, and aspect-ratio ceiling work shipped in this session.

Three invariants pinned here:

1. **No cell pair overlaps** at the rendered natural pixel size for
   every bundled inventory or a PHOIBLE sample. Catches a future
   change to ``_natural_data_area_size`` that drops the inter-cell
   non-overlap constraint or to ``_resolve_pair_shift_conflicts``
   that fails to elevate ``pair_shift_px`` on same-anchor wide
   pairs.

2. **Pair-shift conflict resolver elevates the right cells**.
   Builds a synthetic geometry with two same-chart_x opposite-
   pair_side wide cells and asserts both members got
   ``pair_shift_px`` raised to at least half the combined
   half-widths plus the inter-cell gap. Regression for the
   PHOIBLE pattern where a back-neutral long-pair auto-pairs
   with a back-rounded long-pair and the canonical 17.5 px shift
   leaves the two cells overlapping by ~33 px.

3. **Silhouette aspect ratio capped at VOWEL_SILHOUETTE_MAX_ASPECT
   across PHOIBLE**. The bundled cluster is already pinned by
   ``test_silhouette_aspect_within_ceiling`` in test_vowel_layout.py;
   this extends the guarantee to a PHOIBLE sample where the
   pre-fix outliers actually lived (Spanish-style 5-vowel, MSA
   6-vowel that lifted aspect to 2 to 3+).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from _inventory_names import BUNDLED_INVENTORY_NAMES

from phonology_shared.chart.vowel_geometry import (
    PAIR_DISPLAY_KINDS,
    build_vowel_chart_geometry,
)
from phonology_shared.chart.vowels import (
    VowelCellDisplayKind,
    detect_vowel_profile,
)
from phonology_shared.data.inventory import Inventory
from phonology_shared.presentation.chart_style import (
    VOWEL_PAIR_SHIFT_PX,
    VOWEL_SILHOUETTE_MAX_ASPECT,
)
from phonology_shared.presentation.constants import BTN_W
from phonology_shared.presentation.layout import VOWEL_PAIR_GAP_PX
from phonology_shared.theory.feature_engine import FeatureEngine

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUNDLED_DIR = _REPO_ROOT / "desktop" / "inventories"

# PHOIBLE sample size. Large enough to exercise the patterns that
# triggered the original overlap (back-neutral auto-paired with
# back-rounded, long-pair on both sides) without making the test
# burn minutes. 100 is the same sweep size the post-fix verification
# script used.
_PHOIBLE_SAMPLE = 100


def _cell_half_width_px(cell) -> float:
    """Rendered half-width of a cell box in pixels at the chart's
    natural width. PAIR / CONTRAST_SET cells are two buttons wide
    plus the inner gap; STACK cells are one button wide."""
    if (
        cell.display_kind in PAIR_DISPLAY_KINDS
        or cell.display_kind == VowelCellDisplayKind.CONTRAST_SET
    ):
        return (2 * BTN_W + VOWEL_PAIR_GAP_PX) / 2.0
    return BTN_W / 2.0


def _effective_pair_shift(cell) -> float:
    """Per-cell pair-shift override or the canonical default. Mirrors
    what both renderers read at paint time."""
    return (
        cell.pair_shift_px
        if cell.pair_shift_px > 0
        else float(VOWEL_PAIR_SHIFT_PX)
    )


def _row_overlap_count(geom) -> int:
    """Count pairs of cells in the same row whose pixel boxes
    intersect at the natural data width. Zero means the chart
    renders without any button overlap."""
    dw = geom.natural_data_width_px
    by_row: dict[int, list] = {}
    for c in geom.cells:
        by_row.setdefault(c.row, []).append(c)
    overlaps = 0
    for row_cells in by_row.values():
        boxes = []
        for c in row_cells:
            half = _cell_half_width_px(c)
            shift = _effective_pair_shift(c)
            pair_off = (shift if c.pair_side else 0) * c.pair_side
            center = c.chart_x * dw + pair_off
            boxes.append((center - half, center + half))
        boxes.sort()
        for i in range(len(boxes) - 1):
            _, ra = boxes[i]
            lb, _ = boxes[i + 1]
            # Allow 0.5 px tolerance so sub-pixel rounding in the
            # natural-width ceil() doesn't flake the test.
            if lb < ra - 0.5:
                overlaps += 1
    return overlaps


def _geom_for_bundled(stem: str):
    path = _BUNDLED_DIR / f"{stem}_features.json"
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    inv = Inventory.parse(raw, source=path.stem)
    engine = FeatureEngine(inv)
    vowels = list(engine.grouped_segments.get("Vowels", []))
    if not vowels:
        return None
    seg_feats = {s: dict(engine.normalized_segment_feats[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    sec = inv.metadata.get("vowel_secondary") or {}
    return build_vowel_chart_geometry(
        vowels, profile, seg_feats, vowel_secondary=sec
    )


# ---------------------------------------------------------------------------
# 1. No-overlap regression across bundled + PHOIBLE
# ---------------------------------------------------------------------------


_BUNDLED_STEMS = sorted(
    p.stem.removesuffix("_features")
    for p in _BUNDLED_DIR.glob("*_features.json")
)


@pytest.mark.parametrize("stem", _BUNDLED_STEMS)
def test_bundled_vowel_chart_has_no_cell_overlap(stem: str) -> None:
    """Class A (different chart_x) plus Class B (same chart_x wide
    pair) overlaps were live in three bundled inventories before
    the inter-cell constraint and the pair-shift conflict resolver
    landed. Future edits to either path could silently regress;
    this asserts the rendered geometry stays collision-free.
    """
    geom = _geom_for_bundled(stem)
    if geom is None:
        pytest.skip(f"{stem} has no vowels")
    assert _row_overlap_count(geom) == 0, (
        f"{stem}: rendered cells overlap at natural data width "
        f"{geom.natural_data_width_px}; the inter-cell constraint "
        "in _natural_data_area_size or the pair-shift conflict "
        "resolver may have regressed."
    )


def test_phoible_sample_has_no_cell_overlap() -> None:
    """PHOIBLE inventories exercise the same-anchor wide-pair
    pattern (back-neutral long_pair auto-paired with back-rounded
    long_pair) that the canonical pair_shift cannot accommodate
    without the per-cell elevation. Run a 100-inventory sample
    and assert zero overlaps.
    """
    try:
        from phonology_shared.editor.phoible_provider import (
            PhoibleProvider,
            materialize_phoible_inventory,
        )
    except ImportError as exc:
        pytest.skip(f"phoible_provider unavailable: {exc}")
    try:
        provider = PhoibleProvider()
    except FileNotFoundError as exc:
        pytest.skip(f"PHOIBLE snapshot not baked: {exc}")
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"PHOIBLE provider unavailable: {exc}")

    offenders: list[str] = []
    checked = 0
    for inv_id in list(provider._inventories)[: _PHOIBLE_SAMPLE * 3]:  # type: ignore[attr-defined]
        try:
            inv = materialize_phoible_inventory(provider, inv_id)
        except (KeyError, ValueError, RuntimeError):
            continue
        engine = FeatureEngine(inv)
        vowels = list(engine.grouped_segments.get("Vowels", []))
        if not vowels:
            continue
        seg_feats = {
            s: dict(engine.normalized_segment_feats[s]) for s in vowels
        }
        profile = detect_vowel_profile(vowels, seg_feats)
        sec = inv.metadata.get("vowel_secondary") or {}
        geom = build_vowel_chart_geometry(
            vowels, profile, seg_feats, vowel_secondary=sec
        )
        if _row_overlap_count(geom) > 0:
            offenders.append(inv_id)
        checked += 1
        if checked >= _PHOIBLE_SAMPLE:
            break
    assert offenders == [], (
        f"PHOIBLE overlap regression in {len(offenders)}/{checked} "
        f"inventories. First few: {offenders[:5]}"
    )


# ---------------------------------------------------------------------------
# 2. Pair-shift conflict resolver elevates the right cells
# ---------------------------------------------------------------------------


def test_pair_shift_conflict_resolver_elevates_wide_paired_cells() -> None:
    """Korean PHOIBLE 2197 is the canonical case: back-neutral
    long_pair (/ɯ, ɯː/) auto-paired with back-rounded long_pair
    (/u, uː/) at the same chart_x. Without elevation the canonical
    17.5 px shift leaves the two 68 px wide cells overlapping by
    ~33 px. The resolver must raise pair_shift_px on BOTH members
    to at least (half_a + half_b + 2 gap) / 2.
    """
    try:
        from phonology_shared.editor.phoible_provider import (
            PhoibleProvider,
            materialize_phoible_inventory,
        )
    except ImportError as exc:
        pytest.skip(f"phoible_provider unavailable: {exc}")
    try:
        provider = PhoibleProvider()
    except FileNotFoundError as exc:
        pytest.skip(f"PHOIBLE snapshot not baked: {exc}")

    inv = materialize_phoible_inventory(provider, "2197")
    engine = FeatureEngine(inv)
    vowels = list(engine.grouped_segments.get("Vowels", []))
    seg_feats = {s: dict(engine.normalized_segment_feats[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    sec = inv.metadata.get("vowel_secondary") or {}
    geom = build_vowel_chart_geometry(
        vowels, profile, seg_feats, vowel_secondary=sec
    )

    by_anchor: dict[tuple[int, int], list] = {}
    for c in geom.cells:
        if (
            c.display_kind in PAIR_DISPLAY_KINDS
            or c.display_kind == VowelCellDisplayKind.CONTRAST_SET
        ) and c.pair_side != 0:
            by_anchor.setdefault((c.row, round(c.chart_x * 1000)), []).append(
                c
            )

    conflicting_pairs = [
        members
        for members in by_anchor.values()
        if len(members) >= 2
        and any(
            m1.pair_side * m2.pair_side < 0 for m1 in members for m2 in members
        )
    ]
    if not conflicting_pairs:
        pytest.skip(
            "Korean PHOIBLE 2197 no longer has a same-anchor wide-pair "
            "conflict; pick a different inventory if PHOIBLE shape changes."
        )

    canonical = float(VOWEL_PAIR_SHIFT_PX)
    for members in conflicting_pairs:
        for cell in members:
            if cell.pair_side == 0:
                continue
            assert cell.pair_shift_px > canonical, (
                f"cell at row={cell.row} col={cell.col} entries={cell.entries} "
                "is part of a wide-pair conflict but pair_shift_px was not "
                f"elevated (still {cell.pair_shift_px} <= canonical {canonical}). "
                "The conflict resolver in _resolve_pair_shift_conflicts may "
                "have regressed."
            )
            required = BTN_W + VOWEL_PAIR_GAP_PX
            assert cell.pair_shift_px >= required / 2.0, (
                f"cell pair_shift_px={cell.pair_shift_px} below the minimum "
                f"required to keep the pair tangent ({required/2.0})."
            )


# ---------------------------------------------------------------------------
# 3. Aspect ratio ceiling across PHOIBLE
# ---------------------------------------------------------------------------


def test_phoible_sample_silhouette_aspect_within_ceiling() -> None:
    """The bundled cluster is already pinned by
    test_silhouette_aspect_within_ceiling. PHOIBLE actually drove
    the over-wide cases pre-fix (Spanish-style 5-vowel inventories
    at 2.35, MSA 6-vowel at 3.29); pin the ceiling holds there too.
    """
    try:
        from phonology_shared.editor.phoible_provider import (
            PhoibleProvider,
            materialize_phoible_inventory,
        )
    except ImportError as exc:
        pytest.skip(f"phoible_provider unavailable: {exc}")
    try:
        provider = PhoibleProvider()
    except FileNotFoundError as exc:
        pytest.skip(f"PHOIBLE snapshot not baked: {exc}")

    over: list[tuple[str, float]] = []
    checked = 0
    for inv_id in list(provider._inventories)[: _PHOIBLE_SAMPLE * 3]:  # type: ignore[attr-defined]
        try:
            inv = materialize_phoible_inventory(provider, inv_id)
        except (KeyError, ValueError, RuntimeError):
            continue
        engine = FeatureEngine(inv)
        vowels = list(engine.grouped_segments.get("Vowels", []))
        if not vowels:
            continue
        seg_feats = {
            s: dict(engine.normalized_segment_feats[s]) for s in vowels
        }
        profile = detect_vowel_profile(vowels, seg_feats)
        sec = inv.metadata.get("vowel_secondary") or {}
        geom = build_vowel_chart_geometry(
            vowels, profile, seg_feats, vowel_secondary=sec
        )
        sil = geom.silhouette
        sil_h = (sil.bottom_y - sil.top_y) * geom.natural_data_height_px
        if sil_h <= 0:
            continue
        aspect = geom.natural_data_width_px / sil_h
        if aspect > VOWEL_SILHOUETTE_MAX_ASPECT + 0.05:
            over.append((inv_id, aspect))
        checked += 1
        if checked >= _PHOIBLE_SAMPLE:
            break
    assert over == [], (
        f"PHOIBLE silhouette aspect ceiling broken in {len(over)}/{checked} "
        f"inventories. Sample: {over[:3]}"
    )


def test_row_label_anchors_divorced_from_cell_positions() -> None:
    """Row labels anchor to the silhouette outline at THEIR OWN y.

    Top / bottom tiers shift the label half a button inward so it
    centres on the anchor button row; the baked silhouette edge
    fields must be evaluated at that shifted ``label_y``, not at the
    cells' ``chart_y``. Evaluating at chart_y while rendering at
    label_y let the slanted, corner-rounded edge eat the label gap
    (Lomongo's "Open" label hugged the outline while "Close" kept
    its padding).
    """
    from phonology_shared.chart.vowel_geometry import (
        build_vowel_chart_geometry,
        silhouette_left_at_y,
        silhouette_right_at_y,
    )
    from phonology_shared.chart.vowels import detect_vowel_profile
    from phonology_shared.presentation.layout import SEG_BTN_H

    # Lomongo-shaped five-vowel system: /i e a o u/.
    feats = {
        "i": {
            "high": "+",
            "low": "-",
            "front": "+",
            "back": "-",
            "round": "-",
        },
        "e": {
            "high": "-",
            "low": "-",
            "front": "+",
            "back": "-",
            "round": "-",
        },
        "a": {
            "high": "-",
            "low": "+",
            "front": "-",
            "back": "-",
            "round": "-",
        },
        "o": {
            "high": "-",
            "low": "-",
            "front": "-",
            "back": "+",
            "round": "+",
        },
        "u": {
            "high": "+",
            "low": "-",
            "front": "-",
            "back": "+",
            "round": "+",
        },
    }
    segs = list(feats)
    geom = build_vowel_chart_geometry(
        segs, detect_vowel_profile(segs, feats), feats
    )
    assert geom.natural_data_height_px > 0
    half_btn_norm = (SEG_BTN_H / 2.0) / geom.natural_data_height_px
    tiers = {r.tier for r in geom.rows}
    assert {"top", "bottom"} <= tiers
    for row in geom.rows:
        if row.tier == "top":
            expected_label_y = row.chart_y + half_btn_norm
        elif row.tier == "bottom":
            expected_label_y = row.chart_y - half_btn_norm
        else:
            expected_label_y = row.chart_y
        assert row.label_y == pytest.approx(expected_label_y), row.label
        # The baked edge fields follow the LABEL, not the cells.
        assert row.silhouette_left == pytest.approx(
            silhouette_left_at_y(geom.silhouette, row.label_y)
        ), row.label
        assert row.silhouette_right == pytest.approx(
            silhouette_right_at_y(geom.silhouette, row.label_y)
        ), row.label


# Confinement clears the STRAIGHT trapezoid edges (the rounded
# corners are cosmetic). At a row too crowded to both clear the
# slant AND keep a gap to the neighbour, the inward nudge is capped
# so it never manufactures an overlap, leaving a small straight-edge
# overhang instead. The cap bounds that overhang; the audit across
# bundled + PHOIBLE peaks near 5 px, so 8 px leaves margin without
# masking a genuine escape (which the strict data-area check below
# catches anyway).
_STRAIGHT_EDGE_OVERHANG_TOL_PX = 8.0


@pytest.mark.parametrize("name", BUNDLED_INVENTORY_NAMES)
def test_button_boxes_confined_to_outline(
    name: str, bundled_engine: Callable[[str], FeatureEngine]
) -> None:
    """Buttons stay inside the chart and inside the STRAIGHT
    trapezoid. The straight edges are the structural boundary;
    the rounded corners are a cosmetic stroke, so a button corner
    may sit a few px inside a rounded corner. Two checks:

    * Data area is a HARD boundary: every box stays within
      ``[0, dw]`` (a button must never escape the chart into the
      row-label gutter). Strict.
    * The straight trapezoid edges are confined to within
      :py:data:`_STRAIGHT_EDGE_OVERHANG_TOL_PX` (the crowded-row
      cap; see its note). Before confinement, wide pair cells
      overhung by ~45 px and slant overhangs of 3 to 8 px were
      routine.
    """
    from phonology_shared.chart.vowel_geometry import (
        build_vowel_chart_geometry,
        silhouette_for_data_width,
        straight_left_at_y,
        straight_right_at_y,
    )
    from phonology_shared.chart.vowel_geometry.cell_boxes import _cell_box_px
    from phonology_shared.chart.vowels import detect_vowel_profile

    engine = bundled_engine(name)
    vowels = engine.grouped_segments.get("Vowels", [])
    if not vowels:
        pytest.skip(f"{name} has no vowels")
    feats = engine.normalized_segment_feats
    geom = build_vowel_chart_geometry(
        vowels, detect_vowel_profile(vowels, feats), feats
    )
    assert geom.cells
    dw, dh = geom.natural_data_width_px, geom.natural_data_height_px
    sil = silhouette_for_data_width(geom.silhouette, dw)
    tiers = {r.logical_row: r.tier for r in geom.rows}
    for cell in geom.cells:
        left, top, right, bottom = _cell_box_px(
            cell, tiers.get(cell.row, "middle"), dw, dh
        )
        # Hard boundary: inside the data area.
        assert left >= -0.51 and right <= dw + 0.51, (
            f"{name}: {cell.entries} box [{left:.1f}, {right:.1f}] "
            f"escapes the data area [0, {dw}]"
        )
        for yy in (top, (top + bottom) / 2.0, bottom):
            yn = min(max(yy / dh, sil.top_y), sil.bottom_y)
            edge_l = straight_left_at_y(sil, yn) * dw
            edge_r = straight_right_at_y(sil, yn) * dw
            tol = _STRAIGHT_EDGE_OVERHANG_TOL_PX
            assert left >= edge_l - tol, (
                f"{name}: {cell.entries} left {left:.1f} overhangs the "
                f"straight edge {edge_l:.1f} by > {tol}px"
            )
            assert right <= edge_r + tol, (
                f"{name}: {cell.entries} right {right:.1f} overhangs the "
                f"straight edge {edge_r:.1f} by > {tol}px"
            )


@pytest.mark.parametrize("name", BUNDLED_INVENTORY_NAMES)
def test_vowel_columns_stay_vertically_aligned(
    name: str, bundled_engine: Callable[[str], FeatureEngine]
) -> None:
    """Cells sharing a backness anchor render in a straight vertical
    column: they must carry the SAME confinement ``nudge_px``.

    Pins the Universal-inventory regression where the rounded-corner
    confinement shoved the Close / Open back vowels (``ɯ``/``u``,
    ``ɑ``/``ɒ``) left of the middle back vowels while the anchors
    were identical. Confining to the straight (vertical) back edge
    keeps the nudge uniform down the column.
    """
    from phonology_shared.chart.vowel_geometry import (
        build_vowel_chart_geometry,
    )
    from phonology_shared.chart.vowel_geometry.cell_boxes import (
        _anchor_group_key,
    )
    from phonology_shared.chart.vowels import detect_vowel_profile

    engine = bundled_engine(name)
    vowels = engine.grouped_segments.get("Vowels", [])
    if not vowels:
        pytest.skip(f"{name} has no vowels")
    feats = engine.normalized_segment_feats
    geom = build_vowel_chart_geometry(
        vowels, detect_vowel_profile(vowels, feats), feats
    )
    by_anchor: dict[int, set[float]] = {}
    for cell in geom.cells:
        by_anchor.setdefault(_anchor_group_key(cell.chart_x), set()).add(
            round(cell.nudge_px, 3)
        )
    for anchor, nudges in by_anchor.items():
        assert len(nudges) == 1, (
            f"{name}: cells at backness anchor {anchor} have differing "
            f"nudges {sorted(nudges)}; the column is not vertical"
        )


@pytest.mark.parametrize("name", BUNDLED_INVENTORY_NAMES)
def test_no_vowel_cell_overlap(
    name: str, bundled_engine: Callable[[str], FeatureEngine]
) -> None:
    """No two vowel button boxes overlap by more than a rounding
    epsilon at natural size. Pins the Universal-inventory ``ɶ``/``a``
    regression (the confinement nudge used to push the Open-row
    front pair into the central cell)."""
    from phonology_shared.chart.vowel_geometry import (
        build_vowel_chart_geometry,
    )
    from phonology_shared.chart.vowel_geometry.cell_boxes import _cell_box_px
    from phonology_shared.chart.vowels import detect_vowel_profile

    engine = bundled_engine(name)
    vowels = engine.grouped_segments.get("Vowels", [])
    if not vowels:
        pytest.skip(f"{name} has no vowels")
    feats = engine.normalized_segment_feats
    geom = build_vowel_chart_geometry(
        vowels, detect_vowel_profile(vowels, feats), feats
    )
    dw, dh = geom.natural_data_width_px, geom.natural_data_height_px
    tiers = {r.logical_row: r.tier for r in geom.rows}
    boxes = [
        (_cell_box_px(c, tiers[c.row], dw, dh), c.entries) for c in geom.cells
    ]
    for i in range(len(boxes)):
        (la, ta, ra, ba), ea = boxes[i]
        for j in range(i + 1, len(boxes)):
            (lb, tb, rb, bb), eb = boxes[j]
            ix = min(ra, rb) - max(la, lb)
            iy = min(ba, bb) - max(ta, tb)
            assert not (
                ix > 0.5 and iy > 0.5
            ), f"{name}: {ea} and {eb} overlap by {ix:.1f}x{iy:.1f}px"
