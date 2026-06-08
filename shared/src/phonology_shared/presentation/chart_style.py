"""Vowel-chart visual policy: every constant the renderers consume.

The vowel chart's chrome (title, axis labels, silhouette outline,
diphthong arrows) and behaviour (focused / show-all opacity, lift
geometry) need to render the same on the desktop's Qt widget and
the web's DOM / SVG. Before this module the two renderers held
parallel literals that quietly drifted: title font 8pt-Bold (Qt)
vs 11px / 600 (CSS), arrow stroke 1.75 px vs 0.6 SVG user-units,
focused opacity 1.0 vs 0.95, etc. An audit surfaced ~25 visible
mismatches; this module centralises them so both renderers consume
the same numbers via direct import (desktop) or the build-time
relay into CSS custom properties (web).

The audit's choice of canonical value adopts the web's recent
tuning for PHOIBLE-scale inventories where the values diverged.
The desktop renderer reads from here directly; the web's CSS
reads via custom properties baked into ``dist/index.html`` by
``web/scripts/build.py``.

Categories:

* :data:`VOWEL_CHART_TITLE_*` -- font, weight, letter-spacing,
  padding for the "VOWELS" title row.
* :data:`VOWEL_CHART_COL_LABEL_*` -- col header tracking + font.
* :data:`VOWEL_CHART_ROW_LABEL_*` -- row label font + gutter width.
* :data:`VOWEL_CHART_CONTRAST_SET_*` -- 2x2 contrast-set spacing.
* :data:`VOWEL_SILHOUETTE_*` -- trapezoid outline stroke + alpha.
* :data:`VOWEL_CHART_DATA_MIN_H_PX` -- floor below which the data
  area refuses to compress further (small inventories like Spanish).
* :data:`DIPHTHONG_ARROW_*` -- per-arrow stroke, opacity, arrowhead
  size, control-point lift formula.
* :data:`SEG_GROUP_HEADER_*` -- consonant manner-class header
  font / weight / letter-spacing / padding.
* :data:`SEG_GROUP_GAP_PX` -- vertical gap between consecutive
  manner-class groups in the consonant grid.
* :data:`FEAT_ROW_*` -- feature-row padding, gap, button radius,
  compact-tier height + padding.
* :data:`BORDER_PX` -- border-thickness ladder for segment buttons.

Deliberately out of scope (documented divergences, not bugs):

* **Vowel chart layout** (web float vs desktop QHBoxLayout):
  the web uses CSS ``float`` so consonant rows wrap around the
  chart like text around an image; the desktop uses a fixed-width
  HBox so the chart is a sibling column. Unifying these would
  require either a position-absolute overlay on desktop or a
  grid-template-columns rewrite on web -- both are structural
  changes that go beyond a SSOT pass.
* **Feature-card chrome (--feat-card-chrome-h)**: the constant
  is relayed but not yet consumed by a CSS rule. Splitting it
  into ``--feat-card-margin-top/bottom`` + ``--feat-card-title-h``
  would let both surfaces derive 26 px from one source rather
  than reconstructing it; deferred until a feature-pane chrome
  redesign.
* **Font-size cluster** (segment-button 9pt vs 13px,
  feature-name 10pt vs 14px, etc.): Qt point sizes vs CSS pixel
  sizes is a known cross-platform impedance. The shared
  ``FONT_SIZE_*`` ladder already exists; widget-level fonts
  could migrate to it but the visual delta is small and the
  audit classified these as cosmetic.

Pairing each constant with a docstring naming the divergence it
closes lets the next contributor see why the literal was lifted
rather than just where it landed.
"""

from __future__ import annotations

from phonology_shared.presentation.constants import (
    BTN_W,
    FONT_SIZE_LABEL_PX,
)
from phonology_shared.presentation.layout import (
    SEG_BTN_H,
    SPACING_PX,
    VOWEL_PAIR_GAP_PX,
)

# ---------------------------------------------------------------------------
# Title chrome
# ---------------------------------------------------------------------------

#: Font-size (px) for the "VOWELS" / language title rendered above
#: the trapezoid. Pre-audit desktop used 8pt (Qt) which at 96 DPI
#: rounds to ~10.7 px and scales with DPR; web used 11 px pinned via
#: the shared ``FONT_SIZE_LABEL_PX`` token. Both now read this.
VOWEL_CHART_TITLE_FONT_PX: int = FONT_SIZE_LABEL_PX

