"""Undo/redo data types for the inventory builder.

Module-private symbols (leading underscore) but visible inside the
``builder`` package. Pure data types with no Qt dependency, so the
table machinery and the InventoryBuilder class can both reference
them without dragging GUI imports through the engine-only test
paths that ``Inventory`` and ``FeatureEngine`` live on.

The undo stack is a list of ``_BulkEdit`` records. Each carries the
pre-edit value of every cell that changed plus the single new value
they all moved to. Capped at ``_MAX_UNDO_DEPTH`` (200) so a long
session does not grow the stack without bound.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


class _CellPrev(NamedTuple):
    """One cell's pre-edit state. NamedTuple instead of a raw
    ``tuple[int, int, str]`` so the destructuring in undo / redo
    (``for row, col, old in edit.cells``) reads against named slots
    rather than positional ones. Zero runtime overhead vs. a plain
    tuple."""

    row: int
    col: int
    old: str


@dataclass(frozen=True)
class _BulkEdit:
    """One undoable mutation. ``new`` is the value applied to every
    cell in the batch (uniform: bulk cycle and key set targets always
    pick a single destination value). ``cells`` carries the per cell
    old state as a tuple of ``_CellPrev`` records. Single cell edits
    use a 1 element ``cells`` tuple. Bulk edits share one ``new``
    string across N cells instead of duplicating it N times.

    Memory: tuple wrapper (~56 B) plus ~56 B per cell entry. A 3920
    cell select all batch used to allocate 3920 ``_CellEdit`` records
    (~96 B each, ~375 KB total). The new shape is ~220 KB, a ~40 %
    saving that compounds across the 200 batch undo cap.
    """

    cells: tuple[_CellPrev, ...]
    new: str


# Undo history depth cap. ~200 batches of at most all cells covers a
# normal editing session without unbounded growth.
_MAX_UNDO_DEPTH = 200
