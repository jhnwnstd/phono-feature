"""Undo/redo data types for the inventory editor.

Module-private symbols (leading underscore) but visible inside the
``editor`` package. Pure data types with no Qt dependency, so the
table machinery and the InventoryEditor class can both reference
them without dragging GUI imports through the engine-only test
paths that ``Inventory`` and ``FeatureEngine`` live on.

The undo stack is a list of ``_BulkEdit`` records. Each carries the
pre-edit value of every cell that changed plus the single new value
they all moved to. Capped at :py:data:`MAX_UNDO_DEPTH` (200) so a
long session does not grow the stack without bound. The cap is
defined in :py:mod:`phonology_shared.editor.grid` so the web
editor's JS undo stack uses the same value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from phonology_shared.editor.grid import MAX_UNDO_DEPTH


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


@dataclass(frozen=True)
class _SegmentEdit:
    """An undoable add OR removal of a segment column. ``added`` is
    True for an add (undo removes the column, redo re-inserts it),
    False for a removal (undo re-inserts, redo removes). ``values``
    carries the column's per-feature cell values so a removal can be
    undone with the data intact; for an add they are all ``"0"``.
    ``index`` is the column position the edit acted on."""

    index: int
    segment: str
    values: tuple[str, ...]
    added: bool


@dataclass(frozen=True)
class _FeatureEdit:
    """An undoable add OR removal of a feature row. Mirror of
    :py:class:`_SegmentEdit` on the row axis; ``values`` carries the
    row's per-segment cell values."""

    index: int
    feature: str
    values: tuple[str, ...]
    added: bool


@dataclass(frozen=True)
class _RenameEdit:
    """An undoable segment rename. ``old`` / ``new`` are the column's
    header label before and after; ``index`` is the column."""

    index: int
    old: str
    new: str


# Re-export the shared cap under the package-internal name so
# existing callers (window.py's ``_undo_stack`` cap check) keep
# working without churn.
_MAX_UNDO_DEPTH = MAX_UNDO_DEPTH
