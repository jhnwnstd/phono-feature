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
    PlacementFlag,
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
    # True when at least one of the cell's ``entries`` carries
    # :py:attr:`PlacementFlag.DIPHTHONG` -- the placer sets this
    # flag only on placements whose ``secondary`` lands in a
    # DIFFERENT (row, col) from the primary, so pharyngealised
    # monophthongs (Archi ``/aˤ /iˤ /``) whose secondary
    # collapses back to the primary cell are excluded by
    # construction. Renderers use this flag plus the active
    # :py:class:`VowelChartMode` to filter cell visibility
    # without re-deriving "is this a diphthong" from feature
    # bundles or segment-string parsing.
    is_diphthong: bool = False


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

    ``slot_height_norm`` is the row's allocated share of the
    silhouette's vertical span in normalised ``[0, 1]`` units.
    Sums across all populated rows equals
    ``silhouette.bottom_y - silhouette.top_y``. The renderer
    multiplies this by the data-area's rendered pixel height to
    get the row's pixel budget; if the rendered chart is shorter
    than ``natural_data_height_px`` (the geometry's request), the
    renderer derives a smaller per-button height from this slot so
    a tall stack fits without overflowing into adjacent rows or
    outside the silhouette.
    """

    logical_row: int
    label: str
    chart_y: float
    tier: str = "middle"
    slot_height_norm: float = 0.0
    # Silhouette's actual LEFT and RIGHT edge x at this row's
    # ``chart_y`` (normalised ``[0, 1]``), accounting for the
    # rounded-corner insets at the top + bottom of the polygon.
    # Both renderers consume these for row-label anchoring and
    # any future right-edge label or alignment cue.
    #
    # IMPORTANT: these are stored at the CANONICAL data width
    # (``_VOWEL_CONTENT_W_PX``). For accurate flush at the
    # actual rendered ``dw``, renderers can recompute the
    # silhouette via :py:func:`silhouette_for_data_width` and
    # then call :py:func:`silhouette_left_at_y` /
    # :py:func:`silhouette_right_at_y` with the corrected
    # silhouette. The drift at non-canonical ``dw`` is small
    # (~1 px) so callers that don't need pixel-perfect flush
    # can use these baked values directly.
    silhouette_left: float = 0.0
    silhouette_right: float = 1.0


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
    # CELL-EXTENT FIELDS (cascade source of truth).
    #
    # These four fields let renderers compute the silhouette's
    # left / right edge POSITION IN PIXELS at any data width such
    # that the silhouette wraps the outermost cell flush. The
    # ``top_left/right`` etc. fields above remain for backward
    # compatibility but represent the canonical-width approximation;
    # ``silhouette_left_norm_at_y`` / ``silhouette_right_norm_at_y``
    # are the canonical accessors that take the current data width
    # into account.
    #
    # ``front_anchor_at_top`` / ``front_anchor_at_bottom`` are the
    # front-cell BACKNESS ANCHOR at the silhouette's top and bottom
    # y respectively (in [0, 1]). Cells in the front column at
    # those rows centre on ``front_anchor_at_*  * dw``. The
    # silhouette's actual left edge sits ``cell_outer_extent_px``
    # to the LEFT of that centre so the front-most cell is flush
    # against the silhouette stroke.
    #
    # ``back_anchor`` is the constant back-cell anchor (no row
    # variation -- back cells stay at the same backness across all
    # rows). Silhouette's right edge sits ``cell_outer_extent_px``
    # to the RIGHT of ``back_anchor * dw``.
    #
    # ``cell_outer_extent_px`` is ``pair_shift_px + btn_w / 2`` --
    # the fixed-pixel offset from a paired cell's centre to its
    # outer edge. Both renderers consume this to position the
    # silhouette so the math cascades: at any data width the
    # silhouette is flush with the outermost cell by construction,
    # not by coincidence at the canonical width.
    front_anchor_at_top: float = 0.0
    front_anchor_at_bottom: float = 0.0
    back_anchor: float = 1.0
    cell_outer_extent_px: int = 0
    # Optional fixed-pixel correction added at render time to the
    # back silhouette edge. Default ``0``. The cell-extent fields
    # above made this hook largely vestigial -- the cascade math
    # already enforces flush -- but it stays as an escape hatch
    # for any future per-inventory tweak.
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


#: Gap (px) between vertically stacked segment buttons. Canonical
#: home lives in ``phonology_shared.presentation.chart_style`` as
#: ``VOWEL_CELL_STACK_GAP_PX`` (presentation layer, so build.py can
#: bake it without dragging chart/ imports). Re-exported here for
#: the natural-height math below + any consumer that already
#: imports from this module.
from phonology_shared.presentation.chart_style import (  # noqa: E402
    VOWEL_CELL_STACK_GAP_PX,
    VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC,
)

# Backward-compat alias for the old private name. Internal
# call-sites below still use this; new code should use the
# public symbol above.
_VOWEL_CELL_STACK_GAP_PX: int = VOWEL_CELL_STACK_GAP_PX

#: Density tiers: per-button height when a cell's stack reaches the
#: threshold entry count. Mirrors the CSS rules at
#: ``web/style.css:1219-1234`` (``data-cell-density="dense"`` and
#: ``"ultra"``). The geometry-side ``natural_data_height_px``
#: computation reads this so the chart asks for the rendered pixel
#: height instead of the canonical-button-size theoretical max --
#: pre-fix, PHOIBLE inventories like !XU/UPSID (12-stack) were
#: requesting 931 px while the CSS-rendered chart only needed
#: ~250 px, forcing the panel-body to scroll unnecessarily.
_DENSITY_TIER_DENSE_THRESHOLD: int = 5
_DENSITY_TIER_DENSE_BTN_H: int = SEG_BTN_H - 4  # 22 px (matches CSS)
_DENSITY_TIER_ULTRA_THRESHOLD: int = 10
_DENSITY_TIER_ULTRA_BTN_H: int = SEG_BTN_H - 8  # 18 px (matches CSS)


def effective_button_height_px(stack_depth: int) -> int:
    """Per-button rendered height for a stack of ``stack_depth``
    entries. Matches the CSS density-tier ladder so the geometry's
    natural-height computation tracks the actual rendered height.

    Both renderers consume this to keep their per-button sizing in
    lockstep with the geometry's ``natural_data_height_px``
    request. Web CSS reads ``data-cell-density="dense"`` or
    ``"ultra"`` and applies the calculated heights via
    ``calc(var(--seg-btn-h) - 4px)`` / ``- 8px``. Desktop calls this
    helper directly to set ``setFixedHeight`` on each stacked
    button. Without parity here, a 7-deep stack renders 28 px
    taller on desktop than web (canonical 26 px vs dense 22 px),
    causing the chart layout to look "totally different" even
    though both renderers consume the same shared geometry.
    """
    if stack_depth >= _DENSITY_TIER_ULTRA_THRESHOLD:
        return _DENSITY_TIER_ULTRA_BTN_H
    if stack_depth >= _DENSITY_TIER_DENSE_THRESHOLD:
        return _DENSITY_TIER_DENSE_BTN_H
    return SEG_BTN_H


# Backward-compat alias for the previous private name. Internal
# call-sites below still use this; external imports should use the
# public ``effective_button_height_px``.
_effective_button_height_px = effective_button_height_px


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


def rounded_silhouette_polygon_points(
    silhouette: VowelChartSilhouette,
    radius_frac: float,
    *,
    segments_per_corner: int = 5,
) -> str:
    """Return a CSS ``clip-path: polygon()`` points string that
    approximates the silhouette's outline with rounded corners.

    The 4-corner polygon is replaced by ``4 *
    (segments_per_corner + 1)`` points: at each corner, two
    "inset" points sit ``radius_frac`` along each adjacent edge,
    and the corner itself is approximated by a quadratic Bezier
    curve between those inset points with the corner as control.
    Sampling the curve at ``segments_per_corner + 1`` equally-
    spaced ``t`` values yields a visually smooth round.

    Used by ``build.py`` to bake a CSS variable consumed by the
    web's ``clip-path: polygon(var(--vowel-<shape>-rounded-points))``.
    Desktop's ``QPainterPath`` consumer uses the same
    ``radius_frac`` source but calls Qt's native ``quadTo`` per
    corner so the desktop path stays free of polygon-interpolation
    artefacts. Both renderers share the radius source so their
    corner rounding stays in lockstep.
    """
    # CCW traversal so the polygon interior sits on the right of
    # each directed edge. Top-left -> bottom-left -> bottom-right
    # -> top-right matches the silhouette's polygon definition
    # used elsewhere in this file.
    corners: tuple[tuple[float, float], ...] = (
        (silhouette.top_left, silhouette.top_y),
        (silhouette.bottom_left, silhouette.bottom_y),
        (silhouette.bottom_right, silhouette.bottom_y),
        (silhouette.top_right, silhouette.top_y),
    )
    n = len(corners)
    points: list[tuple[float, float]] = []
    import math

    for i in range(n):
        prev = corners[(i - 1) % n]
        curr = corners[i]
        nxt = corners[(i + 1) % n]
        # Unit vectors from ``curr`` toward each neighbour.
        dx_in = prev[0] - curr[0]
        dy_in = prev[1] - curr[1]
        len_in = math.hypot(dx_in, dy_in) or 1.0
        dx_in /= len_in
        dy_in /= len_in
        dx_out = nxt[0] - curr[0]
        dy_out = nxt[1] - curr[1]
        len_out = math.hypot(dx_out, dy_out) or 1.0
        dx_out /= len_out
        dy_out /= len_out
        # Inset points sit ``radius_frac`` along each edge from the
        # corner. Clamp the radius so a very short edge can't push
        # the inset past the edge's midpoint (would overlap the
        # adjacent corner's arc).
        r_in = min(radius_frac, len_in * 0.45)
        r_out = min(radius_frac, len_out * 0.45)
        p_in = (
            curr[0] + r_in * dx_in,
            curr[1] + r_in * dy_in,
        )
        p_out = (
            curr[0] + r_out * dx_out,
            curr[1] + r_out * dy_out,
        )
        # Quadratic Bezier sampled at ``segments_per_corner + 1``
        # equally-spaced t values. The corner itself is the control
        # point; t=0 emits ``p_in``, t=1 emits ``p_out``.
        for s in range(segments_per_corner + 1):
            t = s / segments_per_corner
            one_minus_t = 1.0 - t
            bx = (
                one_minus_t * one_minus_t * p_in[0]
                + 2.0 * one_minus_t * t * curr[0]
                + t * t * p_out[0]
            )
            by = (
                one_minus_t * one_minus_t * p_in[1]
                + 2.0 * one_minus_t * t * curr[1]
                + t * t * p_out[1]
            )
            points.append((bx, by))
    return ", ".join(f"{x * 100:.3f}% {y * 100:.3f}%" for x, y in points)


def silhouette_for_data_width(
    silhouette: VowelChartSilhouette, data_w_px: int
) -> VowelChartSilhouette:
    """Return a copy of ``silhouette`` with the four corner fields
    recomputed from the cell-extent fields (``front_anchor_at_*``,
    ``back_anchor``, ``cell_outer_extent_px``) for the given
    rendered data width in pixels.

    THE CASCADE INVARIANT: cells are placed at
    ``anchor * dw + sign * cell_outer_extent_px`` (where sign is
    -1 for front, +1 for back, and ``cell_outer_extent_px =
    pair_shift_px + btn_w/2``). The silhouette's corners must
    follow the same formula or the silhouette and outermost cells
    drift apart by the ratio of rendered-to-canonical width.

    Pre-cascade behaviour: the corner fields were computed once
    at geometry build time with a normalised pair-outer extent.
    At the canonical 232 px content width the formula was flush;
    at other widths (a 320 px chart, a 380 px chart) the
    silhouette and the cells drifted by a few pixels. Front and
    back drifted by the SAME amount, but the slanted front edge
    made the gap more visually obvious there than at the
    vertical back edge.

    Post-cascade: every render pass calls this helper with the
    actual ``dw`` it has measured (web ``getBoundingClientRect``,
    desktop ``self.width()``) and the corners track the cells
    flush by construction. Both renderers OVERRIDE the build-time
    silhouette polygon by passing the corrected silhouette
    through :py:func:`rounded_silhouette_polygon_points`.

    For the build-time CSS fallback (no JS) the corner fields
    keep the canonical-dw values populated by ``vowel_silhouette``
    so an offline page still renders a reasonable silhouette.
    """
    if data_w_px <= 0:
        return silhouette
    extent_norm = silhouette.cell_outer_extent_px / data_w_px
    return replace(
        silhouette,
        top_left=silhouette.front_anchor_at_top - extent_norm,
        bottom_left=silhouette.front_anchor_at_bottom - extent_norm,
        top_right=silhouette.back_anchor + extent_norm,
        bottom_right=silhouette.back_anchor + extent_norm,
    )


def silhouette_right_at_y(
    silhouette: VowelChartSilhouette,
    chart_y: float,
    corner_radius_frac: float = VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC,
) -> float:
    """Mirror of :py:func:`silhouette_left_at_y` for the back
    (right) silhouette edge. Returns the silhouette's actual RIGHT
    edge x at ``chart_y``, accounting for the top-right and
    bottom-right rounded-corner insets.

    For a canonical trapezoid the right edge is vertical (back
    anchor doesn't slant per row), so this collapses to
    ``silhouette.top_right`` (== ``silhouette.bottom_right``)
    outside the corner regions. Within the rounded corners the
    helper follows the same quadratic Bezier sampled by
    :py:func:`rounded_silhouette_polygon_points`.

    Both renderers consume this via ``VowelChartRow.silhouette_right``
    (baked per row at geometry build time) so back-edge alignment
    cues stay in lockstep with the rendered silhouette polygon.
    """
    import math

    sil = silhouette
    span_y = sil.bottom_y - sil.top_y
    if span_y <= 0:
        return sil.top_right
    chart_y = max(sil.top_y, min(sil.bottom_y, chart_y))

    # Canonical linear interpolation. For a normal trapezoid
    # top_right == bottom_right (back edge vertical) so the
    # canonical is constant.
    t_linear = (chart_y - sil.top_y) / span_y
    canonical = sil.top_right + (sil.bottom_right - sil.top_right) * t_linear

    # --- top-right corner ---
    # prev neighbour in CCW order = bottom-right (down the right
    # edge); next neighbour = top-left (along the top edge,
    # leftward).
    tr_dx_in = sil.bottom_right - sil.top_right
    tr_dy_in = sil.bottom_y - sil.top_y
    tr_len_in = math.hypot(tr_dx_in, tr_dy_in) or 1.0
    tr_dx_in_norm = tr_dx_in / tr_len_in
    tr_dy_in_norm = tr_dy_in / tr_len_in
    tr_r_in = min(corner_radius_frac, tr_len_in * 0.45)
    tr_r_in_y_abs = abs(tr_r_in * tr_dy_in_norm)

    tr_dx_out = sil.top_left - sil.top_right
    tr_len_out = abs(tr_dx_out) or 1.0
    tr_r_out = min(corner_radius_frac, tr_len_out * 0.45)

    dy_top = chart_y - sil.top_y
    if 0 <= dy_top < tr_r_in_y_abs and tr_r_in_y_abs > 0:
        # y(t) = top_y + t^2 * tr_r_in_y_abs (corner mirror)
        t = math.sqrt(dy_top / tr_r_in_y_abs)
        t = max(0.0, min(1.0, t))
        omt = 1.0 - t
        x_in = sil.top_right + tr_r_in * tr_dx_in_norm  # p_in.x
        x_curr = sil.top_right
        x_out = sil.top_right - tr_r_out  # leftward
        x_corner = omt * omt * x_in + 2.0 * omt * t * x_curr + t * t * x_out
        # The right-side bezier curves LEFTWARD (inward) from the
        # corner; use the smaller of canonical vs corner.
        return min(canonical, x_corner)

    # --- bottom-right corner ---
    br_dx_in = sil.bottom_left - sil.bottom_right
    br_len_in = abs(br_dx_in) or 1.0
    br_r_in = min(corner_radius_frac, br_len_in * 0.45)

    br_dx_out = sil.top_right - sil.bottom_right
    br_dy_out = sil.top_y - sil.bottom_y
    br_len_out = math.hypot(br_dx_out, br_dy_out) or 1.0
    br_dx_out_norm = br_dx_out / br_len_out
    br_dy_out_norm = br_dy_out / br_len_out
    br_r_out = min(corner_radius_frac, br_len_out * 0.45)
    br_r_out_y_abs = abs(br_r_out * br_dy_out_norm)

    dy_bot = sil.bottom_y - chart_y
    if 0 <= dy_bot < br_r_out_y_abs and br_r_out_y_abs > 0:
        omt = math.sqrt(dy_bot / br_r_out_y_abs)
        omt = max(0.0, min(1.0, omt))
        t = 1.0 - omt
        x_in = sil.bottom_right - br_r_in  # leftward along bottom
        x_curr = sil.bottom_right
        x_out = sil.bottom_right + br_r_out * br_dx_out_norm
        x_corner = omt * omt * x_in + 2.0 * omt * t * x_curr + t * t * x_out
        return min(canonical, x_corner)

    return canonical


def silhouette_left_at_y(
    silhouette: VowelChartSilhouette,
    chart_y: float,
    corner_radius_frac: float = VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC,
) -> float:
    """Return the silhouette's actual LEFT edge x (normalised
    ``[0, 1]``) at the given ``chart_y``, accounting for
    top-left and bottom-left rounded-corner insets.

    Outside the corner regions the result is the canonical linear
    interpolation between ``top_left`` and ``bottom_left``: the
    rounded polygon's straight segment between
    ``p_out_top`` and ``p_in_bot`` IS that same line, so the
    canonical interp matches the polygon pixel-for-pixel away
    from the corners.

    Within the corner regions (chart_y within the y-extent of
    the rounded curve) the result follows the SAME quadratic
    Bezier sampled by :py:func:`rounded_silhouette_polygon_points`,
    so a row label anchored to this value lands on the rendered
    silhouette edge with no visible gap.

    Both renderers consume this via ``VowelChartRow.silhouette_left``
    (baked per row at build time); neither replicates the bezier
    math locally.
    """
    import math

    sil = silhouette
    span_y = sil.bottom_y - sil.top_y
    if span_y <= 0:
        return sil.top_left
    # Clamp y to the silhouette range; rows can sit at chart_y
    # values outside [top_y, bottom_y] for non-bracket rows but
    # the meaningful row anchors are inside.
    chart_y = max(sil.top_y, min(sil.bottom_y, chart_y))

    # Canonical linear interpolation (matches the polygon's
    # straight segment between p_out_top and p_in_bot).
    t_linear = (chart_y - sil.top_y) / span_y
    canonical = sil.top_left + (sil.bottom_left - sil.top_left) * t_linear

    # --- top-left corner ---
    tl_dx_out = sil.bottom_left - sil.top_left
    tl_dy_out = sil.bottom_y - sil.top_y
    tl_len_out = math.hypot(tl_dx_out, tl_dy_out) or 1.0
    tl_dx_out_norm = tl_dx_out / tl_len_out
    tl_dy_out_norm = tl_dy_out / tl_len_out
    tl_r_out = min(corner_radius_frac, tl_len_out * 0.45)
    tl_r_out_y = tl_r_out * tl_dy_out_norm

    # top edge (from top_left to top_right). For trapezoid this
    # spans most of the chart; for triangle the top edge is
    # narrower. Sets ``r_in`` for the top-left bezier.
    tl_dx_in = sil.top_right - sil.top_left
    tl_len_in = abs(tl_dx_in) or 1.0
    tl_r_in = min(corner_radius_frac, tl_len_in * 0.45)

    dy_top = chart_y - sil.top_y
    if 0 <= dy_top < tl_r_out_y and tl_r_out_y > 0:
        # Solve y(t) = top_y + t^2 * tl_r_out_y for t
        t = math.sqrt(dy_top / tl_r_out_y)
        t = max(0.0, min(1.0, t))
        omt = 1.0 - t
        x_in = sil.top_left + tl_r_in  # p_in.x
        x_curr = sil.top_left  # control point x
        x_out = sil.top_left + tl_r_out * tl_dx_out_norm  # p_out.x
        x_corner = omt * omt * x_in + 2.0 * omt * t * x_curr + t * t * x_out
        # x_corner is always >= canonical inside the corner region
        # (the bezier curves rightward of the canonical line); use
        # the corner value.
        return max(canonical, x_corner)

    # --- bottom-left corner ---
    bl_dx_in = sil.top_left - sil.bottom_left
    bl_dy_in = sil.top_y - sil.bottom_y
    bl_len_in = math.hypot(bl_dx_in, bl_dy_in) or 1.0
    bl_dx_in_norm = bl_dx_in / bl_len_in
    bl_dy_in_norm = bl_dy_in / bl_len_in
    bl_r_in = min(corner_radius_frac, bl_len_in * 0.45)
    bl_r_in_y_abs = abs(bl_r_in * bl_dy_in_norm)

    bl_dx_out = sil.bottom_right - sil.bottom_left
    bl_len_out = abs(bl_dx_out) or 1.0
    bl_r_out = min(corner_radius_frac, bl_len_out * 0.45)

    dy_bot = sil.bottom_y - chart_y
    if 0 <= dy_bot < bl_r_in_y_abs and bl_r_in_y_abs > 0:
        # y(t) = bottom_y + (1-t)^2 * bl_r_in_y    (bl_r_in_y is negative)
        # bottom_y - y(t) = (1-t)^2 * |bl_r_in_y|
        # 1 - t = sqrt(dy_bot / |bl_r_in_y|)
        omt = math.sqrt(dy_bot / bl_r_in_y_abs)
        omt = max(0.0, min(1.0, omt))
        t = 1.0 - omt
        x_in = sil.bottom_left + bl_r_in * bl_dx_in_norm  # p_in.x
        x_curr = sil.bottom_left  # control point
        x_out = sil.bottom_left + bl_r_out  # p_out.x
        x_corner = omt * omt * x_in + 2.0 * omt * t * x_curr + t * t * x_out
        return max(canonical, x_corner)

    return canonical


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
        # Cell-extent fields stay in lockstep with the corners so
        # the cascade math (silhouette = anchor*dw +/- extent_px)
        # tracks any shrink the slant-cap policy applies.
        front_anchor_at_top=front_at_top,
        front_anchor_at_bottom=front_at_bottom,
        back_anchor=back,
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
    # Density-tier-aware: when the deepest cell in a row crosses
    # the dense / ultra threshold, its rendered per-button height
    # shrinks (matching the CSS rules). The natural-height request
    # tracks the actual rendered height so the chart asks for what
    # the renderer will draw, not the canonical-button theoretical
    # max.
    row_heights: list[int] = []
    for ri in sorted(rows_in_use):
        depth = 1
        for c in cells:
            if c.row != ri:
                continue
            cell_depth = _cell_vertical_depth(c)
            if cell_depth > depth:
                depth = cell_depth
        per_btn_h = _effective_button_height_px(depth)
        row_heights.append(
            depth * per_btn_h + max(0, depth - 1) * _VOWEL_CELL_STACK_GAP_PX
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
    slot_heights_by_row: dict[int, float] = {}
    if len(populated_logical_rows) == 1:
        display_y_by_row = {
            populated_logical_rows[0]: (silhouette.top_y + silhouette.bottom_y)
            / 2
        }
        slot_heights_by_row[populated_logical_rows[0]] = (
            silhouette.bottom_y - silhouette.top_y
        )
    else:
        span = silhouette.bottom_y - silhouette.top_y
        total_depth = sum(row_depths.values())
        display_y_by_row = {}
        cursor = silhouette.top_y
        last_index = len(populated_logical_rows) - 1
        for i, ri in enumerate(populated_logical_rows):
            slot_height = row_depths[ri] / total_depth * span
            slot_heights_by_row[ri] = slot_height
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
            slot_height_norm=slot_heights_by_row[ri],
            silhouette_left=silhouette_left_at_y(
                silhouette, display_y_by_row[ri]
            ),
            silhouette_right=silhouette_right_at_y(
                silhouette, display_y_by_row[ri]
            ),
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
    # Neutral cols (6/7/8) share a backness anchor with the paired
    # cols at the same row (6 with 0/1, 7 with 2/3, 8 with 4/5).
    # When both a neutral and a paired col are populated, the
    # canonical ``pair_side=0`` for the neutral plus the
    # ``pair_side=±1`` for the paired one only separate them by half
    # a button width -- in practice they overlap.
    # ``_neutral_to_paired_anchor`` maps each neutral col to its two
    # paired siblings so we can detect the collision and reroute the
    # neutral cell into the empty pair-side slot.
    _neutral_to_paired_anchor: dict[int, tuple[int, int]] = {
        6: (0, 1),  # front-neutral -> front-unr/front-rnd
        7: (2, 3),  # central-neutral -> central-unr/central-rnd
        8: (4, 5),  # back-neutral -> back-unr/back-rnd
    }

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
            # Neutral col baseline: pair_side=0 (anchor centre).
            # Reroute when a paired col at the same anchor is also
            # populated so the buttons don't overlap.
            paired_lo, paired_hi = _neutral_to_paired_anchor[ci]
            has_lo = (ri, paired_lo) in occupied
            has_hi = (ri, paired_hi) in occupied
            if has_lo and not has_hi:
                # Only the unrounded pair member is taken. Send the
                # neutral cell to the empty rounded position.
                pair_side = +1
            elif has_hi and not has_lo:
                # Only the rounded pair member is taken. Send the
                # neutral cell to the empty unrounded position --
                # this is the canonical "default unrounded"
                # semantics PHOIBLE neutral typically expresses.
                pair_side = -1
            else:
                # Either both pair cols are populated (rare; the
                # placer puts each unique feature shape in its own
                # col) or neither is. Keep the anchor centre.
                pair_side = 0
        else:
            sibling_ci = ci ^ 1
            has_sibling = (ri, sibling_ci) in occupied
            # When a lone paired cell shares its anchor with a
            # populated neutral cell, snap the paired cell to its
            # canonical pair-side. This lets the neutral cell take
            # the empty pair-side (see neutral-col branch above)
            # so both cells land at distinct rendered positions.
            paired_low_col = ci & ~1
            neutral_partner = (paired_low_col >> 1) + 6
            has_neutral = (ri, neutral_partner) in occupied
            if is_pair_layout and not has_sibling and not has_neutral:
                # Lone pair cell with no neutral co-occupant: stay
                # centred on the anchor (the canonical lone-pair
                # rendering).
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
        # ``is_diphthong`` is True when any of this cell's
        # entries carries ``PlacementFlag.DIPHTHONG`` on its
        # placement record. The placer sets that flag only when
        # the segment's secondary lands in a different cell from
        # its primary (post-degeneracy-filter), so
        # pharyngealised monophthongs like Archi ``/aˤ /`` --
        # whose secondary collapses to the primary cell -- are
        # automatically excluded.
        is_diphthong = any(
            PlacementFlag.DIPHTHONG in placements[seg].flags
            for seg in entries
            if seg in placements
        )
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
                is_diphthong=is_diphthong,
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
