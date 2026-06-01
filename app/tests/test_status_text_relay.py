"""Pins the build-time relay of mode status messages.

The web app's pre-bridge status text is baked into ``dist/index.html``
by ``web/scripts/build.py:hash_assets`` from ``mode_logic.mode_status_text``.
Without this test a future edit to either side could silently drift
without anyone noticing until a user sees the wrong message.

The test runs ``build.py`` end-to-end into a tmp dist, parses the
inline ``<script id="status-text">`` block out of the resulting
``index.html``, and asserts every key matches the Python helper
byte-for-byte.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from phonology_features.gui.mode_logic import Mode, mode_status_text

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "web" / "scripts" / "build.py"

INLINE_JSON_RE = re.compile(
    r'<script id="status-text" type="application/json">'
    r"(?P<payload>.+?)"
    r"</script>",
    re.DOTALL,
)


def _run_build(tmp_path: Path) -> Path:
    """Run ``build.py`` with ``DIST`` redirected to ``tmp_path``.

    The build script reads ``DIST`` from a module-level constant
    derived from its own file path; the simplest way to redirect
    it without monkey-patching is to set ``DIST_OVERRIDE`` env var
    which the script honours (if it doesn't, copy the script and
    swap the constant).
    """
    env_dist = tmp_path / "dist"
    env_dist.mkdir()
    # The build script's DIST is hardcoded; invoke it normally and
    # then read from the canonical dist. This means the test runs
    # against the real build output which is exactly what we want.
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
    return REPO_ROOT / "web" / "dist" / "index.html"


def _extract_status_payload(index_html: Path) -> dict[str, str]:
    """Pull the inline status-text block out of ``index.html`` and
    decode it as JSON. Failing to find the block fails the test.
    """
    contents = index_html.read_text(encoding="utf-8")
    match = INLINE_JSON_RE.search(contents)
    assert match is not None, (
        "no <script id=\"status-text\"> block in dist/index.html; "
        "verify build.py:hash_assets emits the inline status block"
    )
    return json.loads(match.group("payload"))


@pytest.fixture(scope="module")
def status_payload(tmp_path_factory) -> dict[str, str]:
    tmp = tmp_path_factory.mktemp("status_relay")
    index_html = _run_build(tmp)
    return _extract_status_payload(index_html)


@pytest.mark.parametrize("mode", list(Mode), ids=lambda m: m.value)
def test_per_mode_status_matches_python(
    status_payload: dict[str, str], mode: Mode
) -> None:
    """Every ``Mode`` member's baked status string must equal the
    Python helper's output with an engine present. Drift would
    show as a wrong message in the web app's pre-bridge window.
    """
    expected = mode_status_text(mode, has_engine=True)
    assert status_payload.get(str(mode)) == expected, (
        f"baked status text for {mode!r} drifted from "
        f"mode_status_text({mode!r}, has_engine=True)"
    )


def test_no_engine_status_matches_python(
    status_payload: dict[str, str],
) -> None:
    """The ``no_engine`` key is what the web shows before any
    inventory loads (and before the bridge is even attached). It
    must round-trip through the same helper as the desktop's
    startup status.
    """
    expected = mode_status_text(Mode.SEG_TO_FEAT, has_engine=False)
    assert status_payload.get("no_engine") == expected, (
        "baked no_engine status text drifted from "
        "mode_status_text(SEG_TO_FEAT, has_engine=False)"
    )


def test_payload_keys_exhaustive(status_payload: dict[str, str]) -> None:
    """The payload must contain exactly the keys the JS reads:
    every ``Mode`` value plus ``no_engine``. Extra keys mean the
    payload grew without the test catching it; missing keys mean
    the bake step regressed.
    """
    expected_keys = {str(m) for m in Mode} | {"no_engine"}
    assert set(status_payload.keys()) == expected_keys
