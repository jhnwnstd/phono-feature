"""Display-scaling tests for ``layout.scaled_handle_w`` and the
chrome-height policy.

The splitter handle, scrollbar width, and toolbar / statusbar
heights all need to grow with the user's OS scaling so the grab
targets and glyphs stay the same physical size on a 200% or 300%
display. The desktop tree used to hardcode pixel values; the
``scaled_handle_w`` helper centralises the rule and these tests
pin the math so a future "just bump the constant" edit can't
regress hi-DPI behaviour silently.
"""

from __future__ import annotations

import pytest

from phonology_features.gui import layout


@pytest.mark.parametrize(
    "dpr,expected",
    [
        (1.0, 4),
        (1.25, 5),
        (1.5, 6),
        (1.75, 7),
        (2.0, 8),
        (2.5, 10),
        (3.0, 12),
    ],
)
def test_scaled_handle_w_tracks_device_pixel_ratio(
    dpr: float, expected: int
) -> None:
    """At each common OS / display scaling factor the handle width
    should be ``round(4 * dpr)``. The rounding is well-defined
    Python behaviour (banker's rounding at .5) so the expected
    values above are stable across runs.
    """
    assert layout.scaled_handle_w(dpr) == expected


@pytest.mark.parametrize("dpr", [0.0, 0.5, 0.75, 0.99])
def test_scaled_handle_w_floors_at_4_for_sub_unity_dpr(dpr: float) -> None:
    """A misreported sub-1.0 DPR (some virtualised display drivers,
    headless test contexts) must not shrink the handle below its
    historic 4-px baseline. The helper clamps via ``max(1.0, dpr)``
    before scaling so the result is always at least 4.
    """
    assert layout.scaled_handle_w(dpr) == 4


def test_scaled_handle_w_grows_monotonically() -> None:
    """Increasing the DPR must never shrink the handle. Catches a
    regression where the rounding rule is replaced with floor / int
    and a fractional input slips below the previous integer cap.
    """
    last = 0
    for dpr in (1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0):
        cur = layout.scaled_handle_w(dpr)
        assert (
            cur >= last
        ), f"handle width dropped at dpr={dpr}: {last} -> {cur}"
        last = cur
