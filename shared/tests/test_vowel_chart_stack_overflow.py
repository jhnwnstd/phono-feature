"""Phase 4: render-side stack-overflow safety.

Pins the geometry contract that lets the renderer keep tall stacks
inside the trapezoid silhouette even when the rendered data area
is shorter than ``natural_data_height_px``:

- Every :py:class:`VowelChartRow` carries ``slot_height_norm``: the
  row's normalised allocation of the silhouette's vertical span.
- Slot heights sum to ``silhouette.bottom_y - silhouette.top_y``
  (the trapezoid's full vertical span).
- Each row's slot is proportional to its max stack depth, so a row
  containing a 7-entry stack gets 7x the height of a row with a
  1-entry stack.
- Renderers multiply ``slot_height_norm`` by the actual rendered
  data-area pixel height to derive the row's pixel budget and pick
  a per-button height that fits the stack inside.

The synthetic inventory below puts 7 vowels into a single
middle-row cell (the canonical Korean-Acehnese-!Xun overflow case).
Pre-fix, the geometry did not expose ``slot_height_norm``, so the
renderer had no information about how much vertical space the row
was allocated and rendered the stack at canonical button height
regardless of available space. Post-fix, the renderer reads the
field and shrinks the per-button height when the slot is tight.
"""

from __future__ import annotations

from phonology_shared.chart.vowels import (
    PlacementPolicy,
    VowelProfile,
    detect_vowel_profile,
)
from phonology_shared.chart.vowels_layout import (
    build_vowel_chart_geometry,
)


def _tall_middle_stack_inventory() -> (
    tuple[list[str], dict[str, dict[str, str]]]
):
    """Build a synthetic 14-vowel inventory where 7 vowels share the
    same middle-row cell (Close-mid Back rounded). The remaining 7
    distribute one per non-Close-mid-Back cell so the chart has
    several populated rows and the middle-row collision is the
    deepest cell.
    """
    # Close-mid Back rounded vowels: all same features except a
    # distinguishing in-cell-contrast feature (long, nasal, ...).
    # Use distinct segment strings so they don't dedupe.
    stack_feats = {
        "high": "-",
        "low": "-",
        "front": "-",
        "back": "+",
        "round": "+",
        "tense": "+",
    }
    in_cell_contrasts = [
        ("o", {}),
        ("oː", {"long": "+"}),
        ("õ", {"nasal": "+"}),
        ("oˀ", {"creaky": "+"}),
        ("o̤", {"breathy": "+"}),
        ("ó", {"hightone": "+"}),
        ("oʰ", {"stress": "+"}),
    ]
    seg_feats: dict[str, dict[str, str]] = {}
    for seg, extra in in_cell_contrasts:
        seg_feats[seg] = {**stack_feats, **extra}

    # Spreader vowels: one per (row, col) so the chart has multiple
    # populated rows and the stack sits in a clear MIDDLE row.
    seg_feats["i"] = {
        "high": "+",
        "low": "-",
        "front": "+",
        "back": "-",
        "round": "-",
        "tense": "+",
    }
    seg_feats["u"] = {
        "high": "+",
        "low": "-",
        "front": "-",
        "back": "+",
        "round": "+",
        "tense": "+",
    }
    seg_feats["e"] = {
        "high": "-",
        "low": "-",
        "front": "+",
        "back": "-",
        "round": "-",
        "tense": "+",
    }
    seg_feats["a"] = {
        "high": "-",
        "low": "+",
        "front": "-",
        "back": "-",
        "round": "-",
    }
    seg_feats["æ"] = {
        "high": "-",
        "low": "+",
        "front": "+",
        "back": "-",
        "round": "-",
    }
    seg_feats["ɛ"] = {
        "high": "-",
        "low": "-",
        "front": "+",
        "back": "-",
        "round": "-",
        "tense": "-",
    }
    seg_feats["ɔ"] = {
        "high": "-",
        "low": "-",
        "front": "-",
        "back": "+",
        "round": "+",
        "tense": "-",
    }
    return list(seg_feats), seg_feats


def _profile_for(seg_feats) -> VowelProfile:
    """Profile that turns the contrast flags on so the divergence
    detector doesn't spuriously fire. Mirrors
    :py:func:`detect_vowel_profile` but lets us inject the synthetic
    bundle deterministically."""
    return detect_vowel_profile(list(seg_feats), seg_feats)


