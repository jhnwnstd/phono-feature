"""Display-kind classifier for one cell's entries (layer 2a).

Coordinate-free decision layer: given the entries at a cell and their
normalised feature bundles, decide which
:py:class:`~phonology_shared.chart.vowels.VowelCellDisplayKind` the
cell renders as (STACK, one of the pair kinds, or CONTRAST_SET), pick
the display order for the entries, and lay out the CONTRAST_SET grid.
Nothing here knows about pixels, coordinates, or the outline.

The classifier's verdict rides a :py:class:`CellClassification` into
the sizing solver, the slot assigner, and the renderer. one verdict
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

#: The horizontal-capsule kinds. one cell that renders every entry
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

    :py:attr:`entries` is the layout-ordered tuple (base first for a
    stack, marked member last for a pair, capsule reading order for
    a CONTRAST_SET). :py:attr:`grid` gives each entry's
    ``(col, row)`` slot for a CONTRAST_SET, and :py:attr:`spans`
    gives each entry's ``(col_span, row_span)``; both are empty for
    non-CONTRAST_SET cells.
    """

    kind: VowelCellDisplayKind
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
    if not differing_display:
        # Nothing the pill can visually distinguish (all display
        # features agree). Even if entries diverge on non-display
        # features (tense, ATR, backness fine-tuning), a pill cannot
        # label that difference. STACK and let the segment glyphs
        # carry the identity.
        return VowelCellDisplayKind.STACK, (), entries, (), ()
    contrast = tuple(sorted(differing_display))
    dimensions = {
        _DIMENSION_KIND_FOR_FEATURE.get(feat, feat)
        for feat in differing_display
    }
    # Single-dimension path (PAIR display kind): every variant marks
    # the same secondary dimension (three phonation variants /a/,
    # /a̤/, /a̰/ read as ONE phonation series). Blocks on
    # ``differing_other`` because a single-dim pair has NO base
    # anchor: every entry is an equal member and a stray tense /
    # ATR / position difference between them means the "pair" would
    # misrepresent the relationship.
    if not differing_other and len(dimensions) == 1:
        (dimension,) = dimensions
        kind = (
            dimension
            if isinstance(dimension, VowelCellDisplayKind)
            else VowelCellDisplayKind.CONTRAST_SET
        )
        ordered = _order_variant_row(entries, bundles, differing_display, kind)
        return kind, contrast, ordered, (), ()
    # Feature-aligned 2x2: complete 4-entry sets on exactly two
    # contrast features (plain / long / nasal / long+nasal). Same
    # ``differing_other`` block as the single-dim path. an aligned
    # 2x2 also has no base to anchor a tense / position outlier
    # against. Partial 3-entry sets fall through to the base-and-
    # variants branch below (which produces the base-spans-left
    # layout).
    if (
        not differing_other
        and len(entries) == 4
        and len(differing_display) == 2
    ):
        ordered, grid = _grid_layout(entries, bundles, contrast)
        if len(set(grid)) == 4:
            spans = tuple((1, 1) for _ in ordered)
            return VowelCellDisplayKind.CONTRAST_SET, contrast, ordered, grid, spans
    # Base-and-variants: a cell with a clear base anchor (one entry
    # with 0 pluses on every contrast feature) plus 2+ variants.
    # Bypasses the ``differing_other`` block because the base
    # defines the "canonical" non-display features and each variant
    # reads as a decorated form of that base. a stray tense / ATR
    # mismatch on one variant does not break the grouping (a !Xu
    # /o̞/ cell tolerates the outlier ``ɔ̃ˤː`` this way and pills
    # all 7 entries together). The renderer draws:
    #
    # * 2-variant cells as a 2x2 with the BASE spanning the LEFT
    #   column (``[BASE][v1]`` / ``[BASE][v2]``).
    # * 3+-variant cells as a base-centred radial (base at (1,1) in
    #   a 3x3, variants surround; left/right cardinals span into
    #   empty corners so no dead space is left inside the frame).
    bav = _base_and_variants_layout(entries, bundles, differing_display)
    if bav is not None:
        ordered, grid, spans = bav
        return VowelCellDisplayKind.CONTRAST_SET, contrast, ordered, grid, spans
    if differing_other:
        # Reached the fallback with a position / tense / ATR
        # difference AND no base-and-variants pattern: name no
        # contrast dimension. The stack advertises no secondary
        # feature because the primary POSITION disagreement is
        # what actually separates the entries.
        return VowelCellDisplayKind.STACK, (), entries, (), ()
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
        kind, _contrast, ordered, grid, spans = classify_display_kind(
            tuple(entries), norm_cache
        )
        out[rc] = CellClassification(
            kind=kind,
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
    the first), rows by the other. When entries collide onto one
    slot the caller detects the mismatch (distinct positions <
    entry count) and falls through to base-and-variants or STACK.
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


#: Fill order for variants surrounding a base at ``(1, 1)``: cardinals
#: first (top, left, right, bottom) then corners (tl, tr, bl, br).
#: Cardinals are visually closer to the base; corners fill only when
#: variant count exceeds four. The left/right cardinals GROW their
#: :py:data:`spans` upward and downward to absorb dead corners in the
#: grid rows that have no explicit corner variant. see the layout
#: docstring below for the span rule.
_BASE_CENTERED_ROLES: tuple[str, ...] = (
    "top",
    "left",
    "right",
    "bottom",
    "tl",
    "tr",
    "bl",
    "br",
)

#: 3x3 grid positions per role, keyed by :py:data:`_BASE_CENTERED_ROLES`.
_BASE_CENTERED_ROLE_POS: dict[str, tuple[int, int]] = {
    "top": (1, 0),
    "left": (0, 1),
    "right": (2, 1),
    "bottom": (1, 2),
    "tl": (0, 0),
    "tr": (2, 0),
    "bl": (0, 2),
    "br": (2, 2),
}

