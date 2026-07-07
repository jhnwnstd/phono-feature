"""Two-stage silhouette-width shrink solver (layer 4b).

Given the per-row minimum-required widths (from cell button counts +
anchor spacing) and a canonical silhouette (top_width /
bottom_width / y bounds), compute the shrunken widths that leave the
widest row just tangent to its own content.

The solver runs in two conceptual stages:

* **Stage 1 (uniform shrink).** Pull top and bottom inward by the
  same amount, set by the most-constrained row's slack. Preserves the
  canonical trapezoid slant.
* **Stage 2 (slant tweak).** With Stage 1's narrower trapezoid in
  hand, LP-solve a per-edge nudge (``d_top``, ``d_bot``) that
  further consumes any residual per-row slack. Bounded by
  :py:data:`_VOWEL_SLANT_CHANGE_CAP_FRAC`, currently ``0.0`` (Stage 2
  disabled by policy; the regression test in
  ``test_vowel_silhouette_shrink.py`` pins the value).

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
#: DIFFERENT amounts (changing the slant).
#:
#: CURRENTLY 0.0, WHICH DISABLES STAGE 2. Asymmetric reshaping
#: makes the silhouette read differently per inventory (each one
#: tilts the canonical trapezoid by its own amount), defeating the
#: chart's at-a-glance familiarity. With Stage 2 off, every
#: inventory's silhouette is the canonical Close-to-Open trapezoid
#: (no shrink for sparse inventories) or a UNIFORMLY scaled copy of
#: it (small uniform shrink for dense inventories that still need
#: cells to fit); the slant is constant across the entire bundled +
#: PHOIBLE set.
#:
#: ``1.0`` would let the slant double (or invert). A regression
#: test in test_vowel_silhouette_shrink.py pins the 0.0 so
#: re-enabling the asymmetric tweak is a deliberate edit, not a
#: drive-by.
_VOWEL_SLANT_CHANGE_CAP_FRAC: float = 0.0

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
) -> tuple[float, float]:
    """Compute shrunken silhouette ``(top_width, bottom_width)`` in
    two conceptual stages.

    **Stage 1 (uniform shrink).** Both widths drop by the same
    amount, set by the most-constrained row's slack between its
    canonical row_width and its minimum-required row_width. The
    trapezoid keeps its canonical proportions while pulling inward
    as a whole; the slant stays constant.

    **Stage 2 (slant tweak).** With Stage 1's narrower trapezoid in
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

    Solves a 2-variable LP that maximises ``d_top + d_bot`` (the area
    removed in this pass, modulo the constant span/2) subject to three
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
    for a 7-row chart this is O(100) trivial 2x2 solves, cheap
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
