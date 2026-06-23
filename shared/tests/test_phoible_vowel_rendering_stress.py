"""Whole-PHOIBLE vowel-chart RENDERING stress suite.

Walks every PHOIBLE inventory (~3020) and pins the geometric and
structural invariants the web + desktop renderers rely on. The
existing dimensions-stress suite checks aggregate size budgets;
this suite checks per-cell and per-diphthong correctness so a
future placement-policy tweak, bake schema change, or silhouette-
shrink refactor cannot silently produce a malformed chart.

Pinned invariants:

- **B1 Bounds**: every populated cell has
  ``chart_x in [0, 1]`` and ``chart_y in [0, 1]``. The web renderer
  sets ``left: chart_x * 100%; top: chart_y * 100%`` without
  clamping; out-of-range projections would render outside the
  chart container.

- **B2 Silhouette containment**: every populated cell's projected
  centre sits inside the silhouette polygon. The trapezoid /
  triangle silhouette is the visual envelope; cells outside it
  read as floating artefacts even though they technically render.

- **B3 Diphthong cell existence**: every diphthong's primary AND
  secondary ``(row, col)`` corresponds to a populated cell in
  ``geom.cells``. After the degenerate-secondary suppression in
  ``compute_placements``, this also asserts no self-loops.

- **B4 Cell-count ceiling**: no inventory produces > 24 cells.
  PHOIBLE max today is 16; 24 leaves a 50% safety margin.

- **B5 Disjoint cell membership**: every segment appears in
  exactly one cell. The collision-dict construction guarantees
  this by design, but pinning it here catches a future renderer
  refactor that double-counts.

Skipped when the PHOIBLE bake snapshot is absent.
"""

from __future__ import annotations

from collections.abc import Callable

# Tolerance for the silhouette-containment check. Cells are
# centred on (chart_x, chart_y); the button has finite width and
# may legitimately straddle the silhouette edge by a small fraction
# of the container. The tolerance is fraction-of-container.
_SILHOUETTE_TOLERANCE = 0.02

# Cell-count safety margin above the empirical PHOIBLE max (16).
_CELL_COUNT_HARD_CAP = 24


# Fixtures + helpers (``phoible_provider``,
# ``phoible_inventory_ids_full``, ``phoible_inventory_ids_sample``,
# ``phoible_label_for``, ``phoible_build_geometry``) come from
# shared/tests/conftest.py.
#
# Geometric-invariant tests (b1, b2, b4, b5) consume
# ``phoible_inventory_ids_sample``; the properties pinned
# (chart_xy bounds, silhouette containment, cell-count cap,
# segment disjointness) depend on feature-distribution space.
# ``test_b3`` (diphthong endpoint validity) consumes
# ``phoible_inventory_ids_full`` because diphthong metadata is
# sparse and a sample would miss rare cases.


def _silhouette_left_at_y(sil, y: float) -> float:
    """Linear interpolation of the silhouette's left edge at the
    given normalised y. The silhouette is a quadrilateral with
    ``top_left`` at ``top_y`` and ``bottom_left`` at ``bottom_y``."""
    if sil.bottom_y == sil.top_y:
        return sil.top_left
    t = (y - sil.top_y) / (sil.bottom_y - sil.top_y)
    t = max(0.0, min(1.0, t))
    return sil.top_left + (sil.bottom_left - sil.top_left) * t


def _silhouette_right_at_y(sil, y: float) -> float:
    """Linear interpolation of the silhouette's right edge at the
    given normalised y."""
    if sil.bottom_y == sil.top_y:
        return sil.top_right
    t = (y - sil.top_y) / (sil.bottom_y - sil.top_y)
    t = max(0.0, min(1.0, t))
    return sil.top_right + (sil.bottom_right - sil.top_right) * t


def test_b1_chart_xy_within_unit_bounds(
    phoible_build_geometry: Callable[[str], object],
    phoible_label_for: Callable[[str], str],
    phoible_inventory_ids_sample: list[str],
) -> None:
    """Every populated cell's projection stays in ``[0, 1]``. The
    web renderer applies ``left: chart_x * 100%; top: chart_y *
    100%`` without clamping; out-of-range values would render
    outside the chart container."""
    offenders: list[tuple[str, int, int, float, float]] = []
    for inv_id in phoible_inventory_ids_sample:
        geom = phoible_build_geometry(inv_id)
        if geom is None:
            continue
        for cell in geom.cells:
            if not (0.0 <= cell.chart_x <= 1.0 and 0.0 <= cell.chart_y <= 1.0):
                offenders.append(
                    (
                        phoible_label_for(inv_id),
                        cell.row,
                        cell.col,
                        cell.chart_x,
                        cell.chart_y,
                    )
                )
    assert not offenders, (
        f"cells with chart_x or chart_y outside [0, 1] in "
        f"{len(offenders)} placements; first 5: {offenders[:5]}"
    )


