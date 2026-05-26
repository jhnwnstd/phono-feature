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
from collections.abc import Mapping, Sequence
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

# Cell-cursor navigation. Maps the typed character to a (dr, dc)
# step in the grid. Vim conventions on h/j/k/l plus the numpad
# directions on 4/5/6/8 give users a choice without leaving the
# home row or the numpad. Shared with the web editor.
MOVE_KEYS: Mapping[str, tuple[int, int]] = MappingProxyType({
    "8": (-1, 0),
    "k": (-1, 0),
    "5": (1, 0),
    "j": (1, 0),
    "4": (0, -1),
    "h": (0, -1),
    "6": (0, 1),
    "l": (0, 1),
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
