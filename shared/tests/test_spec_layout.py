"""The minimal-spec list lays out COLUMN-MAJOR into a table.

A long list of minimal specifications fills the analysis pane's height
first, then wraps into additional columns (so the pane uses its
horizontal space before scrolling). Each column is one table cell, so
the numbering also survives a copy: selecting and copying yields the
specs in column order (1, 2, 3 ... down each column then the next),
not the row-by-row jumble a grid of one-spec cells would give.
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


def _column_count(html: str) -> int:
    return html.count("<td")


def test_multi_spec_is_a_column_cell_table():
    html = _render_spec_list(_specs(10), rows_per_column=4)
    assert "<table" in html and "<br>" in html
    # One <tr>; one <td> per column so a copy walks cell-by-cell.
    assert html.count("<tr>") == 1
    assert _column_count(html) == 3  # ceil(10 / 4)


def test_html_and_copy_order_is_sequential_by_column():
    # The whole point: specs appear in the source (hence clipboard)
    # in numbering order 1..N, filling each column top-to-bottom.
    html = _render_spec_list(_specs(10), rows_per_column=4)
    assert _numbers(html) == list(range(1, 11))


def test_rows_per_column_controls_column_count():
    assert _column_count(_render_spec_list(_specs(12), rows_per_column=4)) == 3
    assert _column_count(_render_spec_list(_specs(12), rows_per_column=6)) == 2
    assert (
        _column_count(_render_spec_list(_specs(12), rows_per_column=12)) == 1
    )


def test_single_spec_stays_a_plain_line_not_a_table():
    html = _render_spec_list([{"Voice": "+"}])
    assert "<table" not in html
    assert "<p>" in html


def test_last_column_holds_the_remainder_no_phantom_specs():
    # 5 specs, 4 rows -> 2 columns; the 2nd column holds only spec 5.
    html = _render_spec_list(_specs(5), rows_per_column=4)
    assert _column_count(html) == 2
    # 4 specs in column 0, 1 in column 1; 5 numbers total, in order.
    assert _numbers(html) == [1, 2, 3, 4, 5]
    cols = re.findall(r"<td[^>]*>(.*?)</td>", html, re.DOTALL)
    # Count the numbered specs per column via the dim number span.
    per_col = [len(re.findall(r">\d+\.</span>", c)) for c in cols]
    assert per_col == [4, 1]


def test_one_row_per_column_gives_one_spec_per_column():
    html = _render_spec_list(_specs(3), rows_per_column=1)
    assert _column_count(html) == 3
    assert _numbers(html) == [1, 2, 3]


def test_non_positive_rows_per_column_falls_back_to_default():
    # 0 / None are treated as "unmeasured": use the shared floor.
    for r in (0, None):
        html = _render_spec_list(
            _specs(ANALYSIS_MIN_VISIBLE_ROWS + 1), rows_per_column=r
        )
        assert _column_count(html) == 2  # N = floor + 1 -> 2 columns


def test_default_rows_per_column_uses_the_shared_floor():
    html = _render_spec_list(_specs(ANALYSIS_MIN_VISIBLE_ROWS * 2))
    assert _column_count(html) == 2
