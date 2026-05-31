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

from phonology_features.gui.constants import BTN_GAP, BTN_W
from phonology_features.gui.widgets import SegmentButton, SegmentGridWidget


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
    assert "GROUP0" in placed_text
    assert "GROUP1" in placed_text
    assert "GROUP2" in placed_text
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
            if hasattr(w, "text") and w.text().startswith("GROUP"):
                slot1_cols_found = True
                break
    assert slot1_cols_found, (
        "expected at least one GROUPx header in the spillover slot 1, "
        "but every header is at column 0"
    )
    scroll.deleteLater()
