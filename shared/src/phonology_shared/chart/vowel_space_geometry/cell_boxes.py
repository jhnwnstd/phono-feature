"""Content-driven pixel boxes for vowel cells (layer 3).

How big a rendered cell is, purely from its own content: button
counts, stack depths, the density-tier button heights, the rendered
box rectangle both renderers draw, and the natural data-area size
derived from the boxes. Box math never sees the outline; relating
boxes to the outline is the pipeline's job alone, which is the
structural fix for the buttons-escaped-the-outline class of bug.

May import :py:mod:`.model`, :py:mod:`.classifier`, :py:mod:`.space`,
the inference layer, and presentation constants; must not import
``slots``, ``silhouette``, ``shrink``, ``projection``, ``rows``,
``furniture``, or ``pipeline``. See the package docstring for the
layer table.
"""

from __future__ import annotations

from phonology_shared.chart.vowel_space_geometry.classifier import (
    PAIR_DISPLAY_KINDS,
)
from phonology_shared.chart.vowel_space_geometry.model import VowelChartCell
from phonology_shared.chart.vowel_space_geometry.column_scheme import (
    horizontal_button_count as _horizontal_button_count_impl,
)
from phonology_shared.chart.vowels import VowelCellDisplayKind
from phonology_shared.presentation.chart_style import (
    VOWEL_CELL_STACK_GAP_PX,
    effective_button_width_px,
)
from phonology_shared.presentation.constants import BTN_W
from phonology_shared.presentation.layout import (
    SEG_BTN_H,
    VOWEL_PAIR_GAP_PX,
    VOWEL_PAIR_SEPARATOR_PX,
)


def horizontal_button_count(
    kind: VowelCellDisplayKind,
    entries: tuple[str, ...],
    grid: tuple[tuple[int, int], ...],
    spans: tuple[tuple[int, int], ...] = (),
) -> int:
    """Convenience wrapper over :py:func:`space.horizontal_button_count`
    with :py:data:`PAIR_DISPLAY_KINDS` (the classifier-owned frozenset)
    bound as the pair-kinds predicate. The one call site every
    consumer inside ``vowel_space_geometry`` uses, so box math, the shrink
    solver's row width demands, and the slot assigner cannot disagree
    on how wide a cell draws.
    """
    return _horizontal_button_count_impl(
        kind, entries, grid, spans, pair_display_kinds=PAIR_DISPLAY_KINDS
    )


#: Two spacing regimes, deliberately distinct so the chart reads its
#: phonology at a glance: a rounded / unrounded PAIR (two mates on the
#: SAME backness anchor) is the tightest thing on the chart, and any
#: two cells at DIFFERENT backness anchors sit strictly farther apart
#: than that, so a lone central vowel (the Open row's central /a/ ~ /ä/
#: beside the front pair /a ɶ/) never reads as a fourth pair member.
#:
#: * ``VOWEL_PAIR_GAP_PX`` (2 px) is the WITHIN-pair daylight: the two
#:   mates render a fixed pixel shift apart regardless of chart width.
#: * ``_INTER_ANCHOR_GAP_PX`` is the BETWEEN-anchor minimum daylight the
#:   width solver guarantees, sized to the canonical inter-backness
#:   ``VOWEL_PAIR_SEPARATOR_PX`` so cross-column spacing in a pinched
#:   Open row matches cross-column spacing everywhere else; and, being
#:   the separator, is comfortably wider than the within-pair gap. This
#:   is the same floor ``_min_row_width_for_meta`` already uses for the
#:   shrink pass, so the grow and shrink passes now agree on how far
#:   apart distinct backness columns sit.

#: Gap (px) between vertically stacked segment buttons. Canonical
#: home lives in ``phonology_shared.presentation.chart_style`` as
#: ``VOWEL_CELL_STACK_GAP_PX`` (presentation layer, so build.py can
#: bake it without dragging chart/ imports); aliased to the
#: module-private spelling this file's box math reads.
_VOWEL_CELL_STACK_GAP_PX: int = VOWEL_CELL_STACK_GAP_PX