def test_geometry_emits_slot_height_norm_per_row() -> None:
    """Each row carries ``slot_height_norm`` >= 0; the sum equals
    the silhouette's vertical span. This is the new contract that
    lets renderers size rows proportionally to their stack depth
    without re-deriving from the cells."""
    vowels, seg_feats = _tall_middle_stack_inventory()
    profile = _profile_for(seg_feats)
    geom = build_vowel_chart_geometry(
        vowels, profile, seg_feats, policy=PlacementPolicy()
    )
    total = sum(row.slot_height_norm for row in geom.rows)
    span = geom.silhouette.bottom_y - geom.silhouette.top_y
    assert abs(total - span) < 1e-6, (
        f"slot_height_norm sums to {total}, expected silhouette "
        f"span {span}"
    )
    for row in geom.rows:
        assert row.slot_height_norm > 0, (
            f"row {row.label} has zero slot height; the stack would "
            f"render at zero pixels regardless of container size"
        )


def test_deeper_row_gets_proportionally_larger_slot() -> None:
    """A row holding a 7-entry stack must receive 7x the slot
    height of a row holding a 1-entry stack. Pins the proportional
    allocation so a renderer derived per-button height from
    ``slot_height_norm × container_px / stack_depth`` will produce
    the same per-button size in both rows: the row's slot is sized
    to make the stack render at canonical button height when the
    chart is at its natural pixel height.
    """
    vowels, seg_feats = _tall_middle_stack_inventory()
    profile = _profile_for(seg_feats)
    geom = build_vowel_chart_geometry(
        vowels, profile, seg_feats, policy=PlacementPolicy()
    )
    # Identify the row with the 7-stack (Close-mid Back).
    rows_by_logical = {row.logical_row: row for row in geom.rows}
    cells_by_row: dict[int, list] = {}
    for cell in geom.cells:
        cells_by_row.setdefault(cell.row, []).append(cell)
    deepest_row_idx = max(
        cells_by_row,
        key=lambda r: max(len(c.entries) for c in cells_by_row[r]),
    )
    deepest_depth = max(len(c.entries) for c in cells_by_row[deepest_row_idx])
    assert deepest_depth == 7, (
        f"expected the synthetic to produce a 7-deep cell; got "
        f"{deepest_depth}. Adjust the test fixture if cell "
        f"classification or feature rules have shifted."
    )
    deepest_slot = rows_by_logical[deepest_row_idx].slot_height_norm
    # A shallowest row (any with depth 1).
    shallow_candidates = [
        r
        for r in cells_by_row
        if max(len(c.entries) for c in cells_by_row[r]) == 1
    ]
    assert shallow_candidates, "synthetic should produce 1-deep rows"
    shallow_slot = rows_by_logical[shallow_candidates[0]].slot_height_norm
    ratio = deepest_slot / shallow_slot
    assert 6.5 < ratio < 7.5, (
        f"deepest row slot / shallowest row slot = {ratio:.2f}; "
        f"expected ~7.0 (proportional to depth ratio)"
    )


