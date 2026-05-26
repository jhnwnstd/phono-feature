"""Tests for :py:mod:`phonology_features.gui.grid_logic`.

The module is pure-Python and consumed by both the desktop builder
(``_BulkCycleTable``, ``InventoryBuilder._to_inventory``) and the
web app builder grid (via the build relay). These tests exercise
its contract directly, no Qt required.
"""

from __future__ import annotations

import pytest

from phonology_engine.inventory import Inventory, ValidationError
from phonology_features.gui.grid_logic import (
    CYCLE_LADDER,
    MINUS_DISPLAY,
    MINUS_SERIALIZED,
    cycle_value,
    grid_to_inventory,
    normalize_minus,
)

# Constants

def test_minus_constants_are_the_distinct_characters_we_expect():
    """The display form is U+2212 MATHEMATICAL MINUS SIGN; the
    serialized form is ASCII U+002D HYPHEN-MINUS. They must be
    distinct so the normalization round-trip is meaningful."""
    assert ord(MINUS_DISPLAY) == 0x2212
    assert MINUS_SERIALIZED == "-"
    assert ord(MINUS_SERIALIZED) == 0x002D
    assert MINUS_DISPLAY != MINUS_SERIALIZED


# cycle_value: the value ladder


def test_cycle_value_zero_goes_to_plus():
    assert cycle_value("0") == "+"


def test_cycle_value_plus_goes_to_minus_display_form():
    """Plus advances to the DISPLAY form of minus (U+2212), not
    ASCII. The grid renders the display form; serialization will
    fold it back."""
    assert cycle_value("+") == MINUS_DISPLAY


def test_cycle_value_minus_returns_to_zero():
    """Both forms of minus complete the cycle back to zero so a
    cell pasted with the serialized form still cycles cleanly."""
    assert cycle_value(MINUS_DISPLAY) == "0"


def test_cycle_value_unknown_resets_to_zero():
    """Defensive: any value outside the ladder resets to ``0``."""
    assert cycle_value("?") == "0"
    assert cycle_value("") == "0"
    assert cycle_value("+++") == "0"


def test_cycle_value_full_round_trip():
    """0 -> + -> minus -> 0 in three steps. Documents the loop
    length so a future change that adds a step (e.g. an
    underspecified-but-present marker) breaks this test
    deliberately."""
    v = "0"
    v = cycle_value(v)
    assert v == "+"
    v = cycle_value(v)
    assert v == MINUS_DISPLAY
    v = cycle_value(v)
    assert v == "0"


# CYCLE_LADDER: the data cycle_value reads, exposed for the web JS


def test_cycle_ladder_matches_cycle_value_for_every_in_ladder_key():
    """The ladder constant is the single source of truth shared with
    the web editor; ``cycle_value`` is a thin lookup. They must
    agree for every key in the ladder so the JS-side lookup
    behaves identically to the Python function."""
    for key, expected_next in CYCLE_LADDER.items():
        assert cycle_value(key) == expected_next


def test_cycle_ladder_is_read_only():
    """The exported mapping is a MappingProxyType so a caller (or a
    bridge user) cannot mutate the singleton and silently change
    behavior elsewhere. The type checker also flags the assignment;
    the runtime check below proves the protection survives even if
    a caller bypasses the static checker."""
    with pytest.raises(TypeError):
        CYCLE_LADDER["0"] = "?"  # type: ignore[index]


def test_cycle_ladder_covers_three_states():
    """Exactly the three values that participate in the cycle.
    Documents the contract: a new state added to the ladder is a
    deliberate change, not an accident."""
    assert set(CYCLE_LADDER.keys()) == {"0", "+", MINUS_DISPLAY}


# normalize_minus: display -> serialized form


def test_normalize_minus_folds_display_to_serialized():
    assert normalize_minus(MINUS_DISPLAY) == MINUS_SERIALIZED


def test_normalize_minus_is_idempotent():
    """Calling twice should be the same as once: critical because
    the save path may call it on both freshly-clicked cells
    (display form) and cells loaded from disk (serialized form)
    without distinguishing."""
    assert normalize_minus(normalize_minus(MINUS_DISPLAY)) == MINUS_SERIALIZED
    assert normalize_minus(normalize_minus("-")) == "-"


