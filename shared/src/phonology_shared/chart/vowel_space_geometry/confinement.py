# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Required Notice: Copyright 2026 John Winstead,
# https://github.com/jhnwnstd/phono-feature
"""Hard-boundary cell confinement (layer 4f).

The final gate the placement pipeline runs before handing cells to
the renderers: nudge cells inward until every button box sits inside
the rendered silhouette. Shift-only -- confinement writes each cell's
``nudge_px`` pixel offset and never feeds back into the solved
chart width; folded into the anchor instead, near-coincident anchors
look separable by widening and the shrink solver inflates dense
PHOIBLE charts to several times their natural width.

Confinement is against the STRAIGHT silhouette edges
(:py:func:`~silhouette.straight_left_at_y` /
:py:func:`~silhouette.straight_right_at_y`), NOT the rounded-corner
polygon. The rounded corners are a cosmetic stroke, not a containment
edge, and confining the vertical back column against them shoves the
top / bottom cells inward and breaks the column's alignment. Row
LABELS instead track :py:func:`~silhouette.silhouette_left_at_y` so
they hug the visible rounded stroke.

Same-anchor groups (identified via
:py:func:`~slots.anchor_group_key`) move TOGETHER so pair tangency
(including an elevated ``pair_shift_px``) is preserved. Per-row
lanes cap the shift so a confined group can never cross into a row
neighbour and manufacture an inter-cell overlap.
"""

from __future__ import annotations

from dataclasses import replace

from phonology_shared.chart.vowel_space_geometry.cell_boxes import _cell_box_px
from phonology_shared.chart.vowel_space_geometry.model import (
    VowelChartCell,
    VowelChartSilhouette,
)
from phonology_shared.chart.vowel_space_geometry.silhouette import (
    silhouette_for_data_width,
    straight_left_at_y,
    straight_right_at_y,
)
from phonology_shared.chart.vowel_space_geometry.sizing import SizedChart
from phonology_shared.chart.vowel_space_geometry.slots import anchor_group_key

#: Safety inset (px) the confinement pass keeps between a button box
#: and the outline. Absorbs the renderers' integer rounding (round-
#: to-nearest on the centre plus the floor-divided half width can
#: land a box ~1.5 px outside the float position).
_CONFINE_MARGIN_PX: float = 2.0

#: Confinement iterations. Nudges are shift-only (no chart resize),
#: so a second pass only verifies the first converged; the audit
#: across the bundled + PHOIBLE catalogues converges in one.
_CONFINE_MAX_PASSES: int = 2


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
    trapezoid, the pipeline's ``_grow_outline_extent`` reserves room
    for the wide edge groups, and this pass closes the residual
    escape modes the anchor model cannot express: a box's corner
    overhanging the slanted front edge even when its centre is
    inside (~4 px), and renderer integer rounding (~1 px).

    Confinement is against the STRAIGHT trapezoid edges
    (:py:func:`~silhouette.straight_left_at_y` /
    :py:func:`~silhouette.straight_right_at_y`), NOT the
    rounded-corner polygon; see the module docstring for why.

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


def confine_cells(
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
