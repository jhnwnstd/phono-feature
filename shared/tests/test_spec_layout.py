"""The minimal-spec list lays out COLUMN-MAJOR into a table.

A long list of minimal specifications fills the analysis pane's height
first, then wraps into additional columns (so the pane uses its
horizontal space before scrolling). These pin the column-major cell
mapping, the row-count control, and the single-spec / trailing-cell
edge cases.
"""

from __future__ import annotations

import re

from phonology_shared.presentation.analysis import _render_spec_list
from phonology_shared.presentation.layout import ANALYSIS_MIN_VISIBLE_ROWS


def _specs(n: int) -> list[dict[str, str]]:
    # Distinct single-feature specs so none dedup away.
    return [{f"F{i}": "+"} for i in range(n)]


def _numbers(html: str) -> list[int]:
    return [int(m) for m in re.findall(r">(\d+)\.</span>", html)]


def _row_cell_counts(html: str) -> list[int]:
    return [row.count("<td") for row in html.split("<tr>")[1:]]


def test_multi_spec_is_a_column_major_table():
    html = _render_spec_list(_specs(10), rows_per_column=4)
    assert "<table" in html and "<br>" not in html
    # 10 specs, 4 rows -> 3 columns; item i sits at (row i%4, col i//4).
    # Emitted row-by-row: r0 -> items 0,4,8 (nums 1,5,9); r1 -> 1,5,9
    # (nums 2,6,10); r2 -> 2,6 (nums 3,7); r3 -> 3,7 (nums 4,8).
    assert _numbers(html) == [1, 5, 9, 2, 6, 10, 3, 7, 4, 8]
    assert html.count("<tr>") == 4


def test_rows_per_column_controls_column_count():
    max_cols = lambda h: max(_row_cell_counts(h))  # noqa: E731
    assert max_cols(_render_spec_list(_specs(12), rows_per_column=4)) == 3
    assert max_cols(_render_spec_list(_specs(12), rows_per_column=6)) == 2
    assert max_cols(_render_spec_list(_specs(12), rows_per_column=12)) == 1


def test_single_spec_stays_a_plain_line_not_a_table():
    html = _render_spec_list([{"Voice": "+"}])
    assert "<table" not in html
    assert "<p>" in html


def test_trailing_cells_are_omitted_no_phantom_empty_cells():
    # 5 specs, 4 rows -> 2 columns; column 2 holds only item 4 (idx 4).
    html = _render_spec_list(_specs(5), rows_per_column=4)
    # r0: idx 0,4 (2 cells); r1: idx 1 (idx 5 absent); r2: idx 2; r3: idx 3.
    assert _row_cell_counts(html) == [2, 1, 1, 1]
    # Every emitted cell carries a number (none are blank fillers).
    assert len(_numbers(html)) == 5


def test_zero_rows_per_column_is_clamped_to_one():
    html = _render_spec_list(_specs(3), rows_per_column=0)
    assert html.count("<tr>") == 3  # one item per row, single column


def test_default_rows_per_column_uses_the_shared_floor():
    html = _render_spec_list(_specs(ANALYSIS_MIN_VISIBLE_ROWS * 2))
    assert html.count("<tr>") == ANALYSIS_MIN_VISIBLE_ROWS
    assert max(_row_cell_counts(html)) == 2
