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
    _cell_pair_offset_px,
    _cell_width_px,
    content_height_px,
)
from phonology_shared.chart.vowel_geometry.classifier import (
    CellClassification,
    classify_cells,
)
from phonology_shared.chart.vowel_geometry.confinement import (
    _CONFINE_MARGIN_PX,
    confine_cells,
)
from phonology_shared.chart.vowel_geometry.slots import (
    SlotPlan,
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
    vowel_silhouette,
)
from phonology_shared.chart.vowel_geometry.sizing import (
    SizedChart,
    apply_size_floors,
    natural_data_area_size,
)
from phonology_shared.chart.vowel_space import _BACKNESS_GROUP_BY_COL, _BACKNESS_X
from phonology_shared.chart.vowels import (
    PlacementPolicy,
    VowelChartShape,
    VowelPlacement,
    VowelProfile,
    _normalize_feat_keys,
    compute_placements,
    infer_vowel_shape,
)

#: Confinement margin + max-passes now live in ``confinement.py``.


def _converged_min_top_width(bottom_width: float, apex: float) -> float:
    """Minimum ``top_width`` for a converged silhouette such that the
    front-column at TOP sits at least as far left as the front-column
    at BOTTOM -- i.e. the silhouette top is at least as wide as the
    bottom, no inversion.

    Derived directly from the anchor geometry. With the back edge held
    vertical (``_BACK_APEX_PULL = 0.0``), silhouette width shrinkage
    at bottom is driven entirely by how far the front column pulls
    inward toward ``apex``. Requiring ``front_at_top <=
    front_at_bottom`` gives::

        back + top_w * (front - back) <= apex + bot_w * (front - apex)

    which solves for::

        top_w >= [(back - apex) + bot_w * (apex - front)] / (back - front)

    Under a lone-back-low inventory (apex == back) this reduces to
    ``top_w >= 0.5 * bot_w`` (top can shrink freely because back is
    the apex). Under central apex it reduces to ``top_w >= 0.5 + 0.5 *
    bot_w``. The value replaces the older ``_CONVERGED_TOP_KEEP =
    0.95`` magic knob, which was a rule-of-thumb ceiling; this
    formula is the exact inversion-avoidance floor and adjusts
    automatically with the shrink solver's ``bottom_width``.
    """
    front = _BACKNESS_X["front"]
    back = _BACKNESS_X["back"]
    span = back - front
    if span <= 0:
        return 0.0
    return ((back - apex) + bottom_width * (apex - front)) / span


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

    ``open_apex_backness`` fires ONLY when the Open row's cells fall
    entirely into the CENTRAL backness slot -- the typologically
    dominant lone-central-low pattern (82.5% of PHOIBLE inventories,
    including Spanish, Japanese, Korean, Indonesian, Ilokano,
    Lomongo, Mandarin, MSA, Romanian, Tobabatak, ...). In these
    inventories the sole low vowel is /a/, and the front-low corner
    collapses to a point at the central apex while the back edge
    stays vertical -- a right-leaning wedge that reads "no low
    front-back contrast, just a low central".

    All other Open-row configurations render the classic trapezoid:
    * Multi-column low (front + central + back, or any two of them):
      real low-row contrast, deserves a trapezoid.
    * Lone back low (German /ɑ/, Turkish /ɑ/ -- 3.8% of PHOIBLE):
      the sole low vowel sits at back, and forcing a wedge would
      collapse the front slant so aggressively that /ɑ/ ends up at
      the wedge apex. The classic trapezoid keeps it at the back
      wall where it belongs.
    * Lone front low (0.3% of PHOIBLE): same reasoning; classic
      trapezoid keeps the vowel at the front wall.
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
        "central"
        if open_backness_slots == {"central"}
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
        # Converged silhouettes get asymmetric shrink so the bottom
        # can narrow past the middle-row's demand (the Open row is
        # sparse in a lone-low inventory; middle rows fit inside the
        # resulting trapezoid). Classic trapezoid keeps uniform shrink
        # so its canonical slant is preserved across inventories.
        asymmetric=silhouette.back_anchor_at_bottom is not None,
    )
    # Converged bottom: floor the top width so the silhouette doesn't
    # invert (top narrower than bottom). Derived from the anchor
    # geometry via :py:func:`_converged_min_top_width`, so the floor
    # adapts to whichever ``bottom_width`` the asymmetric shrink
    # solver picked -- no magic ratio.
    if silhouette.back_anchor_at_bottom is not None:
        shrunken_top_w = max(
            shrunken_top_w,
            _converged_min_top_width(
                shrunken_bot_w, silhouette.back_anchor_at_bottom
            ),
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
    natural_w, natural_h = natural_data_area_size(tuple(cells))
    natural_w, natural_h = apply_size_floors(natural_w, natural_h, row_plan)
    return SizedChart(
        silhouette=silhouette, natural_w=natural_w, natural_h=natural_h
    )


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
    refit_w, refit_h = natural_data_area_size(tuple(cells))
    new_w = max(sized.natural_w, refit_w)
    new_h = max(sized.natural_h, refit_h)
    new_w, new_h = apply_size_floors(new_w, new_h, row_plan)
    if new_w != sized.natural_w or new_h != sized.natural_h:
        sized = SizedChart(
            silhouette=sized.silhouette, natural_w=new_w, natural_h=new_h,
        )
    cells = confine_cells(cells, sized)

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