#: Density tiers: per-button height when a cell's stack reaches the
#: threshold entry count. SINGLE SOURCE for all three consumers:
#: this module's ``natural_data_height_px`` computation, the web's
#: CSS rules (relayed by build.py as ``--vowel-cell-dense-h`` /
#: ``--vowel-cell-ultra-h``), and the web's per-cell tier choice in
#: main.js (thresholds relayed in the ``chart-style`` inline JSON).
#: The geometry sizes its natural-height request from these so it
#: asks for what the renderer actually draws; sized from the
#: canonical button height instead, a 12-deep stack (PHOIBLE
#: !Xu / UPSID) requests 931 px where the rendered chart needs only
#: ~250 px, forcing the panel body to scroll for nothing.
DENSITY_TIER_DENSE_THRESHOLD: int = 5
DENSITY_TIER_DENSE_BTN_H: int = SEG_BTN_H - 4  # 22 px
DENSITY_TIER_ULTRA_THRESHOLD: int = 10
DENSITY_TIER_ULTRA_BTN_H: int = SEG_BTN_H - 8  # 18 px


def effective_button_height_px(stack_depth: int) -> int:
    """Per-button rendered height for a stack of ``stack_depth``
    entries. Matches the CSS density-tier ladder so the geometry's
    natural-height computation tracks the actual rendered height.

    Both renderers consume this to keep their per-button sizing in
    lockstep with the geometry's ``natural_data_height_px``
    request. Web CSS reads ``data-cell-density="dense"`` or
    ``"ultra"`` and applies the same heights via
    ``calc(var(--seg-btn-h) - 4px)`` / ``- 8px``; desktop calls
    this helper directly to set ``setFixedHeight`` on each stacked
    button. Without the parity a 7-deep stack renders 28 px taller
    on desktop than on the web (canonical 26 px vs dense 22 px)
    and the two charts visibly disagree despite consuming the same
    shared geometry.
    """
    if stack_depth >= DENSITY_TIER_ULTRA_THRESHOLD:
        return DENSITY_TIER_ULTRA_BTN_H
    if stack_depth >= DENSITY_TIER_DENSE_THRESHOLD:
        return DENSITY_TIER_DENSE_BTN_H
    return SEG_BTN_H


#: Vertical breathing room between adjacent populated rows. Picked
#: to read as a row break without overweighting the chart's chrome.
_VOWEL_ROW_GAP_PX: int = 6

#: Vertical padding (top + bottom combined) around the row content
#: so the silhouette's top edge can cut through the Close row's
#: button centres without clipping their tops.
_VOWEL_DATA_AREA_VERTICAL_PADDING_PX: int = SEG_BTN_H

#: Minimum visible daylight (px) between two SAME-anchor cells (a
#: rounded / unrounded pair): the tangency target the pair-shift
#: conflict resolver keeps two mates at. Distinct from the wider
#: between-anchor floor below; see the two-regime note at the top of
#: this module.
_INTER_CELL_GAP_PX: float = float(VOWEL_PAIR_GAP_PX)

#: Minimum visible daylight (px) between two DIFFERENT-anchor cells
#: (distinct backness columns). The canonical inter-backness
#: separator, strictly wider than the within-pair gap above, so the
#: width solver spreads distinct columns apart even in a pinched Open
#: row. Matches the shrink pass's ``_VOWEL_MIN_CELL_GAP_NORM``.
_INTER_ANCHOR_GAP_PX: float = float(VOWEL_PAIR_SEPARATOR_PX)


def _cell_horizontal_button_count(cell: VowelChartCell) -> int:
    """Horizontal button count contributed by ``cell``. Delegates to
    :py:func:`horizontal_button_count`, the ONE definition of cell
    width in buttons (a PAIR kind lays every entry in one row, so a
    3-entry phonation capsule is 3 wide, not the 2 a hand-coded pair
    rule used to claim), so the box math here and the shrink solver's
    row width demands can never disagree."""
    return horizontal_button_count(
        cell.display_kind, cell.entries, cell.grid, cell.spans
    )


