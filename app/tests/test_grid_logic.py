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
    MAX_UNDO_DEPTH,
    MINUS_DISPLAY,
    MINUS_SERIALIZED,
    MOVE_KEYS,
    VALUE_KEYS,
    confirm_remove_feature_prompt,
    confirm_remove_segment_prompt,
    cycle_value,
    grid_to_inventory,
    normalize_minus,
    validate_new_feature_label,
    validate_new_segment_label,
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


# VALUE_KEYS: direct-entry keyboard shortcut data, shared with web JS


def test_value_keys_covers_plus_minus_zero():
    """The shortcut set maps every key the cycle ladder produces,
    plus an extra zero alias on the ``0`` key. Documents the
    contract so adding a new value to the cycle without wiring a
    shortcut breaks this test."""
    assert set(VALUE_KEYS.values()) == {"+", MINUS_DISPLAY, "0"}


def test_value_keys_uses_display_minus_not_ascii():
    """The shortcut value must be the display form (U+2212) so
    cells written via the keyboard render identically to cells
    written via the click cycle."""
    assert VALUE_KEYS["2"] == MINUS_DISPLAY


def test_value_keys_zero_and_three_both_produce_zero():
    """Both keys are alias entries for ``0``: ``3`` is the ladder
    position, ``0`` is the natural keyboard slot for "zero"."""
    assert VALUE_KEYS["0"] == "0"
    assert VALUE_KEYS["3"] == "0"


def test_value_keys_is_read_only():
    """Same MappingProxyType guarantee as CYCLE_LADDER: callers
    cannot mutate the singleton and silently change behavior."""
    with pytest.raises(TypeError):
        VALUE_KEYS["1"] = "?"  # type: ignore[index]


# MOVE_KEYS: cell-cursor navigation shortcuts


def test_move_keys_cover_all_four_directions():
    """One Vim, one numpad, and one arrow entry per direction.
    Documents the contract so changing the binding scheme breaks
    this test."""
    directions = {tuple(step) for step in MOVE_KEYS.values()}
    assert directions == {(-1, 0), (1, 0), (0, -1), (0, 1)}


def test_move_keys_vim_numpad_arrow_pairs_match():
    """Each direction has a Vim, a numpad, AND an arrow binding
    that produce the same (dr, dc) step. Users on any of the three
    input vocabularies see identical behavior."""
    assert (
        MOVE_KEYS["h"] == MOVE_KEYS["4"] == MOVE_KEYS["ArrowLeft"] == (0, -1)
    )
    assert MOVE_KEYS["j"] == MOVE_KEYS["5"] == MOVE_KEYS["ArrowDown"] == (1, 0)
    assert MOVE_KEYS["k"] == MOVE_KEYS["8"] == MOVE_KEYS["ArrowUp"] == (-1, 0)
    assert (
        MOVE_KEYS["l"] == MOVE_KEYS["6"] == MOVE_KEYS["ArrowRight"] == (0, 1)
    )


def test_move_keys_arrow_names_use_js_event_key_format():
    """The arrow entries use the same string format JS reports as
    ``event.key`` so the web handler can match without translation.
    The desktop translates these to ``Qt.Key.Key_<X>`` via the
    ``_ARROW_NAME_TO_QT`` table in builder/window.py."""
    for name in ("ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"):
        assert name in MOVE_KEYS, f"missing arrow binding: {name}"


def test_move_keys_is_read_only():
    with pytest.raises(TypeError):
        MOVE_KEYS["h"] = (0, 0)  # type: ignore[index]


# MAX_UNDO_DEPTH: shared with the web editor


def test_max_undo_depth_is_a_positive_int():
    """A positive int cap. The value is documented to be ~200
    batches; this test guards against a typo (e.g. 0 or negative)
    that would make undo silently inert."""
    assert isinstance(MAX_UNDO_DEPTH, int)
    assert MAX_UNDO_DEPTH > 0


def test_max_undo_depth_re_exported_by_builder_edits():
    """The desktop's ``_MAX_UNDO_DEPTH`` alias points at the same
    integer. Web editor caps its own JS stack to this value
    through the bridge."""
    from phonology_features.gui.builder.edits import _MAX_UNDO_DEPTH

    assert (
        _MAX_UNDO_DEPTH is MAX_UNDO_DEPTH or _MAX_UNDO_DEPTH == MAX_UNDO_DEPTH
    )


