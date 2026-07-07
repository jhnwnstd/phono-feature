"""The vowel-chart geometry pipeline (cross-layer orchestrator).

The ONLY module where cell boxes meet the outline. The placement
pipeline is propose-then-confine:

1. ``_plan_placements``: the inference layer proposes logical slots.
2. ``classifier.classify_cells`` + ``slots.assign_pair_sides``:
   coordinate-free arrangement.
3. ``_plan_rows`` (per-row rendered pixel heights via
   ``cell_boxes.content_height_px``, distribution via
   ``rows.distribute_rows``): vertical structure.
4. ``_solve_outline``: the boundary adapts to the rows' width
   demands (shrink).
5. ``_project_cells``: anchors map into the outline; pair-shift
   conflicts resolve.
6. ``_fit_outline_and_size``: the outline reserves extent for wide
   edge cells; the natural size and aspect cap settle.
7. ``_confine_cells``: residual overhangs nudge inward. Shift-only;
   the outline is the HARD boundary for the buttons.
8. ``furniture``: rows, headers, and the diphthong chip list
   bake against the final outline.

``build_vowel_chart_geometry`` is the public entry point both UIs
call (the desktop directly, the web through the bridge); renderers
attach the result as a thin walk with no placement decisions.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace

from phonology_shared.chart.vowel_geometry.cell_boxes import (
    _VOWEL_ROW_GAP_PX,
    _cell_box_px,
    _cell_pair_offset_px,
    _cell_width_px,
    _natural_data_area_size,
    content_height_px,
)
from phonology_shared.chart.vowel_geometry.classifier import (
    CellClassification,
    classify_cells,
)
from phonology_shared.chart.vowel_geometry.slots import (
    SlotPlan,
    anchor_group_key,
    assign_pair_sides,
    resolve_pair_shift_conflicts,
)
from phonology_shared.chart.vowel_geometry.space import open_row_index
from phonology_shared.chart.vowel_geometry.furniture import (
    build_col_headers,
    build_diphthong_segments,
    build_rows,
)
from phonology_shared.chart.vowel_geometry.model import (
    VOWEL_CHART_TITLE,
    VowelChartCell,
    VowelChartGeometry,
    VowelChartSilhouette,
)
from phonology_shared.chart.vowel_geometry.projection import project_anchor_x
from phonology_shared.chart.vowel_geometry.rows import (
    RowPlan,
    distribute_rows,
)
from phonology_shared.chart.vowel_geometry.shrink import _compute_shrunken_widths
from phonology_shared.chart.vowel_geometry.silhouette import (
    _VOWEL_CONTENT_W_PX,
    _corners_from_anchors,
    _silhouette_with_widths,
    silhouette_for_data_width,
    straight_left_at_y,
    straight_right_at_y,
    vowel_silhouette,
)
from phonology_shared.chart.vowel_space import (
    _BACKNESS_GROUP_BY_COL,
    _HEIGHT_Y,
)
from phonology_shared.chart.vowels import (
    PlacementPolicy,
    VowelChartShape,
    VowelPlacement,
    VowelProfile,
    _normalize_feat_keys,
    compute_placements,
    infer_vowel_shape,
)
from phonology_shared.presentation.chart_style import (
    VOWEL_SILHOUETTE_MAX_ASPECT,
)

#: Safety inset (px) the confinement pass keeps between a button box
#: and the outline. Absorbs the renderers' integer rounding (round-
#: to-nearest on the centre plus the floor-divided half width can
#: land a box ~1.5 px outside the float position).
_CONFINE_MARGIN_PX: float = 2.0

#: Confinement iterations. Nudges are shift-only (no chart resize),
#: so a second pass only verifies the first converged; the audit
#: across the bundled + PHOIBLE catalogues converges in one.
_CONFINE_MAX_PASSES: int = 2

# Converged-bottom top-width floor: when the silhouette carries a
# converged bottom (``back_anchor_at_bottom`` set), keep the top
# width at LEAST this fraction of its canonical value even if the
# shrink solver would collapse it further. Below this fraction the
# top and bottom widths cluster too tightly and the outline reads
# as a near-rectangle instead of the intended triangular
# convergence toward the apex. Chosen so the front edge of a
# Spanish-shaped inventory (5 vowels, one central low) reads as a
# strong inward slant while still respecting the shrink solver's
# tighter demands for wider inventories.
_CONVERGED_TOP_KEEP: float = 0.95


def _grow_outline_extent(
    cells: list[VowelChartCell],
    silhouette: VowelChartSilhouette,
) -> VowelChartSilhouette:
    """Outline accommodates content: grow the reserved cell extent
    to wrap the widest edge cell.

    ``cell_outer_extent_px`` assumes a single button beside the
    anchor (pair shift + half a button, 33 px). Wide cells on a
    pair side (long / nasal pairs, contrast sets, especially
    same-anchor tangent pairs with an elevated shift) reach up to
    ~70 px past their anchor; no chart width can absorb a back-
    anchor overhang (the back edge moves with the anchor), so the
    outline itself must reserve the room. Only the cells that BIND
    an edge matter: the front-most and back-most group of each row.
    The cascade fields are per-geometry data both renderers already
    consume, so the grown extent flows to the drawn outline with no
    renderer changes; the corner fields are updated to the matching
    canonical-width approximation for the baked consumers (row
    labels, offline CSS fallback).
    """
    canonical = float(silhouette.cell_outer_extent_px)
    front_reach = canonical
    back_reach = canonical
    by_row: dict[int, list[VowelChartCell]] = {}
    for c in cells:
        by_row.setdefault(c.row, []).append(c)
    for row_cells in by_row.values():
        front_x = min(c.chart_x for c in row_cells)
        back_x = max(c.chart_x for c in row_cells)
        for c in row_cells:
            ww = _cell_width_px(c)
            off = _cell_pair_offset_px(c)
            if abs(c.chart_x - front_x) < 1e-9:
                front_reach = max(
                    front_reach, ww / 2.0 - off + _CONFINE_MARGIN_PX
                )
            if abs(c.chart_x - back_x) < 1e-9:
                back_reach = max(
                    back_reach, off + ww / 2.0 + _CONFINE_MARGIN_PX
                )
    back_needed = int(math.ceil(back_reach))
    front_needed = int(math.ceil(front_reach))
    if (
        back_needed <= silhouette.cell_outer_extent_px
        and front_needed <= silhouette.cell_outer_extent_px
    ):
        return silhouette
    back_norm = back_needed / _VOWEL_CONTENT_W_PX
    front_norm = front_needed / _VOWEL_CONTENT_W_PX
    corners = _corners_from_anchors(
        front_anchor_at_top=silhouette.front_anchor_at_top,
        front_anchor_at_bottom=silhouette.front_anchor_at_bottom,
        back_anchor=silhouette.back_anchor,
        back_anchor_at_bottom=silhouette.back_anchor_at_bottom,
        bottom_width=silhouette.bottom_width,
        extent_norm=back_norm,
        front_extent_norm=front_norm,
    )
    return replace(
        silhouette,
        top_left=corners.top_left,
        bottom_left=corners.bottom_left,
        top_right=corners.top_right,
        bottom_right=corners.bottom_right,
        cell_outer_extent_px=back_needed,
        front_cell_outer_extent_px=front_needed,
    )


def _confine_cells_to_outline(
    cells: list[VowelChartCell],
    silhouette: VowelChartSilhouette,
    dw: int,
    dh: int,
) -> tuple[list[VowelChartCell], bool]:
    """HARD-BOUNDARY pass: nudge cells inward until every button box
    sits inside the rendered outline.

    The placement pipeline is propose-then-confine: the inference
    layer proposes anchors, the projection maps them into the
    trapezoid, :py:func:`_grow_outline_extent` reserves room for
    the wide edge groups, and this pass closes the residual escape
    modes the anchor model cannot express: a box's corner
    overhanging the slanted front edge even when its centre is
    inside (~4 px), and renderer integer rounding (~1 px).

    Confinement is against the STRAIGHT trapezoid edges
    (:py:func:`straight_left_at_y` / :py:func:`straight_right_at_y`),
    NOT the rounded-corner polygon. The rounded corners are a
    cosmetic stroke, not a containment boundary: confining against
    them shoved the top / bottom rows inward by ~one corner radius,
    which broke the vertical back column's alignment and pushed the
    Open-row front pair into the central cell. A rounded button
    corner tucked a few pixels inside a rounded silhouette corner
    reads fine; a misaligned column does not. The back edge is
    vertical, so every back cell confines to the same x and the
    column stays aligned by construction.

    Residuals are bounded and small, so confinement is SHIFT-ONLY:
    it writes the cells' ``nudge_px`` pixel offset and never feeds
    back into the chart's solved width. Same-anchor groups move
    TOGETHER so pair tangency (including an elevated
    ``pair_shift_px``) is preserved. Edges are evaluated on the
    dw-corrected silhouette (what the renderers draw), sampled at
    the box's top, middle, and bottom.

    Returns ``(cells, changed)``.
    """
    sil = silhouette_for_data_width(silhouette, dw)
    out = list(cells)
    groups: dict[tuple[int, int], list[int]] = {}
    for i, c in enumerate(out):
        groups.setdefault((c.row, anchor_group_key(c.chart_x)), []).append(i)

    # Anchor-free horizontal extent per group (the box position with the
    # confinement nudge stripped: nudge shifts a box rigidly, so
    # ``box_x - nudge`` recovers the anchor + pair-shift position). These
    # are stable across passes and feed the neighbour caps below.
    anchor_free: dict[tuple[int, int], tuple[float, float]] = {}
    group_nudge: dict[tuple[int, int], float] = {}
    for key, idxs in groups.items():
        lefts: list[float] = []
        rights: list[float] = []
        for i in idxs:
            c = out[i]
            left, _, right, _ = _cell_box_px(c, dw, dh)
            lefts.append(left - c.nudge_px)
            rights.append(right - c.nudge_px)
        anchor_free[key] = (min(lefts), max(rights))
        group_nudge[key] = out[idxs[0]].nudge_px

    # Per-row inward-shift lanes. The proposed (anchor + pair-shift)
    # positions never overlap, so a group may move toward a row neighbour
    # by at most HALF the anchor-free gap between them: even if both
    # adjacent groups move maximally they only meet at the midpoint
    # (touching, never overlapping). Confinement can clear the outline but
    # may not manufacture an inter-cell overlap; at a row too crowded to
    # both clear the slant AND keep the gap, the bounded straight-edge
    # overhang is the lesser evil versus stacked glyphs.
    lane_hi: dict[tuple[int, int], float] = {k: float("inf") for k in groups}
    lane_lo: dict[tuple[int, int], float] = {k: float("-inf") for k in groups}
    rows_to_keys: dict[int, list[tuple[int, int]]] = {}
    for key in groups:
        rows_to_keys.setdefault(key[0], []).append(key)
    for ks in rows_to_keys.values():
        ks.sort(key=lambda k: anchor_free[k][0])
        for left_k, right_k in zip(ks, ks[1:]):
            half_gap = max(
                0.0, (anchor_free[right_k][0] - anchor_free[left_k][1]) / 2.0
            )
            lane_hi[left_k] = min(lane_hi[left_k], half_gap)
            lane_lo[right_k] = max(lane_lo[right_k], -half_gap)

    changed = False
    for key, idxs in groups.items():
        push_right = 0.0
        push_left = 0.0
        for i in idxs:
            c = out[i]
            left, top, right, bottom = _cell_box_px(c, dw, dh)
            for yy in (top, (top + bottom) / 2.0, bottom):
                yn = min(max(yy / dh, sil.top_y), sil.bottom_y)
                edge_l = straight_left_at_y(sil, yn) * dw + _CONFINE_MARGIN_PX
                edge_r = straight_right_at_y(sil, yn) * dw - _CONFINE_MARGIN_PX
                push_right = max(push_right, edge_l - left)
                push_left = max(push_left, right - edge_r)
        if push_right <= 0.0 and push_left <= 0.0:
            continue
        if push_right > 0.0 and push_left > 0.0:
            # Wider than the outline at this row even after the
            # extent growth; centre so neither side wins.
            shift_px = (push_right - push_left) / 2.0
        else:
            shift_px = push_right if push_right > 0.0 else -push_left
        # Clamp the resulting TOTAL nudge into the group's lane so the
        # shift clears the outline but never crosses into a row neighbour.
        target = group_nudge[key] + shift_px
        target = min(lane_hi[key], max(lane_lo[key], target))
        shift_px = target - group_nudge[key]
        if abs(shift_px) < 1e-9:
            continue
        for i in idxs:
            out[i] = replace(out[i], nudge_px=out[i].nudge_px + shift_px)
        changed = True
    return out, changed


@dataclass(frozen=True)
class PlacementPlan:
    """Stage 1 output: the inference layer's proposals plus the
    facts later stages derive from them once.

    ``open_apex_backness`` names the sole backness slot ("front",
    "central", or "back") when the Open row has cells in exactly one
    backness column. When set, the silhouette converges its bottom
    edge on that column's anchor: the shape becomes a triangle with
    a narrow flat bottom hugging the sole low vowel, and the
    projection's pivot slants from ``back_anchor`` at top_y to that
    column's anchor at bottom_y (both edges slant inward, back
    included). ``None`` means the Open row spans two or more
    backness columns and the classic trapezoid outline applies.
    """

    occupied: Mapping[tuple[int, int], list[str]]
    placements: Mapping[str, VowelPlacement]
    norm_cache: Mapping[str, Mapping[str, str]]
    populated_rows: tuple[int, ...]
    shape: VowelChartShape
    open_apex_backness: str | None


@dataclass(frozen=True)
class SizedChart:
    """Stage 6 output: the outline after extent growth, plus the
    settled natural size the confinement pass and the renderers'
    sizing hints consume."""

    silhouette: VowelChartSilhouette
    natural_w: int
    natural_h: int


def _plan_placements(
    segs: list[str],
    profile: VowelProfile,
    norm_feats: Mapping[str, Mapping[str, str]],
    policy: PlacementPolicy | None,
    segment_secondary: Mapping[str, Mapping[str, str]] | None,
) -> PlacementPlan:
    """Run the inference layer once and derive the shared facts.

    Normalizes every bundle exactly once: the placer and the display
    classifier both need lowercase-keyed bundles, and sharing one
    cache here keeps the interactive inventory-switch path free of
    a second full re-normalization (pure allocation churn).

    ``open_apex_backness`` fires when the Open row's cells all fall
    into ONE backness slot (front / central / back). The silhouette
    then converges its bottom on that column's canonical anchor,
    which encodes the principle "front / central / back positions
    only exist as distinct display columns when the inventory
    contrasts them." When multiple backness slots share the Open row
    (a language with a real three-way low contrast, or even a
    two-way front / back low pair), the field is ``None`` and the
    classic trapezoid renders.
    """
    norm_cache: dict[str, dict[str, str]] = {
        seg: _normalize_feat_keys(norm_feats.get(seg, {})) for seg in segs
    }
    occupied, placements = compute_placements(
        segs,
        profile,
        norm_feats,
        policy,
        segment_secondary=segment_secondary,
        norm_cache=norm_cache,
    )
    open_cols = {
        c for (r, c) in occupied if r == open_row_index
    }
    open_backness_slots = {
        _BACKNESS_GROUP_BY_COL[c] for c in open_cols
        if c in _BACKNESS_GROUP_BY_COL
    }
    open_apex_backness = (
        next(iter(open_backness_slots))
        if len(open_backness_slots) == 1
        else None
    )
    return PlacementPlan(
        occupied=occupied,
        placements=placements,
        norm_cache=norm_cache,
        populated_rows=tuple(sorted({row for (row, _) in occupied})),
        shape=infer_vowel_shape(profile),
        open_apex_backness=open_apex_backness,
    )


def _plan_rows(
    plan: PlacementPlan,
    classifications: Mapping[tuple[int, int], CellClassification],
    silhouette: VowelChartSilhouette,
) -> RowPlan:
    """Distribute the populated rows in the silhouette span
    proportional to per-row rendered content height (the tallest
    cell's pixel height via the shared
    :py:func:`..cell_boxes.content_height_px`). Pixel heights, not
    button counts: the density tiers make per-button height vary
    across rows, and weighting by count starves shallow canonical
    rows next to a deep ultra row until their cells overlap.
    """
    weights: dict[int, int] = {}
    for (ri, _ci), classification in classifications.items():
        h = content_height_px(
            classification.kind,
            len(classification.entries),
            classification.grid,
        )
        if h > weights.get(ri, 0):
            weights[ri] = h
    return distribute_rows(
        plan.populated_rows, weights, silhouette.top_y, silhouette.bottom_y
    )


def _solve_outline(
    slot_plan: SlotPlan,
    row_plan: RowPlan,
    silhouette: VowelChartSilhouette,
) -> VowelChartSilhouette:
    """Shrink the silhouette widths so the trapezoid tracks the
    actual content. With back-anchored cell projection, the shrunken
    widths also pull cell anchors inward by the same factor, so the
    silhouette and the cells stay aligned by construction. Runs
    BEFORE rows are baked so the per-row label anchors match the
    FINAL silhouette; an earlier ordering baked pre-shrink edges,
    leaving the web's row labels floating off the drawn outline.
    """
    shrunken_top_w, shrunken_bot_w = _compute_shrunken_widths(
        slot_plan.row_width_demands,
        row_plan.display_y,
        silhouette.top_y,
        silhouette.bottom_y,
        silhouette.top_width,
        silhouette.bottom_width,
    )
    # Converged bottom: keep the TOP width close to canonical so the
    # visible front slant reads. Otherwise a sparse lone-low-vowel
    # inventory (Spanish, Japanese) shrinks the top toward central
    # too, and both top and bottom cluster together, producing a
    # nearly-rectangular outline that hides the triangular
    # convergence the shape trigger was supposed to signal.
    # Cell-position math is pivot-invariant on distances, so keeping
    # the top wider doesn't collide cells; it only paints more
    # visual "sky" above the outline.
    if silhouette.back_anchor_at_bottom is not None:
        shrunken_top_w = max(
            shrunken_top_w, silhouette.top_width * _CONVERGED_TOP_KEEP
        )
    if (
        shrunken_top_w != silhouette.top_width
        or shrunken_bot_w != silhouette.bottom_width
    ):
        return _silhouette_with_widths(
            silhouette, shrunken_top_w, shrunken_bot_w
        )
    # The back edge stays at the canonical pair-outer default set by
    # ``vowel_silhouette``: the line sits at the back-rounded mate's
    # outer right edge so back vowels sit flush against, never
    # crossing, the silhouette. Snapping it to the rightmost
    # back-vowel button centre per inventory is rejected design
    # space (the line cuts through the buttons); the
    # ``back_right_pixel_offset`` field is the slot where any future
    # per-inventory back-edge policy lands without touching the
    # renderers.
    return silhouette


def _project_cells(
    slot_plan: SlotPlan,
    row_plan: RowPlan,
    silhouette: VowelChartSilhouette,
) -> list[VowelChartCell]:
    """Project each slot's effective anchor through the final
    silhouette and resolve same-anchor pair-shift conflicts. No
    phonology re-decisions happen here; the slots' row/col are
    already final, only their pixel-space position is pending.

    Diphthongs never reach this function: the placer skips them from
    slots (they render as chips below the chart), so every slot here
    is a monophthong cell.
    """
    cells: list[VowelChartCell] = []
    for slot in slot_plan.slots:
        cell_display_y = row_plan.display_y[slot.row]
        chart_x = project_anchor_x(silhouette, slot.anchor_x, cell_display_y)
        cells.append(
            VowelChartCell(
                row=slot.row,
                col=slot.col,
                chart_x=chart_x,
                chart_y=cell_display_y,
                pair_side=slot.pair_side,
                entries=slot.entries,
                display_kind=slot.display_kind,
                contrast_features=slot.contrast_features,
                grid=slot.grid,
            )
        )
    # Same-anchor pair-shift conflicts: two paired cells (opposite
    # pair_side, same chart_x) overlap if the canonical pair_shift
    # cannot accommodate the combined cell widths (PHOIBLE
    # auto-pairs back-neutral with back-rounded; two wide cells
    # overlap by ~33 px). Elevate ``pair_shift_px`` on both members
    # so they stay tangent.
    return resolve_pair_shift_conflicts(cells)


def _fit_outline_and_size(
    cells: list[VowelChartCell],
    silhouette: VowelChartSilhouette,
    row_plan: RowPlan,
) -> SizedChart:
    """Reserve outline extent for the widest edge cells, then settle
    the natural size.

    The aspect cap keeps sparse inventories (Spanish 5-vowel) from
    rendering 2 to 3x as wide as the canonical 10:7 silhouette:
    growing natural_h pulls the aspect back down without touching
    cell positions or dw; dense inventories at or below the ceiling
    are unaffected.

    The row-fit floor then guarantees THE ROW-FIT INVARIANT: at
    natural size, every row's proportional slot covers its rendered
    content. The rows live in the silhouette span (``sil_y_span`` of
    natural_h), so the height request must put at least the summed
    row heights plus inter-row gaps inside that span; the
    content-plus-padding estimate from ``_natural_data_area_size``
    alone undershoots it by the padding-to-span ratio and deep
    inventories' rows overlap their neighbours at natural size.
    Both floors only ever grow ``natural_h``, so applying them in
    sequence satisfies both.
    """
    silhouette = _grow_outline_extent(cells, silhouette)
    natural_w, natural_h = _natural_data_area_size(tuple(cells))
    natural_w, natural_h = _apply_size_floors(natural_w, natural_h, row_plan)
    return SizedChart(
        silhouette=silhouette, natural_w=natural_w, natural_h=natural_h
    )


def _apply_size_floors(
    natural_w: int, natural_h: int, row_plan: RowPlan
) -> tuple[int, int]:
    """Grow ``natural_h`` to satisfy the aspect ceiling and the
    per-row content-fit floor. Both only ever grow the height, never
    shrink either dimension, so this is safe to call multiple times
    over the pipeline (e.g. once inside ``_fit_outline_and_size`` and
    once after the post-finalize refit).
    """
    sil_y_span = _HEIGHT_Y["Open"] - _HEIGHT_Y["Close"]  # 0.90
    if sil_y_span <= 0:
        return natural_w, natural_h
    current_sil_h = sil_y_span * natural_h
    if current_sil_h > 0:
        aspect = natural_w / current_sil_h
        if aspect > VOWEL_SILHOUETTE_MAX_ASPECT:
            needed_sil_h = natural_w / VOWEL_SILHOUETTE_MAX_ASPECT
            natural_h = int(math.ceil(needed_sil_h / sil_y_span))
    rows_px = sum(row_plan.weight[ri] for ri in row_plan.rows)
    gaps_px = (len(row_plan.rows) - 1) * _VOWEL_ROW_GAP_PX
    row_fit_h = int(math.ceil((rows_px + gaps_px) / sil_y_span))
    natural_h = max(natural_h, row_fit_h)
    return natural_w, natural_h


def _confine_cells(
    cells: list[VowelChartCell],
    sized: SizedChart,
) -> list[VowelChartCell]:
    """HARD-BOUNDARY confinement: the outline bounds the buttons.
    Placement above is propose-only; the extent growth reserved room
    for the wide edge groups, and this pass nudges the small
    residual overhangs (slant, corner arcs, rounding) inward.
    Shift-only: nudges never feed back into the solved size.
    """
    for _ in range(_CONFINE_MAX_PASSES):
        cells, confine_changed = _confine_cells_to_outline(
            cells,
            sized.silhouette,
            sized.natural_w,
            sized.natural_h,
        )
        if not confine_changed:
            break
    return cells


def _finalize_row_plan(
    row_plan: RowPlan,
    sized: SizedChart,
    top_y: float,
    bottom_y: float,
) -> RowPlan:
    """Pull the topmost / bottommost rows' centres INWARD so their
    cell edges land next to the silhouette top / bottom edges even
    when the aspect cap grew ``natural_h`` past the row-fit floor
    and left slack in the extreme slots. Middle rows are unchanged
    (their slot centre already IS their cell centre).

    Runs POST-``_fit_outline_and_size`` because half-cell-height in
    silhouette-normalised units is ``(weight[row] / 2) / natural_h``:
    ``weight`` is a rendered pixel height, and only ``sized.natural_h``
    lets us convert it to the [0, 1] silhouette space. The next
    ``_project_cells`` pass then re-projects the extreme rows at the
    finalised centres so the cells' chart_x rides the trapezoid slant
    at the same y the guide diagonals evaluate at (any drift between
    cell-y and guide-y is what nudges guide lines off the pair
    midpoints).
    """
    if len(row_plan.rows) < 2 or sized.natural_h <= 0:
        return row_plan
    dy = dict(row_plan.display_y)
    top_r, bot_r = row_plan.rows[0], row_plan.rows[-1]
    half_top = (row_plan.weight[top_r] / 2.0) / sized.natural_h
    half_bot = (row_plan.weight[bot_r] / 2.0) / sized.natural_h
    dy[top_r] = min(dy[top_r], top_y + half_top)
    dy[bot_r] = max(dy[bot_r], bottom_y - half_bot)
    return replace(row_plan, display_y=dy)


def build_vowel_chart_geometry(
    segs: list[str],
    profile: VowelProfile,
    norm_feats: Mapping[str, Mapping[str, str]],
    policy: PlacementPolicy | None = None,
    segment_secondary: Mapping[str, Mapping[str, str]] | None = None,
) -> VowelChartGeometry:
    """End-to-end: compute placements and produce a render-ready
    chart geometry for both UIs. Stage list and ordering rationale
    in the module docstring.

    ``segment_secondary`` carries final-state feature bundles for
    PHOIBLE diphthong segments. When present, the returned
    geometry's :py:attr:`VowelChartGeometry.diphthongs` lists each
    diphthong segment name; renderers show them as labelled chips
    below the chart (they are never placed in the trapezoid).

    Renderers attach the result directly: no placement decisions
    and no coordinate arithmetic happen at the UI layer.
    """
    plan = _plan_placements(
        segs, profile, norm_feats, policy, segment_secondary
    )

    # Empty case: no vowel occupies a chart cell (consonant-only setup,
    # a fresh "New" with the all-stops placeholder, or a vowel system
    # made ENTIRELY of diphthongs, which are excluded from cells by
    # design). Return a degenerate geometry with the canonical
    # full-range silhouette so renderers can still draw the empty
    # chart chrome (or hide it) by iterating zero-length rows /
    # cells / cols. The diphthongs still travel: they render as chips
    # below the chart, not as cells, so an all-diphthong system must
    # not lose its segments to this shortcut.
    if not plan.populated_rows:
        return VowelChartGeometry(
            title=VOWEL_CHART_TITLE,
            shape=plan.shape,
            silhouette=vowel_silhouette(plan.shape),
            cols=(),
            rows=(),
            cells=(),
            natural_data_width_px=0,
            natural_data_height_px=0,
            diphthongs=build_diphthong_segments(plan.placements),
        )

    # Silhouette: position logic (top/bottom widths) comes from the
    # populated logical row range; display logic (top_y/bottom_y)
    # always spans the full data area so cells use every pixel
    # regardless of which rows are present.
    silhouette = vowel_silhouette(
        plan.shape,
        top_logical_row=plan.populated_rows[0],
        bottom_logical_row=plan.populated_rows[-1],
        open_apex_backness=plan.open_apex_backness,
    )

    classifications = classify_cells(plan.occupied, plan.norm_cache)
    slot_plan = assign_pair_sides(plan.occupied, classifications)
    row_plan = _plan_rows(plan, classifications, silhouette)
    silhouette = _solve_outline(slot_plan, row_plan, silhouette)
    cells = _project_cells(slot_plan, row_plan, silhouette)
    sized = _fit_outline_and_size(cells, silhouette, row_plan)
    # Post-fit nudge: pull extreme rows' cell centres inward so their
    # edges hug the silhouette top / bottom. Needs sized.natural_h to
    # convert half-cell-height into silhouette-normalised space, so it
    # runs here (not in distribute_rows). Then re-project the cells so
    # their chart_x matches the finalised chart_y on the trapezoid slant
    # so cells and guide diagonals share the y they interpolate at.
    row_plan = _finalize_row_plan(
        row_plan, sized, sized.silhouette.top_y, sized.silhouette.bottom_y
    )
    cells = _project_cells(slot_plan, row_plan, sized.silhouette)
    # Re-fit the natural size against the post-finalize cell
    # positions. Under a converged-bottom silhouette the pivot at y
    # depends on how far the row's chart_y sits below top_y, so
    # ``_finalize_row_plan`` (which nudges the topmost row's chart_y
    # toward the silhouette edge) shifts the top row's chart_x
    # outward by a few pixels vs. the initial slot-centre placement.
    # ``natural_w`` was locked against the pre-finalize positions;
    # take the max, then re-apply the aspect ceiling + row-fit floor
    # so a small width bump doesn't push the chart past the sparse-
    # inventory aspect cap.
    refit_w, refit_h = _natural_data_area_size(tuple(cells))
    new_w = max(sized.natural_w, refit_w)
    new_h = max(sized.natural_h, refit_h)
    new_w, new_h = _apply_size_floors(new_w, new_h, row_plan)
    if new_w != sized.natural_w or new_h != sized.natural_h:
        sized = SizedChart(
            silhouette=sized.silhouette, natural_w=new_w, natural_h=new_h,
        )
    cells = _confine_cells(cells, sized)

    # Furniture bakes against the FINAL silhouette and natural size:
    # rows carry label anchors evaluated at label_y; headers read only
    # widths and y bounds, which the extent growth never modifies, so
    # passing the post-growth silhouette is identical to the pre-growth
    # one for them.
    rows = build_rows(row_plan, sized.silhouette, sized.natural_h)
    return VowelChartGeometry(
        title=VOWEL_CHART_TITLE,
        shape=plan.shape,
        silhouette=sized.silhouette,
        cols=build_col_headers(sized.silhouette),
        rows=rows,
        cells=tuple(cells),
        natural_data_width_px=sized.natural_w,
        natural_data_height_px=sized.natural_h,
        diphthongs=build_diphthong_segments(plan.placements),
    )
