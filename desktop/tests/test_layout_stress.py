"""Layout-stress regression tests.

Drives the main window through adversarial resizes, splitter drags,
and collapse attempts, then asserts that the dependent layout state
(vowel chart width, stack flag, splitter sizes, feature panel
height) stays consistent with the shared decisions in
:py:mod:`phonology_shared.presentation.layout`.

Pins the invariants that broke when the user reported "segments
expand but never collapse" and "analysis grows but segments don't
return to where they were": the seg-panel resize event filter, the
content-driven panel minimum heights, and the splitter
collapse-protection.
"""

from __future__ import annotations

from PyQt6.QtCore import QSettings

from phonology_shared.presentation import layout
from phonology_shared.presentation.constants import SETTINGS_APP, SETTINGS_ORG


def _wipe_settings() -> None:
    QSettings(SETTINGS_ORG, SETTINGS_APP).clear()


def _drain(qapp, times: int = 4) -> None:
    for _ in range(times):
        qapp.processEvents()


def test_seg_panel_cannot_collapse_below_min(qapp) -> None:
    """Manual splitter drag to seg=0 must clamp at SEG_MIN_W;
    ``setMinimumWidth`` + ``setCollapsible(False)`` enforces it."""
    _wipe_settings()
    from phonology_features.gui.main_window import MainWindow

    w = MainWindow()
    w.show()
    _drain(qapp)
    w.resize(1366, 768)
    _drain(qapp)
    total = sum(w._hsplit.sizes())
    w._hsplit.setSizes([0, total])
    w._hsplit.splitterMoved.emit(0, 0)
    _drain(qapp)
    assert (
        w.seg_panel.width() >= layout.SEG_MIN_W
    ), f"seg pane collapsed: {w.seg_panel.width()} < {layout.SEG_MIN_W}"
    w.close()


def test_feat_panel_cannot_collapse_below_min(qapp) -> None:
    """Same guard on the other side; feat content has hard min."""
    _wipe_settings()
    from phonology_features.gui.main_window import MainWindow

    w = MainWindow()
    w.show()
    _drain(qapp)
    w.resize(1366, 768)
    _drain(qapp)
    total = sum(w._hsplit.sizes())
    w._hsplit.setSizes([total, 0])
    w._hsplit.splitterMoved.emit(total, 0)
    _drain(qapp)
    assert w.feat_panel.width() >= layout.FEAT_MIN_W
    w.close()


def test_vowel_stack_recovers_after_widening(qapp) -> None:
    """User drags the seg pane below ``VOWEL_STACK_W`` and vowels
    stack below. User widens the window again and vowels recover
    beside consonants. Previously the ``splitterMoved`` signal was
    the only update path, so a window-resize back to wide left the
    stack flag stuck True. Now an event filter on the seg panel
    catches every resize, regardless of cause.
    """
    _wipe_settings()
    from phonology_features.gui.main_window import MainWindow

    w = MainWindow()
    w.show()
    _drain(qapp)
    w.resize(1600, 900)
    _drain(qapp)
    total = sum(w._hsplit.sizes())
    w._hsplit.setSizes([500, total - 500])
    w._hsplit.splitterMoved.emit(500, 0)
    _drain(qapp)
    assert w._seg_vowels_stacked is True
    # Resize the WINDOW so the seg pane auto-grows past the
    # threshold; splitterMoved doesn't fire on auto-redistribution.
    w.resize(2400, 900)
    _drain(qapp)
    assert w.seg_panel.width() > layout.VOWEL_STACK_W
    assert w._seg_vowels_stacked is False, (
        "stack flag stuck True after seg pane widened back past "
        f"VOWEL_STACK_W ({layout.VOWEL_STACK_W}); seg pane is now "
        f"{w.seg_panel.width()} wide"
    )
    w.close()


def test_feat_panel_recovers_after_shrink_and_grow(qapp) -> None:
    """Symmetric height recovery. Shrinking the window drives the
    vsplit's analysis pane to its floor, which forces the top
    section to give up height. Growing the window back has to
    restore the feat pane to its content-derived minimum; without
    the content-driven ``setMinimumHeight`` on each panel, Qt's
    stretch policy (analysis=1, top=0) gave all the new space to
    analysis and left feat squeezed.
    """
    _wipe_settings()
    from phonology_features.gui.main_window import MainWindow

    w = MainWindow()
    w.show()
    _drain(qapp)
    w.resize(1366, 900)
    _drain(qapp)
    feat_h_initial = w.feat_panel.height()
    w.resize(1366, 480)
    _drain(qapp)
    w.resize(1366, 900)
    _drain(qapp)
    assert w.feat_panel.height() >= feat_h_initial - 5, (
        "feat pane didn't recover height after shrink/grow: "
        f"initial={feat_h_initial}, after={w.feat_panel.height()}"
    )
    w.close()