#: Font weight for the title. Desktop used ``QFont.Weight.Bold``
#: (~700); web used CSS ``font-weight: 600``. We standardise on
#: 600 (semibold) -- web's choice, slightly lighter, more in
#: keeping with axis labels in IPA charts.
VOWEL_CHART_TITLE_FONT_WEIGHT: int = 600

#: Letter-spacing (px) applied to the title. Desktop assembled
#: ``letter-spacing: 1px`` inline; web's CSS specified 0.5 px.
#: Picking the web's value: tighter tracking matches the rest of
#: the chart's label spacing ladder.
VOWEL_CHART_TITLE_LETTER_SPACING_PX: float = 0.5

#: Padding tuple ``(top, right, bottom, left)`` in px around the
#: title text. Desktop used ``(2, 2, 0, 2)`` (no bottom); web used
#: ``(--space-xs, 2px, --space-xs, 2px)`` which resolves to
#: ``(4, 2, 4, 2)``. Adopting the web's symmetric padding so the
#: title-to-column-headers gap is consistent.
VOWEL_CHART_TITLE_PADDING_PX: tuple[int, int, int, int] = (
    SPACING_PX["xs"],
    2,
    SPACING_PX["xs"],
    2,
)

#: Height (px) of the title strip / chrome row above the trapezoid.
#: Pre-relay only the desktop had this as a literal (``_TITLE_H =
#: 20``); the web sized it intrinsically via ``grid-template-rows:
#: auto auto 1fr``. The chrome height is what the desktop reserves
#: for the title row regardless of the title text length. Adopting
#: 20 px as the canonical value lets the web's grid use the same
#: min-height so cells above the trapezoid land at the same y on
#: both UIs (especially relevant after the title font change
#: shifted the intrinsic height by ~1-2 px).
VOWEL_CHART_TITLE_H_PX: int = 20

#: Height (px) of the column-header strip (Front / Central / Back).
#: Pre-relay only the desktop had this as a literal
#: (``_COL_HEADER_H = 18``); the web used ``height: 1.4em`` which
#: resolved to ~14 px at the micro font, leaving the header row
#: 4 px shorter on web. Adopting 18 px as the canonical value so
#: the topmost vowel row sits at the same y on both UIs.
VOWEL_CHART_COL_HEADER_H_PX: int = 18

#: Pixel padding inside the chart widget's right edge. The
#: desktop's ``_PAD_R = 12`` keeps cells at ``chart_x=1`` (back
#: column) from sitting flush against the widget border. Web's
#: ``.vowel-chart`` had only ``padding: ... 2px``, so back-column
#: cells touched the chart container edge on web. Relaying this
#: lets the web's CSS apply the same right inset to ``.vowel-chart``
#: so both UIs leave the same breathing room around the silhouette.
VOWEL_CHART_PAD_R_PX: int = 12

#: Pixel padding inside the chart widget's bottom edge. Same
#: rationale as :data:`VOWEL_CHART_PAD_R_PX`: open vowels (lowest
#: row) shouldn't sit flush against the bottom border.
VOWEL_CHART_PAD_B_PX: int = 10


# ---------------------------------------------------------------------------
# Column headers (Front / Central / Back)
# ---------------------------------------------------------------------------

#: Font-size (px) for the column-header labels. Pre-audit desktop
#: used 7 pt (Qt); web used 11 px pinned via shared token. Both
#: now read this.
VOWEL_CHART_COL_LABEL_FONT_PX: int = FONT_SIZE_LABEL_PX

#: Letter-spacing (px) on column headers. Pre-audit desktop used
#: 0 (nothing); web applied 0.5 px. The 0.5 px tracking makes the
#: column headers read as axis labels rather than body text.
VOWEL_CHART_COL_LABEL_LETTER_SPACING_PX: float = 0.5


# ---------------------------------------------------------------------------
# Row labels (Close / Near-close / ... / Open)
# ---------------------------------------------------------------------------

#: Font-size (px) for the row labels. Pre-audit desktop used 7 pt;
#: web used the shared label token (11 px).
VOWEL_CHART_ROW_LABEL_FONT_PX: int = FONT_SIZE_LABEL_PX

#: Font weight for the row labels. Pre-audit desktop used Qt
#: ``Normal`` (400); web used ``font-weight: 500`` with the
#: rationale that axis labels read as lighter than headings.
#: Adopting web's 500 so the axis-label rhythm matches.
VOWEL_CHART_ROW_LABEL_FONT_WEIGHT: int = 500

