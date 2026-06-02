"""Cross-tests for the three JS pre-bridge fallback algorithms.

``web/main.js`` keeps three local mirrors of Python helpers so the
UI can render the first frame before Pyodide finishes mounting
(~200 ms of "blank screen" otherwise). The mirrors are required;
the risk is that a future edit to the Python helper silently drifts
from its JS mirror and the pre-bridge frame renders subtly wrong.

These tests pin both ends:

* the JS function body (extracted by regex from ``web/main.js``)
  is hashed; if the body changes the test fails with the new hash
  so the editor must look at the corresponding Python helper too;
* a Python re-implementation of the JS algorithm (kept here next
  to the canonical Python) is fuzzed against the canonical helper
  to prove both ends agree on a representative input grid.

If you edit a JS fallback, regenerate the hash with
``pytest --update-goldens`` (or by reading the failure output) and
update the Python re-implementation here to match. The fuzz check
will then prove the new behaviour matches the canonical Python.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from phonology_features.gui import layout

MAIN_JS = Path(__file__).resolve().parents[2] / "web" / "main.js"

# Each entry: (function name in JS, sha256 hex of normalised body).
# Update the hash when you intentionally edit the JS body; the
# corresponding Python mirror at the bottom of this file must move
# in lockstep, and the fuzz check then proves both are right.
EXPECTED_BODY_HASHES = {
    "_fallbackBestNCols": (
        "44d9f338eb3cdfac2ea2ca57906a6ad06b603be00e1cf78597fddb2e229013e4"
    ),
    "_fallbackPartitionSpillover": (
        "50af36a8c3916cb6b61cdd2b9cab4e39387324364a448b8c61a5479a14c83ef3"
    ),
    # ``classifyEditorSelection`` mirrors ``grid_logic.classify_selection``
    # so the editor's ``- Segment`` / ``- Feature`` enable rules
    # match the desktop. Running through the bridge per shift-drag
    # would lag; the parity-tested local mirror is the trade-off.
    "classifyEditorSelection": (
        "5a54ebca4044fdd6e95e91dcf8fe3b2f1750821f156e0b3ba7bf52461b617086"
    ),
}


def _normalise(src: str) -> str:
    """Collapse runs of whitespace so cosmetic reformat doesn't trip
    the hash check. Comments are stripped so doc edits don't either.
    """
    no_block_comments = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    no_line_comments = re.sub(r"//[^\n]*", "", no_block_comments)
    return re.sub(r"\s+", " ", no_line_comments).strip()


def _extract_js_body(fn_name: str) -> str:
    """Pull one JS function's source out of ``web/main.js``.

    Anchored on the ``function NAME(`` declaration; reads forward
    until a balanced closing brace ends the body. Brittle to clever
    bracing in the body itself; the three target fallbacks are
    plain function declarations with simple bodies.
    """
    src = MAIN_JS.read_text(encoding="utf-8")
    start = re.search(
        rf"function\s+{re.escape(fn_name)}\s*\([^)]*\)\s*\{{",
        src,
    )
    assert start is not None, f"{fn_name!r} not found in main.js"
    i = start.end()
    depth = 1
    while i < len(src) and depth > 0:
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    return src[start.end() : i - 1]


@pytest.mark.parametrize("fn_name", list(EXPECTED_BODY_HASHES))
def test_js_fallback_body_hash_pinned(fn_name: str) -> None:
    """Hash the JS body to flag any edit that wasn't paired with a
    corresponding update to the Python mirror below.

    Whitespace and comments are stripped before hashing so cosmetic
    edits don't fire. If you intentionally changed the algorithm,
    update ``EXPECTED_BODY_HASHES`` and the corresponding mirror.
    """
    body = _extract_js_body(fn_name)
    digest = hashlib.sha256(_normalise(body).encode("utf-8")).hexdigest()
    expected = EXPECTED_BODY_HASHES[fn_name]
    assert digest == expected, (
        f"{fn_name} body changed in main.js; if intentional, set "
        f"EXPECTED_BODY_HASHES[{fn_name!r}] = {digest!r} and verify "
        f"the corresponding Python mirror in this test file still "
        f"reflects the algorithm. Old: {expected}"
    )


# ----------------------------------------------------------------------
# Python re-implementations of the JS fallbacks.
#
# These are intentionally separate from the canonical Python helpers
# (layout.best_segment_n_cols, layout.partition_groups_for_spillover)
# and are kept in lockstep with the JS bodies above. The fuzz tests
# below assert that the JS mirror, the JS-mirror-as-Python, and the
# canonical Python all produce the same output.
# ----------------------------------------------------------------------


def _js_best_n_cols(group_size: int, max_cols: int) -> int:
    """Python translation of ``_fallbackBestNCols`` in main.js."""
    if group_size <= 0:
        return 1
    if max_cols <= 1:
        return 1
    if group_size <= max_cols:
        return group_size
    for n in range(max_cols, 1, -1):
        r = group_size % n
        if r == 0 or r >= 2:
            return n
    return max_cols


def _js_partition_spillover(
    heights: list[int], available: int, n_cols: int = 2
) -> int:
    """Python translation of ``_fallbackPartitionSpillover`` in main.js."""
    n = len(heights)
    if n == 0 or available <= 0:
        return n

    def fits(main_count: int) -> bool:
        h = sum(heights[:main_count])
        spill = heights[main_count:]
        for i in range(0, len(spill), n_cols):
            h += max(spill[i : i + n_cols])
        return h <= available

    main_count = n
    while main_count > 0 and not fits(main_count):
        main_count -= 1
    return main_count


# ----------------------------------------------------------------------
# Fuzz parity: the JS mirror (as Python) must equal the canonical
# Python for every input the algorithm could see in production.
# ----------------------------------------------------------------------


@pytest.mark.parametrize("group_size", list(range(0, 30)))
@pytest.mark.parametrize("max_cols", list(range(1, 16)))
def test_best_n_cols_js_matches_python(group_size: int, max_cols: int) -> None:
    """``_fallbackBestNCols`` must match ``layout.best_segment_n_cols``
    for every (group_size, max_cols) pair the UI can ask about. Range
    chosen to cover the largest bundled inventory's manner-class
    cardinality and the widest realistic column count.
    """
    assert _js_best_n_cols(group_size, max_cols) == layout.best_segment_n_cols(
        group_size, max_cols
    )


def _js_classify_editor_selection(
    cells: list[tuple[int, int]], num_rows: int, num_cols: int
) -> dict[str, object]:
    """Python translation of ``classifyEditorSelection`` in main.js.

    Returns the same shape the JS function returns (``{kind, row,
    column}`` where ``row`` / ``column`` may be absent for shapes
    that don't name a single index). Kept here next to the hash
    pin so a JS edit forces a corresponding update; the fuzz
    parametrisation below then proves both agree with
    ``grid_logic.classify_selection``.
    """
    sel = list(set(cells))
    n = len(sel)
    if n == 0:
        return {"kind": "empty"}
    if n == 1:
        r, c = sel[0]
        return {"kind": "single_cell", "row": r, "column": c}
    cols = {c for _, c in sel}
    rows = {r for r, _ in sel}
    the_col = next(iter(cols)) if len(cols) == 1 else None
    the_row = next(iter(rows)) if len(rows) == 1 else None
    r_min = min(r for r, _ in sel)
    r_max = max(r for r, _ in sel)
    c_min = min(c for _, c in sel)
    c_max = max(c for _, c in sel)
    if num_rows > 0 and the_col is not None and n == num_rows:
        return {"kind": "single_column", "column": the_col}
    if num_cols > 0 and the_row is not None and n == num_cols:
        return {"kind": "single_row", "row": the_row}
    if num_rows > 0 and num_cols > 0 and n == num_rows * num_cols:
        return {"kind": "full_grid"}
    rect_size = (r_max - r_min + 1) * (c_max - c_min + 1)
    if n == rect_size:
        return {"kind": "rectangle"}
    return {"kind": "irregular"}


@pytest.mark.parametrize(
    "heights",
    [
        [],
        [40],
        [40, 40],
        [40, 60, 40, 100, 40],
        [120, 80, 60, 40, 90, 110, 70, 50],
        [50] * 20,
        [200, 80, 60, 80, 200, 60, 80],
    ],
)
@pytest.mark.parametrize("available", [0, 100, 200, 400, 600, 900])
def test_partition_spillover_js_matches_python(
    heights: list[int], available: int
) -> None:
    """``_fallbackPartitionSpillover`` must match
    ``layout.partition_groups_for_spillover`` for representative
    height arrays and panel sizes. Heights chosen to cover the
    cases the seg-pane spillover rebalancer hits on the bundled
    inventories.
    """
    assert _js_partition_spillover(
        heights, available
    ) == layout.partition_groups_for_spillover(heights, available)


# ----------------------------------------------------------------------
# Editor selection-shape classifier parity.
# ``classifyEditorSelection`` (main.js) mirrors
# ``grid_logic.classify_selection`` so the editor's remove-button
# enable rules stay in lockstep with the desktop. Bridge calls per
# shift-drag would lag; the parity check below is what keeps the
# two sides aligned.
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,num_rows,num_cols,cells,expected_kind",
    [
        ("empty", 4, 3, [], "empty"),
        ("single-cell", 4, 3, [(1, 1)], "single_cell"),
        (
            "single-column-fills",
            3,
            3,
            [(0, 1), (1, 1), (2, 1)],
            "single_column",
        ),
        # A 3-cell contiguous run inside a 4x3 grid is a 3x1
        # rectangle, NOT single_column (single_column requires
        # selection.count == num_rows, i.e. the entire column).
        (
            "rectangle-3-tall-1-wide",
            4,
            3,
            [(0, 1), (1, 1), (2, 1)],
            "rectangle",
        ),
        (
            "single-row-fills",
            3,
            3,
            [(0, 0), (0, 1), (0, 2)],
            "single_row",
        ),
        # A 3-cell horizontal run inside a 3x4 grid covers 3 of 4
        # columns, so it's a 1x3 rectangle, NOT single_row.
        (
            "rectangle-1-tall-3-wide",
            3,
            4,
            [(0, 0), (0, 1), (0, 2)],
            "rectangle",
        ),
        (
            "full-grid-2x2",
            2,
            2,
            [(0, 0), (0, 1), (1, 0), (1, 1)],
            "full_grid",
        ),
        (
            "rectangle-2x3-in-4x4",
            4,
            4,
            [(1, 1), (1, 2), (1, 3), (2, 1), (2, 2), (2, 3)],
            "rectangle",
        ),
        (
            "irregular-L-shape",
            4,
            4,
            [(0, 0), (1, 0), (2, 0), (3, 0), (3, 1), (3, 2)],
            "irregular",
        ),
        (
            "irregular-diagonal",
            3,
            3,
            [(0, 0), (1, 1), (2, 2)],
            "irregular",
        ),
        # Degenerate 1-row grid: cells fill the entire grid; the
        # single_column check needs len(cols)==1 which is false
        # here, so single_row wins. Mirrors the JS body's check
        # order; both surfaces agree because the python-translation
        # follows the same condition sequence.
        ("degenerate-1x3", 1, 3, [(0, 0), (0, 1), (0, 2)], "single_row"),
        ("degenerate-3x1", 3, 1, [(0, 0), (1, 0), (2, 0)], "single_column"),
    ],
)
def test_classify_selection_js_python_canonical_three_way_agreement(
    name: str,
    num_rows: int,
    num_cols: int,
    cells: list[tuple[int, int]],
    expected_kind: str,
) -> None:
    """The JS classifier, its Python translation, and the canonical
    Python helper must all agree on every representative shape. A
    drift in any one surface trips this test before users see a
    desktop / web disagreement on the remove-button enable rules.
    """
    from phonology_features.gui.grid_logic import classify_selection

    canonical = classify_selection(cells, num_rows, num_cols)
    js_translation = _js_classify_editor_selection(cells, num_rows, num_cols)
    assert canonical.kind == expected_kind, (
        f"{name}: canonical Python returned {canonical.kind!r}, "
        f"expected {expected_kind!r}"
    )
    assert js_translation["kind"] == canonical.kind, (
        f"{name}: JS translation returned {js_translation['kind']!r}, "
        f"canonical Python returned {canonical.kind!r}"
    )
    # When the shape names a single index, both surfaces must agree
    # on which row / column.
    if canonical.row is not None:
        assert js_translation.get("row") == canonical.row, (
            f"{name}: row mismatch: JS={js_translation.get('row')!r}, "
            f"canonical={canonical.row!r}"
        )
    if canonical.column is not None:
        assert js_translation.get("column") == canonical.column, (
            f"{name}: column mismatch: JS={js_translation.get('column')!r}, "
            f"canonical={canonical.column!r}"
        )


def test_selection_shape_remove_target_js_matches_python() -> None:
    """The JS ``SELECTION_SHAPE_REMOVE_TARGET`` literal (an
    ``Object.freeze({...})`` in main.js) maps each shape kind to
    ``"segment"`` or ``"feature"`` (or absent for "no remove
    available"). The desktop's
    ``grid_logic.SELECTION_SHAPE_REMOVE_TARGET`` is the canonical
    source; if either side gains a new shape mapping, this test
    forces the other side to follow.
    """
    from phonology_features.gui.grid_logic import (
        SELECTION_SHAPE_REMOVE_TARGET,
    )

    src = MAIN_JS.read_text(encoding="utf-8")
    match = re.search(
        r"const SELECTION_SHAPE_REMOVE_TARGET\s*=\s*Object\.freeze\(\s*"
        r"\{(?P<body>.+?)\}\s*\)\s*;",
        src,
        re.DOTALL,
    )
    assert match is not None, (
        "SELECTION_SHAPE_REMOVE_TARGET literal not found in main.js; "
        "if the literal was renamed, update this test's regex"
    )
    body = match.group("body")
    # Parse the simple key: value pairs (quoted strings on both
    # sides). The literal is small and stable; a real JS parser
    # would be overkill.
    pair_re = re.compile(r'"(?P<k>[^"]+)"\s*:\s*"(?P<v>[^"]+)"')
    js_table = {m.group("k"): m.group("v") for m in pair_re.finditer(body)}
    py_table = dict(SELECTION_SHAPE_REMOVE_TARGET)
    # Filter out None-valued shapes from the Python side: the JS
    # literal only enumerates the "enables a remove button" cases
    # and treats absent keys as None via ``?? null`` at lookup time.
    py_table = {k: v for k, v in py_table.items() if v is not None}
    assert js_table == py_table, (
        f"SELECTION_SHAPE_REMOVE_TARGET drift: JS={js_table!r}, "
        f"Python={py_table!r}"
    )
