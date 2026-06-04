"""Hash-pin parity gates for JS pre-bridge fallback algorithms.

``web/main.js`` keeps three local mirrors of Python helpers so the
UI can render the first frame before Pyodide finishes mounting
(~200 ms of "blank screen" otherwise). The mirrors must stay
algorithmically in lockstep with the canonical Python.

The contract here is the hash pin: if the JS body changes, the
hash test fails with the new hash. The editor MUST then verify
the corresponding Python helper still matches; once they do, they
update ``EXPECTED_BODY_HASHES``. The hash pin is the load-bearing
parity gate and the only one this file enforces -- the previous
fuzz-with-python-translation belt-and-suspenders was 250+ lines of
test code for a trade-off the project doesn't need.

The mirrored functions:

* ``_fallbackBestNCols`` mirrors ``layout.best_segment_n_cols``.
* ``_fallbackPartitionSpillover`` mirrors
  ``layout.partition_groups_for_spillover``.
* ``classifyEditorSelection`` mirrors
  ``grid_logic.classify_selection``. The editor's remove-button
  enable rules key on its output.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

MAIN_JS = Path(__file__).resolve().parents[2] / "web" / "main.js"

EXPECTED_BODY_HASHES = {
    "_fallbackBestNCols": (
        "44d9f338eb3cdfac2ea2ca57906a6ad06b603be00e1cf78597fddb2e229013e4"
    ),
    "_fallbackPartitionSpillover": (
        "50af36a8c3916cb6b61cdd2b9cab4e39387324364a448b8c61a5479a14c83ef3"
    ),
    "classifyEditorSelection": (
        "5a54ebca4044fdd6e95e91dcf8fe3b2f1750821f156e0b3ba7bf52461b617086"
    ),
}


def _normalise(src: str) -> str:
    """Strip comments + collapse whitespace so cosmetic JS reformat
    doesn't trip the hash."""
    no_block = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    no_line = re.sub(r"//[^\n]*", "", no_block)
    return re.sub(r"\s+", " ", no_line).strip()


def _extract_js_body(fn_name: str) -> str:
    """Pull one JS function's source out of ``web/main.js``.
    Anchored on ``function NAME(``; reads forward to the balanced
    closing brace."""
    src = MAIN_JS.read_text(encoding="utf-8")
    start = re.search(
        rf"function\s+{re.escape(fn_name)}\s*\([^)]*\)\s*\{{", src
    )
    assert start is not None, f"{fn_name!r} not found in main.js"
    i = start.end()
    depth = 1
    while i < len(src) and depth > 0:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    return src[start.end() : i - 1]


@pytest.mark.parametrize("fn_name", list(EXPECTED_BODY_HASHES))
def test_js_fallback_body_hash_pinned(fn_name: str) -> None:
    """If the hash fails, the JS body changed; verify the
    canonical Python helper still matches algorithmically, then
    update ``EXPECTED_BODY_HASHES`` with the new digest from the
    failure message."""
    body = _extract_js_body(fn_name)
    digest = hashlib.sha256(_normalise(body).encode("utf-8")).hexdigest()
    expected = EXPECTED_BODY_HASHES[fn_name]
    assert digest == expected, (
        f"{fn_name} body changed in main.js; if intentional, set "
        f"EXPECTED_BODY_HASHES[{fn_name!r}] = {digest!r} and verify "
        f"the canonical Python helper still reflects the same "
        f"algorithm. Old: {expected}"
    )


def test_selection_shape_remove_target_js_matches_python() -> None:
    """The JS ``SELECTION_SHAPE_REMOVE_TARGET`` literal must agree
    with ``grid_logic.SELECTION_SHAPE_REMOVE_TARGET``. If either
    side gains a new shape mapping, this test forces the other to
    follow."""
    from phonology_shared.editor.grid import (
        SELECTION_SHAPE_REMOVE_TARGET,
    )

    src = MAIN_JS.read_text(encoding="utf-8")
    match = re.search(
        r"const SELECTION_SHAPE_REMOVE_TARGET\s*=\s*Object\.freeze\(\s*"
        r"\{(?P<body>.+?)\}\s*\)\s*;",
        src,
        re.DOTALL,
    )
    assert (
        match is not None
    ), "SELECTION_SHAPE_REMOVE_TARGET literal not found in main.js"
    pair_re = re.compile(r'"(?P<k>[^"]+)"\s*:\s*"(?P<v>[^"]+)"')
    js_table = {m["k"]: m["v"] for m in pair_re.finditer(match["body"])}
    py_table = {
        k: v for k, v in SELECTION_SHAPE_REMOVE_TARGET.items() if v is not None
    }
    assert js_table == py_table, (
        f"SELECTION_SHAPE_REMOVE_TARGET drift: "
        f"JS={js_table!r}, Python={py_table!r}"
    )
