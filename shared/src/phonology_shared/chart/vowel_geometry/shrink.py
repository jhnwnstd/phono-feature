"""Uniform-shrink silhouette-width solver (layer 4b).

Given the per-row minimum-required widths (from cell button counts +
anchor spacing) and a canonical silhouette (top_width / bottom_width /
y bounds), compute the shrunken widths that leave the widest row just
tangent to its own content.

Uniform shrink: both widths drop by the SAME amount, set by the most-
constrained row's slack. The trapezoid keeps its canonical proportions
while pulling inward as a whole; the slant stays constant. This is
what gives every inventory's silhouette a stable visual identity: a
5-vowel Spanish chart and a 33-vowel Maximalist chart share the same
trapezoid proportions, with the dense one just slightly narrower
overall.

(An earlier per-inventory Stage 2 asymmetric slant tweak solved a 2-
variable LP for extra per-edge shrinkage but tilted the canonical
trapezoid differently for every inventory, defeating the chart's at-
a-glance familiarity. Retired; if per-inventory slant asymmetry is
ever needed again, add it as an INVENTORY-DRIVEN policy (e.g. read
the populated-column count) rather than a magic knob.)

Cell-blind: the solver reads per-row ``(anchor_x, pair_side,
n_buttons)`` demands only. The pipeline builds those demands from
classified cells and feeds them here; no cell object crosses the
layer boundary. The silhouette layer applies the resulting widths
via :py:func:`~silhouette._silhouette_with_widths`.
"""

from __future__ import annotations

from collections.abc import Mapping

from phonology_shared.chart.vowel_space import _CANONICAL_CONTENT_W_PX
from phonology_shared.presentation.constants import BTN_W
from phonology_shared.presentation.layout import (
    VOWEL_PAIR_GAP_PX,
    VOWEL_PAIR_SEPARATOR_PX,
)

#: How aggressively the silhouette's top_width and bottom_width
#: shrink toward the most-constrained row's minimum required width.
#: ``0.0`` keeps the canonical widths; ``1.0`` would consume all the
#: slack. Both the silhouette outline and the projection use the
#: resulting widths, so cells follow the silhouette by construction.
_VOWEL_SHRINK_FACTOR: float = 0.3

#: Minimum visual separation between adjacent cells in the same
#: row (expressed as a fraction of the canonical content width).
#: Matches the inter-pair separator on the canonical 3-slot
#: layout, so two pinched-together slots end up with the same
#: comfortable gap as canonical adjacent pairs.
_VOWEL_MIN_CELL_GAP_NORM: float = (
    VOWEL_PAIR_SEPARATOR_PX / _CANONICAL_CONTENT_W_PX
)


