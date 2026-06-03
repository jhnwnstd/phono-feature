"""Validation-report HTML escapes user-supplied issue text.

``render_validation_report`` interpolates raw issue strings; if
one of them quotes back inventory data containing tag characters
the helper must not let it break out of the ``<p>``. Both UIs
consume the same renderer, so this gate lives in shared/.
"""

from __future__ import annotations

from phonology_shared.render.analysis import render_validation_report


def test_render_validation_report_escapes_issue_text() -> None:
    issues = (
        "segment '<script>': bad",
        "feature '\"oops\"': bad",
    )
    out = render_validation_report(issues)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