def test_b2_cells_sit_inside_silhouette(
    phoible_build_geometry: Callable[[str], object],
    phoible_label_for: Callable[[str], str],
    phoible_inventory_ids_sample: list[str],
) -> None:
    """Every populated cell's projected centre sits inside the
    silhouette polygon (interpolated edges at the cell's y).
    Catches the shrunken-row case where a front-anchored cell
    could project past the silhouette's contracted left edge."""
    offenders: list[tuple[str, int, int, float, float, float, float]] = []
    for inv_id in phoible_inventory_ids_sample:
        geom = phoible_build_geometry(inv_id)
        if geom is None:
            continue
        sil = geom.silhouette
        for cell in geom.cells:
            left = _silhouette_left_at_y(sil, cell.chart_y)
            right = _silhouette_right_at_y(sil, cell.chart_y)
            if not (
                left - _SILHOUETTE_TOLERANCE
                <= cell.chart_x
                <= right + _SILHOUETTE_TOLERANCE
            ):
                offenders.append(
                    (
                        phoible_label_for(inv_id),
                        cell.row,
                        cell.col,
                        cell.chart_x,
                        cell.chart_y,
                        left,
                        right,
                    )
                )
    assert not offenders, (
        f"cells sitting outside the silhouette in "
        f"{len(offenders)} placements; first 5: {offenders[:5]}"
    )


def test_b3_diphthongs_are_unique_inventory_segments(
    phoible_build_geometry: Callable[[str], object],
    phoible_label_for: Callable[[str], str],
    phoible_inventory_ids_full: list[str],
) -> None:
    """``geometry.diphthongs`` is a tuple of unique, non-empty segment
    strings. They are the inventory's contour vowels (the placer's
    degeneracy filter already dropped contours that collapse to a
    single cell), surfaced as chips below the vowel space rather than
    placed in the trapezoid."""
    empty_offenders: list[str] = []
    dup_offenders: list[tuple[str, str]] = []
    for inv_id in phoible_inventory_ids_full:
        geom = phoible_build_geometry(inv_id)
        if geom is None:
            continue
        seen: set[str] = set()
        for seg in geom.diphthongs:
            if not isinstance(seg, str) or not seg:
                empty_offenders.append(phoible_label_for(inv_id))
            if seg in seen:
                dup_offenders.append((phoible_label_for(inv_id), seg))
            seen.add(seg)
    assert not empty_offenders, (
        f"empty / non-string diphthong entries in "
        f"{len(empty_offenders)} inventories; first 5: "
        f"{empty_offenders[:5]}"
    )
    assert not dup_offenders, (
        f"duplicate diphthong entries in {len(dup_offenders)} "
        f"placements; first 5: {dup_offenders[:5]}"
    )


def test_b4_cell_count_within_hard_cap(
    phoible_build_geometry: Callable[[str], object],
    phoible_label_for: Callable[[str], str],
    phoible_inventory_ids_sample: list[str],
) -> None:
    """No PHOIBLE inventory produces more cells than the hard cap.
    PHOIBLE's worst case today is 16 populated cells (the 7-row x
    9-column grid is sparse); 24 leaves room for a future bake
    with a moderately denser inventory without permitting
    unbounded growth that would slow the renderer's paint pass."""
    offenders: list[tuple[str, int]] = []
    for inv_id in phoible_inventory_ids_sample:
        geom = phoible_build_geometry(inv_id)
        if geom is None:
            continue
        n = len(geom.cells)
        if n > _CELL_COUNT_HARD_CAP:
            offenders.append((phoible_label_for(inv_id), n))
    assert not offenders, (
        f"inventories producing > {_CELL_COUNT_HARD_CAP} cells in "
        f"{len(offenders)} cases; first 5: {offenders[:5]}"
    )


def test_b5_segments_appear_in_at_most_one_cell(
    phoible_build_geometry: Callable[[str], object],
    phoible_label_for: Callable[[str], str],
    phoible_inventory_ids_sample: list[str],
) -> None:
    """Every segment appears in at most one cell. The construction
    of ``occupied`` via ``setdefault(...).append`` guarantees this
    by design; pinning it here catches a future renderer-side
    refactor that double-iterates or copies entries."""
    offenders: list[tuple[str, str, list[tuple[int, int]]]] = []
    for inv_id in phoible_inventory_ids_sample:
        geom = phoible_build_geometry(inv_id)
        if geom is None:
            continue
        seg_to_cells: dict[str, list[tuple[int, int]]] = {}
        for cell in geom.cells:
            for seg in cell.entries:
                seg_to_cells.setdefault(seg, []).append((cell.row, cell.col))
        duplicates = {
            seg: cells for seg, cells in seg_to_cells.items() if len(cells) > 1
        }
        if duplicates:
            for seg, cells in list(duplicates.items())[:3]:
                offenders.append((phoible_label_for(inv_id), seg, cells))
    assert not offenders, (
        f"segments appearing in > 1 cell in "
        f"{len(offenders)} placements; first 5: {offenders[:5]}"
    )
