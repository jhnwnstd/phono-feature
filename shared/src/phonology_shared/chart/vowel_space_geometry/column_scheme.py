"""Vowel-space coordinate system (layer 1).

The single source of truth for the 9-column x row-index vowel-chart
grid the whole package sits on. Every higher layer -- display-kind
classifier, slot assignment, silhouette geometry, projection, row
plan, sizing, confinement -- reads its column-to-anchor mapping,
neutral-column reroute maps, and Open-row index from HERE, so a
future column-scheme change (e.g. adding a fourth backness column,
splitting the neutral-round column) lands in ONE file.

This module owns coordinate FACTS derived from the lower-level
``chart.vowel_space`` module (which owns the ANCHOR VALUES in
normalised [0, 1] space). It carries no arithmetic and no cells; the
box math, projection, and outline geometry all sit above it.

Depends only on ``chart.vowel_space`` (the anchor-value foundation)
and ``chart.vowels`` (the placement-layer display-kind enum). May
NOT import any other module in ``vowel_space_geometry``.
"""

from __future__ import annotations

from phonology_shared.chart.vowel_space import (
    _BACKNESS_GROUP_BY_COL,
    _BACKNESS_X,
)
from phonology_shared.chart.vowels import VowelCellDisplayKind

#: Column-to-backness-anchor map derived from the coordinate
#: foundation. The 9-column scheme (0/1 front pair, 2/3 central pair,
#: 4/5 back pair, 6/7/8 neutral-round per backness) is owned by
#: ``vowel_space``; this dict is the pre-computed inverse view every
#: higher layer reads to translate a logical column into its data-x
#: anchor. Built once at import; per-call dict comprehensions would
#: rebuild it on every projection.
col_to_anchor: dict[int, float] = {
    col: _BACKNESS_X[key] for col, key in _BACKNESS_GROUP_BY_COL.items()
}

#: Canonical backness slot order (front, central, back). Neutral-
#: rounding columns collapse onto their backness slot: col 6 -> front
#: slot, col 7 -> central slot, col 8 -> back slot. Used by the
#: sizing solver's per-slot width demand and by the confinement pass'
#: anchor-group key.
backness_slot_order: tuple[str, ...] = ("front", "central", "back")

#: Column-to-slot map: paired cols share their slot with the
#: matching neutral col so the sizing solver treats a front pair AND
#: a front-neutral as ONE anchor group.
col_to_slot: dict[int, int] = {
    col: backness_slot_order.index(key)
    for col, key in _BACKNESS_GROUP_BY_COL.items()
}

#: Neutral-column to (unrounded pair col, rounded pair col). The
#: pair-side assignment uses this to reroute a neutral-round cell
#: into an empty pair-side slot when its paired sibling is
#: populated, so both cells sit at distinct rendered positions
#: instead of stacking on the same anchor. Written out (not
#: derived) because the mapping is a design decision, not an
#: arithmetic consequence.
neutral_to_paired: dict[int, tuple[int, int]] = {
    6: (0, 1),  # front-neutral  -> front-unr / front-rnd
    7: (2, 3),  # central-neutral -> central-unr / central-rnd
    8: (4, 5),  # back-neutral   -> back-unr / back-rnd
}

#: Inverse view of :py:data:`neutral_to_paired`: paired col -> the
#: neutral col sharing its backness anchor. Derived rather than
#: written out so the two maps cannot drift.
paired_to_neutral: dict[int, int] = {
    paired: neutral
    for neutral, pair in neutral_to_paired.items()
    for paired in pair
}


def horizontal_button_count(
    kind: VowelCellDisplayKind,
    entries: tuple[str, ...],
    grid: tuple[tuple[int, int], ...],
    *,
    pair_display_kinds: frozenset[VowelCellDisplayKind],
) -> int:
    """Horizontal button count of one cell: how many buttons wide it
    renders. A PAIR kind lays EVERY entry in one row (2 for a plain
    pair; 3-4 for a plain / breathy / creaky series or a 4-way
    phonation set); a CONTRAST_SET spans its ``grid`` column extent
    (base-centred row ``var | base | var`` is 3, a 2x2 is 2;
    canonical 2 when no grid); STACK is 1 wide.

    THE ONE definition of cell width in buttons: ``cell_boxes``
    sizing delegates here and the shrink solver's row width demands
    are built from it, so the box math, the natural sizing, and the
    shrink floor can never disagree about how wide a cell draws.

    ``pair_display_kinds`` is a caller-supplied set of kinds that
    render horizontally (the ``PAIR_DISPLAY_KINDS`` frozenset the
    classifier layer owns). Passed as a parameter instead of imported
    so this module does not accrete a dependency on the classifier
    layer just to spell one predicate.
    """
    if kind in pair_display_kinds:
        return len(entries)
    if kind == VowelCellDisplayKind.CONTRAST_SET:
        if not grid:
            return 2
        return max(col for col, _row in grid) + 1
    return 1
