"""Undo/redo data types for the inventory editor.

Module-private but visible inside the ``editor`` package. Pure data
types with no Qt dependency, so the table machinery and the
InventoryEditor can both reference them without dragging GUI imports
through the engine-only test paths.

The undo stack is a list of ``_BulkEdit`` records, capped at
:py:data:`MAX_UNDO_DEPTH` (200) so a long session does not grow it
without bound. The cap lives in :py:mod:`phonology_shared.editor.grid`
so the web editor's JS undo stack uses the same value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from phonology_shared.editor.grid import MAX_UNDO_DEPTH


class _CellPrev(NamedTuple):
    """One cell's pre-edit state. NamedTuple, not a raw
    ``tuple[int, int, str]``, so undo/redo destructuring reads named
    slots. Zero runtime overhead over a plain tuple."""

    row: int
    col: int
    old: str


@dataclass(frozen=True)
class _BulkEdit:
    """One undoable mutation. ``new`` is the single value applied to
    every cell in the batch (bulk cycle and key-set always pick one
    destination value); ``cells`` carries the per-cell old state.
    Sharing one ``new`` across N cells instead of storing it per cell
    saves ~40% over the old per-cell-record shape, which compounds
    across the 200-batch undo cap.
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