#: Solver-facing cap on how many buttons a wide CONTRAST_SET
#: (base-and-variants) pill contributes to the row-width demand.
#: Set to 3 -- the width of the base-centered radial layout's
#: 3x3 grid, and of a 3-entry aligned 2x2 whose bounding box is
#: 2 wide. A click-language chart with 5-6-way phonation pills
#: sizes like a compact chart that has room for those pills at
#: their natural 3-column width; the vowel space is measured by
#: the number of DISTINCT QUALITIES (populated cells) times the
#: radial pill's canonical 3-button footprint, NOT by each cell's
#: full variant count. PAIR kinds keep their actual button count.
#: A CONTRAST_SET wider than 3 buttons (only reachable via the
#: horizontal 3-entry triple, which is exactly 3) hits this cap
#: but never exceeds it, so no pill overflows its reserved slot.
_SOLVER_MAX_CONTRAST_SET_BUTTONS: int = 3


def _cell_solver_button_count(cell: VowelChartCell) -> int:
    """The horizontal button count the SIZING solver reserves for
    ``cell`` in the row-width demand.

    * PAIR kinds (long / nasal / rhotic / phonation / tone /
      pharyngeal): the ACTUAL button count, so a 3-4-way phonation
      capsule reserves what it draws and never overflows.
    * CONTRAST_SET (aligned 2x2 or a base-and-variants layout):
      capped at :py:data:`_SOLVER_MAX_CONTRAST_SET_BUTTONS` so a
      wide click-language pill sizes like a plain pair; overflow
      is handled by the confinement pass.

    The RENDERER still draws :py:func:`_cell_horizontal_button_count`
    buttons; the two disagree by design for wide CONTRAST_SET cells.
    """
    n = _cell_horizontal_button_count(cell)
    if cell.display_kind == VowelCellDisplayKind.CONTRAST_SET:
        return min(n, _SOLVER_MAX_CONTRAST_SET_BUTTONS)
    return n


def _cell_solver_width_px(cell: VowelChartCell) -> int:
    """Solver-facing width (px) for ``cell``: the width the sizing
    and shrink solvers reserve, capped at the canonical pair
    footprint. Rendered width is :py:func:`_cell_width_px`; use this
    only inside the sizing / shrink solvers, never inside the box
    math the renderer consumes."""
    n = _cell_solver_button_count(cell)
    return n * BTN_W + (n - 1) * VOWEL_PAIR_GAP_PX


def _cell_width_px(cell: VowelChartCell) -> int:
    """Rendered pixel width of the cell's button block: ``n``
    buttons side by side with the pair gap between them, using the
    horizontal-density-tiered per-button width (see
    :py:func:`effective_button_width_px`) so wide !Xoo-style pills
    shrink their buttons rather than blowing up the row demand. The
    one width formula every consumer shares (the box rect, the
    conflict resolver, the natural sizing, the pipeline's extent
    growth) so "how wide is this cell" can never fork."""
    n_h = _cell_horizontal_button_count(cell)
    btn_w = effective_button_width_px(n_h)
    return n_h * btn_w + (n_h - 1) * VOWEL_PAIR_GAP_PX


def _cell_pair_offset_px(cell: VowelChartCell) -> float:
    """Signed horizontal offset (px) from the cell's anchor to its
    rendered centre: the pair-side shift plus the confinement nudge.
    The one offset formula the box rect, the natural sizing, and the
    pipeline's extent growth share, so "how far is this cell pushed
    off its anchor" can never fork (the vertical-axis mate of
    :py:func:`_cell_width_px`)."""
    return cell.pair_side * cell.pair_shift_px + cell.nudge_px