def test_neutral_col_does_not_collide_with_pair_col_at_same_anchor() -> None:
    """When a neutral col (6/7/8) and a paired col (0/1, 2/3, 4/5)
    are both populated at the same backness anchor in the same row,
    they MUST land at distinct rendered positions. Pre-fix, Korean
    PHOIBLE / SPA / UPSID had segments at col 5 (back-rnd) and col 8
    (back-neu) BOTH at chart_x=0.853 with overlapping pair-shift
    offsets; buttons rendered fully on top of each other.

    The geometry's pair-side discipline must guarantee that any two
    cells sharing the same backness anchor land at distinct
    rendered pair-side positions: -1 (anchor-shift), 0 (anchor),
    +1 (anchor+shift). With three slots per anchor (low-pair,
    neutral, high-pair) and at most two of them paired, no two
    populated cells should ever end up at the same pair-side.
    """
    from phonology_shared.chart.vowels_layout import (
        build_vowel_chart_geometry,
    )

    # Synthetic inventory with both col 1 (front-rounded) and col 6
    # (front-neutral) populated at Close row: exact shape of the
    # Korean/PHOIBLE row=0 collision.
    seg_feats = {
        "y": {  # front rounded -> col 1, ps=+1
            "high": "+",
            "low": "-",
            "front": "+",
            "back": "-",
            "round": "+",
        },
        "ia": {  # front "neutral" (round=0) -> col 6, ps=0
            "high": "+",
            "low": "-",
            "front": "+",
            "back": "-",
        },
        "u": {  # back rounded -> spreader, no overlap
            "high": "+",
            "low": "-",
            "front": "-",
            "back": "+",
            "round": "+",
        },
        "a": {  # bottom -> spreader
            "high": "-",
            "low": "+",
            "front": "-",
            "back": "-",
            "round": "-",
        },
    }
    vowels = list(seg_feats)
    profile = detect_vowel_profile(vowels, seg_feats)
    geom = build_vowel_chart_geometry(
        vowels, profile, seg_feats, policy=PlacementPolicy()
    )
    # Find the two close-front cells
    from phonology_shared.presentation.constants import BTN_W
    from phonology_shared.presentation.layout import VOWEL_PAIR_GAP_PX

    pair_shift_px = (BTN_W + VOWEL_PAIR_GAP_PX) // 2

    close_front_cells = [
        c for c in geom.cells if c.row == 0 and c.col in (0, 1, 6)
    ]
    assert len(close_front_cells) == 2, (
        f"expected col 1 and col 6 in Close row; got "
        f"{[(c.col, c.entries) for c in close_front_cells]}"
    )

    def _cx_px(cell):
        return (
            cell.chart_x * geom.natural_data_width_px
            + cell.pair_side * pair_shift_px
        )

    rendered_positions = sorted(_cx_px(c) for c in close_front_cells)
    gap_px = rendered_positions[1] - rendered_positions[0]
    # Cells need at least one button-width of space between
    # rendered centres so the buttons don't visually overlap.
    assert gap_px >= BTN_W, (
        f"col 1 and col 6 rendered {gap_px:.1f} px apart but the "
        f"button width is {BTN_W} px; buttons overlap by "
        f"{BTN_W - gap_px:.1f} px. Pre-fix Korean PHOIBLE renders "
        f"the 6-deep neutral stack at chart_x and the 2-deep pair "
        f"stack at chart_x + {pair_shift_px} px, but {pair_shift_px} "
        f"is less than BTN_W. Fix: when neutral col shares anchor "
        f"with a paired col, the neutral cell should land at the "
        f"empty pair-side instead of at the anchor centre."
    )


def test_renderer_can_derive_button_height_from_slot() -> None:
    """End-to-end policy check: at any rendered data-area pixel
    height H, the renderer can compute a per-button height that
    keeps the stack inside its slot. The formula:

        slot_px = row.slot_height_norm * H
        per_button_px = (slot_px - (N - 1) * gap_px) / N

    must yield a positive value (or a clamped minimum) for any
    sensible H. This is the contract Phase 4's renderer wiring
    relies on.
    """
    vowels, seg_feats = _tall_middle_stack_inventory()
    profile = _profile_for(seg_feats)
    geom = build_vowel_chart_geometry(
        vowels, profile, seg_feats, policy=PlacementPolicy()
    )
    rows_by_logical = {row.logical_row: row for row in geom.rows}
    deepest_row_idx = max(
        rows_by_logical,
        key=lambda r: max(len(c.entries) for c in geom.cells if c.row == r),
    )
    row = rows_by_logical[deepest_row_idx]
    deepest_cell = max(
        (c for c in geom.cells if c.row == deepest_row_idx),
        key=lambda c: len(c.entries),
    )
    n = len(deepest_cell.entries)
    gap_px = 1
    # A pessimistic container: the chart is rendered at HALF its
    # natural height (a constrained pane / narrow viewport).
    container_h = geom.natural_data_height_px // 2
    slot_px = row.slot_height_norm * container_h
    per_button_px = (slot_px - (n - 1) * gap_px) / n
    # The renderer must clamp; for this test we just confirm the
    # formula yields a positive number.
    assert per_button_px > 0, (
        f"derived per-button height is {per_button_px:.1f} px for "
        f"a {n}-deep stack at container {container_h}px"
    )
    # And at the canonical natural height, the per-button height
    # matches the row's density-tier rendered height. For a 7-stack
    # the row activates the "dense" tier (22 px). Calling
    # ``effective_button_height_px`` from the geometry module
    # exposes the same ladder both renderers follow, so the formula
    # below comes out close to ``effective_h`` rather than the
    # canonical 26 px.
    from phonology_shared.chart.vowels_layout import (
        effective_button_height_px,
    )

    effective_h = effective_button_height_px(n)
    canonical_slot_px = row.slot_height_norm * geom.natural_data_height_px
    canonical_per_button = (canonical_slot_px - (n - 1) * gap_px) / n
    assert effective_h - 2 <= canonical_per_button <= effective_h + 2, (
        f"canonical per-button height = {canonical_per_button:.1f} "
        f"(expected ~{effective_h} px for a {n}-stack); the row's "
        f"slot allocation drifted from the rendered button-height "
        f"contract"
    )
