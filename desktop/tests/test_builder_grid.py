"""Tests for the inventory editor grid cell helpers."""

from __future__ import annotations

from phonology_features.gui.editor.grid import make_cell


def test_make_cell_normalizes_ascii_minus_to_unicode_minus(qapp):
    cell = make_cell("-")
    assert cell.text() == "\u2212"
