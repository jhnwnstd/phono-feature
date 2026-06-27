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
        "silhouette_corner_radius_frac",
        "vowel_cell_dense_threshold",
        "vowel_btn_min_h_px",
    ):
        assert key in payload


def _status_text_payload(built_dist: Path) -> dict:
    html = (built_dist / "index.html").read_text(encoding="utf-8")
    match = re.search(
        r'<script id="status-text"[^>]*>(.+?)</script>',
        html,
        re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group(1))


def test_status_text_inline_json(built_dist: Path) -> None:
    payload = _status_text_payload(built_dist)
    assert "clipboard_copy_template" in payload


def test_enum_value_tables_relayed(built_dist: Path) -> None:
    """Every Python enum member that main.js mirrors as a defensive
    pre-bridge fallback must appear, name and value, in the baked
    status-text payload. This is the parity guard the MODE / theme /
    palette / match-mode fallbacks in main.js advertise: a rename to
    a Python enum member trips HERE rather than silently drifting the
    JS fallback until a user clicks. (Replaces the per-constant
    test_status_text_relay guard the build comments used to cite.)
    """
    from phonology_shared.presentation.mode_logic import Mode
    from phonology_shared.presentation.palette import PaletteMode, Theme
    from phonology_shared.theory.feature_engine import MatchMode

    payload = _status_text_payload(built_dist)
    tables = {
        "mode_values": Mode,
        "theme_values": Theme,
        "palette_mode_values": PaletteMode,
        "match_mode_values": MatchMode,
    }
    for key, enum in tables.items():
        baked = payload.get(key)
        assert baked, f"{key} missing or empty in status-text payload"
        for member in enum:
            assert baked.get(member.name) == member.value, (
                f"{key} drifted: Python {member.name}={member.value!r} "
                f"not relayed (payload has {baked.get(member.name)!r})"
            )


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