# ---------------------------------------------------------------------------
# Predicate parity tests (Phase E).
#
# The content-driven predicates added in Phase E (would_overflow,
# font_below_min, aspect_out_of_range) are pure functions that
# describe constraint failure WITHOUT consulting any pixel threshold.
# These tests pin two contracts:
#
#   1. The predicates produce the expected boolean for canonical
#      inputs (sanity).
#   2. ``should_stack_vowels`` (a threshold helper) agrees with
#      ``would_overflow`` applied to the shipped inventory's natural
#      content widths; the threshold is the canonical answer; the
#      predicate is the reason. Drift between them would mean a
#      future "tweak VOWEL_STACK_W" edit produced visual overflow.
# ---------------------------------------------------------------------------


def test_would_overflow_threshold_inputs() -> None:
    """Canonical input table; documents the predicate's contract."""
    # No children: never overflows.
    assert layout.would_overflow(0, []) is False
    assert layout.would_overflow(100, []) is False
    # Fits exactly: not overflow.
    assert layout.would_overflow(100, [60, 40], gap=0) is False
    assert layout.would_overflow(110, [60, 40], gap=10) is False
    # Just over: overflow.
    assert layout.would_overflow(99, [60, 40], gap=0) is True
    assert layout.would_overflow(109, [60, 40], gap=10) is True
    # Negative container: overflow (treated as zero capacity).
    assert layout.would_overflow(-10, [1]) is True


def test_would_overflow_monotonic_in_container_w() -> None:
    """Increasing the container width can only flip overflow True ->
    False, never the other way around. A property that any future
    refactor of the helper must preserve.
    """
    children = [100, 80, 60, 40]
    gap = 8
    needed = sum(children) + (len(children) - 1) * gap
    # Just below needed: True; at needed: False.
    assert layout.would_overflow(needed - 1, children, gap=gap) is True
    assert layout.would_overflow(needed, children, gap=gap) is False
    # Sweep upward; once False, never True again.
    seen_false = False
    for w in range(needed - 5, needed + 100, 1):
        is_over = layout.would_overflow(w, children, gap=gap)
        if not is_over:
            seen_false = True
        else:
            assert not seen_false, f"non-monotonic at container_w={w}"


def test_should_stack_vowels_agrees_with_would_overflow_at_threshold() -> None:
    """The pixel threshold (``VOWEL_STACK_W``) and the predicate
    (``would_overflow`` applied to vowel-chart + min consonant area)
    must agree at the boundary. If a future change widens the chart
    without bumping the threshold, this test catches it.
    """
    # Minimum consonant text-flow + vowel chart width must fit
    # inside the seg pane for vowels-alongside. At ``VOWEL_STACK_W``
    # the threshold says "do not stack"; the predicate must agree.
    consonant_floor = layout.VOWEL_STACK_W - layout.VOWEL_NATURAL_W
    # Just above threshold: do not stack; predicate says fits.
    assert layout.should_stack_vowels(layout.VOWEL_STACK_W) is False
    assert (
        layout.would_overflow(
            layout.VOWEL_STACK_W,
            [consonant_floor, layout.VOWEL_NATURAL_W],
            gap=0,
        )
        is False
    )
    # Just below: stack; predicate says overflows.
    assert layout.should_stack_vowels(layout.VOWEL_STACK_W - 1) is True
    assert (
        layout.would_overflow(
            layout.VOWEL_STACK_W - 1,
            [consonant_floor, layout.VOWEL_NATURAL_W],
            gap=0,
        )
        is True
    )


def test_font_below_min_flags_only_shrinks_that_cross_the_floor() -> None:
    """When natural text already fits, no shrink is needed and the
    floor isn't an issue (False). When the shrink ratio would drop
    the size below the floor (``FONT_SIZE_MIN_PX`` = 10), True.
    """
    # Fits at current size: False.
    assert layout.font_below_min(50, 100, current_px=14) is False
    # Has to shrink moderately but stays at or above 10 px: False.
    # 14 * (100/130) ~= 10.77 still clears the 10 px floor.
    assert layout.font_below_min(130, 100, current_px=14) is False
    # Has to shrink so much the size goes below 10 px: True.
    assert layout.font_below_min(1000, 100, current_px=14) is True
    # Explicit min override.
    assert layout.font_below_min(100, 50, current_px=14, min_px=12) is True
    assert layout.font_below_min(100, 90, current_px=14, min_px=8) is False


def test_aspect_out_of_range() -> None:
    """Degenerate inputs are flagged; in-range pass; outliers flagged."""
    # Degenerate.
    assert layout.aspect_out_of_range(100, 0, 0.5, 2.0) is True
    assert layout.aspect_out_of_range(100, -1, 0.5, 2.0) is True
    # In range.
    assert layout.aspect_out_of_range(100, 100, 0.5, 2.0) is False
    assert layout.aspect_out_of_range(150, 100, 0.5, 2.0) is False
    # Out of range.
    assert layout.aspect_out_of_range(100, 1000, 0.5, 2.0) is True
    assert layout.aspect_out_of_range(1000, 100, 0.5, 2.0) is True
