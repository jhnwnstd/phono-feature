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
    entry's ``(col, row)`` slot in the capsule for a CONTRAST_SET
    (empty for pair / stack cells), and :py:attr:`spans` gives each
    entry's ``(col_span, row_span)`` -- non-trivial only for the
    base-and-variants layout where the base spans multiple rows in
    the left column.
    """

    kind: VowelCellDisplayKind
    contrast_features: tuple[str, ...]
    entries: tuple[str, ...]
    grid: tuple[tuple[int, int], ...] = ()
    spans: tuple[tuple[int, int], ...] = ()


def classify_display_kind(
    entries: tuple[str, ...],
    norm_feats: Mapping[str, Mapping[str, str]],
) -> tuple[
    VowelCellDisplayKind,
    tuple[str, ...],
    tuple[str, ...],
    tuple[tuple[int, int], ...],
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
      5. Group the display features by DIMENSION. ONE dimension ->
         that dimension's horizontal capsule (however many features
         or entries encode it).
      6. Exactly two differing display FEATURES with 4 entries at
         all four combinations -> CONTRAST_SET (feature-aligned 2x2).
      7. Base-and-variants pattern (1 base + N monofactor variants,
         each variant carrying exactly one ``+`` on the differing
         features) -> CONTRAST_SET with base spanning the left
         column and variants packed row-first on the right. Handles
         !Xoo-family cells whose 3-6 entries span several secondary
         phonation-family dimensions without fitting a 2x2.
      8. Otherwise -> contrast-AWARE STACK, base-first.
    """
    if len(entries) < 2:
        return VowelCellDisplayKind.STACK, (), entries, (), ()
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
        return VowelCellDisplayKind.STACK, (), entries, (), ()
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
        return kind, contrast, ordered, (), ()
    # Feature-aligned 2x2 first: a complete 4-entry set on exactly
    # two contrast features (e.g. plain / long / nasal / long+nasal)
    # reads best as a TABULAR 2x2 with axes named by feature, not
    # as a series of base + variants. Only fires when the 2x2 has no
    # slot collisions -- the aligned grid bins entries by ``+`` on
    # each of the two features, and two entries that differ only on
    # ``-`` vs ``0`` collide onto one slot.
    if len(differing_display) == 2 and 2 <= len(entries) <= 4:
        ordered, grid = _grid_layout(entries, bundles, contrast)
        if len(set(grid)) == len(entries):
            spans = tuple((1, 1) for _ in ordered)
            return VowelCellDisplayKind.CONTRAST_SET, contrast, ordered, grid, spans
        # Slot collision: fall through to base-and-variants or STACK.
    # Base-and-variants pattern: 1 base + N variants (each variant
    # carrying at least one contrast ``+``, mono- or multi-marked).
    # Fires for click-language cells whose 3-8 entries decorate one
    # base with several secondary features -- !Xoo /a/'s 5-6-way
    # phonation series, !Xu /a/'s length + nasal + rtr combinations,
    # etc. The renderer draws the base spanning the left column
    # top-to-bottom with variants packed row-first on the right.
    bav = _base_and_variants_layout(entries, bundles, differing_display)
    if bav is not None:
        ordered, grid, spans = bav
        return VowelCellDisplayKind.CONTRAST_SET, contrast, ordered, grid, spans
    ordered = _order_base_first(entries, bundles, contrast)
    return VowelCellDisplayKind.STACK, contrast, ordered, (), ()


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
        kind, contrast, ordered, grid, spans = classify_display_kind(
            tuple(entries), norm_cache
        )
        out[rc] = CellClassification(
            kind=kind,
            contrast_features=contrast,
            entries=ordered,
            grid=grid,
            spans=spans,
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
    """Feature-aligned 2x2 for a two-feature CONTRAST_SET.

    Columns bin by one contrast feature (``long`` if present, else
    the first), rows by the other. Cells with matching feature
    values collide onto one slot; the caller detects that collision
    (grid has fewer distinct tuples than entries) and falls through
    to a base-and-variants or STACK layout instead.

    The 2 / 3-entry base-centred case that this helper used to
    handle now lives in :py:func:`_base_and_variants_layout`.
    """
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


def _base_and_variants_layout(
    entries: tuple[str, ...],
    bundles: list[Mapping[str, str]],
    contrast_features: Collection[str],
) -> tuple[
    tuple[str, ...],
    tuple[tuple[int, int], ...],
    tuple[tuple[int, int], ...],
] | None:
    """Detect the 1-base + N-monofactor-variants pattern and lay it
    out as a 2-row grid: base on the LEFT spanning the whole capsule
    height, monofactor variants packed row-first into the columns on
    the right (``ceil(n_variants / 2)`` columns of two rows each). A
    3-entry cell becomes a 2-col x 2-row layout with the base at
    ``(0, 0)`` spanning both rows and the two variants stacked at
    ``(1, 0)`` and ``(1, 1)``; a 6-way !Xoo quality becomes a 4-col
    x 2-row layout, and so on.

    Requires:

    * ``len(entries) >= 3``.
    * Exactly one BASE entry (no ``+`` on any contrast feature).
    * At least 2 non-base entries. Non-base entries may carry ANY
      number of ``+`` marks -- a monofactor variant (``+nasal``)
      and a compound variant (``+nasal +rtr``) both fit; they still
      read as a series decorated on top of the same base. Rejecting
      compound variants left !Xun and !Xu stuck on STACK because
      their /a/ series carries ``ãˤ`` (+nasal +rtr) and similar
      compounds; accepting them lets those inventories pill too.

    Returns ``(ordered, grid, spans)`` on match, ``None`` otherwise:

    * ``ordered`` puts the base first, then the variants ordered by
      (fewest pluses first) then by the sorted contrast-feature
      value tuple, then by segment label.
    * ``grid`` places the base at ``(0, 0)`` and packs variants at
      ``(1..n_var_cols, 0)`` then ``(1..n_var_cols, 1)``.
    * ``spans`` gives the base ``(1, 2)`` so it fills the left
      column top-to-bottom; variants are ``(1, 1)`` each.

    Why 2 rows over 1: the horizontal single-row shape stayed one
    button-height tall but grew the row-width demand linearly with
    N variants, forcing the aspect-ratio cap to widen AND heighten
    the whole vowel space for click-language qualities. The 2-row
    shape keeps the pill's WIDTH bounded (``ceil(N/2)`` columns of
    canonical button-width) at the cost of a ``2 * SEG_BTN_H`` tall
    row -- only in rows that HOST such a cell. Rows without a wide
    pill stay canonical height, so a mixed !Xoo chart with wide
    pills in 3 rows and single vowels in the other 2 does not
    blow up horizontally OR uniformly vertically.
    """
    if len(entries) < 3:
        return None
    contrast_sorted = tuple(sorted(contrast_features))
    if not contrast_sorted:
        return None
    base_idx: int | None = None
    variant_idxs: list[int] = []
    for i, b in enumerate(bundles):
        pluses = [f for f in contrast_sorted if b.get(f) == "+"]
        if len(pluses) == 0:
            if base_idx is not None:
                return None  # more than one candidate base
            base_idx = i
        else:
            variant_idxs.append(i)
    if base_idx is None or len(variant_idxs) < 2:
        return None

    def _variant_sort_key(i: int) -> tuple[int, tuple[str, ...], str]:
        b = bundles[i]
        n_pluses = sum(1 for f in contrast_sorted if b.get(f) == "+")
        values = tuple(b.get(f, "0") for f in contrast_sorted)
        return n_pluses, values, entries[i]

    ordered_variants = sorted(variant_idxs, key=_variant_sort_key)
    ordered = (entries[base_idx],) + tuple(
        entries[i] for i in ordered_variants
    )
    n_variants = len(ordered_variants)
    n_var_rows = 2
    n_var_cols = (n_variants + n_var_rows - 1) // n_var_rows
    grid: list[tuple[int, int]] = [(0, 0)]
    spans: list[tuple[int, int]] = [(1, n_var_rows)]
    for k in range(n_variants):
        row = k // n_var_cols
        col = 1 + (k % n_var_cols)
        grid.append((col, row))
        spans.append((1, 1))
    return ordered, tuple(grid), tuple(spans)
