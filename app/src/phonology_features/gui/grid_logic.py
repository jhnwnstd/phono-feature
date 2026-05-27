"""Portable inventory-builder grid logic.

Shared by the desktop builder (the ``_BulkCycleTable`` and
``InventoryBuilder._to_inventory`` path) and the web app's editor
grid (relayed into the Pyodide bundle via
``web/scripts/build.py:RELAYED_SOURCES``). Nothing here imports Qt
or the DOM. Both frontends adapt these helpers to their native
widget vocabulary.

Single source of truth for:

* The cell value-cycle ladder (``0`` -> ``+`` -> minus -> ``0``).
* The display-vs-serialized form of the minus value (U+2212 vs the
  ASCII hyphen-minus).
* The snapshot path that converts grid state into a validated
  :py:class:`Inventory` via :py:meth:`Inventory.from_grid`.

Extracting these out of the Qt-bound ``builder/`` package keeps the
two frontends genuinely identical rather than approximately
identical. Edits to the ladder or to the omit-on-zero serialization
rule land in both UIs on the next build.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from phonology_engine.inventory import Inventory

# Display form of the negative cell value. U+2212 MATHEMATICAL MINUS
# SIGN, chosen for typographic symmetry with the plus glyph. The grid
# renders this; the on-disk JSON uses ASCII hyphen-minus instead.
MINUS_DISPLAY: str = "−"

# Serialized form. ASCII U+002D HYPHEN-MINUS, what every external
# tool (regex, jq, spreadsheets, code) expects to see in JSON values.
MINUS_SERIALIZED: str = "-"

# The value-cycle ladder, ``0`` -> ``+`` -> minus -> ``0``. Exposed
# as a read-only mapping so both the desktop builder and the web
# editor can drive the click-to-cycle behavior off the same data.
# Treat any value not in the ladder as a return to ``0``: the
# defensive default in :py:func:`cycle_value` and the fallback the
# web JS uses when looking up a cell with a drift-induced unknown
# value. Wrapped in :py:class:`MappingProxyType` so callers cannot
# mutate the singleton.
CYCLE_LADDER: Mapping[str, str] = MappingProxyType({
    "0": "+",
    "+": MINUS_DISPLAY,
    MINUS_DISPLAY: "0",
})

# Direct-entry keyboard shortcuts. Maps the typed character (the
# logical key, not a platform-specific scancode) to the cell value
# applied. Both the desktop (which translates ``Qt.Key.Key_N`` to
# the character) and the web (which reads ``event.key`` directly)
# look up this mapping so the shortcuts stay in lockstep.
#
# ``"0"`` is accepted alongside ``"3"`` because the zero key sits
# in the natural "zero" slot on most keyboards, and ``0`` reads as
# "underspecified" intuitively. Both produce the same cell value.
VALUE_KEYS: Mapping[str, str] = MappingProxyType({
    "1": "+",
    "2": MINUS_DISPLAY,
    "3": "0",
    "0": "0",
})

# Cell-cursor navigation. Maps a logical key name to a (dr, dc)
# step in the grid. Three vocabularies are supported so users on
# different input habits all get a binding:
#
# * Arrow keys: ``ArrowUp`` / ``ArrowDown`` / ``ArrowLeft`` /
#   ``ArrowRight``. These match the JS ``event.key`` values
#   directly; the desktop translates them to ``Qt.Key.Key_Up``
#   etc. via the wrapper in ``builder/window.py``.
# * Vim: h / j / k / l. Single chars; translate uppercase to the
#   matching ``Qt.Key.Key_<X>`` constant on the desktop.
# * Numpad: 4 / 5 / 6 / 8. Same translation rule.
#
# The desktop used to delegate arrow-key handling to Qt's built-in
# ``QTableWidget`` navigation; the web had no equivalent and arrow
# keys did nothing in the editor. Putting all three vocabularies in
# the shared mapping keeps both frontends in lockstep and means a
# new binding (e.g. PageUp / PageDown) lands once and propagates.
MOVE_KEYS: Mapping[str, tuple[int, int]] = MappingProxyType({
    # Arrows.
    "ArrowUp": (-1, 0),
    "ArrowDown": (1, 0),
    "ArrowLeft": (0, -1),
    "ArrowRight": (0, 1),
    # Vim.
    "h": (0, -1),
    "j": (1, 0),
    "k": (-1, 0),
    "l": (0, 1),
    # Numpad.
    "4": (0, -1),
    "5": (1, 0),
    "6": (0, 1),
    "8": (-1, 0),
})

# Maximum depth of the undo / redo stack. A typical editing session
# does not exceed a few dozen batches; the cap is generous enough
# that nobody hits it in practice and small enough that the stack
# cannot grow unbounded.
MAX_UNDO_DEPTH: int = 200


def cycle_value(current: str) -> str:
    """Return the next value in the ladder. Unknown inputs reset to
    ``0``. Pure lookup over :py:data:`CYCLE_LADDER`.
    """
    return CYCLE_LADDER.get(current, "0")


def normalize_minus(value: str) -> str:
    """Fold the display minus to the serialized form. Idempotent.
    Cells may be written in either form depending on whether the
    user typed/clicked them or pasted them from another source; the
    save path always normalizes before validation.
    """
    return MINUS_SERIALIZED if value == MINUS_DISPLAY else value


def _canonicalize_label(label: str) -> str:
    """Trim, then NFC-normalize. Mirrors the inventory parser's
    name canonicalization path (NFC + strip). Doing it here surfaces
    NFC-equivalent duplicates at add-time rather than at save-time,
    where the error message would land far from the offending input.
    """
    return unicodedata.normalize("NFC", label.strip())


def validate_new_segment_label(
    label: str,
    existing: Sequence[str],
    *,
    max_segments: int | None = None,
) -> str:
    """Return the canonical (NFC-normalized, trimmed) form of
    ``label`` after validating it for use as a new segment column.

    Catches the failure modes the desktop user used to hit only at
    save time:

    * Empty after trim.
    * Duplicate of an existing segment after NFC normalization
      (e.g. "Café" precomposed vs "Café" decomposed).
    * Inventory has reached ``max_segments`` (per :py:data:`limits.
      MAX_SEGMENTS`); caller passes the cap so this module stays
      independent of the limits module.

    Raises :py:class:`ValueError` with user-facing wording. Shared
    with the web editor so both frontends produce identical
    error messages.
    """
    trimmed = label.strip()
    if not trimmed:
        raise ValueError("Segment label is empty.")
    canonical = unicodedata.normalize("NFC", trimmed)
    if canonical in existing:
        raise ValueError(f"Segment '{canonical}' already exists.")
    if max_segments is not None and len(existing) >= max_segments:
        raise ValueError(
            f"Cannot add segment: limit of {max_segments} reached."
        )
    return canonical


def validate_new_feature_label(
    label: str,
    existing: Sequence[str],
    *,
    max_features: int | None = None,
) -> str:
    """Return the canonical (NFC-normalized, trimmed) form of
    ``label`` after validating it for use as a new feature row.

    Same shape as :py:func:`validate_new_segment_label`; catches
    empty, NFC-duplicate, and over-cap inputs at add-time.
    """
    trimmed = label.strip()
    if not trimmed:
        raise ValueError("Feature label is empty.")
    canonical = unicodedata.normalize("NFC", trimmed)
    if canonical in existing:
        raise ValueError(f"Feature '{canonical}' already exists.")
    if max_features is not None and len(existing) >= max_features:
        raise ValueError(
            f"Cannot add feature: limit of {max_features} reached."
        )
    return canonical


def confirm_remove_segment_prompt(seg: str) -> str:
    """Return the user-facing confirmation message for removing a
    segment column. Shared with the web editor so the wording stays
    in sync across frontends. The desktop wraps this in
    :py:class:`QMessageBox.Question`; the web wraps it in
    :py:func:`window.confirm`.
    """
    return f"Remove segment '{seg}'?"


def confirm_remove_feature_prompt(feat: str) -> str:
    """Return the user-facing confirmation message for removing a
    feature row. Same shape as
    :py:func:`confirm_remove_segment_prompt`.
    """
    return f"Remove feature '{feat}'?"


def grid_to_inventory(
    *,
    name: str,
    features: Sequence[str],
    segments: Sequence[str],
    cells: Sequence[Sequence[str]],
) -> Inventory:
    """Snapshot grid state as a validated :py:class:`Inventory`.

    ``cells`` is indexed as ``cells[feature_index][segment_index]``,
    mirroring the desktop's ``rows = features, cols = segments``
    layout. Each cell value may be in display form (U+2212) or
    serialized form (ASCII hyphen-minus); :py:func:`normalize_minus`
    folds both to the canonical form before validation.

    Cells with value ``"0"`` are OMITTED from the per-segment
    bundle. :py:meth:`Inventory.parse` documents the "missing
    feature => ``'0'``" semantics, so writing explicit zeros would
    silently inflate sparsely-authored on-disk files on every
    builder round-trip. Omission keeps load/save symmetric.

    Routes through :py:meth:`Inventory.from_grid`, which funnels
    into :py:meth:`Inventory.parse`. Validation errors (unknown
    feature value, duplicate name after IPA folding, etc.) surface
    as :py:class:`ValidationError`; the function never produces a
    partially-built inventory.

    Raises :py:class:`ValueError` if the ``cells`` shape does not
    match the declared ``features`` and ``segments`` sizes.
    """
    n_features = len(features)
    n_segments = len(segments)
    if len(cells) != n_features:
        raise ValueError(
            f"cells has {len(cells)} rows, expected {n_features} "
            f"(one per feature)"
        )
    for r, row in enumerate(cells):
        if len(row) != n_segments:
            raise ValueError(
                f"cells row {r} has {len(row)} columns, "
                f"expected {n_segments} (one per segment)"
            )

    segments_dict: dict[str, dict[str, str]] = {}
    for c, seg in enumerate(segments):
        feats: dict[str, str] = {}
        for r, feat in enumerate(features):
            val = normalize_minus(cells[r][c])
            if val == "0":
                continue
            feats[feat] = val
        segments_dict[seg] = feats

    return Inventory.from_grid(
        name=name,
        features=list(features),
        segments=segments_dict,
    )


# Selection shape -----------------------------------------------------

# Discrete shape names a cell selection can take. Used by both
# frontends to decide which remove-button to enable and to keep the
# "what counts as a single-column selection" rule in one place. The
# enum-style strings are stable; do not rename without also updating
# the JS-side classifier and the SELECTION_SHAPE_REMOVE_TARGET table
# below.
SELECTION_SHAPE_EMPTY: str = "empty"
SELECTION_SHAPE_SINGLE_CELL: str = "single_cell"
SELECTION_SHAPE_SINGLE_COLUMN: str = "single_column"
SELECTION_SHAPE_SINGLE_ROW: str = "single_row"
SELECTION_SHAPE_FULL_GRID: str = "full_grid"
SELECTION_SHAPE_RECTANGLE: str = "rectangle"
SELECTION_SHAPE_IRREGULAR: str = "irregular"


@dataclass(frozen=True)
class SelectionShape:
    """Classification of a cell selection's structural shape.

    ``kind`` is one of the ``SELECTION_SHAPE_*`` constants.
    ``row`` and ``column`` are populated when the shape names a
    specific index (``single_cell``, ``single_column``,
    ``single_row``); they are ``None`` otherwise.
    """

    kind: str
    row: int | None = None
    column: int | None = None


def classify_selection(
    cells: Iterable[tuple[int, int]],
    num_rows: int,
    num_cols: int,
) -> SelectionShape:
    """Classify a set of ``(row, col)`` cells by structural shape.

    The contract:

    * No cells: ``empty``.
    * Exactly one cell: ``single_cell`` with ``row`` and ``column``.
    * Every cell in a single column (count == ``num_rows``):
      ``single_column`` with ``column``.
    * Every cell in a single row (count == ``num_cols``):
      ``single_row`` with ``row``.
    * Every cell in the grid: ``full_grid``.
    * A contiguous rectangle of more than one row AND more than
      one column: ``rectangle``.
    * Anything else: ``irregular``.

    Pure-Python and consumed by:

    * The desktop ``_on_selection_changed`` which uses the result
      to enable / disable the ``- Segment`` / ``- Feature`` buttons.
    * The web editor's selection helpers which mirror the same
      rules locally (per-click bridge calls would be too expensive
      on rapid shift+drag); the JS implementation must agree with
      this function. Test cases verify the contract here.
    """
    cells_set = set(cells)
    n = len(cells_set)
    if n == 0:
        return SelectionShape(kind=SELECTION_SHAPE_EMPTY)
    if n == 1:
        (r, c), = cells_set
        return SelectionShape(
            kind=SELECTION_SHAPE_SINGLE_CELL, row=r, column=c
        )
    cols = {c for _, c in cells_set}
    rows = {r for r, _ in cells_set}
    if num_rows > 0 and len(cols) == 1 and n == num_rows:
        return SelectionShape(
            kind=SELECTION_SHAPE_SINGLE_COLUMN, column=next(iter(cols))
        )
    if num_cols > 0 and len(rows) == 1 and n == num_cols:
        return SelectionShape(
            kind=SELECTION_SHAPE_SINGLE_ROW, row=next(iter(rows))
        )
    if num_rows > 0 and num_cols > 0 and n == num_rows * num_cols:
        return SelectionShape(kind=SELECTION_SHAPE_FULL_GRID)
    # Contiguous rectangle?
    r0, r1 = min(rows), max(rows)
    c0, c1 = min(cols), max(cols)
    expected = (r1 - r0 + 1) * (c1 - c0 + 1)
    if n == expected:
        return SelectionShape(kind=SELECTION_SHAPE_RECTANGLE)
    return SelectionShape(kind=SELECTION_SHAPE_IRREGULAR)


# Which remove button (if any) a given selection shape should
# enable. ``None`` means "no remove available". Shared with the web
# editor so a future shape (e.g. ``single_column`` allowing
# multi-column remove) lands once and propagates to both UIs.
SELECTION_SHAPE_REMOVE_TARGET: Mapping[str, str | None] = MappingProxyType({
    SELECTION_SHAPE_SINGLE_COLUMN: "segment",
    SELECTION_SHAPE_SINGLE_ROW: "feature",
})


def remove_target_for_shape(shape: SelectionShape) -> str | None:
    """Return ``"segment"``, ``"feature"``, or ``None`` for the
    given selection shape, per :py:data:`SELECTION_SHAPE_REMOVE_TARGET`.
    """
    return SELECTION_SHAPE_REMOVE_TARGET.get(shape.kind)
