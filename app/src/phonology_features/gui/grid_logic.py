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
