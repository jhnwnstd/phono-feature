"""Display-kind classifier for one cell's entries (layer 2a).

Coordinate-free decision layer: given the entries at a cell and their
normalised feature bundles, decide which
:py:class:`~phonology_shared.chart.vowels.VowelCellDisplayKind` the
cell renders as (STACK, one of the pair kinds, or CONTRAST_SET), pick
the display order for the entries, and lay out the CONTRAST_SET grid.
Nothing here knows about pixels, coordinates, or the outline.

The classifier's verdict rides a :py:class:`CellClassification` into
the sizing solver, the slot assigner, and the renderer -- one verdict
per cell, computed exactly once by :py:func:`classify_cells`.

Depends only on ``chart.vowels`` (the display-kind enum + the
dimension-and-feature dictionaries). May not import ``model``,
``cell_boxes``, or anything above.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass

from phonology_shared.chart.vowels import (
    _DIMENSION_KIND_FOR_FEATURE,
    _DISPLAY_CONTRAST_FEATURES,
    _PAIR_KIND_FOR_FEATURE,
    VowelCellDisplayKind,
)

#: The horizontal-capsule kinds -- one cell that renders every entry
#: side by side in a single row (2 for a plain pair, 3-4 for a
#: phonation series). Derived from
#: :py:data:`_DIMENSION_KIND_FOR_FEATURE` (every dimension IS a
#: horizontal-capsule kind, which is exactly the invariant the
#: classifier's single-dimension branch relies on) so a new dimension
#: cannot be forgotten here. Consumed by the sizing solver's cell
#: width formula and by the slot assigner's pair-side rules.
PAIR_DISPLAY_KINDS: frozenset[VowelCellDisplayKind] = frozenset(
    _DIMENSION_KIND_FOR_FEATURE.values()
)

#: Inverse of :py:data:`_PAIR_KIND_FOR_FEATURE`: the single feature
#: whose ``+`` value marks the right-hand member of each simple pair
#: kind. PHONATION_PAIR is absent from the source map (its dimension
#: spans several features, so it orders through the shared base-first
#: rule) so it stays absent here.
_PAIR_KIND_TO_FEATURE: dict[VowelCellDisplayKind, str] = {
    kind: feat for feat, kind in _PAIR_KIND_FOR_FEATURE.items()
}


@dataclass(frozen=True)
class CellClassification:
    """One cell's display-kind verdict.

    :py:attr:`kind` is the chosen :py:class:`VowelCellDisplayKind`.
    :py:attr:`contrast_features` is the sorted tuple of display-
    contrast features the entries differ on (``()`` for a
    position-driven stack). :py:attr:`entries` is the entries
    reordered by the layout convention: base member first / marked
    member(s) after for a pair, base-first for a stack, capsule
    reading order for a CONTRAST_SET. :py:attr:`grid` gives each
    entry's ``(col, row)`` slot in the capsule for a CONTRAST_SET;
    empty for pair / stack cells.
    """

    kind: VowelCellDisplayKind
    contrast_features: tuple[str, ...]
    entries: tuple[str, ...]
    grid: tuple[tuple[int, int], ...] = ()


def classify_display_kind(
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
    contrast_features, ordered_entries, grid)``.

    An in-cell contrast is a DIMENSION, not a single feature: features
    that encode the same secondary contrast share one display kind (all
    phonation features -> PHONATION_PAIR), so the classifier counts
    dimensions, and any dimension grows to several features the way
    phonation does.

    Decision tree:
      1. < 2 entries -> STACK.
      2. Compute the set of features whose values are NOT identical
         across the entries (skipping ``None``-only differences so
         a one-sided ``"0"`` does not register as a contrast).
      3. Partition into display features (intersection with
         :py:data:`_DISPLAY_CONTRAST_FEATURES`) and other features.
      4. If any non-display feature differs -> a featureless STACK.
         The entries differ on a POSITION feature the 2-D quadrilateral
         cannot resolve; stacking is the honest layout.
      5. Group the display features by DIMENSION (the kind each maps to
         via :py:data:`_DIMENSION_KIND_FOR_FEATURE`). ONE dimension ->
         that dimension's horizontal capsule, however many features or
         entries encode it (plain / long; plain / breathy / creaky).
      6. Exactly two differing display FEATURES (two binary dimensions),
         2-4 entries -> CONTRAST_SET (feature-aligned 2x2).
      7. Otherwise (3+ dimensions, or a multi-value dimension crossed
         with another) -> a contrast-AWARE STACK: the contrast features
         are kept and the entries ordered base-first.
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
    dimensions = {
        _DIMENSION_KIND_FOR_FEATURE.get(feat, feat)
        for feat in differing_display
    }
    if len(dimensions) == 1:
        (dimension,) = dimensions
        kind = (
            dimension
            if isinstance(dimension, VowelCellDisplayKind)
            else VowelCellDisplayKind.CONTRAST_SET
        )
        ordered = _order_variant_row(entries, bundles, differing_display, kind)
        return kind, contrast, ordered, ()
    if len(differing_display) == 2 and 2 <= len(entries) <= 4:
        ordered, grid = _grid_layout(entries, bundles, contrast)
        if len(set(grid)) == len(entries):
            return VowelCellDisplayKind.CONTRAST_SET, contrast, ordered, grid
        # Slot collision (a "-" vs "0" split that the aligned 2x2 bins
        # to one slot); fall back to the contrast-aware STACK.
    ordered = _order_base_first(entries, bundles, contrast)
    return VowelCellDisplayKind.STACK, contrast, ordered, ()


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
        kind, contrast, ordered, grid = classify_display_kind(
            tuple(entries), norm_cache
        )
        out[rc] = CellClassification(
            kind=kind,
            contrast_features=contrast,
            entries=ordered,
            grid=grid,
        )
    return out


# -----------------------------------------------------------------------
# Entry-ordering helpers. Private: consumers of the classifier read
# ``CellClassification.entries`` after ``classify_cells`` has already
# applied the ordering.
# -----------------------------------------------------------------------


def _order_base_first(
    entries: tuple[str, ...],
    bundles: list[Mapping[str, str]],
    feats: Collection[str],
) -> tuple[str, ...]:
    """Order a variant group so it reads as a series: base (no ``+``
    on any contrast feature) first, then single-feature variants,
    then any multi-marked entries, within each tier by the contrast
    features in sorted order. Shared by the contrast-aware STACK
    and the single-dimension capsules so a stacked !Xoo series and a
    phonation capsule order by the same rule."""
    ordered_feats = sorted(feats)

    def key(i: int) -> tuple[int, tuple[str, ...]]:
        bundle = bundles[i]
        marked = sum(1 for feat in ordered_feats if bundle.get(feat) == "+")
        return marked, tuple(bundle.get(feat, "0") for feat in ordered_feats)

    order = sorted(range(len(entries)), key=key)
    return tuple(entries[i] for i in order)


def _order_variant_row(
    entries: tuple[str, ...],
    bundles: list[Mapping[str, str]],
    feats: Collection[str],
    kind: VowelCellDisplayKind,
) -> tuple[str, ...]:
    """Order a single-DIMENSION variant group left-to-right: base
    (unmarked) member(s) first, ``+``-valued (marked) member(s) to the
    right. A 2-entry SINGLE-FEATURE pair keeps the established pair
    convention (:py:func:`_order_pair_entries`: marked member right,
    tone by value). Everything else, including every phonation
    group, uses the shared base-first ordering (which reduces to
    modal-first for a 2-entry phonation pair under any encoding)."""
    if len(entries) == 2 and kind in _PAIR_KIND_TO_FEATURE:
        return _order_pair_entries(entries, bundles, kind)
    return _order_base_first(entries, bundles, feats)


def _order_pair_entries(
    entries: tuple[str, ...],
    bundles: list[Mapping[str, str]],
    kind: VowelCellDisplayKind,
) -> tuple[str, ...]:
    """Reorder a 2-entry SINGLE-FEATURE pair so the "marked" member
    sits on the right (canonical reading direction)."""
    feat = _PAIR_KIND_TO_FEATURE[kind]
    a_val = bundles[0].get(feat)
    b_val = bundles[1].get(feat)
    if a_val == "+" and b_val != "+":
        return (entries[1], entries[0])
    return entries


def _grid_layout(
    entries: tuple[str, ...],
    bundles: list[Mapping[str, str]],
    contrast: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[tuple[int, int], ...]]:
    """Assign each entry a ``(col, row)`` slot in the CONTRAST_SET
    capsule. Returns the entries in stable reading order plus the
    parallel slot tuple.

    A partial set with a single BASE form (no ``+`` in any contrast
    feature, e.g. plain ``u`` among ``u / uː / ũː``) reads best as a
    HORIZONTAL row with the base CENTRED and its variants FLANKING it
    (2 entries -> ``base | var``; 3 entries -> ``var | base | var``).
    A complete 4-entry set (no empty quadrant to centre around) keeps
    the feature-ALIGNED 2x2; a base-less partial set likewise keeps
    its aligned gap.
    """
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
            row_ordered = (entries[base_i], entries[variants[0]])
        else:
            row_ordered = (
                entries[variants[0]],
                entries[base_i],
                entries[variants[1]],
            )
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