def _grid_cols_rows(
    grid: tuple[tuple[int, int], ...],
    spans: tuple[tuple[int, int], ...] = (),
) -> tuple[int, int]:
    """``(n_cols, n_rows)`` occupied by a CONTRAST_SET's ``(col, row)``
    slots: one past the max ``col + col_span`` and ``row + row_span``
    on each axis. A complete 2x2 -> ``(2, 2)``. A base-and-variants
    layout with base ``(0, 0)`` spanning ``(1, 2)`` plus one variant
    column -> ``(2, 2)``. Empty grid falls back to the canonical 2x2
    footprint; ``spans`` defaults to ``(1, 1)`` per entry when omitted.
    """
    if not grid:
        return (2, 2)
    if spans:
        return (
            max(
                col + col_span
                for (col, _row), (col_span, _row_span) in zip(grid, spans)
            ),
            max(
                row + row_span
                for (_col, row), (_col_span, row_span) in zip(grid, spans)
            ),
        )
    return (
        max(col for col, _row in grid) + 1,
        max(row for _col, row in grid) + 1,
    )


def vertical_depth(
    kind: VowelCellDisplayKind,
    n_entries: int,
    grid: tuple[tuple[int, int], ...] = (),
    spans: tuple[tuple[int, int], ...] = (),
) -> int:
    """Vertical row count a cell of ``kind`` with ``n_entries``
    contributes. PAIR kinds are 1 row; CONTRAST_SET is driven by its
    ``grid`` extent (a 2x2 is 2; a base-and-variants layout with base
    spanning two rows is 2), falling back to ``ceil(entries / 2)``
    when no grid is supplied; STACK is ``len(entries)``. The single
    definition shared by the height sizing, the confinement box math,
    and the pipeline's row-depth pre-pass, so the three can never
    disagree on how tall a cell renders. ``spans`` is treated as
    ``(1, 1)`` per entry when omitted.
    """
    if kind in PAIR_DISPLAY_KINDS:
        return 1
    if kind == VowelCellDisplayKind.CONTRAST_SET:
        if grid:
            return _grid_cols_rows(grid, spans)[1]
        return (n_entries + 1) // 2
    return n_entries


def content_height_px(
    kind: VowelCellDisplayKind,
    n_entries: int,
    grid: tuple[tuple[int, int], ...] = (),
    spans: tuple[tuple[int, int], ...] = (),
) -> int:
    """Rendered pixel height of a cell's button block: ``depth``
    button rows at the density-tier height with the stack gap
    between them.

    NOT monotonic in entry count: a 10-entry stack renders SHORTER
    than a 9-entry one because the ultra tier drops the per-button
    height from 22 to 18 px. Per-row maxima must therefore compare
    heights via this function, never raw depths; comparing depths
    lets the 9-deep cell overflow a slot sized for the 10-deep one.
    """
    depth = vertical_depth(kind, n_entries, grid, spans)
    eff_h = effective_button_height_px(depth)
    return depth * eff_h + (depth - 1) * _VOWEL_CELL_STACK_GAP_PX


def _cell_height_px(cell: VowelChartCell) -> int:
    """:py:func:`content_height_px` for an already-built cell. The
    vertical mate of :py:func:`_cell_width_px`: the one height
    formula the box rect, the natural sizing, and the pipeline's
    row weighting share."""
    return content_height_px(
        cell.display_kind, len(cell.entries), cell.grid, cell.spans
    )


def _cell_box_px(
    cell: VowelChartCell, dw: int, dh: int
) -> tuple[float, float, float, float]:
    """The cell's rendered button box ``(left, top, right, bottom)``
    in data-area pixels at the given rendered size.

    Mirrors BOTH renderers' placement math (desktop
    ``_layout_children``; web ``.vowel-chart-cell`` CSS): centre at
    ``chart_x * dw`` plus the signed pair shift, width from the
    horizontal button count, height from the stack depth at the
    density-tier button height. ``chart_y`` is the CELL CENTRE for
    every row (the pipeline's ``_finalize_row_plan`` nudges the
    extreme rows' centres inward so their edges hug the silhouette
    top / bottom), so the box uniformly centre-anchors on it. The
    confinement pass and the containment tests use this one
    definition, so "inside the outline" is judged against the same
    boxes the renderers draw.
    """
    ww = _cell_width_px(cell)
    wh = _cell_height_px(cell)
    left = cell.chart_x * dw - ww / 2.0 + _cell_pair_offset_px(cell)
    cy = cell.chart_y * dh
    top = cy - wh / 2.0
    return left, top, left + ww, top + wh
