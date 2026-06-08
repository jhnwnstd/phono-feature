"""Pins the build-time relay of engine hard caps to the web app.

``web/scripts/build.py:_build_limits_payload`` bakes the engine's
``MAX_INVENTORY_FILE_BYTES`` / ``MAX_SEGMENTS`` / ``MAX_FEATURES``
/ ``MAX_NAME_LENGTH`` into ``dist/index.html`` as an inline
``<script id="limits">`` block. ``web/main.js`` reads it at boot
into the ``LIMITS`` constant and uses ``LIMITS.max_inventory_file_bytes``
as the upload pre-check cap.

Without this test a future edit to
``shared/src/phonology_shared/data/limits.py`` could silently
drift from the JS pre-check (the prior bug: JS held 5 MB while
the engine held 50 MB; a 20 MB file passed the JS gate then
failed in Pyodide with a confusing generic error). The build
runs in a subprocess, the inline block is parsed back out, and
every key is asserted equal to its Python source.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from phonology_shared.data import (
    MAX_FEATURES,
    MAX_INVENTORY_FILE_BYTES,
    MAX_NAME_LENGTH,
    MAX_SEGMENTS,
)
from phonology_shared.editor.phoible_provider import (
    PHOIBLE_PREVIEW_SEGMENT_LIMIT,
)
from phonology_shared.presentation.layout import FEAT_COMPACT_THRESHOLD

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "web" / "scripts" / "build.py"

INLINE_JSON_RE = re.compile(
    r'<script id="limits" type="application/json">'
    r"(?P<payload>.+?)"
    r"</script>",
    re.DOTALL,
)


@pytest.fixture(scope="module")
def limits_payload() -> dict[str, int]:
    """Build the bundle once and return the parsed limits payload.

    The build script writes to its canonical ``web/dist/``; we read
    back from there. Module-scoped so the (slow-ish) subprocess
    build only runs once for the test file.
    """
    result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"build.py failed: {result.stderr}\n{result.stdout}"
        )
    index_html = REPO_ROOT / "web" / "dist" / "index.html"
    contents = index_html.read_text(encoding="utf-8")
    match = INLINE_JSON_RE.search(contents)
    assert match is not None, (
        'no <script id="limits"> block in dist/index.html; verify '
        "build.py:hash_assets emits the inline limits block"
    )
    return json.loads(match.group("payload"))


@pytest.mark.parametrize(
    "key,expected",
    [
        ("max_features", MAX_FEATURES),
        ("max_segments", MAX_SEGMENTS),
        ("max_name_length", MAX_NAME_LENGTH),
        ("max_inventory_file_bytes", MAX_INVENTORY_FILE_BYTES),
        (
            "phoible_preview_segment_limit",
            PHOIBLE_PREVIEW_SEGMENT_LIMIT,
        ),
        ("feat_compact_threshold", FEAT_COMPACT_THRESHOLD),
    ],
)
def test_baked_limit_matches_python(
    limits_payload: dict[str, int], key: str, expected: int
) -> None:
    """Each key in the baked payload must equal its Python source.
    Drift would silently let JS pre-checks accept files the engine
    rejects (or vice versa).
    """
    assert limits_payload.get(key) == expected, (
        f"baked LIMITS.{key} drifted from limits.{key.upper()}; "
        f"got {limits_payload.get(key)!r}, expected {expected!r}"
    )


def test_payload_keys_exhaustive(limits_payload: dict[str, int]) -> None:
    """Pin the key set so adding a new limit on either side requires
    updating both the bake and this test in lockstep.
    """
    expected_keys = {
        "max_features",
        "max_segments",
        "max_name_length",
        "max_inventory_file_bytes",
        "phoible_preview_segment_limit",
        "feat_compact_threshold",
    }
    assert set(limits_payload.keys()) == expected_keys
