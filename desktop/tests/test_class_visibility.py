"""Tests for the segment-class visibility filter and the diphthong chip
strip, the two surfaces a recent regression pass found under-covered.

The visibility filter (the seg-header ``⊟`` menu) hides/shows whole
segment classes. The contract these tests pin:

1. Showing a class again must REPAINT its buttons to the live analysis
   state. Hiding forces the class' buttons to DEFAULT; without a
   re-run on show, a feature query active in FEAT mode would leave the
   re-shown buttons neutral instead of matched/unmatched.
2. Hiding a class with a selected segment must prune that segment from
   the selection (and re-run the analysis against the pruned set).
3. Hidden classes leave the consonant grid and come back on show.
4. A label that no longer names a class in the live inventory (an
   inventory swap under an open menu) must not pollute the hidden set.

The chip strip places the segment's POOLED ``SegmentButton`` (the same
instance the rest of the app tracks), so a chip click selects through
the standard flow and Clear resets the chip with everything else: no
parallel, latch-prone button.
"""

from __future__ import annotations

from pathlib import Path

from phonology_features.gui.main_window import Mode
from phonology_features.gui.widgets import SegmentState
from phonology_shared.chart.consonants import (
    VOCOID_GROUP_NAME,
    VOWEL_GROUP_NAME,
)

_INVENTORIES = Path(__file__).resolve().parent.parent / "inventories"


def _first_consonant_class(window) -> str:
    """A populated non-vowel, non-vocoid class label."""
    return next(
        g
        for g, segs in window.engine.grouped_segments.items()
        if g not in (VOWEL_GROUP_NAME, VOCOID_GROUP_NAME) and segs
    )


def _chips(window) -> list:
    layout = window.vowel_chart_widget._chip_strip_layout
    out = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        widget = item.widget() if item is not None else None
        if widget is not None:
            out.append(widget)
    return out


# ---------------------------------------------------------------------------
# Visibility filter
# ---------------------------------------------------------------------------
def test_show_class_repaints_analysis_state_in_feat_mode(window):
    """Hiding then showing a class in FEAT mode must leave its buttons in
    their matched/unmatched state, NOT the DEFAULT the hide path forced.
    Showing alone (no further interaction) has to re-run the analysis."""
    window._set_mode(Mode.FEAT_TO_SEG)
    window._feat_rows["Voice"]._on_click("+")
    window._run_pending_update()
    label = _first_consonant_class(window)
    seg = window.engine.grouped_segments[label][0]
    before = window._seg_buttons[seg]._state
    assert before != SegmentState.DEFAULT  # the query painted it
    window._set_class_visible(label, False)
    window._set_class_visible(label, True)
    # No further interaction between hide+show and this assertion.
    assert window._seg_buttons[seg]._state == before


def test_hide_class_prunes_selected_segment(window):
    """A selected segment in a newly-hidden class must leave the
    selection (it has no visible button left to deselect)."""
    label = _first_consonant_class(window)
    seg = window.engine.grouped_segments[label][0]
    window._on_segment_clicked(seg, True)
    window._run_pending_update()
    assert seg in window._selected_segments
    window._set_class_visible(label, False)
    assert seg not in window._selected_segments


def test_hidden_class_leaves_grid_and_returns_on_show(window):
    label = _first_consonant_class(window)
    assert label in window.seg_grid_widget._groups
    window._set_class_visible(label, False)
    assert label not in window.seg_grid_widget._groups
    window._set_class_visible(label, True)
    assert label in window.seg_grid_widget._groups


def test_set_class_visible_ignores_unknown_label(window):
    """A stale label (e.g. from a menu still open across an inventory
    swap) must not enter the hidden set."""
    before = set(window._hidden_segment_classes)
    window._set_class_visible("NoSuchClassLabel", False)
    assert window._hidden_segment_classes == before


# ---------------------------------------------------------------------------
# Diphthong chip strip
# ---------------------------------------------------------------------------
def test_diphthong_chip_is_pooled_button(window):
    """Each chip IS the segment's pooled button, so it is a single
    source of truth rather than a parallel selection surface."""
    window._load_path(str(_INVENTORIES / "german_features.json"))
    window._set_mode(Mode.SEG_TO_FEAT)
    chips = _chips(window)
    assert chips, "German has diphthongs; expected chips"
    for chip in chips:
        assert chip is window._seg_buttons[chip.text()]


def test_diphthong_chip_resets_on_clear(window):
    """Selecting via a chip then Clear must reset the chip too: no
    latched checked state surviving the wipe."""
    window._load_path(str(_INVENTORIES / "german_features.json"))
    window._set_mode(Mode.SEG_TO_FEAT)
    chip = _chips(window)[0]
    seg = chip.text()
    chip.click()
    window._run_pending_update()
    assert seg in window._selected_segments
    assert chip.isChecked()
    window._clear_segments()
    assert seg not in window._selected_segments
    assert not chip.isChecked()
    assert chip._state == SegmentState.DEFAULT
