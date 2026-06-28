"""Parity guard for the two editor-editor surfaces ``web/main.js``
mirrors from shared Python.

The web editor keeps two pieces of selection logic in JS for speed
(a per-click bridge hop would lag shift-drag and key-repeat):

* ``classifyEditorSelection`` mirrors
  :py:func:`phonology_shared.editor.grid.classify_selection`
* the ``SELECTION_SHAPE_REMOVE_TARGET`` object mirrors the Python
  table of the same name.

Because they are hand-mirrored, they can drift. This test runs the
REAL JS classifier (extracted from ``web/main.js`` and driven by
node) over an exhaustive set of selections on small grids and asserts
it agrees with the Python classifier cell for cell, and statically
compares the two remove-target tables. It replaces the
``test_jsfallback_parity.py`` guard that was removed for these
surfaces. Edit either side without the other and this fails loudly.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from itertools import combinations
from pathlib import Path

import pytest

from phonology_shared.editor.grid import (
    SELECTION_SHAPE_REMOVE_TARGET,
    classify_selection,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WEB_MAIN_JS = _REPO_ROOT / "web" / "main.js"


def _extract(pattern: str) -> str:
    """Pull one source span out of ``web/main.js`` or fail with a
    message that names what went missing (a rename should update this
    test, not silently match nothing)."""
    src = _WEB_MAIN_JS.read_text(encoding="utf-8")
    m = re.search(pattern, src, re.DOTALL)
    assert m is not None, f"could not locate /{pattern}/ in web/main.js"
    return m.group(0)


def test_remove_target_table_matches() -> None:
    """The JS ``SELECTION_SHAPE_REMOVE_TARGET`` object must equal the
    Python table value for value."""
    block = _extract(
        r"const SELECTION_SHAPE_REMOVE_TARGET = Object\.freeze\(\{.*?\}\)"
    )
    js_pairs = dict(re.findall(r'"([a-z_]+)":\s*"([a-z]+)"', block))
    py_pairs = {k.value: v for k, v in SELECTION_SHAPE_REMOVE_TARGET.items()}
    assert js_pairs == py_pairs, (
        "JS and Python remove-target tables drifted; reconcile "
        "web/main.js SELECTION_SHAPE_REMOVE_TARGET with "
        "shared/editor/grid.py."
    )


# Every grid shape that exercises a distinct branch of the classifier:
# 1x1 (a true single cell), degenerate 1xN / Nx1 (where one cell is a
# whole row/column), and 2x2 / 2x3 / 3x3 (full grid, rectangle,
# irregular). Subsets are enumerated exhaustively per shape below.
_GRID_DIMS = [
    (1, 1),
    (1, 2),
    (2, 1),
    (1, 3),
    (3, 1),
    (2, 2),
    (2, 3),
    (3, 2),
    (3, 3),
]


def _all_cases() -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for nr, nc in _GRID_DIMS:
        all_cells = [(r, c) for r in range(nr) for c in range(nc)]
        for k in range(len(all_cells) + 1):
            for combo in combinations(all_cells, k):
                cases.append(
                    {
                        "numRows": nr,
                        "numCols": nc,
                        "cells": [list(rc) for rc in combo],
                    }
                )
    return cases


def _py_shape(case: dict[str, object]) -> dict[str, object]:
    shape = classify_selection(
        [tuple(c) for c in case["cells"]],  # type: ignore[misc]
        case["numRows"],  # type: ignore[arg-type]
        case["numCols"],  # type: ignore[arg-type]
    )
    return {"kind": shape.kind.value, "row": shape.row, "column": shape.column}


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_classify_selection_js_matches_python(tmp_path: Path) -> None:
    """Drive the real ``classifyEditorSelection`` over every selection
    on the grids in ``_GRID_DIMS`` and require it to match
    ``classify_selection`` exactly."""
    classifier = _extract(
        r"\nfunction classifyEditorSelection\(\) \{.*?\n\}\n"
    )
    parse = _extract(r"const parseCellKey = \(key\) => \{.*?\n\};")
    harness = (
        "const editorState = "
        "{features: [], segments: [], selected: new Set()};\n"
        + parse
        + "\n"
        + classifier
        + "\n"
        "const cases = JSON.parse("
        "require('fs').readFileSync(process.argv[2], 'utf8'));\n"
        "const out = cases.map(({numRows, numCols, cells}) => {\n"
        "  editorState.features = Array(numRows).fill(0);\n"
        "  editorState.segments = Array(numCols).fill(0);\n"
        "  editorState.selected = new Set(cells.map(([r, c]) => r + ',' + c));"
        "\n"
        "  const s = classifyEditorSelection();\n"
        "  return {kind: s.kind, row: s.row ?? null,"
        " column: s.column ?? null};\n"
        "});\n"
        "process.stdout.write(JSON.stringify(out));\n"
    )
    cases = _all_cases()
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps(cases), encoding="utf-8")
    harness_file = tmp_path / "harness.cjs"
    harness_file.write_text(harness, encoding="utf-8")
    proc = subprocess.run(
        ["node", str(harness_file), str(cases_file)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"node harness failed:\n{proc.stderr}"
    js_out = json.loads(proc.stdout)
    assert len(js_out) == len(cases)
    mismatches = [
        (case, js, _py_shape(case))
        for case, js in zip(cases, js_out)
        if js != _py_shape(case)
    ]
    assert not mismatches, (
        f"{len(mismatches)} classify_selection JS/Python mismatches; "
        f"first: {mismatches[0]}"
    )
