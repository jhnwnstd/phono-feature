"""Vowel-chart layout geometry: silhouette sizing, cell placement,
and the render-ready :py:class:`VowelChartGeometry` shared by both
UIs. Lives separately from :py:mod:`phonology_shared.chart.vowels`
(the placement/inference layer) so the trapezoid silhouette solver
and per-cell positioning logic are greppable in isolation.

The inference layer answers "where in the vowel space does this
segment belong" (a phonological question over feature bundles).
This layer answers "given those placements, what does the chart
LOOK like" (a layout question over normalised ``[0, 1]`` coordinates
and pixel sizes). Both UIs (desktop Qt widget, web Pyodide-bridge
renderer) consume the :py:class:`VowelChartGeometry` produced by
:py:func:`build_vowel_chart_geometry`; neither duplicates placement
decisions or physical-coordinate arithmetic.

For backward compatibility, :py:mod:`phonology_shared.chart.vowels`
re-exports every public symbol declared here so existing imports
keep working.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from phonology_shared.chart.vowels import (
    _BACKNESS_X,
    _DISPLAY_CONTRAST_FEATURES,
    _HEIGHT_Y,
    _PAIR_KIND_FOR_FEATURE,
    _PAIR_OUTER_EXTENT,
    _ROW_LABEL_TO_INDEX,
    COL_LABELS,
    ROW_LABELS,
    PlacementPolicy,
    VowelCellDisplayKind,
    VowelChartShape,
    VowelProfile,
    _normalize_feat_keys,
    compute_placements,
    infer_vowel_shape,
    vowel_silhouette,
)
from phonology_shared.presentation.constants import BTN_W
from phonology_shared.presentation.layout import (
    SEG_BTN_H,
    VOWEL_PAIR_GAP_PX,
    VOWEL_PAIR_SEPARATOR_PX,
)

# ---------------------------------------------------------------------------
# Render-ready chart geometry.
#
# The dataclasses and ``build_vowel_chart_geometry`` below are the
# single source of truth that both the desktop Qt widget and the web
# Pyodide bridge consume. After the geometry is built, each renderer
# is a thin walk of the structure: emit a label per row, a button per
# cell entry. No frontend duplicates placement decisions or
# physical-coordinate arithmetic.
# ---------------------------------------------------------------------------

#: Title shown above the chart on both UIs. Centralised so a
#: future rename (e.g. localisation) touches one constant. The
#: placement contract for both renderers lives on
#: :py:class:`VowelChartGeometry`: centred over the data area only,
#: at the top of the chart's rectangular chrome.
VOWEL_CHART_TITLE: str = "VOWELS"


@dataclass(frozen=True)
class VowelChartCell:
    """A populated chart cell with its position resolved.

    The cell carries two ORTHOGONAL pieces of information so the
    renderer can keep "where in the trapezoid does this cell
    belong" (a position concern) cleanly separate from "how far
    apart should paired mates sit visually" (a display concern):

    * ``chart_x`` / ``chart_y``: normalised ``[0, 1]`` floats for
      the cell's BACKNESS ANCHOR projected through the chart's
      :py:class:`VowelChartShape`. Both unrounded and rounded
      mates at the same backness share the same anchor, so the
      paired-mate spacing does NOT change with chart width or
      with how narrow a low row becomes inside the trapezoid.
      Renderers drop the cell at
      ``left: calc(chart_x * 100%)`` / ``top: calc(chart_y * 100%)``
      (web) or the equivalent ``move()`` (Qt).
    * ``pair_side``: ``-1`` for the unrounded mate, ``+1`` for the
      rounded mate, ``0`` for an unrounded/rounded-unknown cell.
      The renderer applies a FIXED PIXEL shift of
      ``pair_side * (BTN_W + VOWEL_PAIR_GAP_PX) / 2`` on top of
      the anchor so paired mates are always exactly tangent
      regardless of the row's effective width.

    ``row`` / ``col`` are the abstract logical placement (0..5
    each). ``entries`` is the segments occupying this cell, ordered
    by descending placement confidence (ties broken by ascending
    segment string).

    ``display_kind`` tells the renderer how to arrange the entries
    inside the cell. ``STACK`` is the default vertical-stack
    layout. ``LONG_PAIR`` / ``NASAL_PAIR`` / ``RHOTIC_PAIR`` /
    ``PHONATION_PAIR`` / ``TONE_PAIR`` are side-by-side layouts
    (two entries differing only on a single in-cell-contrast
    feature; the marked member sits on the right).
    ``CONTRAST_SET`` is a 2x2 grid for 3-4 entries differing on
    multiple display features.

    ``contrast_features`` is the sorted tuple of display-contrast
    features that drove the kind choice (``()`` for ``STACK``).

    Invariants pinned by :py:mod:`tests.test_phoible_vowel_rendering_stress`
    across the full PHOIBLE catalogue:

    1. ``chart_x in [0, 1]`` and ``chart_y in [0, 1]``. The
       web renderer applies ``left: chart_x * 100%`` and
       ``top: chart_y * 100%`` without clamping.
    2. The cell's projected centre sits inside the
       :py:class:`VowelChartSilhouette` polygon (tolerance ~2% of
       the container) so the chart's outline always wraps the
       buttons.
    3. ``(row, col)`` is unique across all cells in the same
       geometry. The collision dict in :py:func:`compute_placements`
       enforces this by construction.
    4. ``entries`` is non-empty and contains no duplicate segments;
       every segment string appears in at most one cell across the
       geometry.
    """

    row: int
    col: int
    chart_x: float
    chart_y: float
    pair_side: int
    entries: tuple[str, ...]
    display_kind: VowelCellDisplayKind = VowelCellDisplayKind.STACK
    contrast_features: tuple[str, ...] = ()


@dataclass(frozen=True)
class VowelChartRow:
    """A row to render. ``logical_row`` indexes into ``ROW_LABELS``.
    ``chart_y`` is the row's normalised vertical position inside
    the trapezoid data area so a row-label renderer can vertically
    align the label with the row's data cells via
    ``top: calc(chart_y * 100%)``.

    ``tier`` tells renderers how the row's cells should anchor
    vertically: ``"top"`` rows anchor at chart_y and stacks hang
    DOWN, ``"bottom"`` rows anchor at chart_y and stacks rise UP,
    ``"middle"`` rows centre on chart_y. ``"only"`` is the
    single-row case (centre, with no other rows to grow into).
    """

    logical_row: int
    label: str
    chart_y: float
    tier: str = "middle"


@dataclass(frozen=True)
class VowelChartColHeader:
    """A backness column header (Front / Central / Back).

    ``chart_x`` is the column's backness ANCHOR as a normalised
    ``[0, 1]`` fraction of the data-area width. Renderers sit each
    header at ``chart_x * 100%`` so the header lines up over the
    centre of its column's cells at the widest (top) row.
    """

    label: str
    chart_x: float


@dataclass(frozen=True)
class VowelChartSilhouette:
    """The outline of the chart's data area, adapted to the
    inventory's populated rows.

    Position vs display split: ``top_y`` / ``bottom_y`` are the
    DISPLAY positions of the silhouette's top and bottom edges in
    the data area's normalised ``[0, 1]`` coordinate space (the
    silhouette always spans the full data area vertically so cells
    fill the available room). ``top_left`` / ``top_right`` /
    ``bottom_left`` / ``bottom_right`` are the four corners'
    horizontal positions, derived from the POSITIONAL identity of
    the topmost and bottommost populated logical rows (an
    inventory whose lowest row is Close-mid carries a much wider
    bottom edge than one whose lowest row is Open).

    Renderers draw the outline straight between these corners and
    project each cell's ``chart_x`` by linearly interpolating
    between ``top_width`` and ``bottom_width`` at the cell's
    ``chart_y`` so cells sit on the silhouette slant by
    construction.

    ``top_width`` / ``bottom_width`` are the row widths (full
    content-area fraction) at the two edges, exposed as
    independent data so the renderer can interpolate without
    re-deriving from the corners.
    """

    shape: VowelChartShape
    top_y: float
    bottom_y: float
    top_left: float
    top_right: float
    bottom_left: float
    bottom_right: float
    top_width: float
    bottom_width: float
    # Optional fixed-pixel correction added at render time to the
    # back silhouette edge. Renderers compute the back-edge x as
    # ``dx + top_right * dw + back_right_pixel_offset``; the
    # default ``0`` leaves the line at the canonical normalised
    # position ``top_right * dw``. The field is a refactor hook for
    # any future per-inventory back-edge tweak (e.g. snap-to-button
    # styles, breathing-room tuning); both UIs already consume it
    # through the shared formula so a value change here propagates
    # to desktop and web without touching either renderer.
    back_right_pixel_offset: int = 0


@dataclass(frozen=True, slots=True)
class VowelChartDiphthong:
    """One diphthong's primary -> secondary endpoint pair, with the
    grid coordinates the renderer uses to position the arrow.

    The endpoint's ``(row, col)`` keys identify the logical cells;
    ``primary_chart_x`` / ``primary_chart_y`` and
    ``secondary_chart_x`` / ``secondary_chart_y`` are the projected
    fractional positions (``[0, 1]``) the renderer applies directly.
    Carrying the projection here (rather than asking the renderer to
    look up cells in :py:attr:`VowelChartGeometry.cells`) decouples
    the diphthong overlay from cell population: a secondary that
    points to an unpopulated logical slot (PHOIBLE diphthong glides
    landing on a row/col the inventory does not otherwise specify)
    still gets a valid endpoint.

    The geometry builder computes the projection through the same
    silhouette + row-distribution math the populated cells use, so
    the arrow lands at the would-be cell position regardless of
    whether a vowel actually populates that slot.
    """

    segment: str
    primary_row: int
    primary_col: int
    secondary_row: int
    secondary_col: int
    primary_chart_x: float = 0.0
    primary_chart_y: float = 0.0
    secondary_chart_x: float = 0.0
    secondary_chart_y: float = 0.0


@dataclass(frozen=True, slots=True)
class VowelChartBand:
    """One height-tier band stripe. ``top_norm`` / ``bottom_norm``
    are clamped to the silhouette's y span; renderers apply them
    as ``top: top_norm * 100%; height: (bottom_norm - top_norm) *
    100%`` (web) or the equivalent fillRect (desktop). ``tinted``
    is True on alternate rows so the every-other-row rhythm is
    decided once rather than recomputed in each renderer's loop.
    """

    top_norm: float
    bottom_norm: float
    tinted: bool


@dataclass(frozen=True)
class VowelChartGeometry:
    """Complete render-ready description of a vowel chart.

    Both Qt and the web bridge consume this verbatim: emit one row
    label per :py:attr:`rows` entry, one cell per :py:attr:`cells`
    entry, and one button per segment in each cell.

    :py:attr:`shape` is the visual envelope the renderer paints
    around the chart (trapezoid by default, triangle for
    inventories without a backness contrast). The placement
    coordinates inside the chart do not change with shape; only
    the chart's outer outline does.

    :py:attr:`silhouette` carries the inventory-adapted silhouette
    corners so the renderer can paint the outline and confirm
    every cell sits on its slant.

    :py:attr:`natural_data_width_px` and
    :py:attr:`natural_data_height_px` are the data-area's preferred
    pixel dimensions, derived from the inventory's content: the
    width grows with the widest row's button + gap requirements,
    and the height grows with row count + per-row vertical-stack
    depth. Renderers should treat these as the chart container's
    PREFERRED natural size and add chrome (title, row labels,
    column headers, padding) on top.

    Empty rows (no vowels in any column at that height tier) are
    OMITTED from :py:attr:`rows`; renderers iterate the list as-is
    without a "is this row populated" check.

    **Title placement contract.** :py:attr:`title` is the heading
    text both renderers display above the chart. Both UIs MUST
    place it CENTRED OVER THE DATA AREA (not over "row-label
    gutter + data area" together) and at the TOP of the chart's
    rectangular chrome. The desktop achieves this by manually
    moving the title QLabel to ``(dx + (dw - tw) // 2, 0)`` inside
    :py:meth:`VowelChartWidget._layout_children`; the web pins
    ``.vowel-chart-title`` to grid row 1, column 2 of the
    ``.vowel-chart`` grid (the data column only). New renderers
    must follow the same rule so the title stays visually aligned
    with the column headers and the data cells below.
    """

    title: str
    shape: VowelChartShape
    silhouette: VowelChartSilhouette
    cols: tuple[VowelChartColHeader, ...]
    rows: tuple[VowelChartRow, ...]
    cells: tuple[VowelChartCell, ...]
    natural_data_width_px: int
    natural_data_height_px: int
    # Diphthong rendering hints. One entry per vowel segment whose
    # PHOIBLE encoding spans two cells: the renderer draws a curved
    # arrow from ``primary_cell`` to ``secondary_cell``; the glyph
    # itself stays in ``primary_cell``. Empty for monophthong-only
    # inventories.
    diphthongs: tuple[VowelChartDiphthong, ...] = ()
    # Height-tier banding rectangles. One band per populated row,
    # with ``(top_norm, bottom_norm)`` clamped to the silhouette
    # span and ``tinted`` alternating every other row. Renderers
    # paint as a translucent fill behind cells; midpoint math
    # lives here so both renderers iterate, not compute.
    bands: tuple[VowelChartBand, ...] = ()


#: Gap between vertically stacked segment buttons inside a single
#: cell. Smaller than the inter-row gap because the stack reads as
#: one cell, not several.
_VOWEL_CELL_STACK_GAP_PX: int = 1

#: Vertical breathing room between adjacent populated rows. Picked
#: to read as a row break without overweighting the chart's chrome.
_VOWEL_ROW_GAP_PX: int = 6

#: Vertical padding (top + bottom combined) around the row content
#: so the silhouette's top edge can cut through the Close row's
#: button centres without clipping their tops.
_VOWEL_DATA_AREA_VERTICAL_PADDING_PX: int = SEG_BTN_H

#: Reference content width (px) used to convert cell pixel sizes
#: into the normalised ``[0, 1]`` coordinate space the silhouette
#: lives in. Matches the canonical anchor derivation in
#: :py:func:`_derive_backness_anchors` so cell-extent math stays
#: consistent with chart_x.
_VOWEL_CONTENT_W_PX: float = float(
    3 * (2 * BTN_W + VOWEL_PAIR_GAP_PX) + 2 * VOWEL_PAIR_SEPARATOR_PX
)

#: How aggressively the silhouette's top_width and bottom_width
#: shrink toward each row's minimum-required width. ``0.0`` keeps
#: the canonical widths; ``1.0`` would consume all per-row slack.
#: Stage 1 uses this against the most-constrained row's slack;
#: Stage 2 reuses it as the per-row consumption ceiling so the same
#: aggression governs both passes. Both the silhouette outline and
#: the back-anchored cell projection use the resulting widths, so
#: cells follow the silhouette by construction with no drift.
_VOWEL_SHRINK_FACTOR: float = 0.3

#: Hard cap on how much Stage 2 may tilt the trapezoid, expressed
#: as a fraction of the canonical slant ``canonical_top_width -
#: canonical_bottom_width``. Stage 1 preserves the canonical
#: proportions; Stage 2 then asks: with the new narrower trapezoid,
#: is there still slack at the top OR the bottom that pure uniform
#: shrink missed? If so, top and bottom are nudged inward by
#: DIFFERENT amounts (changing the slant), capped here so the chart
#: stays visually recognisable as the canonical IPA trapezoid.
#: ``0.0`` disables Stage 2; ``1.0`` would let the slant double (or
#: invert).
_VOWEL_SLANT_CHANGE_CAP_FRAC: float = 0.30

#: Minimum visual separation between adjacent cells in the same
#: row (expressed as a fraction of the canonical content width).
#: Matches the inter-pair separator on the canonical 3-slot
#: layout, so two pinched-together slots end up with the same
#: comfortable gap as canonical adjacent pairs.
_VOWEL_MIN_CELL_GAP_NORM: float = VOWEL_PAIR_SEPARATOR_PX / _VOWEL_CONTENT_W_PX


def _row_content_extent(
    cells: tuple[VowelChartCell, ...],
    row: int,
) -> tuple[float, float] | None:
    """Leftmost and rightmost normalised x extent of the cells at
    ``row``. Returns ``None`` when the row has no cells.

    Cell widths are taken as the rendered button or Long-pair-
    container size, converted to normalised coords via the
    canonical content-width reference.
    """
    row_cells = [c for c in cells if c.row == row]
    if not row_cells:
        return None
    pair_shift = (BTN_W + VOWEL_PAIR_GAP_PX) / 2.0 / _VOWEL_CONTENT_W_PX
    single_half = (BTN_W / 2.0) / _VOWEL_CONTENT_W_PX
    long_pair_half = (
        (2 * BTN_W + VOWEL_PAIR_GAP_PX) / 2.0 / _VOWEL_CONTENT_W_PX
    )
    lefts: list[float] = []
    rights: list[float] = []
    for cell in row_cells:
        is_pair = cell.display_kind in PAIR_DISPLAY_KINDS
        half = long_pair_half if is_pair else single_half
        center = cell.chart_x + cell.pair_side * pair_shift
        lefts.append(center - half)
        rights.append(center + half)
    return min(lefts), max(rights)


def _min_row_width_for_meta(
    row_cells: list[tuple[int, int, bool]],
) -> float:
    """Lower bound on ``row_width`` such that the row's cells do
    not overlap given back-anchored projection.

    Each tuple is ``(col, pair_side, is_long_pair)``; the cell's
    horizontal extent is its half-width plus its pair-side offset
    from the row's projected anchor. With back-anchored projection
    ``chart_x = back + W * (anchor - back)``, the distance between
    two cells at adjacent anchors scales linearly with ``W``; this
    function solves for the minimum ``W`` such that every adjacent
    pair has at least ``_VOWEL_MIN_CELL_GAP_NORM`` between them
    (zero if a single cell occupies the row).
    """
    if len(row_cells) < 2:
        return 0.0
    canonical_anchor: dict[int, float] = {
        0: _BACKNESS_X["front"],
        1: _BACKNESS_X["front"],
        6: _BACKNESS_X["front"],
        2: _BACKNESS_X["central"],
        3: _BACKNESS_X["central"],
        7: _BACKNESS_X["central"],
        4: _BACKNESS_X["back"],
        5: _BACKNESS_X["back"],
        8: _BACKNESS_X["back"],
    }
    pair_shift = (BTN_W + VOWEL_PAIR_GAP_PX) / 2.0 / _VOWEL_CONTENT_W_PX
    single_half = (BTN_W / 2.0) / _VOWEL_CONTENT_W_PX
    long_pair_half = (
        (2 * BTN_W + VOWEL_PAIR_GAP_PX) / 2.0 / _VOWEL_CONTENT_W_PX
    )
    sorted_meta = sorted(row_cells, key=lambda c: canonical_anchor[c[0]])
    min_w = 0.0
    for (col_a, ps_a, lp_a), (col_b, ps_b, lp_b) in zip(
        sorted_meta, sorted_meta[1:]
    ):
        anchor_a = canonical_anchor[col_a]
        anchor_b = canonical_anchor[col_b]
        if anchor_b <= anchor_a:
            # Same backness slot -- pair_side handles separation.
            continue
        half_a = long_pair_half if lp_a else single_half
        half_b = long_pair_half if lp_b else single_half
        # Center distance at row_width=W = W*(anchor_b - anchor_a)
        # + (ps_b - ps_a) * pair_shift. For non-overlap with a
        # min visible gap, this must be >= half_a + half_b + gap.
        required = (
            _VOWEL_MIN_CELL_GAP_NORM
            + half_a
            + half_b
            - (ps_b - ps_a) * pair_shift
        )
        w_req = required / (anchor_b - anchor_a)
        if w_req > min_w:
            min_w = w_req
    return max(0.0, min(1.0, min_w))


def _compute_shrunken_widths(
    cells_meta_by_row: dict[int, list[tuple[int, int, bool]]],
    display_y_by_row: dict[int, float],
    top_y: float,
    bottom_y: float,
    canonical_top_width: float,
    canonical_bottom_width: float,
) -> tuple[float, float]:
    """Compute shrunken silhouette ``(top_width, bottom_width)`` in
    two conceptual stages.

    **Stage 1 -- uniform shrink.** Both widths drop by the same
    amount, set by the most-constrained row's slack between its
    canonical row_width and its minimum-required row_width. The
    trapezoid keeps its canonical proportions while pulling inward
    as a whole; the slant stays constant.

    **Stage 2 -- slant tweak.** With Stage 1's narrower trapezoid in
    hand, rows that still have slack let us nudge the top OR the
    bottom further inward by DIFFERENT amounts. This changes the
    slant; :py:data:`_VOWEL_SLANT_CHANGE_CAP_FRAC` caps the change
    so the result still reads as the canonical IPA trapezoid.

    Both stages share the same ``_min_row_width_for_meta`` floor and
    the same ``_VOWEL_SHRINK_FACTOR`` aggression so a future tuning
    of either touches both passes consistently.
    """
    if _VOWEL_SHRINK_FACTOR <= 0.0:
        return canonical_top_width, canonical_bottom_width
    span = bottom_y - top_y
    if span <= 0:
        return canonical_top_width, canonical_bottom_width
    row_data: list[tuple[float, float]] = []
    for r, meta in cells_meta_by_row.items():
        if r not in display_y_by_row:
            continue
        t = (display_y_by_row[r] - top_y) / span
        row_data.append((t, _min_row_width_for_meta(meta)))
    if not row_data:
        return canonical_top_width, canonical_bottom_width
    stage1_top, stage1_bot = _stage1_uniform_shrink(
        row_data, canonical_top_width, canonical_bottom_width
    )
    return _stage2_slant_tweak(
        row_data,
        stage1_top,
        stage1_bot,
        canonical_top_width,
        canonical_bottom_width,
    )


def _stage1_uniform_shrink(
    row_data: list[tuple[float, float]],
    canonical_top_width: float,
    canonical_bottom_width: float,
) -> tuple[float, float]:
    """Stage 1: pull top and bottom inward by the same amount,
    bounded by the most-constrained row. Preserves the canonical
    slant.
    """
    min_slack = float("inf")
    for t, min_w in row_data:
        canonical_row_w = (
            canonical_top_width * (1.0 - t) + canonical_bottom_width * t
        )
        slack = canonical_row_w - min_w
        if slack < min_slack:
            min_slack = slack
    if min_slack <= 0 or min_slack == float("inf"):
        return canonical_top_width, canonical_bottom_width
    consume = _VOWEL_SHRINK_FACTOR * min_slack
    return (
        max(0.0, canonical_top_width - consume),
        max(0.0, canonical_bottom_width - consume),
    )


def _stage2_slant_tweak(
    row_data: list[tuple[float, float]],
    stage1_top: float,
    stage1_bot: float,
    canonical_top_width: float,
    canonical_bottom_width: float,
) -> tuple[float, float]:
    """Stage 2: with Stage 1's narrower trapezoid, see how much more
    width each edge can lose by nudging top and bottom independently.

    Solves a 2-variable LP -- maximise ``d_top + d_bot`` (the area
    removed in this pass, modulo the constant span/2) -- with three
    families of constraints:

    1. Per-row slack. After Stage 1, each row at ``t`` still has
       ``stage1_row_w(t) - min_w`` of slack; ``_VOWEL_SHRINK_FACTOR``
       of that is the per-row consumption ceiling, matching Stage 1's
       conservativeness. ``d_top * (1 - t) + d_bot * t <= ceiling``.
    2. Slant cap. ``|d_top - d_bot| <= cap``, where ``cap`` is a
       fraction of the canonical slant magnitude. Symmetric so the
       slant may either flatten (top loses more) or steepen (bottom
       loses more) within the same budget.
    3. Box bounds. ``0 <= d_top <= stage1_top`` and analogous for
       ``d_bot``, so neither edge can run negative.

    With only two variables the optimum sits at a vertex of the
    feasible polygon, which is the intersection of two binding
    constraints. We enumerate every pair, accept feasible
    intersections, and keep the best score. With ~10 constraints
    for a 7-row chart this is O(100) trivial 2x2 solves -- cheap
    enough to skip a dedicated LP dependency.
    """
    if _VOWEL_SLANT_CHANGE_CAP_FRAC <= 0.0:
        return stage1_top, stage1_bot
    canonical_slant = abs(canonical_top_width - canonical_bottom_width)
    if canonical_slant <= 0.0:
        return stage1_top, stage1_bot
    cap = _VOWEL_SLANT_CHANGE_CAP_FRAC * canonical_slant
    constraints: list[tuple[float, float, float]] = []
    for t, min_w in row_data:
        stage1_row_w = stage1_top * (1.0 - t) + stage1_bot * t
        slack = max(0.0, stage1_row_w - min_w)
        constraints.append((1.0 - t, t, _VOWEL_SHRINK_FACTOR * slack))
    constraints.append((1.0, -1.0, cap))
    constraints.append((-1.0, 1.0, cap))
    constraints.append((-1.0, 0.0, 0.0))
    constraints.append((0.0, -1.0, 0.0))
    constraints.append((1.0, 0.0, stage1_top))
    constraints.append((0.0, 1.0, stage1_bot))
    eps = 1e-9

    def feasible(d_top: float, d_bot: float) -> bool:
        return all(a * d_top + b * d_bot <= c + eps for a, b, c in constraints)

    best = (0.0, 0.0)
    best_score = 0.0
    n = len(constraints)
    for i in range(n):
        a1, b1, c1 = constraints[i]
        for j in range(i + 1, n):
            a2, b2, c2 = constraints[j]
            det = a1 * b2 - a2 * b1
            if abs(det) < 1e-12:
                continue
            d_top = (c1 * b2 - c2 * b1) / det
            d_bot = (a1 * c2 - a2 * c1) / det
            if not feasible(d_top, d_bot):
                continue
            score = d_top + d_bot
            if score > best_score:
                best_score = score
                best = (d_top, d_bot)
    d_top, d_bot = best
    return (
        max(0.0, stage1_top - d_top),
        max(0.0, stage1_bot - d_bot),
    )


def _silhouette_with_widths(
    silhouette: VowelChartSilhouette,
    top_width: float,
    bottom_width: float,
) -> VowelChartSilhouette:
    """Recompute silhouette corners for new ``top_width`` /
    ``bottom_width`` while keeping shape, y bounds, and the back
    anchor + pixel offset. The back edge stays a vertical line at
    ``back`` (anchor) + ``back_right_pixel_offset`` (pixels).
    """
    front = _BACKNESS_X["front"]
    back = _BACKNESS_X["back"]
    pair_outer = _PAIR_OUTER_EXTENT
    front_at_top = back + top_width * (front - back)
    front_at_bottom = back + bottom_width * (front - back)
    return replace(
        silhouette,
        top_left=front_at_top - pair_outer,
        top_right=back + pair_outer,
        bottom_left=front_at_bottom - pair_outer,
        bottom_right=back + pair_outer,
        top_width=top_width,
        bottom_width=bottom_width,
    )


#: PAIR display kinds; renderers lay these out as one horizontal
#: row of two buttons. Shared by ``_cell_natural_size`` and both
#: renderer dispatches.
PAIR_DISPLAY_KINDS: frozenset[VowelCellDisplayKind] = frozenset(
    {
        VowelCellDisplayKind.LONG_PAIR,
        VowelCellDisplayKind.NASAL_PAIR,
        VowelCellDisplayKind.RHOTIC_PAIR,
        VowelCellDisplayKind.PHONATION_PAIR,
        VowelCellDisplayKind.TONE_PAIR,
    }
)


def _classify_vowel_cell_display(
    entries: tuple[str, ...],
    norm_feats: Mapping[str, Mapping[str, str]],
) -> tuple[VowelCellDisplayKind, tuple[str, ...], tuple[str, ...]]:
    """Pick a :py:class:`VowelCellDisplayKind` for ``entries``.

    Pure classifier over canonical feature bundles: no coordinate
    knowledge, no renderer knowledge. Returns ``(kind,
    contrast_features, ordered_entries)`` where
    ``contrast_features`` is the sorted tuple of in-cell-contrast
    features the entries differ on (``()`` for ``STACK``) and
    ``ordered_entries`` is the input tuple with the PAIR ordering
    convention (marked / ``+``-valued member on the right) applied
    when the kind is a PAIR; otherwise input order is preserved.

    Decision tree:
      1. < 2 entries -> STACK.
      2. Compute the set of features whose values are NOT identical
         across the entries (skipping ``None``-only differences so
         a one-sided ``"0"`` does not register as a contrast).
      3. Partition into display features (intersection with
         :py:data:`_DISPLAY_CONTRAST_FEATURES`) and other features.
      4. If any non-display feature differs -> STACK. The entries
         differ on a position feature; stacking is the safe layout.
      5. Two entries differing on exactly one display feature ->
         the matching PAIR kind (or PHONATION_PAIR for the joint
         breathy/creaky case).
      6. Two entries differing on multiple display features OR
         3-4 entries differing on any display features ->
         CONTRAST_SET.
      7. Otherwise -> STACK.
    """
    if len(entries) < 2:
        return VowelCellDisplayKind.STACK, (), entries
    bundles = [
        _normalize_feat_keys(norm_feats.get(seg, {})) for seg in entries
    ]
    all_keys: set[str] = set()
    for b in bundles:
        all_keys.update(b)
    differing: set[str] = set()
    for key in all_keys:
        vals = {b.get(key) for b in bundles}
        vals.discard(None)
        if len(vals) > 1:
            differing.add(key)
    differing_display = differing & _DISPLAY_CONTRAST_FEATURES
    differing_other = differing - _DISPLAY_CONTRAST_FEATURES
    if differing_other or not differing_display:
        return VowelCellDisplayKind.STACK, (), entries
    contrast = tuple(sorted(differing_display))
    if len(entries) == 2:
        if differing_display.issubset({"breathy", "creaky"}):
            kind = VowelCellDisplayKind.PHONATION_PAIR
        elif len(differing_display) == 1:
            (only,) = differing_display
            kind = _PAIR_KIND_FOR_FEATURE.get(
                only, VowelCellDisplayKind.CONTRAST_SET
            )
        else:
            kind = VowelCellDisplayKind.CONTRAST_SET
        ordered: tuple[str, ...] = entries
        if kind in PAIR_DISPLAY_KINDS:
            ordered = _order_pair_entries(entries, bundles, kind)
        return kind, contrast, ordered
    if 3 <= len(entries) <= 4:
        return VowelCellDisplayKind.CONTRAST_SET, contrast, entries
    return VowelCellDisplayKind.STACK, (), entries


def _order_pair_entries(
    entries: tuple[str, ...],
    bundles: list[dict[str, str]],
    kind: VowelCellDisplayKind,
) -> tuple[str, ...]:
    """Reorder a 2-entry PAIR tuple so the "marked" member sits on
    the right (canonical reading direction).

    LONG_PAIR / NASAL_PAIR / RHOTIC_PAIR / TONE_PAIR sort by the
    underlying feature value (``+`` to the right). PHONATION_PAIR
    puts the modal entry (neither breathy nor creaky) on the left
    when one exists; otherwise sorts on whichever feature is the
    single contrast. The reordering is stable: ties keep input
    order.
    """
    feature_for_kind = {
        VowelCellDisplayKind.LONG_PAIR: "long",
        VowelCellDisplayKind.NASAL_PAIR: "nasal",
        VowelCellDisplayKind.RHOTIC_PAIR: "rhotic",
        VowelCellDisplayKind.TONE_PAIR: "tone",
    }
    if kind in feature_for_kind:
        feat = feature_for_kind[kind]
        a_val = bundles[0].get(feat)
        b_val = bundles[1].get(feat)
        if a_val == "+" and b_val != "+":
            return (entries[1], entries[0])
        return entries
    if kind == VowelCellDisplayKind.PHONATION_PAIR:

        def _is_modal(b: dict[str, str]) -> bool:
            return b.get("breathy") not in ("+",) and b.get("creaky") not in (
                "+",
            )

        if _is_modal(bundles[0]) and not _is_modal(bundles[1]):
            return entries
        if _is_modal(bundles[1]) and not _is_modal(bundles[0]):
            return (entries[1], entries[0])
        for feat in ("breathy", "creaky"):
            a_val = bundles[0].get(feat)
            b_val = bundles[1].get(feat)
            if a_val == "+" and b_val != "+":
                return (entries[1], entries[0])
            if b_val == "+" and a_val != "+":
                return entries
    return entries


def _natural_data_area_size(
    cells: tuple[VowelChartCell, ...],
) -> tuple[int, int]:
    """Derive the chart data area's preferred pixel size from the
    inventory's content.

    The chart grows along both axes so the rendered cells have room
    to breathe:

    * Width is set by the widest populated row's button + gap
      requirements. Each backness slot (front / central / back)
      contributes ``N * BTN_W + (N - 1) * VOWEL_PAIR_GAP_PX`` where
      ``N`` is the slot's button count (a PAIR cell contributes 2
      buttons horizontally; a CONTRAST_SET cell contributes 2; a
      regular single contributes 1). Slot widths are separated by
      ``VOWEL_PAIR_SEPARATOR_PX``.
    * Height is set by the populated rows' content height: each
      row contributes ``max_stack * SEG_BTN_H + (max_stack - 1) *
      stack_gap`` where ``max_stack`` is the row's deepest vertical
      depth. PAIR cells count as 1 (horizontal layout); CONTRAST_SET
      cells count as ``ceil(entries / 2)`` (2x2 or 2x1 grid). STACK
      cells count as ``len(entries)``. Rows are separated by
      ``_VOWEL_ROW_GAP_PX`` and the silhouette adds vertical
      padding above the top row and below the bottom row.
    """
    if not cells:
        # Fall back to a single canonical pair slot.
        return (
            2 * BTN_W + VOWEL_PAIR_GAP_PX,
            SEG_BTN_H + _VOWEL_DATA_AREA_VERTICAL_PADDING_PX,
        )

    # col -> backness slot (front=0, central=1, back=2).
    col_to_slot: dict[int, int] = {
        0: 0,
        1: 0,
        6: 0,
        2: 1,
        3: 1,
        7: 1,
        4: 2,
        5: 2,
        8: 2,
    }

    def _cell_button_width_count(cell: VowelChartCell) -> int:
        """Horizontal button count contributed by ``cell`` for slot
        sizing. PAIR cells take 2; CONTRAST_SET takes 2 (2-column
        grid); STACK takes 1.
        """
        if cell.display_kind in PAIR_DISPLAY_KINDS:
            return 2
        if cell.display_kind == VowelCellDisplayKind.CONTRAST_SET:
            return 2
        return 1

    def _cell_vertical_depth(cell: VowelChartCell) -> int:
        """Vertical row count contributed by ``cell`` for height
        sizing. PAIR cells are 1 row; CONTRAST_SET is
        ``ceil(entries / 2)``; STACK is ``len(entries)``.
        """
        if cell.display_kind in PAIR_DISPLAY_KINDS:
            return 1
        if cell.display_kind == VowelCellDisplayKind.CONTRAST_SET:
            return (len(cell.entries) + 1) // 2
        return len(cell.entries)

    rows_in_use: set[int] = {c.row for c in cells}
    max_row_w = 2 * BTN_W + VOWEL_PAIR_GAP_PX
    for ri in rows_in_use:
        # Buttons per backness slot at this row.
        slot_buttons: dict[int, int] = {0: 0, 1: 0, 2: 0}
        for c in cells:
            if c.row != ri:
                continue
            slot = col_to_slot[c.col]
            slot_buttons[slot] += _cell_button_width_count(c)
        populated_slots = [s for s, n in slot_buttons.items() if n > 0]
        if not populated_slots:
            continue
        slot_widths = [
            slot_buttons[s] * BTN_W
            + max(0, slot_buttons[s] - 1) * VOWEL_PAIR_GAP_PX
            for s in populated_slots
        ]
        row_w = sum(slot_widths) + (len(populated_slots) - 1) * (
            VOWEL_PAIR_SEPARATOR_PX
        )
        max_row_w = max(max_row_w, row_w)

    # Height: per-row max stack depth, plus inter-row gaps and
    # vertical padding for the silhouette's top/bottom offset.
    row_heights: list[int] = []
    for ri in sorted(rows_in_use):
        depth = 1
        for c in cells:
            if c.row != ri:
                continue
            cell_depth = _cell_vertical_depth(c)
            if cell_depth > depth:
                depth = cell_depth
        row_heights.append(
            depth * SEG_BTN_H + max(0, depth - 1) * _VOWEL_CELL_STACK_GAP_PX
        )

    total_h = sum(row_heights) + (len(row_heights) - 1) * _VOWEL_ROW_GAP_PX
    total_h += _VOWEL_DATA_AREA_VERTICAL_PADDING_PX
    return max_row_w, total_h


def build_vowel_chart_geometry(
    segs: list[str],
    profile: VowelProfile,
    norm_feats: Mapping[str, Mapping[str, str]],
    policy: PlacementPolicy | None = None,
    vowel_secondary: Mapping[str, Mapping[str, str]] | None = None,
) -> VowelChartGeometry:
    """End-to-end: compute placements and produce a render-ready
    chart geometry for both UIs.

    Steps:
      1. Delegate to :py:func:`compute_placements` for the per-vowel
         cell + collision-grouping decision.
      2. For each populated cell, build a :py:class:`VowelChartCell`
         carrying its occupants.
      3. For each populated height tier, build a
         :py:class:`VowelChartRow` with the assigned physical grid
         row.

    ``vowel_secondary`` carries final-state feature bundles for
    PHOIBLE diphthong segments. When present, the returned geometry's
    :py:attr:`VowelChartGeometry.diphthongs` lists one entry per
    diphthong with both endpoint cells so renderers can draw a
    curved arrow between them.

    Renderers attach the result directly: no placement decisions
    and no coordinate arithmetic happen at the UI layer.
    """
    occupied, placements = compute_placements(
        segs, profile, norm_feats, policy, vowel_secondary=vowel_secondary
    )

    populated_logical_rows = sorted({row for (row, _) in occupied})
    shape = infer_vowel_shape(profile)

    # Empty case: the inventory has no vowels (consonant-only setup,
    # or a fresh "New" with the default-segments placeholder which
    # is all-stops). Skip every row/cell-dependent computation and
    # return a degenerate geometry with the canonical full-range
    # silhouette so renderers can still draw the empty chart chrome
    # (or hide it) by iterating zero-length ``rows`` / ``cells`` /
    # ``cols``. Without this short-circuit the silhouette index
    # ``populated_logical_rows[0]`` raises IndexError and the whole
    # New-inventory flow dies for any inventory without vowels.
    if not populated_logical_rows:
        return VowelChartGeometry(
            title=VOWEL_CHART_TITLE,
            shape=shape,
            silhouette=vowel_silhouette(shape),
            cols=(),
            rows=(),
            cells=(),
            natural_data_width_px=0,
            natural_data_height_px=0,
        )

    # Silhouette: position logic (top/bottom widths) comes from the
    # populated logical row range; display logic (top_y/bottom_y)
    # always spans the full data area so cells use every pixel
    # regardless of which rows are present.
    silhouette = vowel_silhouette(
        shape,
        top_logical_row=populated_logical_rows[0],
        bottom_logical_row=populated_logical_rows[-1],
    )

    # Display y per populated row: distributed in the silhouette's
    # vertical span PROPORTIONAL TO PER-ROW CONTENT DEPTH so a row
    # with a tall stack (Korean PHOIBLE has 7 entries at Close-Back,
    # 6 at Close-Front) gets enough vertical room before the next
    # row starts. Even distribution let a 7-button stack at row 0
    # overlap rows 2/4/5 below; the stack visually invaded the
    # Close-mid / Open-mid cells.
    #
    # Per-row depth is the max ``_cell_vertical_depth`` (PAIR -> 1;
    # CONTRAST_SET -> ceil(n/2); STACK -> n) computed by running
    # the same display-kind classifier ``cell_meta`` will use a few
    # lines below; here we only need the depth.
    #
    # Each row gets a slot whose height is ``depth / total_depth``
    # of the silhouette span. The row's chart_y anchor sits at:
    #   - top of slot for the topmost row (the CSS row-tier
    #     ``top`` anchor renders the stack DOWNWARD from chart_y);
    #   - bottom of slot for the bottommost row (``bottom`` anchor
    #     renders UPWARD from chart_y);
    #   - centre of slot for middle rows (default centred anchor).
    # The renderer's ``data-row-tier`` attribute matches this
    # scheme so the cell box fills its slot.
    # Classify every populated cell ONCE. Both ``_row_depth`` (the
    # depth pre-pass below) and the later ``cell_meta`` loop need
    # the same ``(display_kind, contrast_features, ordered_entries)``
    # tuple; profiling (W2: 5252 calls / 259 ms across 200 PHOIBLE
    # inventories) showed the classifier ran twice per cell. One
    # build_vowel_chart_geometry call now produces one classification
    # per cell, indexed by (row, col).
    cell_classifications: dict[
        tuple[int, int],
        tuple[
            VowelCellDisplayKind,
            tuple[str, ...],
            tuple[str, ...],
        ],
    ] = {
        rc: _classify_vowel_cell_display(tuple(entries), norm_feats)
        for rc, entries in occupied.items()
    }

    def _row_depth(ri: int) -> int:
        max_depth = 1
        for (r, _c), _entries in occupied.items():
            if r != ri:
                continue
            display_kind, _, ord_entries = cell_classifications[(r, _c)]
            if display_kind in PAIR_DISPLAY_KINDS:
                depth = 1
            elif display_kind == VowelCellDisplayKind.CONTRAST_SET:
                depth = (len(ord_entries) + 1) // 2
            else:
                depth = len(ord_entries)
            if depth > max_depth:
                max_depth = depth
        return max_depth

    row_depths = {ri: _row_depth(ri) for ri in populated_logical_rows}
    if len(populated_logical_rows) == 1:
        display_y_by_row = {
            populated_logical_rows[0]: (silhouette.top_y + silhouette.bottom_y)
            / 2
        }
    else:
        span = silhouette.bottom_y - silhouette.top_y
        total_depth = sum(row_depths.values())
        display_y_by_row = {}
        cursor = silhouette.top_y
        last_index = len(populated_logical_rows) - 1
        for i, ri in enumerate(populated_logical_rows):
            slot_height = row_depths[ri] / total_depth * span
            if i == 0:
                # Top row anchors at the top of its slot.
                display_y_by_row[ri] = cursor
            elif i == last_index:
                # Bottom row anchors at the bottom of its slot.
                display_y_by_row[ri] = cursor + slot_height
            else:
                # Middle rows anchor at the centre of their slot.
                display_y_by_row[ri] = cursor + slot_height / 2
            cursor += slot_height

    if len(populated_logical_rows) == 1:
        _row_tier = {populated_logical_rows[0]: "only"}
    else:
        _row_tier = {
            populated_logical_rows[0]: "top",
            populated_logical_rows[-1]: "bottom",
        }
    rows = tuple(
        VowelChartRow(
            logical_row=ri,
            label=ROW_LABELS[ri],
            chart_y=display_y_by_row[ri],
            tier=_row_tier.get(ri, "middle"),
        )
        for ri in populated_logical_rows
    )

    def _width_at_display_y(y: float) -> float:
        """Linear interp between silhouette top and bottom widths
        at the given display y. Unifies position (silhouette) and
        display (cell y) at the cell projection step so cells lie
        on the silhouette slant by construction.
        """
        if silhouette.bottom_y == silhouette.top_y:
            return silhouette.top_width
        t = (y - silhouette.top_y) / (silhouette.bottom_y - silhouette.top_y)
        return silhouette.top_width * (1.0 - t) + silhouette.bottom_width * t

    back = _BACKNESS_X["back"]

    # Map ``col`` to its backness anchor. Pair side (unrounded vs
    # rounded) is handled separately by the renderer as a fixed
    # pixel shift so the within-pair gap stays constant regardless
    # of how narrow a row becomes inside the trapezoid. Cols 6..8
    # are the neutral-round slots that sit on the anchor centre
    # with no L/R shift.
    _col_to_anchor: dict[int, float] = {
        0: _BACKNESS_X["front"],
        1: _BACKNESS_X["front"],
        2: _BACKNESS_X["central"],
        3: _BACKNESS_X["central"],
        4: _BACKNESS_X["back"],
        5: _BACKNESS_X["back"],
        6: _BACKNESS_X["front"],
        7: _BACKNESS_X["central"],
        8: _BACKNESS_X["back"],
    }
    open_row_index = _ROW_LABEL_TO_INDEX["Open"]
    # Open-row front-pair cells (cols 0 / 1) take priority for the
    # bottom-left of the trapezoid. When they are empty, the Open
    # central pair migrates leftward to occupy that visual slot
    # (a one-low-vowel inventory's central /a/ should not sit at
    # the geometric midpoint of the narrowed bottom edge). When
    # the front pair IS populated, central stays at its true
    # central anchor so the two cells do not collide.
    open_front_populated = (open_row_index, 0) in occupied or (
        open_row_index,
        1,
    ) in occupied

    # First pass: classify each cell's display kind, resolve
    # ordering, and compute col / pair_side. The display layer
    # needs these to size the silhouette before it can fix cell
    # ``chart_x`` positions. No phonology re-decisions happen
    # below this point -- the cell COL/row are already final;
    # only their pixel-space position is still pending.
    cell_meta: list[
        tuple[
            int,
            int,
            tuple[str, ...],
            VowelCellDisplayKind,
            tuple[str, ...],
            int,
        ]
    ] = []
    cells_meta_by_row: dict[int, list[tuple[int, int, bool]]] = {}
    for ri, ci in sorted(occupied):
        display_kind, contrast_features, entries = cell_classifications[
            (ri, ci)
        ]
        is_pair_layout = display_kind in PAIR_DISPLAY_KINDS
        if ci >= 6:
            pair_side = 0
        else:
            sibling_ci = ci ^ 1
            has_sibling = (ri, sibling_ci) in occupied
            if is_pair_layout and not has_sibling:
                pair_side = 0
            else:
                pair_side = 1 if ci % 2 else -1
        cell_meta.append(
            (
                ri,
                ci,
                entries,
                display_kind,
                contrast_features,
                pair_side,
            )
        )
        cells_meta_by_row.setdefault(ri, []).append(
            (ci, pair_side, is_pair_layout)
        )

    # Shrink silhouette widths so the trapezoid tracks the actual
    # content. With back-anchored cell projection, the shrunken
    # widths also pull cell anchors inward by the same factor, so
    # the silhouette and the cells stay aligned by construction.
    shrunken_top_w, shrunken_bot_w = _compute_shrunken_widths(
        cells_meta_by_row,
        display_y_by_row,
        silhouette.top_y,
        silhouette.bottom_y,
        silhouette.top_width,
        silhouette.bottom_width,
    )
    if (
        shrunken_top_w != silhouette.top_width
        or shrunken_bot_w != silhouette.bottom_width
    ):
        silhouette = _silhouette_with_widths(
            silhouette, shrunken_top_w, shrunken_bot_w
        )

    # The back edge stays at the canonical ``_PAIR_OUTER_PIXEL_EXTENT``
    # default set by ``vowel_silhouette``: the line sits at the back-
    # rounded mate's outer right edge so back vowels stay flush
    # against (but not crossing) the silhouette. An earlier policy
    # snapped the line to the rightmost back-vowel BUTTON CENTRE per
    # inventory; the visual result intersected the buttons, which we
    # rejected. The shared field / formula stays in place
    # (``dx + top_right * dw + back_right_pixel_offset``) so any
    # future per-inventory policy lands in this slot without touching
    # the renderers.

    # Second pass: project cells using the final silhouette
    # widths. PAIR cells without an opposite-rounding sibling
    # render centred on their anchor (pair_side=0); regular pairs
    # and lone PAIR cells with a sibling keep canonical pair_side.
    cells: list[VowelChartCell] = []
    for (
        ri,
        ci,
        entries,
        display_kind,
        contrast_features,
        pair_side,
    ) in cell_meta:
        if ri == open_row_index and ci in (2, 3) and not open_front_populated:
            anchor_x = _BACKNESS_X["front"]
        else:
            anchor_x = _col_to_anchor[ci]
        cell_display_y = display_y_by_row[ri]
        row_width = _width_at_display_y(cell_display_y)
        chart_x = back + row_width * (anchor_x - back)
        cells.append(
            VowelChartCell(
                row=ri,
                col=ci,
                chart_x=chart_x,
                chart_y=cell_display_y,
                pair_side=pair_side,
                entries=entries,
                display_kind=display_kind,
                contrast_features=contrast_features,
            )
        )

    # Column headers sit at the silhouette's top edge so they line
    # up with the topmost populated row's cells. Their chart_x is
    # the topmost row's projected backness anchor (front migrates
    # inward as the silhouette narrows; central shifts toward the
    # back anchor too; back stays flush with the vertical right
    # edge).
    _col_label_to_anchor_key = ("front", "central", "back")
    top_row_width = silhouette.top_width
    col_headers = tuple(
        VowelChartColHeader(
            label=label,
            chart_x=back
            + top_row_width
            * (_BACKNESS_X[_col_label_to_anchor_key[ci]] - back),
        )
        for ci, label in enumerate(COL_LABELS)
    )

    natural_w, natural_h = _natural_data_area_size(tuple(cells))

    def _project_to_chart_xy(ri: int, ci: int) -> tuple[float, float]:
        """Project a logical (row, col) to its (chart_x, chart_y)
        using the same silhouette + row-distribution math the
        populated cells consume. Used by the diphthong overlay so
        an arrow whose secondary lands on an unpopulated slot still
        has a valid endpoint (rather than being silently dropped by
        the renderer).

        For rows outside ``populated_logical_rows`` we fall back to
        the canonical row-y from ``_HEIGHT_Y`` so a diphthong glide
        targeting an empty tier still points at a sensible vertical
        position; the silhouette may not visually extend to that y,
        but the arrow geometry stays defined.
        """
        if ri in display_y_by_row:
            cy = display_y_by_row[ri]
        else:
            cy = _HEIGHT_Y[ROW_LABELS[ri]]
        if ri == open_row_index and ci in (2, 3) and not open_front_populated:
            anchor_x = _BACKNESS_X["front"]
        else:
            anchor_x = _col_to_anchor[ci]
        row_w = _width_at_display_y(cy)
        return back + row_w * (anchor_x - back), cy

    # Diphthong rendering hints. One entry per placement whose
    # ``secondary`` attribute is non-null. Order is stable across
    # builds (insertion order of ``placements``, which iterates
    # ``segs`` in caller-supplied order) so diff-driven tests on
    # the geometry stay reproducible.
    diphthongs_list: list[VowelChartDiphthong] = []
    for seg, p in placements.items():
        if p.secondary is None:
            continue
        primary_x, primary_y = _project_to_chart_xy(p.row, p.col)
        secondary_x, secondary_y = _project_to_chart_xy(
            p.secondary.row, p.secondary.col
        )
        diphthongs_list.append(
            VowelChartDiphthong(
                segment=seg,
                primary_row=p.row,
                primary_col=p.col,
                secondary_row=p.secondary.row,
                secondary_col=p.secondary.col,
                primary_chart_x=primary_x,
                primary_chart_y=primary_y,
                secondary_chart_x=secondary_x,
                secondary_chart_y=secondary_y,
            )
        )
    diphthongs = tuple(diphthongs_list)
    # Height-tier bands: one stripe per populated row, clamped to
    # the silhouette's vertical span, with ``tinted`` alternating
    # so the every-other-row rhythm is decided once here rather
    # than recomputed by each renderer.
    row_ys = tuple(r.chart_y for r in rows)
    bands_list: list[VowelChartBand] = []
    n_rows = len(row_ys)
    for i, y in enumerate(row_ys):
        above = (row_ys[i - 1] + y) / 2 if i > 0 else silhouette.top_y
        below = (
            (y + row_ys[i + 1]) / 2 if i < n_rows - 1 else silhouette.bottom_y
        )
        bands_list.append(
            VowelChartBand(
                top_norm=above, bottom_norm=below, tinted=i % 2 == 0
            )
        )
    bands = tuple(bands_list)
    return VowelChartGeometry(
        title=VOWEL_CHART_TITLE,
        shape=shape,
        silhouette=silhouette,
        cols=col_headers,
        rows=rows,
        cells=tuple(cells),
        natural_data_width_px=natural_w,
        natural_data_height_px=natural_h,
        diphthongs=diphthongs,
        bands=bands,
    )
