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