# validate_new_segment_label / validate_new_feature_label


def test_validate_new_segment_label_trims_whitespace():
    assert validate_new_segment_label("  p  ", []) == "p"


def test_validate_new_segment_label_rejects_empty():
    with pytest.raises(ValueError, match="empty"):
        validate_new_segment_label("   ", [])


def test_validate_new_segment_label_rejects_duplicate():
    """The error message embeds the offending label so the user
    knows which entry conflicts. The wording must match the
    desktop's prior inline message so both frontends produce the
    same status-bar text."""
    with pytest.raises(ValueError, match="already exists"):
        validate_new_segment_label("p", ["p", "b", "t"])


def test_validate_new_segment_label_duplicate_uses_trimmed_form():
    """Trim runs BEFORE the dupe check, so leading/trailing
    whitespace doesn't smuggle a duplicate past the check."""
    with pytest.raises(ValueError, match="'p'"):
        validate_new_segment_label("  p  ", ["p"])


def test_validate_new_segment_label_accepts_new_label():
    assert validate_new_segment_label("ɡ", ["p", "b", "t"]) == "ɡ"


def test_validate_new_feature_label_trims_and_dedupes():
    assert validate_new_feature_label(" Voice ", ["Nasal"]) == "Voice"
    with pytest.raises(ValueError, match="empty"):
        validate_new_feature_label("", [])
    with pytest.raises(ValueError, match="'Voice'"):
        validate_new_feature_label("Voice", ["Voice"])


def test_validate_new_segment_label_catches_nfc_duplicates():
    """U+00E9 (precomposed é) and ``e`` + U+0301 (combining acute)
    look identical on screen but are distinct code points. The
    inventory parser rejects them as duplicates after NFC
    normalization; this validator catches them at add-time so the
    user sees the conflict before commit.

    Building the decomposed form explicitly is necessary because
    Python string literals stored in this source file end up NFC
    even when typed as a decomposed sequence (the file editor
    may have folded them on save).
    """
    import unicodedata as ud

    precomposed = ud.normalize("NFC", "é")
    decomposed = ud.normalize("NFD", "é")
    assert precomposed != decomposed
    with pytest.raises(ValueError, match="already exists"):
        validate_new_segment_label(decomposed, [precomposed])


def test_validate_new_feature_label_catches_nfc_duplicates():
    import unicodedata as ud

    precomposed = ud.normalize("NFC", "Tensé")
    decomposed = ud.normalize("NFD", "Tensé")
    assert precomposed != decomposed
    with pytest.raises(ValueError, match="already exists"):
        validate_new_feature_label(decomposed, [precomposed])


def test_validate_new_segment_label_enforces_cap_when_provided():
    """When ``max_segments`` is passed the validator refuses adds
    that would exceed the cap. The desktop and web wrappers always
    pass the cap; calling the bare helper without one preserves
    backwards-compatible behavior."""
    with pytest.raises(ValueError, match="limit of 3 reached"):
        validate_new_segment_label("d", ["a", "b", "c"], max_segments=3)
    # Same call without the cap: succeeds.
    assert validate_new_segment_label("d", ["a", "b", "c"]) == "d"


def test_validate_new_feature_label_enforces_cap_when_provided():
    with pytest.raises(ValueError, match="limit of 2 reached"):
        validate_new_feature_label(
            "C",
            ["A", "B"],
            max_features=2,
        )


# Confirm-remove prompts: shared so the wording matches across UIs


def test_confirm_remove_segment_prompt_quotes_the_label():
    """The desktop ``ask_question`` body and the web ``confirm``
    body must produce identical text; both call this formatter."""
    assert confirm_remove_segment_prompt("p") == "Remove segment 'p'?"


def test_confirm_remove_feature_prompt_quotes_the_label():
    assert confirm_remove_feature_prompt("Voice") == "Remove feature 'Voice'?"


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
            ["+", "+", "+"],  # Voice
            ["0", "0", "+"],  # Nasal
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


# classify_selection: shared selection-shape classifier


def test_classify_selection_empty():
    from phonology_features.gui.grid_logic import (
        SELECTION_SHAPE_EMPTY,
        classify_selection,
    )

    s = classify_selection([], 5, 5)
    assert s.kind == SELECTION_SHAPE_EMPTY
    assert s.row is None and s.column is None


