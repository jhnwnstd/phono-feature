"""Sanity tests for the desktop ``SegmentGridWidget`` spillover path.

The decision (how many groups stay in main flow vs go to the 2-column
spillover) is exercised in ``test_segment_spillover.py`` against the
pure-Python ``partition_groups_for_spillover``. These tests pin the
*rendering* side: SegmentGridWidget actually positions the right
widgets in the right cells when the viewport is too short for the
single-column flow.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QScrollArea

from phonology_features.gui.widgets import SegmentButton, SegmentGridWidget
from phonology_shared.presentation.constants import BTN_GAP, BTN_W


def _make_groups(count: int, segs_per: int = 3) -> tuple[dict, dict]:
    groups: dict = {}
    buttons: dict = {}
    for i in range(count):
        manner = f"Group{i}"
        segs = [f"s{i}_{j}" for j in range(segs_per)]
        groups[manner] = segs
        for s in segs:
            buttons[s] = SegmentButton(s)
    return groups, buttons


def test_spillover_unused_when_viewport_fits(qapp) -> None:
    """Tall viewport → every group stays in the main single-column flow.
    Nothing should land in the spillover half-width slots."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    grid = SegmentGridWidget()
    grid.resize(BTN_W * 8 + BTN_GAP * 7, 1000)
    scroll.setWidget(grid)
    scroll.resize(grid.width(), 4000)
    groups, buttons = _make_groups(3)
    grid.set_groups(groups, buttons)
    grid._do_relayout()
    # No partition needed; all 3 headers and 9 buttons sit in the main
    # ``[0, n_cols)`` columns.
    items = [
        grid._grid.itemAtPosition(r, 0) for r in range(grid._grid.rowCount())
    ]
    placed = [i.widget() for i in items if i is not None]
    placed_text = [w.text() for w in placed if hasattr(w, "text") and w.text()]
    # Headers render title-case (no ``.upper()``) for a consistent label
    # voice across the app.
    assert "Group0" in placed_text
    assert "Group1" in placed_text
    assert "Group2" in placed_text
    scroll.deleteLater()


def test_spillover_engages_when_viewport_too_short(qapp) -> None:
    """Short viewport → bottom groups get pushed into the 2-col
    spillover rows. The header for the last group should appear in
    a half-width column starting past the ``slot_cols + 1`` gap col."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    grid = SegmentGridWidget()
    n_cols_target = 8
    grid.resize(BTN_W * n_cols_target + BTN_GAP * (n_cols_target - 1), 600)
    scroll.setWidget(grid)
    # Tight viewport: small enough that not all 6 groups fit single-column.
    scroll.resize(grid.width(), 220)
    groups, buttons = _make_groups(6, segs_per=4)
    grid.set_groups(groups, buttons)
    grid._do_relayout()
    # Spillover threshold landed somewhere; some groups should be in
    # the spillover slot 1 (col_start > 0) rather than the main flow.
    slot1_cols_found = False
    for r in range(grid._grid.rowCount()):
        for c in range(1, grid._grid.columnCount()):
            item = grid._grid.itemAtPosition(r, c)
            if item is None:
                continue
            w = item.widget()
            if w is None:
                continue
            if hasattr(w, "text") and w.text().startswith("Group"):
                slot1_cols_found = True
                break
    assert slot1_cols_found, (
        "expected at least one Groupx header in the spillover slot 1, "
        "but every header is at column 0"
    )
    scroll.deleteLater()


def test_row_minimums_reset_when_relayout_shrinks(qapp) -> None:
    """A taller layout's inter-group spacer minimums must not linger on
    rows a later, shorter layout leaves empty.

    ``QGridLayout.takeAt`` removes layout *items* but not the
    ``setRowMinimumHeight`` properties, and ``rowCount`` never shrinks.
    Without an explicit reset, swapping a tall group set for a short one
    leaves phantom vertical gaps below the real content. The widget
    zeroes the row minimums on every rebuild; this pins that.
    """
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    grid = SegmentGridWidget()
    grid.resize(BTN_W * 8 + BTN_GAP * 7, 1000)
    scroll.setWidget(grid)
    scroll.resize(grid.width(), 4000)
    # Tall layout: many single-column groups -> many spacer rows.
    big_groups, big_buttons = _make_groups(10)
    grid.set_groups(big_groups, big_buttons)
    grid._do_relayout()
    assert any(
        grid._grid.rowMinimumHeight(r) > 0
        for r in range(grid._grid.rowCount())
    ), "expected the tall layout to set inter-group spacer minimums"
    # Shorter layout: far fewer content rows.
    small_groups, small_buttons = _make_groups(2)
    grid.set_groups(small_groups, small_buttons)
    grid._do_relayout()
    small_max_content = max(
        (
            r
            for r in range(grid._grid.rowCount())
            if any(
                grid._grid.itemAtPosition(r, c) is not None
                for c in range(grid._grid.columnCount())
            )
        ),
        default=-1,
    )
    stale = [
        r
        for r in range(small_max_content + 1, grid._grid.rowCount())
        if grid._grid.rowMinimumHeight(r) > 0
    ]
    assert stale == [], f"stale row minimums on empty rows: {stale}"
    scroll.deleteLater()
