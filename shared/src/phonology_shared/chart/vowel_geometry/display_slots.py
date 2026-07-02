"""Display-slot semantics for the vowel chart (layer 2).

Coordinate-free arrangement decisions: which display kind a cell
renders as (stack, the five pair kinds, contrast set), how pair
entries are ordered, which pair side each cell takes, and which
backness anchor a column maps to. Everything here is expressed in
logical columns and abstract vowel-space fractions; nothing in this
module knows about pixels, box sizes, or the outline.

May import :py:mod:`.model` and the inference layer
(:py:mod:`phonology_shared.chart.vowels`); must not import
``cell_boxes``, ``outline``, ``furniture``, or ``pipeline``. See the
package docstring for the layer table.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from phonology_shared.chart.vowel_space import (
    _BACKNESS_GROUP_BY_COL,
    _BACKNESS_X,
    _ROW_LABEL_TO_INDEX,
)
from phonology_shared.chart.vowels import (
    _DISPLAY_CONTRAST_FEATURES,
    _PAIR_KIND_FOR_FEATURE,
    VowelCellDisplayKind,
)

#: Column-semantics views derived from the single source
#: ``vowel_space._BACKNESS_GROUP_BY_COL`` (the coordinate-system
#: module owns the 9-column scheme: 0/1 front pair, 2/3 central
#: pair, 4/5 back pair, 6/7/8 neutral-round). Built once at import
#: so the sizing and projection passes never rebuild per-call dict
#: literals, and a future column-scheme change lands in one place.
_COL_TO_ANCHOR: dict[int, float] = {
    col: _BACKNESS_X[key] for col, key in _BACKNESS_GROUP_BY_COL.items()
}
_BACKNESS_SLOT_ORDER: tuple[str, ...] = ("front", "central", "back")
_COL_TO_SLOT: dict[int, int] = {
    col: _BACKNESS_SLOT_ORDER.index(key)
    for col, key in _BACKNESS_GROUP_BY_COL.items()
}

#: Logical index of the Open row, the one row with placement
#: special-casing (see :py:func:`effective_anchor_x`).
_OPEN_ROW_INDEX: int = _ROW_LABEL_TO_INDEX["Open"]

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
) -> tuple[
    VowelCellDisplayKind,
    tuple[str, ...],
    tuple[str, ...],
    tuple[tuple[int, int], ...],
]:
    """Pick a :py:class:`VowelCellDisplayKind` for ``entries``.

    Pure classifier over canonical feature bundles: no coordinate
    knowledge, no renderer knowledge. ``norm_feats`` must carry
    ALREADY-NORMALIZED (lowercase-keyed) bundles; the geometry
    build normalizes the inventory once and shares the result
    between the placer and this classifier. Returns ``(kind,
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
        return VowelCellDisplayKind.STACK, (), entries, ()
    bundles: list[Mapping[str, str]] = [
        norm_feats.get(seg, {}) for seg in entries
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
        return VowelCellDisplayKind.STACK, (), entries, ()
    contrast = tuple(sorted(differing_display))
    n_feats = len(differing_display)
    # ONE secondary contrast (length OR nasal OR rhotic OR phonation OR
    # tone): a HORIZONTAL variant capsule of any size (2, 3, 4). The
    # feature keys the display kind; entries order plain -> marked.
    if n_feats == 1:
        (only,) = differing_display
        if only in ("breathy", "creaky"):
            kind = VowelCellDisplayKind.PHONATION_PAIR
        else:
            kind = _PAIR_KIND_FOR_FEATURE.get(
                only, VowelCellDisplayKind.CONTRAST_SET
            )
        ordered = _order_variant_row(entries, bundles, only, kind)
        return kind, contrast, ordered, ()
    if differing_display.issubset({"breathy", "creaky"}):
        # Joint breathy/creaky (two features, but the phonation
        # dimension) reads as one horizontal phonation capsule.
        ordered = _order_pair_entries(
            entries, bundles, VowelCellDisplayKind.PHONATION_PAIR
        )
        return VowelCellDisplayKind.PHONATION_PAIR, contrast, ordered, ()
    # TWO secondary contrasts (e.g. length x nasal): a feature-ALIGNED
    # 2x2 gridded capsule for 3-4 entries (columns = one contrast,
    # rows = the other). Dzongkha's u/uː/ũː land here.
    if n_feats == 2 and 2 <= len(entries) <= 4:
        ordered, grid = _grid_layout(entries, bundles, contrast)
        return VowelCellDisplayKind.CONTRAST_SET, contrast, ordered, grid
    # >2 contrasts, or too many entries: stack (no clean linked layout).
    return VowelCellDisplayKind.STACK, (), entries, ()


def _order_variant_row(
    entries: tuple[str, ...],
    bundles: list[Mapping[str, str]],
    feat: str,
    kind: VowelCellDisplayKind,
) -> tuple[str, ...]:
    """Order a single-feature variant group left-to-right, plain member(s)
    first and the ``+``-valued (marked) member(s) on the right. Phonation
    keeps its modal-first ordering."""
    if kind == VowelCellDisplayKind.PHONATION_PAIR:
        return _order_pair_entries(entries, bundles, kind)
    order = sorted(
        range(len(entries)), key=lambda i: bundles[i].get(feat) == "+"
    )
    return tuple(entries[i] for i in order)


def _grid_layout(
    entries: tuple[str, ...],
    bundles: list[Mapping[str, str]],
    contrast: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[tuple[int, int], ...]]:
    """Assign each entry a ``(col, row)`` slot in the contrast capsule.
    Returns the entries in stable reading order plus the parallel slot
    tuple; the renderers size the capsule from the slots' extent (columns
    x rows).

    A partial set with a single BASE form (the entry with no ``+`` in any
    contrast feature, e.g. plain ``u`` among ``u / uː / ũː``) reads best as
    a HORIZONTAL row with the base CENTRED and its variants FLANKING it:
    a 3-entry set becomes ``var | base | var`` (least-marked variant left,
    most-marked right); a 2-entry set becomes ``base | var``. A complete
    4-entry set has no empty quadrant to centre around, so it keeps the
    feature-ALIGNED 2x2 (columns = one contrast, rows the other;
    ``+`` -> col/row 1); a base-less partial set likewise keeps its
    aligned gap."""
    base_idxs = [
        i
        for i, b in enumerate(bundles)
        if not any(b.get(f) == "+" for f in contrast)
    ]
    if len(base_idxs) == 1 and 2 <= len(entries) <= 3:
        base_i = base_idxs[0]

        def _n_marks(i: int) -> int:
            return sum(1 for f in contrast if bundles[i].get(f) == "+")

        variants = sorted(
            (i for i in range(len(entries)) if i != base_i),
            key=lambda i: (_n_marks(i), entries[i]),
        )
        row_ordered: tuple[str, ...]
        if len(variants) == 1:
            # Two entries: base first, its variant to the right.
            row_ordered = (entries[base_i], entries[variants[0]])
        else:
            # Three entries: base in the MIDDLE, variants flanking it
            # (least-marked on the left, most-marked on the right).
            row_ordered = (
                entries[variants[0]],
                entries[base_i],
                entries[variants[1]],
            )
        # One horizontal row: column = reading order, single row.
        row_grid = tuple((col, 0) for col in range(len(entries)))
        return row_ordered, row_grid
    col_feat = "long" if "long" in contrast else contrast[0]
    row_feat = contrast[1] if contrast[0] == col_feat else contrast[0]
    tagged: list[tuple[int, int, str]] = []
    for seg, bundle in zip(entries, bundles):
        col = 1 if bundle.get(col_feat) == "+" else 0
        row = 1 if bundle.get(row_feat) == "+" else 0
        tagged.append((row, col, seg))
    tagged.sort(key=lambda t: (t[0], t[1]))
    ordered = tuple(t[2] for t in tagged)
    grid = tuple((t[1], t[0]) for t in tagged)
    return ordered, grid


#: Inverse of :py:data:`_PAIR_KIND_FOR_FEATURE`: the single feature
#: whose ``+`` value marks the right-hand member of each simple pair
#: kind. PHONATION_PAIR is absent from the source map (it covers the
#: joint breathy/creaky contrast and orders on modality instead, see
#: :py:func:`_order_pair_entries`), so it stays absent here.
_PAIR_KIND_TO_FEATURE: dict[VowelCellDisplayKind, str] = {
    kind: feat for feat, kind in _PAIR_KIND_FOR_FEATURE.items()
}


def _order_pair_entries(
    entries: tuple[str, ...],
    bundles: list[Mapping[str, str]],
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
    if kind in _PAIR_KIND_TO_FEATURE:
        feat = _PAIR_KIND_TO_FEATURE[kind]
        a_val = bundles[0].get(feat)
        b_val = bundles[1].get(feat)
        if a_val == "+" and b_val != "+":
            return (entries[1], entries[0])
        return entries
    if kind == VowelCellDisplayKind.PHONATION_PAIR:

        def _is_modal(b: Mapping[str, str]) -> bool:
            return b.get("breathy") != "+" and b.get("creaky") != "+"

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


#: Maps each neutral col to its two paired siblings. Neutral cols
#: (6/7/8) share a backness anchor with the paired cols at the same
#: row (6 with 0/1, 7 with 2/3, 8 with 4/5). When both a neutral and
#: a paired col are populated, the canonical ``pair_side=0`` for the
#: neutral plus the ``pair_side=±1`` for the paired one only
#: separate them by half a button width; in practice they overlap,
#: so :py:func:`_assign_pair_sides` reroutes the neutral cell into
#: the empty pair-side slot.
_NEUTRAL_TO_PAIRED: dict[int, tuple[int, int]] = {
    6: (0, 1),  # front-neutral -> front-unr/front-rnd
    7: (2, 3),  # central-neutral -> central-unr/central-rnd
    8: (4, 5),  # back-neutral -> back-unr/back-rnd
}

#: Inverse view of ``_NEUTRAL_TO_PAIRED``: paired col -> the neutral
#: col sharing its backness anchor. Derived rather than written out
#: so the two maps cannot drift.
_PAIRED_TO_NEUTRAL: dict[int, int] = {
    paired: neutral
    for neutral, pair in _NEUTRAL_TO_PAIRED.items()
    for paired in pair
}


@dataclass(frozen=True)
class CellClassification:
    """One cell's display-kind verdict from
    :py:func:`_classify_vowel_cell_display`: the kind, the
    display-contrast features that drove it, and the entries with
    the PAIR ordering convention applied."""

    kind: VowelCellDisplayKind
    contrast_features: tuple[str, ...]
    entries: tuple[str, ...]
    #: For a CONTRAST_SET cell, each entry's ``(col, row)`` in the capsule
    #: grid (parallel to ``entries``); empty for pair / stack cells, which
    #: need no grid coordinates. A base-centred set is a single row
    #: (``var | base | var``); a complete set is a 2x2.
    grid: tuple[tuple[int, int], ...] = ()


def classify_cells(
    occupied: Mapping[tuple[int, int], list[str]],
    norm_cache: Mapping[str, Mapping[str, str]],
) -> dict[tuple[int, int], CellClassification]:
    """Classify every populated cell exactly once.

    The row-depth pre-pass and the slot assignment both consume the
    same verdict; classifying here and handing the table to both
    keeps the classifier, the dominant cost when sweeping large
    PHOIBLE inventories, at one run per cell instead of two.
    """
    out: dict[tuple[int, int], CellClassification] = {}
    for rc, entries in occupied.items():
        kind, contrast, ordered, grid = _classify_vowel_cell_display(
            tuple(entries), norm_cache
        )
        out[rc] = CellClassification(
            kind=kind,
            contrast_features=contrast,
            entries=ordered,
            grid=grid,
        )
    return out


def effective_anchor_x(
    row: int, col: int, open_front_populated: bool
) -> float:
    """The backness anchor a cell actually renders at.

    Identical to ``_COL_TO_ANCHOR[col]`` except for the Open-row
    central migration: when the Open row has NO front cell (pair
    cols 0/1 or the front-neutral col 6), its central pair (cols
    2/3) migrates to the front anchor so a one-low-vowel
    inventory's /a/ does not sit at the geometric midpoint of the
    narrowed bottom edge. Single definition consumed by the slot
    assignment AND the diphthong projection so the two can never
    disagree about where a cell's anchor is.
    """
    if row == _OPEN_ROW_INDEX and col in (2, 3) and not open_front_populated:
        return _BACKNESS_X["front"]
    return _COL_TO_ANCHOR[col]


@dataclass(frozen=True)
class CellSlot:
    """One populated cell's coordinate-free arrangement: the logical
    grid slot, the classified display payload, the pair side, and
    the EFFECTIVE backness anchor (post Open-row migration). The
    pipeline's projection stage turns these into positioned
    :py:class:`..model.VowelChartCell` instances."""

    row: int
    col: int
    entries: tuple[str, ...]
    display_kind: VowelCellDisplayKind
    contrast_features: tuple[str, ...]
    pair_side: int
    anchor_x: float
    #: ``(col, row)`` per entry for a CONTRAST_SET; empty otherwise.
    #: Carried through so the projection can hand it to
    #: :py:class:`..model.VowelChartCell`.
    grid: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class SlotPlan:
    """Output of :py:func:`_assign_pair_sides`: the per-cell slots
    the projection consumes, plus the per-row ``(anchor_x,
    pair_side, is_pair_layout)`` width demands the outline's shrink
    solver feeds to ``_min_row_width_for_meta``. Carrying the
    EFFECTIVE anchor keeps the shrink floor consistent with where
    cells actually render."""

    slots: tuple[CellSlot, ...]
    row_width_demands: Mapping[int, list[tuple[float, int, bool]]]


def _assign_pair_sides(
    occupied: Mapping[tuple[int, int], list[str]],
    classifications: Mapping[tuple[int, int], CellClassification],
    open_front_populated: bool,
) -> SlotPlan:
    """Assign each populated cell its pair side and effective
    backness anchor.

    Neutral cols (6/7/8) baseline at ``pair_side=0`` (anchor
    centre) and reroute into an empty pair-side slot when exactly
    one of their paired siblings is populated, so the two cells
    land at distinct rendered positions. Paired cols snap to their
    canonical side whenever a sibling or a neutral co-occupant is
    present; a lone pair-layout cell with neither stays centred on
    the anchor.
    """
    slots: list[CellSlot] = []
    cells_meta_by_row: dict[int, list[tuple[float, int, bool]]] = {}
    for ri, ci in sorted(occupied):
        classification = classifications[(ri, ci)]
        is_pair_layout = classification.kind in PAIR_DISPLAY_KINDS
        if ci >= 6:
            # Neutral col baseline: pair_side=0 (anchor centre).
            # Reroute when a paired col at the same anchor is also
            # populated so the buttons don't overlap.
            paired_lo, paired_hi = _NEUTRAL_TO_PAIRED[ci]
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
            # A lone paired cell sharing its anchor with a populated
            # neutral cell snaps to its canonical side so the
            # neutral cell can take the empty one (see the neutral
            # branch above) and both land at distinct positions.
            has_neutral = (ri, _PAIRED_TO_NEUTRAL[ci]) in occupied
            if is_pair_layout and not has_sibling and not has_neutral:
                # Lone pair cell with no co-occupant: stay centred
                # on the anchor (the canonical lone-pair rendering).
                pair_side = 0
            else:
                pair_side = 1 if ci % 2 else -1
        anchor_x = effective_anchor_x(ri, ci, open_front_populated)
        slots.append(
            CellSlot(
                row=ri,
                col=ci,
                entries=classification.entries,
                display_kind=classification.kind,
                contrast_features=classification.contrast_features,
                pair_side=pair_side,
                anchor_x=anchor_x,
                grid=classification.grid,
            )
        )
        cells_meta_by_row.setdefault(ri, []).append(
            (anchor_x, pair_side, is_pair_layout)
        )
    return SlotPlan(slots=tuple(slots), row_width_demands=cells_meta_by_row)