def test_classify_selection_single_cell():
    from phonology_features.gui.grid_logic import (
        SELECTION_SHAPE_SINGLE_CELL,
        classify_selection,
    )

    s = classify_selection([(2, 3)], 5, 5)
    assert s.kind == SELECTION_SHAPE_SINGLE_CELL
    assert s.row == 2 and s.column == 3


def test_classify_selection_single_column():
    from phonology_features.gui.grid_logic import (
        SELECTION_SHAPE_SINGLE_COLUMN,
        classify_selection,
    )

    # All rows of column 2.
    s = classify_selection([(r, 2) for r in range(5)], 5, 5)
    assert s.kind == SELECTION_SHAPE_SINGLE_COLUMN
    assert s.column == 2
    assert s.row is None


def test_classify_selection_single_row():
    from phonology_features.gui.grid_logic import (
        SELECTION_SHAPE_SINGLE_ROW,
        classify_selection,
    )

    s = classify_selection([(1, c) for c in range(5)], 5, 5)
    assert s.kind == SELECTION_SHAPE_SINGLE_ROW
    assert s.row == 1
    assert s.column is None


def test_classify_selection_full_grid():
    from phonology_features.gui.grid_logic import (
        SELECTION_SHAPE_FULL_GRID,
        classify_selection,
    )

    cells = [(r, c) for r in range(3) for c in range(4)]
    s = classify_selection(cells, 3, 4)
    assert s.kind == SELECTION_SHAPE_FULL_GRID


def test_classify_selection_rectangle():
    from phonology_features.gui.grid_logic import (
        SELECTION_SHAPE_RECTANGLE,
        classify_selection,
    )

    cells = [(r, c) for r in range(2, 4) for c in range(1, 3)]
    s = classify_selection(cells, 5, 5)
    assert s.kind == SELECTION_SHAPE_RECTANGLE


def test_classify_selection_irregular():
    """An L-shape is not a rectangle and not a single column/row."""
    from phonology_features.gui.grid_logic import (
        SELECTION_SHAPE_IRREGULAR,
        classify_selection,
    )

    cells = [(0, 0), (0, 1), (0, 2), (1, 0), (2, 0)]
    s = classify_selection(cells, 5, 5)
    assert s.kind == SELECTION_SHAPE_IRREGULAR


def test_classify_selection_partial_column_is_not_single_column():
    """Same column but missing some rows should NOT be single_column;
    that distinction is what the desktop's ``- Segment`` enable rule
    keys on."""
    from phonology_features.gui.grid_logic import (
        SELECTION_SHAPE_IRREGULAR,
        SELECTION_SHAPE_RECTANGLE,
        classify_selection,
    )

    # 3 of 5 rows in column 2: not full column.
    s = classify_selection([(0, 2), (1, 2), (2, 2)], 5, 5)
    # Three contiguous cells in one column form a 3x1 rectangle.
    assert s.kind in (
        SELECTION_SHAPE_RECTANGLE,
        SELECTION_SHAPE_IRREGULAR,
    )
    assert s.kind != "single_column"


def test_remove_target_for_shape():
    from phonology_features.gui.grid_logic import (
        SELECTION_SHAPE_FULL_GRID,
        SELECTION_SHAPE_RECTANGLE,
        SELECTION_SHAPE_SINGLE_CELL,
        SELECTION_SHAPE_SINGLE_COLUMN,
        SELECTION_SHAPE_SINGLE_ROW,
        SelectionShape,
        remove_target_for_shape,
    )

    assert (
        remove_target_for_shape(
            SelectionShape(kind=SELECTION_SHAPE_SINGLE_COLUMN, column=2)
        )
        == "segment"
    )
    assert (
        remove_target_for_shape(
            SelectionShape(kind=SELECTION_SHAPE_SINGLE_ROW, row=2)
        )
        == "feature"
    )
    # All other shapes return None.
    for kind in (
        SELECTION_SHAPE_SINGLE_CELL,
        SELECTION_SHAPE_RECTANGLE,
        SELECTION_SHAPE_FULL_GRID,
    ):
        assert remove_target_for_shape(SelectionShape(kind=kind)) is None