def test_normalize_minus_passes_other_values_through():
    """Only the display-form minus is special; everything else
    rides through unchanged."""
    for value in ("+", "0", "", "?", "−x"):
        # The second case is "minus followed by x" which is not the
        # display form itself; we expect no fold.
        assert normalize_minus(value) == value


# grid_to_inventory: the snapshot path


@pytest.fixture
def simple_grid():
    """Three segments, two features, mixed values for round-trip
    testing."""
    return {
        "name": "Test",
        "features": ["Voice", "Nasal"],
        "segments": ["b", "d", "m"],
        # cells[feature_index][segment_index]
        "cells": [
            ["+", "+", "+"],     # Voice
            ["0", "0", "+"],     # Nasal
        ],
    }


def test_grid_to_inventory_round_trip(simple_grid):
    inv = grid_to_inventory(**simple_grid)
    assert isinstance(inv, Inventory)
    assert inv.name == "Test"
    assert inv.features == ("Voice", "Nasal")
    assert set(inv.segments.keys()) == {"b", "d", "m"}
    assert inv.segments["b"].get("Voice") == "+"
    assert inv.segments["m"].get("Nasal") == "+"
    # Zero cells were omitted; the inventory parser treats missing
    # as "0" so the round-trip is lossless.
    assert "Nasal" not in inv.segments["b"]


def test_grid_to_inventory_omits_zero_cells():
    """An all-zero column ends up with an empty per-segment dict.
    Avoids inflating sparse inventories on every save."""
    inv = grid_to_inventory(
        name="X",
        features=["F1", "F2"],
        segments=["a"],
        cells=[["0"], ["0"]],
    )
    assert inv.segments["a"] == {}


def test_grid_to_inventory_normalizes_display_minus():
    """Cells written with U+2212 land in the JSON as ASCII minus."""
    inv = grid_to_inventory(
        name="X",
        features=["Voice"],
        segments=["t"],
        cells=[[MINUS_DISPLAY]],
    )
    assert inv.segments["t"]["Voice"] == "-"


def test_grid_to_inventory_accepts_serialized_minus():
    """Pasted or loaded values may already be ASCII minus; both
    forms must work to avoid a surprise on round-trip from disk."""
    inv = grid_to_inventory(
        name="X",
        features=["Voice"],
        segments=["t"],
        cells=[["-"]],
    )
    assert inv.segments["t"]["Voice"] == "-"


def test_grid_to_inventory_rejects_wrong_row_count():
    """Row count must equal feature count. Surfaces a programming
    error in the caller before it can produce a corrupt inventory."""
    with pytest.raises(ValueError, match="cells has 1 rows, expected 2"):
        grid_to_inventory(
            name="X",
            features=["F1", "F2"],
            segments=["a"],
            cells=[["0"]],
        )


def test_grid_to_inventory_rejects_jagged_rows():
    """Every row must have the same column count as the segment
    list."""
    with pytest.raises(
        ValueError, match="cells row 1 has 1 columns, expected 2"
    ):
        grid_to_inventory(
            name="X",
            features=["F1", "F2"],
            segments=["a", "b"],
            cells=[["0", "0"], ["+"]],
        )


def test_grid_to_inventory_propagates_validation_errors():
    """Unknown cell values surface as ValidationError from the
    inventory parser, not silently as ``"0"``. The cycle ladder
    only produces ``+/-/0/U+2212`` so any other value is a bug
    worth surfacing."""
    with pytest.raises(ValidationError):
        grid_to_inventory(
            name="X",
            features=["Voice"],
            segments=["t"],
            cells=[["?"]],
        )


def test_grid_to_inventory_preserves_feature_order():
    """The serialized features list must match the input order so
    the rebuilt inventory uses the same column ordering."""
    inv = grid_to_inventory(
        name="X",
        features=["Z_first", "A_second"],
        segments=["a"],
        cells=[["+"], ["+"]],
    )
    assert inv.features == ("Z_first", "A_second")