#: Fixed gutter width (px) reserved for the row-label column. Web
#: used ``minmax(60px, auto)`` (60 px floor, grows); desktop used
#: fixed 72 px. Standardising on 72 px because "Near-close" and
#: "Open-mid" labels fit comfortably with breathing room. Web
#: switches from ``minmax(60px, auto)`` to a fixed 72 px column.
VOWEL_CHART_ROW_LABEL_GUTTER_PX: int = 72

#: Pixel gap between a row label's right edge and the silhouette's
#: slanted left edge at that row. Pre-relay desktop used 10 px
#: (``_ROW_LABEL_GAP_PX``); web used ``var(--space-md) + 2px`` =
#: 10 px after the spacing-ladder resolved. The values matched by
#: coincidence; pinning the canonical 10 px here so future tweaks
#: to ``SPACING_PX["md"]`` don't silently desync the two UIs.
VOWEL_CHART_ROW_LABEL_GAP_PX: int = 10


# ---------------------------------------------------------------------------
# Cell positioning math (pair-shift)
# ---------------------------------------------------------------------------

#: Half-stride (px) the renderer shifts a paired cell off its
#: backness anchor so the unrounded mate sits left and the rounded
#: mate sits right. Pre-relay desktop computed this inline as
#: ``(BTN_W + VOWEL_PAIR_GAP_PX) // 2`` (integer floor) and the
#: CSS repeated ``(var(--seg-btn-w) + var(--vowel-pair-gap)) / 2``
#: in three transform rules. The math is the same today but a
#: future ``BTN_W`` bump (different font, denser layout) would
#: silently break the rounded/unrounded tangency contract on one
#: side until everyone resynced. Single source here.
VOWEL_PAIR_SHIFT_PX: float = (BTN_W + VOWEL_PAIR_GAP_PX) / 2


# ---------------------------------------------------------------------------
# Segment-grid: manner-class group headers (PLOSIVE, FRICATIVE, ...)
# ---------------------------------------------------------------------------

#: Font size (px) for the manner-class group header label. Pre-relay
#: desktop used 8 pt (~10.7 px) while web used the shared label
#: token (11 px). Adopting the shared token so high-DPI desktop
#: displays don't shift the gap below the header.
SEG_GROUP_HEADER_FONT_PX: int = FONT_SIZE_LABEL_PX

#: Font weight for the group header. Pre-relay desktop used
#: ``QFont.Weight.Bold`` (~700) while web used CSS ``font-weight:
#: 600``. Adopting 600 (semibold) for consistency with the vowel
#: chart's title weight and the rest of the axis-label rhythm.
SEG_GROUP_HEADER_FONT_WEIGHT: int = 600

#: Letter-spacing (px) on group headers. Both renderers used 1 px
#: as a literal; pinning the canonical value here so a future
#: tweak doesn't desync.
SEG_GROUP_HEADER_LETTER_SPACING_PX: int = 1

#: Padding tuple ``(top, right, bottom, left)`` in px around the
#: manner-class header text. Pre-relay desktop used ``(4, 2, 1, 2)``
#: (1 px bottom -- header sits almost flush against the first row);
#: web used ``(4, 2, 6, 2)`` (--space-sm bottom -- header floats
#: ~5 px above the first row). Adopting ``(4, 2, 2, 2)`` as the
#: canonical mid-point: enough gap that the header doesn't read
#: as clipped, tight enough that the manner-class label clearly
#: belongs to the row below it.
SEG_GROUP_HEADER_PADDING_PX: tuple[int, int, int, int] = (4, 2, 2, 2)

#: Vertical gap (px) between consecutive manner-class groups in
#: the consonant grid. Pre-relay desktop used the bare ``BTN_GAP``
#: stride (4 px) while web added ``margin-bottom: --space-md``
#: (8 px) to ``.seg-group``. Adopting 8 px so adjacent manner
#: classes read as distinct sections.
SEG_GROUP_GAP_PX: int = SPACING_PX["md"]


# ---------------------------------------------------------------------------
# Feature row (+/- buttons + badge + feature name)
# ---------------------------------------------------------------------------

