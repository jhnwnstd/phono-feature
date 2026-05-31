"""Tests for ``partition_groups_for_spillover`` in ``gui.layout``.

This is the single source of truth that both the desktop's
``SegmentGridWidget`` and the web's ``rebalanceSegmentSpillover`` call
to decide which manner-class groups stay in the main single-column
flow versus get rearranged into a 2-column spillover at the bottom of
the segments pane. Behavior parity across the two frontends depends
on this function's output being deterministic, so the tests below pin
the boundary cases.
"""

from __future__ import annotations

from phonology_features.gui.layout import partition_groups_for_spillover


def test_everything_fits_keeps_all_groups_in_main() -> None:
    # Three 100-tall groups in a 400-tall pane: ample headroom; no
    # group should be pushed into the spillover.
    assert (
        partition_groups_for_spillover([100, 100, 100], available_height=400)
        == 3
    )


def test_one_group_overflow_moves_the_last_to_spillover() -> None:
    # 4 × 100 = 400, available = 350 → bottom group goes to spillover.
    # main: 3 × 100 = 300; spillover: 1 group in a row of 2, row height
    # = max(100) = 100. Total = 400 — still over budget.
    # Drop another: main 2 × 100 = 200; spillover 2 in a row of 2,
    # row height = 100. Total = 300 ≤ 350. main_count = 2.
    assert partition_groups_for_spillover([100, 100, 100, 100], 350) == 2


def test_pair_packing_uses_row_max_height() -> None:
    # Uneven heights: the spillover-row height is the taller of the
    # pair, so a tall+short pair counts as the tall one's height.
    # [200, 50, 50] with available = 150: main 1 (h=200) + spillover
    # max(50, 50)=50 → 250 > 150; drop main to 0: spillover row =
    # max(200, 50)=200 + max(50)=50 → still over. Returns 0 — every
    # group went to spillover and it still wouldn't fit, but the
    # function is honest about the partition rather than expanding
    # available_height.
    assert partition_groups_for_spillover([200, 50, 50], 150) == 0


def test_three_column_spillover_packs_three_per_row() -> None:
    # 6 × 100 in a 250-tall pane with 3-col spillover: spillover
    # rows pack 3 groups each. main=0 → 2 rows of 3 × max(100)=100 →
    # 200 ≤ 250. Returns 0.
    assert (
        partition_groups_for_spillover(
            [100, 100, 100, 100, 100, 100],
            available_height=250,
            n_spillover_cols=3,
        )
        == 0
    )


def test_zero_available_height_skips_spillover() -> None:
    # First-paint / pre-resize case: no measured height yet. The
    # partition leaves every group in main rather than collapsing
    # everything into the spillover; the caller can re-run once it
    # has a real viewport height.
    assert (
        partition_groups_for_spillover([100, 100, 100], available_height=0)
        == 3
    )


def test_empty_input_returns_zero() -> None:
    assert partition_groups_for_spillover([], available_height=500) == 0
