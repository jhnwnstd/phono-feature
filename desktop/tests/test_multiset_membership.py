"""Desktop MULTISET rendering: a multi-membership consonant occupies
every manner row it reaches, with synchronized state and a cue.

This is the desktop mirror of the web ``check_multiset.py`` oracle: the
scout flagged the ``SegmentButton`` pool (keyed by glyph) plus Qt's
one-parent rule as SILENT RENDER-LOSS, where a shared glyph would vanish
from every row but its last. The fix mints one widget per placement and
fans state out from the glyph; these assertions pin both against the live
producer output (``mb`` reaches Nasals AND Plosives).
"""

from __future__ import annotations

from pathlib import Path

from phonology_features.gui.main_window import Mode
from phonology_features.gui.widgets import SegmentState
from phonology_shared.data.inventory import Inventory


def _prenasalized_inventory(path: Path) -> str:
    """A tiny inventory whose ``mb`` has a nasal->oral contour, so it
    reaches BOTH Nasals and Plosives. Written to JSON and loaded through
    the normal path so it exercises the full render pipeline."""
    feats = ["Consonantal", "Sonorant", "Continuant", "Nasal", "Syllabic"]
    segs = {
        "mb": {
            "Consonantal": "+",
            "Sonorant": "+",
            "Continuant": "-",
            "Nasal": "+",
            "Syllabic": "-",
        },
        "b": {
            "Consonantal": "+",
            "Sonorant": "-",
            "Continuant": "-",
            "Nasal": "-",
            "Syllabic": "-",
        },
        "m": {
            "Consonantal": "+",
            "Sonorant": "+",
            "Continuant": "-",
            "Nasal": "+",
            "Syllabic": "-",
        },
        "a": {
            "Consonantal": "-",
            "Sonorant": "+",
            "Continuant": "+",
            "Nasal": "-",
            "Syllabic": "+",
        },
    }
    inv = Inventory.from_grid(
        name="Multi",
        features=feats,
        segments=segs,
        metadata={
            "segment_sequences": {
                "mb": {"Sonorant": ["+", "-"], "Nasal": ["+", "-"]}
            }
        },
    )
    inv.write_atomic(str(path))
    return str(path)


def test_multiset_consonant_renders_in_every_reached_row(window, tmp_path):
    window._load_path(_prenasalized_inventory(tmp_path / "multi.json"))

    # The engine places mb in BOTH manner classes (substance-free reach).
    groups = window.engine.grouped_segments
    assert "mb" in groups.get("Nasals", [])
    assert "mb" in groups.get("Plosives", [])

    # Each placement is a DISTINCT widget (a Qt widget has one parent, so
    # a shared one would vanish from all but the last row).
    instances = window._seg_buttons["mb"]
    assert len(instances) == 2
    assert instances[0] is not instances[1]

    # Both placements are tracked in the grid, keyed by (manner, seg).
    grid_buttons = window.seg_grid_widget._buttons
    assert ("Nasals", "mb") in grid_buttons
    assert ("Plosives", "mb") in grid_buttons
    assert (
        grid_buttons[("Nasals", "mb")] is not grid_buttons[("Plosives", "mb")]
    )
    assert set(instances) == {
        grid_buttons[("Nasals", "mb")],
        grid_buttons[("Plosives", "mb")],
    }

    # The cue count (2) is on every instance and comes from the producer's
    # grouping, so it cannot disagree with the rows it marks.
    assert all(b._multiclass_count == 2 for b in instances)
    # a single-membership consonant carries no cue
    assert all(b._multiclass_count == 1 for b in window._seg_buttons["b"])


def test_multiset_click_syncs_every_placement(window, tmp_path):
    window._load_path(_prenasalized_inventory(tmp_path / "multi.json"))
    window._set_mode(Mode.SEG_TO_FEAT)
    instances = window._seg_buttons["mb"]

    # Clicking one placement selects the GLYPH; the state fans out to
    # every placement so its rows never disagree.
    window._on_segment_clicked("mb", True)
    assert all(b._state == SegmentState.SELECTED for b in instances)
    assert all(b.isChecked() for b in instances)

    window._on_segment_clicked("mb", False)
    assert all(b._state == SegmentState.DEFAULT for b in instances)
    assert all(not b.isChecked() for b in instances)


def test_multiset_relayout_preserves_both_placements(window, tmp_path):
    window._load_path(_prenasalized_inventory(tmp_path / "multi.json"))
    window._set_mode(Mode.SEG_TO_FEAT)
    window._on_segment_clicked("mb", True)

    grid = window.seg_grid_widget
    grid.resize(400, 800)
    grid.request_sync_relayout()
    grid._do_relayout()

    # Both placements survive the relayout (the silent-render-loss guard),
    # each in its own grid cell, and both stay selected.
    idx = grid._grid.indexOf(grid._buttons[("Nasals", "mb")])
    jdx = grid._grid.indexOf(grid._buttons[("Plosives", "mb")])
    assert idx != -1 and jdx != -1 and idx != jdx
    assert all(
        b._state == SegmentState.SELECTED for b in window._seg_buttons["mb"]
    )
