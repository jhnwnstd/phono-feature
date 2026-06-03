"""Tests for the feature-panel card layout policy.

The two-column feature pane uses *soft pins* for the canonical blocks:

  Left column:  Major Class (top) -> Place -> balanced fill
  Right column: Manner (top)      -> balanced fill

If any of those three groups has no active features for the current
inventory, the soft pin is skipped (nothing is hardcoded into a slot).
Everything else is sorted by active feature count descending and
dropped into whichever column is shorter at the moment of placement.

Crucially, the balancer measures *active* feature counts (not the
declared FEATURE_GROUPS sizes) and includes a per-card overhead so
that a column with many small cards isn't under-counted relative to
one with a few big cards. The goal is to minimise the window height
needed to fit the taller column.
"""

from __future__ import annotations


def _card_titles(layout) -> list[str]:
    """Group-card titles from a column layout, in display order."""
    titles: list[str] = []
    for i in range(layout.count()):
        widget = layout.itemAt(i).widget()
        if widget is None:
            continue
        card_layout = widget.layout()
        if card_layout is None or card_layout.count() == 0:
            continue
        first = card_layout.itemAt(0).widget()
        if first is not None and hasattr(first, "text"):
            titles.append(first.text())
    return titles


def _column_height(layout) -> int:
    """Sum of sizeHint().height() for every card in the column.

    Reflects actual rendered height including each card's header +
    padding, which is what the user sees when the columns sit side by
    side."""
    total = 0
    for i in range(layout.count()):
        widget = layout.itemAt(i).widget()
        if widget is None:
            continue
        total += widget.sizeHint().height()
    return total


def test_left_column_pins_major_class_then_place(window):
    titles = _card_titles(window._feat_left_layout)
    assert titles[:2] == [
        "Major Class",
        "Place",
    ], f"Major Class and Place must lead the left column, got {titles}"


def test_right_column_pins_manner(window):
    titles = _card_titles(window._feat_right_layout)
    assert (
        titles[0] == "Manner"
    ), f"Manner must be the first card on the right column, got {titles}"


def test_columns_balanced_by_actual_height_on_hayes(window):
    """With the active-count-aware balancer, Hayes should land within a
    single card's overhead between left and right column heights.

    Major(4) + Place(11) on left totals 15 active rows;
    Manner(7) + Laryngeal(3) + Prosodic(2) + Tongue-Root(1) on right
    totals 13 active rows but adds 4 card overheads vs 2 on the left,
    closing the gap to ~zero in actual rendered pixels."""
    window.show()
    window.resize(1200, 900)
    window.repaint()  # force layout pass so sizeHint reflects visible rows
    left_h = _column_height(window._feat_left_layout)
    right_h = _column_height(window._feat_right_layout)
    diff = abs(left_h - right_h)
    # ~32 px per card overhead is the smallest "unit" the algorithm can
    # rebalance at. Anything wider than that means a swap was missed.
    assert diff <= 35, (
        f"columns unbalanced on Hayes: left={left_h}px, right={right_h}px,"
        f" diff={diff}px"
    )


def test_columns_rebalance_per_inventory(window):
    """Switching inventories must trigger a fresh redistribute. Soft
    pins still apply, and the heights stay close to balanced even when
    active counts shift."""
    window._load_path("inventories/blevins_features.json")
    window.show()
    window.resize(1200, 900)
    window.repaint()
    titles_left = _card_titles(window._feat_left_layout)
    titles_right = _card_titles(window._feat_right_layout)
    assert titles_left[:2] == ["Major Class", "Place"]
    assert titles_right[0] == "Manner"
    # Allow up to 2 card overheads of slop. Blevins doesn't have all
    # groups so a wider gap is sometimes unavoidable.
    diff = abs(
        _column_height(window._feat_left_layout)
        - _column_height(window._feat_right_layout)
    )
    assert diff <= 64, f"Blevins columns unbalanced: diff={diff}px"