#: Cap on variants a single base-centered pill can hold. A 3x3 grid
#: has 8 non-centre positions; a cell with 9+ variants falls back to
#: STACK with density tiering.
_BASE_CENTERED_MAX_VARIANTS: int = 8


def _base_and_variants_layout(
    entries: tuple[str, ...],
    bundles: list[Mapping[str, str]],
    contrast_features: Collection[str],
) -> tuple[
    tuple[str, ...],
    tuple[tuple[int, int], ...],
    tuple[tuple[int, int], ...],
] | None:
    """Group a cell of 1 base + 2-8 variants into a compact capsule.

    Two shapes come through:

    * **2 variants** (3 entries): 2x2 with base at ``(0, 0)`` spanning
      the left column top-to-bottom; the two variants stack at
      ``(1, 0)`` and ``(1, 1)``.
    * **3-8 variants** (4-9 entries): 3x3 with base at ``(1, 1)`` and
      variants filling cardinal positions first (top, left, right,
      bottom) then corners in reading order. The left and right
      cardinals grow their ``row_span`` upward and downward into
      empty corner slots so every grid cell is covered.

    Requires exactly one BASE (no ``+`` on any contrast feature) and
    2-8 non-base variants; anything else returns ``None`` (the
    caller then falls back to STACK). Variants are sorted by fewest
    pluses first, then by dimension group size descending (so a
    phonation trio clusters into adjacent cardinal slots), then by
    feature tuple, then by segment label.
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
    if len(variant_idxs) > _BASE_CENTERED_MAX_VARIANTS:
        # 3x3 ring capacity exceeded. Fall through to STACK; the
        # density tier keeps it compact and the contrast features
        # ride the STACK's ``contrast_features`` field.
        return None

    def _dims_of(i: int) -> tuple[str, ...]:
        b = bundles[i]
        marked = [f for f in contrast_sorted if b.get(f) == "+"]
        return tuple(
            sorted(str(_DIMENSION_KIND_FOR_FEATURE.get(f, f)) for f in marked)
        )

    # Group size per (dims tuple) across all variants: variants
    # that share a dimension (creaky / breathy / epilaryngeal all
    # phonation) form a group. Larger groups sort FIRST so they take
    # the cardinal fill positions (top / left / right / bottom) and
    # cluster edge-adjacent around the base. a phonation trio ends
    # up as a T-cluster around the base rather than scattered across
    # cardinals + corners.
    group_sizes: dict[tuple[str, ...], int] = {}
    for i in variant_idxs:
        d = _dims_of(i)
        group_sizes[d] = group_sizes.get(d, 0) + 1

    def _variant_sort_key(
        i: int,
    ) -> tuple[int, int, tuple[str, ...], tuple[str, ...], str]:
        b = bundles[i]
        marked = tuple(f for f in contrast_sorted if b.get(f) == "+")
        n_pluses = len(marked)
        dims = _dims_of(i)
        # ``-group_size`` puts the largest group first; ``dims``
        # keeps deterministic ordering across ties; ``marked`` and
        # the segment label break within-group ties.
        return n_pluses, -group_sizes[dims], dims, marked, entries[i]

    ordered_variants = sorted(variant_idxs, key=_variant_sort_key)
    ordered = (entries[base_idx],) + tuple(
        entries[i] for i in ordered_variants
    )
    n_variants = len(ordered_variants)

    if n_variants == 2:
        # 2x2 with the BASE spanning the LEFT column top-to-bottom
        # (rows 0-1) and the two variants STACKED on the right at
        # ``(1, 0)`` and ``(1, 1)``. The base's glyph centres
        # naturally in its 2-row-tall cell, so the layout reads as
        # ``[BASE  ][v1]`` / ``[BASE  ][v2]`` -- variant-on-the-right
        # is the pair convention, and letting the base span both
        # rows keeps the pill compact (2 x 2 = 66 x 52 px) rather
        # than pushing the variants into a wide horizontal triple.
        grid: tuple[tuple[int, int], ...] = ((0, 0), (1, 0), (1, 1))
        spans = ((1, 2), (1, 1), (1, 1))
        return ordered, grid, spans

    present_roles: set[str] = {
        _BASE_CENTERED_ROLES[k] for k in range(n_variants)
    }
    # Always use a 3-row grid so the base at (1, 1) sits at the true
    # geometric centre. When there is no bottom variant (N == 3) the
    # base extends down into (1, 2) so the centre column reads as one
    # continuous base cell instead of leaving a dead centre-bottom.
    base_row_span = 1 if "bottom" in present_roles else 2

    def _cardinal_span(
        col: int, top_corner: str, bot_corner: str
    ) -> tuple[tuple[int, int], tuple[int, int]]:
        start = 0 if top_corner not in present_roles else 1
        end = 3 if bot_corner not in present_roles else 2
        return (col, start), (1, end - start)

    grid_list: list[tuple[int, int]] = [(1, 1)]
    spans_list: list[tuple[int, int]] = [(1, base_row_span)]
    for k in range(n_variants):
        role = _BASE_CENTERED_ROLES[k]
        if role == "left":
            pos, sp = _cardinal_span(0, "tl", "bl")
        elif role == "right":
            pos, sp = _cardinal_span(2, "tr", "br")
        else:
            pos, sp = _BASE_CENTERED_ROLE_POS[role], (1, 1)
        grid_list.append(pos)
        spans_list.append(sp)
    return ordered, tuple(grid_list), tuple(spans_list)