#: Vertical padding (px) inside a feature row's content margins.
#: Pre-relay desktop used ``setContentsMargins(8, 3, 8, 3)`` while
#: web used CSS ``padding: 2px var(--space-md)``. Both pin the
#: same horizontal padding (= --space-md = 8 px); the vertical
#: value diverged (3 vs 2 px). Adopting 3 px so the row's inner
#: chrome matches the desktop's row-stride math
#: (``FEAT_ROW_H = 30 + 1`` spacing = 31 px).
FEAT_ROW_PADDING_V_PX: int = 3

#: Horizontal padding (px) inside a feature row. Already
#: ``SPACING_PX["md"]`` on both sides; pinning here so the
#: chart_style module is the one source for any future tweak.
FEAT_ROW_PADDING_H_PX: int = SPACING_PX["md"]

#: Gap (px) between the feature-name label, +/- buttons, and
#: badge. Already ``SPACING_PX["xs"]`` on both sides; pinning here
#: so desktop can read the constant instead of a literal ``4``.
FEAT_ROW_GAP_PX: int = SPACING_PX["xs"]

#: Border-radius (px) for the +/- buttons on a feature row.
#: Pre-relay both sides used a literal ``5`` (no shared token).
#: Promoting to a named constant so a future tweak lands once.
FEAT_BTN_RADIUS_PX: int = 5

#: Compact-tier row height (px). When the feature panel would
#: otherwise overflow (feature count >= FEAT_COMPACT_THRESHOLD),
#: rows shrink to this height to fit more in the same pane.
#: Mirrors desktop ``_DENSITY_COMPACT.row_h``; pre-relay the web
#: had no compact mode and relied on the panel scrollbar.
FEAT_ROW_H_COMPACT_PX: int = 26

#: Compact-tier vertical padding (px) inside a row. Mirrors
#: desktop ``_DENSITY_COMPACT.margin_v`` (2 px vs NORMAL's 3 px).
FEAT_ROW_PADDING_V_COMPACT_PX: int = 2


# ---------------------------------------------------------------------------
# Segment-button border thickness ladder
# ---------------------------------------------------------------------------

#: Border thickness ladder for segment buttons (and any other
#: chart element with a state-driven outline). Pre-relay desktop
#: hardcoded ``1.5px`` / ``2px`` / ``1px`` literals across every
#: state in its QSS strings while web read ``--border-thin /
#: --border-std / --border-thick`` tokens from theme.css. Adopting
#: the web's token names so a future HiDPI sweep (e.g. switching
#: ``std`` to an integer px) is one constant edit.
BORDER_PX: dict[str, float] = {
    "thin": 1.0,
    "std": 1.5,
    "thick": 2.0,
}


# ---------------------------------------------------------------------------
# Stack inter-button gap (vertical)
# ---------------------------------------------------------------------------

#: Pixel gap between vertically stacked buttons inside a single
#: ``STACK``-display-kind cell. Both renderers consume this:
#: desktop calls ``QVBoxLayout.setSpacing`` with it, web's CSS
#: reads ``--vowel-cell-stack-gap`` baked from it, and the
#: geometry's ``natural_data_height_px`` math reads it via the
#: re-export at
#: :py:data:`phonology_shared.chart.vowels_layout.VOWEL_CELL_STACK_GAP_PX`.
#: Lives here (presentation layer) rather than in the chart
#: module so build.py can bake it without dragging the chart/
#: import chain into the build script.
VOWEL_CELL_STACK_GAP_PX: int = 1


# ---------------------------------------------------------------------------
# Contrast-set grid (3-4 entries differing on 2+ display features)
# ---------------------------------------------------------------------------

#: Row-gap (px) inside a contrast-set 2x2 grid. Pre-audit desktop
#: used 1 px; web used the shared ``VOWEL_PAIR_GAP_PX`` (2 px) on
#: both axes. Adopting 2 px so the grid reads as a 2x2 with
#: balanced spacing on each axis. Column gap already uses
#: ``VOWEL_PAIR_GAP_PX``; this constant pins the row axis to the
#: same value.
VOWEL_CHART_CONTRAST_SET_ROW_GAP_PX: int = 2


# ---------------------------------------------------------------------------
# Silhouette (trapezoid outline + container floor)
# ---------------------------------------------------------------------------