def _min_row_width_for_meta(
    row_cells: list[tuple[float, int, int]],
) -> float:
    """Lower bound on ``row_width`` such that the row's cells do
    not overlap given back-anchored projection.

    Each tuple is ``(anchor_x, pair_side, n_buttons)`` where
    ``anchor_x`` is the cell's EFFECTIVE backness anchor (after any
    Open-row central migration) and ``n_buttons`` its horizontal
    button count (``cell_boxes.horizontal_button_count``); the
    cell's horizontal extent is its half-width plus its pair-side
    offset from the row's projected anchor. With back-anchored
    projection ``chart_x = back + W * (anchor - back)``, the
    distance between two cells at adjacent anchors scales linearly
    with ``W``; this function solves for the minimum ``W`` such that
    every adjacent pair has at least ``_VOWEL_MIN_CELL_GAP_NORM``
    between them (zero if a single cell occupies the row).
    """
    if len(row_cells) < 2:
        return 0.0
    pair_shift = (BTN_W + VOWEL_PAIR_GAP_PX) / 2.0 / _CANONICAL_CONTENT_W_PX

    def half(n_buttons: int) -> float:
        # n buttons side by side with the pair gap between them, halved:
        # n=1 reduces to BTN_W/2 and n=2 to the classic pair half-width,
        # so the 3-4 button capsules reserve exactly what they draw.
        width_px = n_buttons * BTN_W + (n_buttons - 1) * VOWEL_PAIR_GAP_PX
        return width_px / 2.0 / _CANONICAL_CONTENT_W_PX

    sorted_meta = sorted(row_cells, key=lambda c: c[0])
    min_w = 0.0
    for (anchor_a, ps_a, n_a), (anchor_b, ps_b, n_b) in zip(
        sorted_meta, sorted_meta[1:]
    ):
        if anchor_b <= anchor_a:
            # Same backness slot; pair_side handles separation.
            continue
        half_a = half(n_a)
        half_b = half(n_b)
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
    cells_meta_by_row: Mapping[int, list[tuple[float, int, int]]],
    display_y_by_row: Mapping[int, float],
    top_y: float,
    bottom_y: float,
    canonical_top_width: float,
    canonical_bottom_width: float,
    asymmetric: bool = False,
) -> tuple[float, float]:
    """Compute shrunken silhouette ``(top_width, bottom_width)``.

    Two policies:

    * **Uniform shrink** (classic trapezoid, ``asymmetric=False``):
      both widths drop by the SAME amount, set by the most-constrained
      row's slack. Preserves the canonical trapezoid slant so a 5-vowel
      Spanish chart and a 33-vowel Maximalist chart share the same
      trapezoid proportions.
    * **Asymmetric shrink** (converged bottom, ``asymmetric=True``):
      top and bottom widths shrink INDEPENDENTLY, each by its own
      row's slack. For a lone-low-vowel inventory the Open row demands
      near-zero width while the Close row still needs its wide-pair
      layout; asymmetric shrink lets the bottom narrow far more than
      the top, so the silhouette actually reads as a wedge converging
      on the sole low vowel instead of a barely-narrowing rectangle.
      Middle rows sit inside the resulting trapezoid; the linear
      interpolation of widths covers their demand because the top row
      is the widest by construction.
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
    if asymmetric:
        return _shrink_per_edge(
            row_data, canonical_top_width, canonical_bottom_width
        )
    return _shrink_uniform(
        row_data, canonical_top_width, canonical_bottom_width
    )


# Kept as alias for the historical name external tests import.
def _stage1_uniform_shrink(
    row_data: list[tuple[float, float]],
    canonical_top_width: float,
    canonical_bottom_width: float,
) -> tuple[float, float]:
    return _shrink_uniform(
        row_data, canonical_top_width, canonical_bottom_width
    )


def _shrink_uniform(
    row_data: list[tuple[float, float]],
    canonical_top_width: float,
    canonical_bottom_width: float,
) -> tuple[float, float]:
    """Pull top and bottom inward by the same amount, bounded by
    the most-constrained row. Preserves the canonical slant.
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


def _shrink_per_edge(
    row_data: list[tuple[float, float]],
    canonical_top_width: float,
    canonical_bottom_width: float,
) -> tuple[float, float]:
    """Shrink top and bottom edges INDEPENDENTLY, each by its own
    row's slack. Used for converged silhouettes where the Open row
    demands near-zero width but the Close row still needs its wide
    Close pair; per-edge shrink lets the bottom collapse toward the
    apex without dragging the top with it.

    Middle rows may sit anywhere within the resulting trapezoid;
    their widths come from linear interp between top and bottom.
    Since the top row is the widest by construction under
    ``open_apex_backness`` (Open row is sparse), middle rows fit.
    """
    top_row_data = [(t, w) for t, w in row_data if t <= 0.0 + 1e-9]
    bot_row_data = [(t, w) for t, w in row_data if t >= 1.0 - 1e-9]
    top_min = max(w for _t, w in top_row_data) if top_row_data else 0.0
    bot_min = max(w for _t, w in bot_row_data) if bot_row_data else 0.0
    top_slack = canonical_top_width - top_min
    bot_slack = canonical_bottom_width - bot_min
    top_consume = _VOWEL_SHRINK_FACTOR * top_slack if top_slack > 0 else 0.0
    bot_consume = _VOWEL_SHRINK_FACTOR * bot_slack if bot_slack > 0 else 0.0
    return (
        max(0.0, canonical_top_width - top_consume),
        max(0.0, canonical_bottom_width - bot_consume),
    )
