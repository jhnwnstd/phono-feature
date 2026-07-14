"""Slot assignment for classified vowel cells (layer 2b).

Given a table of :py:class:`~classifier.CellClassification` verdicts
(one per populated cell), decide where each cell sits along the
horizontal axis: its backness anchor (from :py:mod:`.space`), its
pair side (-1 unrounded / +1 rounded / 0 anchor-centre), and the
per-cell ``pair_shift_px`` value that keeps mates tangent when the
canonical shift is too small (a same-anchor collision of two wide
capsules).

Produces:

* :py:class:`CellSlot` -- one per populated cell, carrying every
  arrangement decision the projection stage needs.
* :py:class:`SlotPlan` -- the slots plus per-row width demands the
  shrink solver feeds to ``_min_row_width_for_meta``.

Coordinate-free; nothing here touches pixels or the outline. The
projection stage that consumes these slots lives in
:py:mod:`.projection`.

Depends on ``model`` (for :py:class:`~model.VowelChartCell`, which
:py:func:`resolve_pair_shift_conflicts` iterates over post-projection),
:py:mod:`.space` (column-to-anchor + neutral-reroute maps),
:py:mod:`.classifier` (:py:data:`~classifier.PAIR_DISPLAY_KINDS`,
:py:class:`~classifier.CellClassification`), and :py:mod:`.cell_boxes`
(cell-width + inter-cell-gap for the pair-shift conflict solver).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from phonology_shared.chart.vowel_space_geometry.cell_boxes import (
    _INTER_CELL_GAP_PX,
    SOLVER_MAX_CONTRAST_SET_BUTTONS,
    _cell_width_px,
    horizontal_button_count,
)
from phonology_shared.chart.vowel_space_geometry.classifier import (
    PAIR_DISPLAY_KINDS,
    CellClassification,
)
from phonology_shared.chart.vowel_space_geometry.column_scheme import (
    col_to_anchor,
    neutral_to_paired,
    paired_to_neutral,
)
from phonology_shared.chart.vowel_space_geometry.model import VowelChartCell
from phonology_shared.chart.vowels import VowelCellDisplayKind
from phonology_shared.presentation.chart_style import VOWEL_PAIR_SHIFT_PX


@dataclass(frozen=True)
class CellSlot:
    """One populated cell's coordinate-free arrangement: the logical
    grid slot, the classified display payload, the pair side, and
    the canonical backness anchor.

    The projection stage turns each ``CellSlot`` into a positioned
    :py:class:`~model.VowelChartCell` by reading its ``anchor_x``
    through :py:func:`~projection.project_anchor_x`. The projection
    reads the silhouette's canonical apex (if set) and applies the
    lone-central-low bottom warp -- ``/a/`` lands at ~1/3 of the
    shrunken front-back span, hugging (but not sitting on) the
    central anchor. without any per-cell anchor override here.
    """

    row: int
    col: int
    entries: tuple[str, ...]
    display_kind: VowelCellDisplayKind
    pair_side: int
    anchor_x: float
    #: ``(col, row)`` per entry for a CONTRAST_SET; empty otherwise.
    grid: tuple[tuple[int, int], ...] = ()
    #: Parallel to :py:attr:`grid`: ``(col_span, row_span)`` per
    #: entry (defaults to ``(1, 1)`` when unspecified). Non-trivial
    #: only for the base-and-variants layout.
    spans: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class SlotPlan:
    """Result of :py:func:`assign_pair_sides`: the per-cell slots the
    projection consumes, plus the per-row ``(anchor_x, pair_side,
    n_buttons)`` width demands the outline's shrink solver feeds to
    :py:func:`~shrink.min_row_width_for_meta`. ``n_buttons`` comes from
    :py:func:`horizontal_button_count`, so the shrink floor reserves
    what the cell actually draws."""

    slots: tuple[CellSlot, ...]
    row_width_demands: Mapping[int, list[tuple[float, int, int]]]


def assign_pair_sides(
    occupied: Mapping[tuple[int, int], list[str]],
    classifications: Mapping[tuple[int, int], CellClassification],
) -> SlotPlan:
    """Assign each populated cell its pair side and canonical
    backness anchor.

    Neutral cols (6/7/8) baseline at ``pair_side=0`` (anchor centre)
    and reroute into an empty pair-side slot when exactly one of
    their paired siblings is populated, so the two cells land at
    distinct rendered positions. Paired cols snap to their canonical
    side whenever a sibling or a neutral co-occupant is present; a
    lone pair-layout cell with neither stays centred on the anchor.
    """
    slots: list[CellSlot] = []
    cells_meta_by_row: dict[int, list[tuple[float, int, int]]] = {}
    for ri, ci in sorted(occupied):
        classification = classifications[(ri, ci)]
        is_pair_layout = classification.kind in PAIR_DISPLAY_KINDS
        n_buttons = horizontal_button_count(
            classification.kind,
            classification.entries,
            classification.grid,
            classification.spans,
        )
        if ci >= 6:
            # Neutral col baseline: pair_side=0 (anchor centre).
            # Reroute when a paired col at the same anchor is also
            # populated so the buttons don't overlap.
            paired_lo, paired_hi = neutral_to_paired[ci]
            has_lo = (ri, paired_lo) in occupied
            has_hi = (ri, paired_hi) in occupied
            if has_lo and not has_hi:
                # Only the unrounded pair member is taken. Send the
                # neutral cell to the empty rounded position.
                pair_side = +1
            elif has_hi and not has_lo:
                # Only the rounded pair member is taken. Send the
                # neutral cell to the empty unrounded position;
                # this is the canonical "default unrounded"
                # semantics PHOIBLE neutral typically expresses.
                pair_side = -1
            else:
                # Either both pair cols are populated (rare; the
                # placer puts each unique feature shape in its own
                # col) or neither is. Keep the anchor centre.
                pair_side = 0
        else:
            # Pair cols come in (unrounded, rounded) couples at
            # consecutive even/odd indices, so XOR-1 is the sibling.
            has_sibling = (ri, ci ^ 1) in occupied
            has_neutral = (ri, paired_to_neutral[ci]) in occupied
            if is_pair_layout and not has_sibling and not has_neutral:
                # Lone pair cell with no co-occupant: stay centred
                # on the anchor (the canonical lone-pair rendering).
                pair_side = 0
            else:
                pair_side = 1 if ci % 2 else -1
        anchor_x = col_to_anchor[ci]
        slots.append(
            CellSlot(
                row=ri,
                col=ci,
                entries=classification.entries,
                display_kind=classification.kind,
                pair_side=pair_side,
                anchor_x=anchor_x,
                grid=classification.grid,
                spans=classification.spans,
            )
        )
        # Cap CONTRAST_SET width demand at the radial pill's 3-col
        # footprint so a click-language pill sizes like a plain pair.
        solver_n_buttons = (
            min(n_buttons, SOLVER_MAX_CONTRAST_SET_BUTTONS)
            if classification.kind == VowelCellDisplayKind.CONTRAST_SET
            else n_buttons
        )
        cells_meta_by_row.setdefault(ri, []).append(
            (anchor_x, pair_side, solver_n_buttons)
        )
    return SlotPlan(slots=tuple(slots), row_width_demands=cells_meta_by_row)


# -----------------------------------------------------------------------
# Post-projection: same-anchor collision resolver.
# -----------------------------------------------------------------------


def anchor_group_key(chart_x: float) -> int:
    """Quantised anchor identity: cells whose ``chart_x`` agree to
    the nearest thousandth share a backness anchor. The conflict
    resolver and the confinement pass group by this key so
    same-anchor cells are handled as one column and pair tangency
    survives any shift applied to the group."""
    return round(chart_x * 1000)


def resolve_pair_shift_conflicts(
    cells: list[VowelChartCell],
) -> list[VowelChartCell]:
    """Elevate ``cell.pair_shift_px`` on same-anchor opposite-side
    pairs where the canonical
    :py:data:`~phonology_shared.presentation.constants.VOWEL_PAIR_SHIFT_PX`
    would not keep the two mates tangent.

    Same-``chart_x`` + opposite ``pair_side`` cells render at
    ``cx*dw ± pair_shift_px``. They overlap iff the sum of their
    half-widths exceeds ``2 * pair_shift_px``. The canonical shift
    (17.5 px) is sized for single-button cells; two ``long_pair``
    cells (68 px each) overshoot by ~33 px. Elevating
    ``pair_shift_px`` on both members to
    ``(half_a + half_b + gap) / 2`` makes them tangent.
    """
    canonical = float(VOWEL_PAIR_SHIFT_PX)
    rows: dict[int, list[int]] = {}
    for idx, c in enumerate(cells):
        rows.setdefault(c.row, []).append(idx)
    updated: dict[int, float] = {}
    for row_indices in rows.values():
        groups: dict[int, list[int]] = {}
        for idx in row_indices:
            key = anchor_group_key(cells[idx].chart_x)
            groups.setdefault(key, []).append(idx)
        for grouped in groups.values():
            if len(grouped) < 2:
                continue
            for i_idx, ai in enumerate(grouped):
                for bi in grouped[i_idx + 1 :]:
                    a, b = cells[ai], cells[bi]
                    if a.pair_side * b.pair_side >= 0:
                        continue
                    half_a = _cell_width_px(a) / 2.0
                    half_b = _cell_width_px(b) / 2.0
                    needed = (half_a + half_b + _INTER_CELL_GAP_PX) / 2.0
                    if needed <= canonical:
                        continue
                    for k in (ai, bi):
                        cur = updated.get(k, 0.0)
                        if needed > cur:
                            updated[k] = needed
    if not updated:
        return cells
    return [
        replace(c, pair_shift_px=updated[idx]) if idx in updated else c
        for idx, c in enumerate(cells)
    ]
