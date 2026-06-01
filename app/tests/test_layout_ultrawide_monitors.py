"""Ultrawide-monitor cap tests for ``layout.content_max_w`` and
``recommended_initial_window_size``.

On 3440 / 3840 / 5120 px monitors the segments pane would otherwise
absorb every extra pixel and the consonant grid would fan out to 25+
columns. The new ``content_max_w`` helper composes an absolute cap
(``CONTENT_MAX_W_ABS``) with a ratio cap (``CONTENT_MAX_W_RATIO``)
and feeds the first-launch window size and the web's ``.grid``
``max-width`` rule. These tests pin both axes.
"""

from __future__ import annotations

import pytest

from phonology_features.gui import layout


@pytest.mark.parametrize(
    "screen_w,expected_max",
    [
        # Normal monitors: the cap doesn't bite. The helper returns
        # the screen width itself (floored at the vowel-safe
        # MIN_FIRST_LAUNCH_W on tiny screens).
        (1280, 1280),
        (1920, 1920),
        (2400, 2400),
        # Ultrawide and larger: the absolute cap kicks in.
        (2401, layout.CONTENT_MAX_W_ABS),
        (3440, layout.CONTENT_MAX_W_ABS),
        (3840, layout.CONTENT_MAX_W_ABS),
        (5120, layout.CONTENT_MAX_W_ABS),
    ],
)
def test_content_max_w_caps_at_absolute_above_ceiling(
    screen_w: int, expected_max: int
) -> None:
    """``content_max_w`` returns ``min(CONTENT_MAX_W_ABS, screen_w)``
    floored at the first-launch minimum. Below ``CONTENT_MAX_W_ABS``
    the helper returns the screen width itself (the cap doesn't
    bite); at and above the ceiling the absolute cap wins.
    """
    assert layout.content_max_w(screen_w) == expected_max


def test_content_max_w_never_below_min_first_launch() -> None:
    """A tiny screen (e.g. a kiosk display) must not return a cap
    smaller than ``MIN_FIRST_LAUNCH_W``; that floor exists so the
    vowel chart can sit beside the consonants.
    """
    assert (
        layout.content_max_w(640) >= layout.MIN_FIRST_LAUNCH_W
    )
    assert (
        layout.content_max_w(100) >= layout.MIN_FIRST_LAUNCH_W
    )


@pytest.mark.parametrize(
    "screen_w,screen_h",
    [
        (3440, 1440),
        (3840, 1600),
        (3840, 2160),
        (5120, 1440),
        (5120, 2880),
    ],
)
def test_recommended_initial_window_capped_on_ultrawide(
    screen_w: int, screen_h: int
) -> None:
    """``recommended_initial_window_size`` previously returned 80%
    of the screen. On a 3840-px monitor that's 3072 px wide, past
    the useful content cap. After the ultrawide pass the width is
    additionally capped at ``content_max_w(screen_w)`` so a fresh
    launch on a 4K / 5K display lands at a sensible width. Height
    stays uncapped (vertical eye-travel is fine).
    """
    w, h = layout.recommended_initial_window_size(screen_w, screen_h)
    assert w <= layout.content_max_w(screen_w), (
        f"first-launch width {w} exceeds content cap"
        f" {layout.content_max_w(screen_w)} on {screen_w}x{screen_h}"
    )
    # Height should still be 80% (or the floor); not capped.
    expected_h = max(layout.MIN_FIRST_LAUNCH_H, int(screen_h * 0.80))
    assert h == expected_h


def test_recommended_initial_window_unchanged_on_normal_monitor() -> None:
    """On a 1920x1080 monitor the cap doesn't bite (1536 < 2400);
    the original 80% formula still applies. Same for 2560x1440
    (2048 < 2400). The cap only narrows the recommended window on
    truly ultrawide screens.
    """
    w, h = layout.recommended_initial_window_size(1920, 1080)
    assert w == int(1920 * layout.DEFAULT_SCREEN_FRACTION)
    assert h == max(layout.MIN_FIRST_LAUNCH_H, int(1080 * 0.80))

    w, h = layout.recommended_initial_window_size(2560, 1440)
    assert w == int(2560 * layout.DEFAULT_SCREEN_FRACTION)


def test_content_max_w_absolute_constant_sanity() -> None:
    """Guard against an accidental edit that makes the cap negative
    or smaller than the vowel-safe first-launch floor. The cap must
    be at least ``MIN_FIRST_LAUNCH_W`` so the helper never returns
    less than its floor.
    """
    assert layout.CONTENT_MAX_W_ABS >= layout.MIN_FIRST_LAUNCH_W
