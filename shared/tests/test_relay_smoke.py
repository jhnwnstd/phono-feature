"""The build script that bakes shared Python constants into the
web bundle has its own internal assertions; a green build is the
gate. This smoke test confirms that the artifacts the renderer
reads end up populated, without pinning any specific value (which
would just block iteration on the values themselves).

Replaces the per-constant relay tests in test_status_text_relay,
test_chart_style_relay, and test_limits_relay, none of which
caught a bug that the build script's own KeyError checks would
not have caught a step earlier.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DIST = _REPO_ROOT / "web" / "dist"


@pytest.fixture(scope="session")
def built_dist() -> Path:
    if not _DIST.exists():
        subprocess.run(
            [sys.executable, "web/scripts/build.py"],
            cwd=_REPO_ROOT,
            check=True,
            capture_output=True,
        )
    return _DIST


def test_layout_css_populated(built_dist: Path) -> None:
    matches = list(built_dist.glob("layout.*.css"))
    assert matches, "build did not produce a layout css file"
    css = matches[0].read_text(encoding="utf-8")
    assert "--vowel-chart-title-h" in css
    assert "--seg-btn-w" in css


def test_chart_style_inline_json(built_dist: Path) -> None:
    html = (built_dist / "index.html").read_text(encoding="utf-8")
    match = re.search(
        r'<script id="chart-style"[^>]*>(.+?)</script>',
        html,
        re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1))
    for key in (
        "diphthong_lift_chord_frac",
        "diphthong_arrowhead_len_frac",
        "silhouette_corner_radius_frac",
    ):
        assert key in payload


def test_status_text_inline_json(built_dist: Path) -> None:
    html = (built_dist / "index.html").read_text(encoding="utf-8")
    match = re.search(
        r'<script id="status-text"[^>]*>(.+?)</script>',
        html,
        re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1))
    assert "clipboard_copy_template" in payload


def test_limits_inline_json(built_dist: Path) -> None:
    html = (built_dist / "index.html").read_text(encoding="utf-8")
    match = re.search(
        r'<script id="limits"[^>]*>(.+?)</script>',
        html,
        re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1))
    for key in ("max_segments", "max_features"):
        assert key in payload
