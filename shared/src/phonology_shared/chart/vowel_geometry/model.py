"""Render-ready wire types for the vowel chart (layer: model).

The seven frozen dataclasses below are the complete contract both
renderers consume: the desktop walks them directly, the web receives
them flattened by ``view_models._vowel_chart_summary``. Everything
that crosses the renderer boundary lives in this one module so "what
does the wire carry" is a single-file read.

Every other layer of :py:mod:`phonology_shared.chart.vowel_geometry`
may import this module; this module imports only the inference-layer
enums and the presentation constants its field defaults need. See the
package docstring for the full layer table and dependency rules.
"""

from __future__ import annotations

from dataclasses import dataclass

from phonology_shared.chart.vowels import (
    VowelCellDisplayKind,
    VowelChartShape,
)
from phonology_shared.presentation.chart_style import VOWEL_PAIR_SHIFT_PX

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
      The renderer offsets the cell from its anchor by the FIXED
      PIXEL amount ``pair_side * pair_shift_px + nudge_px`` (see
      those fields below) so paired mates stay exactly tangent
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
    # :py:attr:`PlacementFlag.DIPHTHONG`; the placer sets this
    # flag only on placements whose ``secondary`` lands in a
    # DIFFERENT (row, col) from the primary, so pharyngealised
    # monophthongs (Archi ``/aˤ /iˤ /``) whose secondary
    # collapses back to the primary cell are excluded by
    # construction. Renderers use this flag plus the active
    # :py:class:`VowelChartMode` to filter cell visibility
    # without re-deriving "is this a diphthong" from feature
    # bundles or segment-string parsing.
    is_diphthong: bool = False
    # Effective pair-side displacement in pixels. Defaults to the
    # canonical ``VOWEL_PAIR_SHIFT_PX`` which is sized for single-
    # button cells. When two paired cells at the SAME chart_x are
    # both wider than a single button (PHOIBLE inventories with
    # long_pair / nasal_pair / contrast_set cells at the back
    # column where back-neutral auto-pairs with back-rounded),
    # the geometry build elevates this to half the combined cell
    # widths so the two cells stay tangent instead of overlapping
    # by the cell-width-minus-canonical-shift delta (~33 px for
    # two long_pair cells). Always populated with the effective
    # value, so both renderers and the sizing math read it
    # UNCONDITIONALLY; no consumer re-implements a "0 means
    # canonical" fallback.
    pair_shift_px: float = float(VOWEL_PAIR_SHIFT_PX)
    # Signed horizontal confinement offset in pixels, applied by
    # both renderers on top of the anchor + pair shift:
    # ``centre = chart_x * dw + pair_side * pair_shift_px +
    # nudge_px``. Written only by the hard-boundary pass
    # (``pipeline._confine_cells_to_outline``) to pull a button box
    # inside the outline when its corner overhangs the slanted
    # front edge or a rounded corner arc. It MUST stay a pixel
    # offset, never a chart_x delta: confinement folded into the
    # anchor makes near-coincident anchors look separable by
    # widening, and the width solver then inflates dense PHOIBLE
    # charts to several times their natural width (~900 px).
    nudge_px: float = 0.0


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
    # Display y for the ROW LABEL (normalised ``[0, 1]``). Equal to
    # ``chart_y`` for middle / only tiers; shifted inward by half a
    # button height (in units of ``natural_data_height_px``) on top
    # and bottom tiers, whose cells anchor an EDGE on chart_y and
    # grow inward, so the label centres on the anchor button row
    # like the middle-tier labels do. Defaults to 0.0 only for
    # hand-built test fixtures; the geometry build always populates
    # it.
    label_y: float = 0.0
    # Silhouette's actual LEFT and RIGHT edge x at this row's
    # ``label_y`` (normalised ``[0, 1]``), accounting for the
    # rounded-corner insets at the top + bottom of the polygon.
    # Evaluated at the LABEL's y (not the cells' chart_y) so the
    # label-to-outline gap stays constant: label placement is
    # deliberately divorced from cell positioning, which can sit
    # off the outline (anchor migration, pair shifts) without
    # dragging the labels with it.
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
    # ``top_left/right`` etc. fields above carry the
    # canonical-width approximation for consumers with no live
    # width (the offline CSS fallback, the baked per-row label
    # fields); renderers with a measured width pass the silhouette
    # through ``outline.silhouette_for_data_width`` first, which
    # recomputes those corners from the fields below.
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
    # variation; back cells stay at the same backness across all
    # rows). Silhouette's right edge sits ``cell_outer_extent_px``
    # to the RIGHT of ``back_anchor * dw``.
    #
    # ``cell_outer_extent_px`` is ``pair_shift_px + btn_w / 2``:
    # the fixed-pixel offset from a paired cell's centre to its
    # outer edge. Both renderers consume this to position the
    # silhouette so the math cascades: at any data width the
    # silhouette is flush with the outermost cell by construction,
    # not by coincidence at the canonical width.
    front_anchor_at_top: float = 0.0
    front_anchor_at_bottom: float = 0.0
    back_anchor: float = 1.0
    cell_outer_extent_px: int = 0
    # Optional FRONT-side extent override. ``0`` means "mirror
    # ``cell_outer_extent_px``" (the historical symmetric
    # behaviour). The outline-growth pass sets the two sides
    # independently so a wide back-edge group (same-anchor tangent
    # pairs on dense PHOIBLE inventories need ~70 px) does not
    # float the front edge away from ordinary single-button front
    # cells.
    front_cell_outer_extent_px: int = 0
    # Optional fixed-pixel correction added at render time to the
    # back silhouette edge. Default ``0``. The cell-extent fields
    # above made this hook largely vestigial (the cascade math
    # already enforces flush), but it stays as an escape hatch
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