#: Stroke width (device px) for the trapezoid silhouette outline.
#: Adopted 0.75 px during the "soft modern" pass, bumped back to
#: 1.0 after user feedback that the desktop silhouette was so
#: faint at 0.75 px / 70 % alpha on the post-shrink chart widths
#: (320 px instead of 440 px) that it read as "missing entirely".
#: Sub-pixel widths render with antialiasing on both Qt and the
#: browser; 1.0 stays comfortably above the "is this rendering?"
#: visibility threshold while staying quieter than the 1.5 px
#: standard interactive borders elsewhere in the app.
VOWEL_SILHOUETTE_STROKE_PX: float = 1.0

#: Corner radius for the silhouette outline as a FRACTION of the
#: data-area width. Pre-redesign the outline was a sharp 4-point
#: polygon; the "soft modern" pass rounds every corner so the
#: chart picks up the same radius language as the rest of the
#: app's UI (rounded buttons, panels). Expressed as a fraction
#: because CSS ``clip-path`` polygon coordinates resolve in the
#: element's normalised coord space -- a fixed pixel radius
#: would either need a JS recompute on every resize or a
#: viewbox-based SVG element. Fraction gives ~5 px on a typical
#: 280 px data area and ~8 px on a wide 440 px chart, which
#: stays visually proportional. Both renderers consume the same
#: value: web's ``rounded_silhouette_polygon_points`` helper
#: expands each corner into ``segments_per_corner+1`` interpolated
#: points along a quadratic Bezier; desktop's QPainterPath uses
#: ``quadTo`` between the same per-corner inset points.
VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC: float = 0.018

#: Alpha (0..1) for the silhouette outline color. Pre-audit
#: desktop set ``setAlpha(178)`` (~70 %); web used CSS
#: ``color-mix(70%, transparent)``. Both expressed the same intent
#: (~70 % opacity); pinning the canonical value here so neither
#: side drifts.
VOWEL_SILHOUETTE_ALPHA: float = 0.70

#: Minimum height (px) the data area refuses to compress below.
#: Web set this to ``max(8 * SEG_BTN_H, natural_data_h)`` = at
#: least 208 px so tiny inventories (5-vowel Spanish) still draw
#: a reasonable trapezoid. Desktop's floor was set via the
#: outer region's minimum, effectively ~192 px after chrome
#: subtraction. Standardising on 8 * SEG_BTN_H = 208 px.
VOWEL_CHART_DATA_MIN_H_PX: int = 8 * SEG_BTN_H


# ---------------------------------------------------------------------------
# Diphthong arrows (curved arrows from primary to secondary cell)
# ---------------------------------------------------------------------------

#: Stroke width (px) for the curved arrow path.
DIPHTHONG_ARROW_STROKE_PX: float = 1.0

#: Stroke + arrowhead opacity in diphthong display mode (arrows
#: are always-on in that mode; dimmed-other-arrows on hover is
#: handled in the renderer, not via an alpha constant).
DIPHTHONG_ARROW_FOCUSED_ALPHA: float = 0.95

#: Arrowhead length as a fraction of the data-area width.
#: Pre-audit desktop fixed at 7 px (proportionally tiny on wide
#: charts); web used 2.5 SVG user-units (= 2.5 % of data width).
#: Standardising on the web's scaling behaviour: arrowheads grow
#: with chart width so they stay readable on narrow and wide
#: charts alike. 0.025 maps to ~7 px on a ~280 px data area
#: (Korean PHOIBLE) and ~15 px on a wide PHOIBLE inventory.
DIPHTHONG_ARROWHEAD_LEN_FRAC: float = 0.025

#: Arrowhead half-width as a fraction of the data-area width
#: (perpendicular to the chord tangent). Combined with
#: :data:`DIPHTHONG_ARROWHEAD_LEN_FRAC`, the arrowhead is a
#: triangle whose dimensions scale with the chart.
DIPHTHONG_ARROWHEAD_HALF_FRAC: float = 0.014

#: Fraction of the chord length used as the base lift for the
#: quadratic-Bezier control point. Both renderers used 0.18 today
#: but expressed in different coordinate systems; pinning the
#: shared value here so any rebalance touches one literal.
DIPHTHONG_LIFT_CHORD_FRAC: float = 0.18

#: Cap on the lift expressed as a fraction of the data-area
#: width. Pre-audit desktop capped at 0.05 (5 %); web capped at
#: 0.08 (8 %) of the data width. Adopting 0.08 so the curve
#: has more visible arc on cross-chart diphthongs (English /aɪ/,
#: German /au/), particularly when many arrows fan out from the
#: same source cell.
DIPHTHONG_LIFT_WIDTH_FRAC_CAP: float = 0.08
