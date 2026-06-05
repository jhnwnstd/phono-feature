"""Desktop tests for the analysis-pane floor invariant.

The analysis pane sits at a stable 4-row floor on every inventory in
every mode. The pane has no expand toggle: each tab's
``_CopyableTextEdit`` (``QTextEdit`` subclass) provides built-in
scrollbars when its content overflows, so the pane's outer geometry
never has to grow to accommodate large analysis output.

These tests pin the user-facing contracts:

1. ``AnalysisPanel.minimumSizeHint().height()`` is the same integer
   regardless of which inventory is loaded -- the user's complaint
   that "the analysis pane size depends on whichever inventory was
   loaded first" must no longer reproduce.

2. The shared ``analysis_content_floor_h()`` value drives the
   minimum-size hint via ``REGION_CONSTRAINTS['analysis_panel'].min_h``.
   A future tweak to either fails this test rather than silently
   shrinking the analysis pane.

3. Inventory swap does NOT mutate the vsplit sizes, so the user
   never sees the analysis pane jump up or down between loads.

4. Mode swap (seg-to-feat / feat-to-seg) does NOT change the pane's
   floor either; the floor is a layout fact, not a mode fact.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QApplication

from phonology_features.gui.main_window import MainWindow, Mode
from phonology_shared.presentation import layout

INVENTORIES = Path(__file__).resolve().parent.parent / "inventories"


def _load(window: MainWindow, name: str) -> None:
    path = INVENTORIES / name
    if not path.exists():
        import pytest

        pytest.skip(f"missing inventory: {name}")
    window._load_path(str(path))


# ---------------------------------------------------------------------------
# Floor invariance across inventory swaps
# ---------------------------------------------------------------------------


def test_analysis_min_size_hint_is_inventory_independent(
    qapp: QApplication, window: MainWindow
) -> None:
    """Load three inventories in sequence; the analysis pane's
    minimum size hint must not budge. This is the property the user
    means by "should not depend accidentally on whatever inventory
    was loaded first".
    """
    snapshots: list[int] = []
    for name in (
        "spanish_features.json",
        "hayes_features.json",
        "english_features.json",
    ):
        _load(window, name)
        qapp.processEvents()
        snapshots.append(window.analysis.minimumSizeHint().height())
    assert len(set(snapshots)) == 1, (
        f"analysis minimumSizeHint().height() drifted across inventories: "
        f"{snapshots}"
    )
    assert snapshots[0] == layout.analysis_content_floor_h()


def test_analysis_min_size_hint_matches_shared_floor(
    qapp: QApplication, window: MainWindow
) -> None:
    """The widget reads from ``REGION_CONSTRAINTS['analysis_panel'].min_h``,
    which is the shared ``analysis_content_floor_h()`` value. Pin the
    relationship here so a future tweak to either fails this test
    rather than silently shrinking the analysis pane.
    """
    assert (
        window.analysis.minimumSizeHint().height()
        == layout.analysis_content_floor_h()
    )


# ---------------------------------------------------------------------------
# Inventory swap does NOT change the analysis pane height
# ---------------------------------------------------------------------------


def test_inventory_swap_preserves_vsplit_sizes(
    qapp: QApplication, window: MainWindow
) -> None:
    """After the first inventory has loaded and the user has any
    established splitter ratio, loading a NEW inventory must not
    resize the vsplit. The user-visible regression this guards
    against: the analysis pane height changing every time you pick
    a different inventory from the dropdown.
    """
    # Settle initial layout.
    qapp.processEvents()
    # Pretend the user has interacted (or settings restored), so
    # ``has_saved_splitter`` is True and we go through
    # ``reflow_top_pane_only`` instead of ``apply_splitter_sizes``.
    window._geom.has_saved_splitter = True
    sizes_before = list(window._vsplit.sizes())
    _load(window, "spanish_features.json")
    qapp.processEvents()
    sizes_after = list(window._vsplit.sizes())
    assert sizes_after == sizes_before, (
        f"vsplit sizes mutated across inventory load: "
        f"{sizes_before} -> {sizes_after}"
    )


def test_mode_swap_does_not_change_analysis_min_height(
    qapp: QApplication, window: MainWindow
) -> None:
    """Toggling between seg-to-feat and feat-to-seg modes touches a
    bunch of state but must NEVER change the analysis pane's
    minimumSizeHint. Sanity check the floor is mode-independent too.
    """
    floor_initial = window.analysis.minimumSizeHint().height()
    window._set_mode(Mode.FEAT_TO_SEG)
    qapp.processEvents()
    assert window.analysis.minimumSizeHint().height() == floor_initial
    window._set_mode(Mode.SEG_TO_FEAT)
    qapp.processEvents()
    assert window.analysis.minimumSizeHint().height() == floor_initial
