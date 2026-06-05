"""Pin that the analysis pane's Class-tab verdict cue resets when
the user swaps top-level modes.

Saved feedback ([[feedback_display_state_must_reset]]) calls out
analysis-pane cues as state that must clear on user actions. The
class-state cue (the green / red band on the Class tab when the
segment selection is or is not a natural class) is one such cue.

In FEAT mode the cue is meaningless (the analysis is keyed by a
feature query, not a segment selection), so the shared view-model
returns ``"class_state": "neutral"`` for every FEAT-mode payload.
This test sets up a non-neutral cue in SEG mode, switches to FEAT,
and asserts the cue cleared. Without this test the deferred-refresh
path could regress and leave the prior session's red band visible
across a mode swap.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QApplication


def test_class_state_resets_on_mode_swap_to_feat(
    window, qapp: QApplication
) -> None:
    """Select segments that aren't a natural class, run the
    pending update to paint the not_natural cue, then swap to FEAT
    mode and assert the cue clears.
    """
    # Voiceless bilabial stop + voiced alveolar nasal: not a
    # natural class in any reasonable feature inventory; the
    # view-model returns ``class_state="not_natural"``.
    window._on_segment_clicked("p", True)
    window._on_segment_clicked("n", True)
    window._run_pending_update()
    assert window.analysis._class_state == "not_natural", (
        "fixture invalid: expected /p, n/ to register as a "
        "not-natural class in this inventory"
    )

    window._set_mode("feat_to_seg")
    # apply_phases schedules ``_deferred_refresh_analysis`` via a
    # zero-delay singleShot; pump the queue so it fires.
    qapp.processEvents()

    assert window.analysis._class_state == "neutral", (
        "FEAT mode must always report neutral; the not_natural "
        "band from the SEG-mode selection must not persist."
    )


def test_class_state_resets_after_clear(window) -> None:
    """Smoke test for the existing clear() path that the deferred
    refresh test relies on: a non-neutral state set via
    ``set_sections`` followed by ``clear()`` returns to neutral.
    Pins the AnalysisPanel-internal invariant that the cross-mode
    test above leans on.
    """
    panel = window.analysis
    panel.set_sections(
        "<p>sel</p>",
        "<p>cls</p>",
        "<p>feat</p>",
        "<p>con</p>",
        class_state="not_natural",
    )
    assert panel._class_state == "not_natural"
    panel.clear()
    assert panel._class_state == "neutral"
