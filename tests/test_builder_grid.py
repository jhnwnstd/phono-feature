"""Tests for the inventory builder grid cell helpers."""

from __future__ import annotations

from gui.builder.grid import make_cell


def test_make_cell_normalizes_ascii_minus_to_unicode_minus(qapp):
    cell = make_cell("-")
    assert cell.text() == "\u2212"
