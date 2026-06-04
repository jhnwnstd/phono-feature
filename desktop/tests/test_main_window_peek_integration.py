"""End-to-end tests for the analysis-pane expand toggle.

⤢ grows the analysis pane upward to fit its active tab's content,
floored at 50 percent and capped at 80 percent of the vsplit
total. The chips strip and the Class / Features / Contrasts tabs
all stay visible because they ARE the pane that's growing. ⤣
restores the prior split.

Offscreen Qt does NOT honour ``QSplitter.setSizes`` (the layout
pass that actually applies the new sizes requires the widget
tree to be painted, which the offscreen platform skips). So these
tests verify the toggle's *side effects* — stash state, glyph,
expansion target math — rather than the live splitter pixel
sizes. Real-desktop behaviour rides on Qt's own ``setSizes``
contract; the unit tests here pin everything around it.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from phonology_features.gui.main_window import MainWindow


@pytest.fixture()
def window(qapp: QApplication) -> MainWindow:
    w = MainWindow()
    w.resize(1600, 900)
    w.show()
    qapp.processEvents()
    w.inventory_combo.setCurrentIndex(1)
    qapp.processEvents()
    return w


def _select(
    window: MainWindow, app: QApplication, segs: tuple[str, ...]
) -> None:
    for s in segs:
        btn = window._seg_buttons.get(s)
        if btn is not None:
            btn.click()
    app.processEvents()
    while window._debounce.isActive():
        app.processEvents()


def test_expand_stashes_prior_sizes(
    qapp: QApplication, window: MainWindow
) -> None:
    """⤢ click captures the pre-expand vsplit sizes for restore."""
    _select(window, qapp, ("b", "d", "ɡ"))
    before = window._vsplit.sizes()
    assert window._pre_expand_vsplit_sizes is None
    window.analysis.expand_btn.click()
    qapp.processEvents()
    assert window._pre_expand_vsplit_sizes == before
    assert window.analysis.expand_btn.text() == "⤣"


def test_collapse_clears_stash_and_restores_glyph(
    qapp: QApplication, window: MainWindow
) -> None:
    """⤣ click drops the stash and flips the glyph back. This is
    the canonical "undo what you just did" the user expects."""
    _select(window, qapp, ("b", "d", "ɡ"))
    window.analysis.expand_btn.click()
    qapp.processEvents()
    assert window._pre_expand_vsplit_sizes is not None
    window.analysis.expand_btn.click()
    qapp.processEvents()
    assert window._pre_expand_vsplit_sizes is None
    assert window.analysis.expand_btn.text() == "⤢"


def test_clear_restores_an_expanded_pane(
    qapp: QApplication, window: MainWindow
) -> None:
    """Clear is the canonical reset path. If the user expanded
    the pane and then hit Clear, the toggle state must reset to
    "not expanded" so the next ⤢ click goes through the open
    path again. Otherwise the user gets stuck."""
    _select(window, qapp, ("b", "d", "ɡ"))
    window.analysis.expand_btn.click()
    qapp.processEvents()
    assert window._pre_expand_vsplit_sizes is not None
    window._reset_both_sides(silent=False)
    qapp.processEvents()
    assert window._pre_expand_vsplit_sizes is None
    assert window.analysis.expand_btn.text() == "⤢"


def test_expand_button_round_trips_repeatedly(
    qapp: QApplication, window: MainWindow
) -> None:
    """Four alternating clicks: each click alternates between
    expanded and restored. The toggle never gets stuck in either
    direction."""
    _select(window, qapp, ("b", "d", "ɡ", "v", "z"))
    for i in range(4):
        window.analysis.expand_btn.click()
        qapp.processEvents()
        if i % 2 == 0:
            assert window.analysis.expand_btn.text() == "⤣"
            assert window._pre_expand_vsplit_sizes is not None
        else:
            assert window.analysis.expand_btn.text() == "⤢"
            assert window._pre_expand_vsplit_sizes is None


def test_expand_does_not_mutate_top_pane_min_heights(
    qapp: QApplication, window: MainWindow
) -> None:
    """⤢ now leaves every top-pane minimumHeight UNCHANGED.

    The previous implementation zeroed ``hsplit.minimumHeight``,
    ``seg_panel.minimumHeight``, and ``feat_panel.minimumHeight`` so
    the splitter was free to compress the top; that mutation went
    stale across inventory swaps and forced the segment grid to
    reflow on every expand. The new policy: ``fit_to_content``
    already caps each top pane's minimumHeight at
    ``vsplit_total - analysis_content_floor_h()`` so the splitter
    has room to compress without runtime mutation, and the expand /
    restore cycle is purely a vsplit size change plus a
    ``_layout_frozen`` flag.
    """
    _select(window, qapp, ("b", "d"))
    originals = (
        window._hsplit.minimumHeight(),
        window.seg_panel.minimumHeight(),
        window.feat_panel.minimumHeight(),
    )
    window.analysis.expand_btn.click()
    qapp.processEvents()
    assert window._hsplit.minimumHeight() == originals[0]
    assert window.seg_panel.minimumHeight() == originals[1]
    assert window.feat_panel.minimumHeight() == originals[2]
    assert window._layout_frozen is True
    window.analysis.expand_btn.click()
    qapp.processEvents()
    assert window._hsplit.minimumHeight() == originals[0]
    assert window.seg_panel.minimumHeight() == originals[1]
    assert window.feat_panel.minimumHeight() == originals[2]
    assert window._layout_frozen is False


def test_expand_target_is_fifty_five_percent_of_vsplit(
    qapp: QApplication, window: MainWindow
) -> None:
    """The toggle calls ``setSizes`` with analysis = 55% of the
    vsplit total, matching the web ``.analysis.expanded`` rule.
    Verified by intercepting the ``setSizes`` call since
    offscreen Qt does not actually apply the new sizes."""
    _select(window, qapp, ("b", "d"))
    captured: list[list[int]] = []
    orig = window._vsplit.setSizes

    def trace(sizes: list[int]) -> None:
        captured.append(list(sizes))
        orig(sizes)

    window._vsplit.setSizes = trace  # type: ignore[method-assign]
    total = sum(window._vsplit.sizes())
    window.analysis.expand_btn.click()
    qapp.processEvents()
    assert captured, "setSizes should have been called once"
    new_analysis = captured[-1][1]
    assert new_analysis == int(0.55 * total)
