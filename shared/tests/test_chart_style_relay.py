"""Pins the build-time relay of vowel-chart visual policy.

The shared module
:py:mod:`phonology_shared.presentation.chart_style` is the single
source of truth for the vowel chart's visual constants: title font /
padding / letter-spacing, axis labels, contrast-set spacing,
silhouette outline + alpha, diphthong arrow stroke + opacity +
arrowhead + lift formula.

Two relay paths feed the web app:

* CSS custom properties in ``dist/layout.css`` (baked by
  ``web/scripts/build.py:generate_layout_css``). The web's CSS
  rules read these via ``var(--vowel-chart-*)`` so the JS doesn't
  need to know about the values.
* An inline ``<script id="chart-style">`` JSON block in
  ``dist/index.html`` carrying the SVG arrow-builder's numeric
  constants (lift formula, arrowhead fractions). The JS reads it
  into the ``CHART_STYLE`` constant at boot.

Both paths must reflect the Python source. Pre-relay desktop and
web held parallel literals that drifted (title 8pt-Bold vs
11px/600, arrow stroke 1.75px vs 0.6 user-units, etc.). This file
runs the full build and asserts every relayed value matches the
Python source byte-for-byte.

Skipped in environments without playwright if the build can't
spin up (the relay test itself doesn't need a browser; the build
script is pure Python).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from phonology_shared.presentation import chart_style

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "web" / "scripts" / "build.py"

CHART_STYLE_JSON_RE = re.compile(
    r'<script id="chart-style" type="application/json">'
    r"(?P<payload>.+?)"
    r"</script>",
    re.DOTALL,
)


def _run_build() -> tuple[Path, Path]:
    """Run ``build.py`` once and return (index.html, layout.css)
    from the canonical dist. Built fresh each test session so the
    relay payload reflects the current Python sources.
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
    dist = REPO_ROOT / "web" / "dist"
    layout_css = next(dist.glob("layout.*.css"), None)
    if layout_css is None:
        # Some build configs name it ``layout.css`` un-hashed.
        layout_css = dist / "layout.css"
    return dist / "index.html", layout_css


@pytest.fixture(scope="module")
def built_dist() -> tuple[Path, Path]:
    return _run_build()


def _extract_chart_style_json(index_html: Path) -> dict:
    contents = index_html.read_text(encoding="utf-8")
    match = CHART_STYLE_JSON_RE.search(contents)
    assert match is not None, (
        'no <script id="chart-style"> block in dist/index.html; '
        "verify build.py emits the inline chart-style block"
    )
    return json.loads(match.group("payload"))


# ---------------------------------------------------------------------------
# Inline JSON block (consumed by main.js for the SVG arrow generator)
# ---------------------------------------------------------------------------


def test_chart_style_json_matches_python(
    built_dist: tuple[Path, Path],
) -> None:
    """Every key the JS reads from the inline JSON block matches
    the corresponding Python constant. Catches a future Python
    edit that doesn't refresh the build, or a build-script bug
    that drops a key."""
    payload = _extract_chart_style_json(built_dist[0])
    expected = {
        "diphthong_lift_chord_frac": (chart_style.DIPHTHONG_LIFT_CHORD_FRAC),
        "diphthong_lift_width_frac_cap": (
            chart_style.DIPHTHONG_LIFT_WIDTH_FRAC_CAP
        ),
        "diphthong_arrowhead_len_frac": (
            chart_style.DIPHTHONG_ARROWHEAD_LEN_FRAC
        ),
        "diphthong_arrowhead_half_frac": (
            chart_style.DIPHTHONG_ARROWHEAD_HALF_FRAC
        ),
    }
    assert payload == expected, (
        f"chart-style relay drifted: baked {payload!r} vs "
        f"chart_style {expected!r}"
    )


# ---------------------------------------------------------------------------
# CSS custom properties (consumed by style.css rules)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "css_var,py_value,suffix",
    [
        (
            "--vowel-chart-title-font",
            chart_style.VOWEL_CHART_TITLE_FONT_PX,
            "px",
        ),
        (
            "--vowel-chart-title-weight",
            chart_style.VOWEL_CHART_TITLE_FONT_WEIGHT,
            "",
        ),
        (
            "--vowel-chart-title-letter-spacing",
            chart_style.VOWEL_CHART_TITLE_LETTER_SPACING_PX,
            "px",
        ),
        (
            "--vowel-chart-col-label-font",
            chart_style.VOWEL_CHART_COL_LABEL_FONT_PX,
            "px",
        ),
        (
            "--vowel-chart-col-label-letter-spacing",
            chart_style.VOWEL_CHART_COL_LABEL_LETTER_SPACING_PX,
            "px",
        ),
        (
            "--vowel-chart-row-label-font",
            chart_style.VOWEL_CHART_ROW_LABEL_FONT_PX,
            "px",
        ),
        (
            "--vowel-chart-row-label-weight",
            chart_style.VOWEL_CHART_ROW_LABEL_FONT_WEIGHT,
            "",
        ),
        (
            "--vowel-chart-row-label-gutter",
            chart_style.VOWEL_CHART_ROW_LABEL_GUTTER_PX,
            "px",
        ),
        (
            "--vowel-chart-contrast-set-row-gap",
            chart_style.VOWEL_CHART_CONTRAST_SET_ROW_GAP_PX,
            "px",
        ),
        (
            "--vowel-silhouette-stroke",
            chart_style.VOWEL_SILHOUETTE_STROKE_PX,
            "px",
        ),
        (
            "--vowel-silhouette-alpha",
            chart_style.VOWEL_SILHOUETTE_ALPHA,
            "",
        ),
        (
            "--vowel-chart-data-min-h",
            chart_style.VOWEL_CHART_DATA_MIN_H_PX,
            "px",
        ),
        (
            "--vowel-band-alpha",
            chart_style.VOWEL_BAND_ALPHA,
            "",
        ),
        (
            "--diphthong-arrow-stroke",
            chart_style.DIPHTHONG_ARROW_STROKE_PX,
            "px",
        ),
        (
            "--diphthong-arrow-focused-alpha",
            chart_style.DIPHTHONG_ARROW_FOCUSED_ALPHA,
            "",
        ),
        (
            "--diphthong-arrow-show-all-alpha",
            chart_style.DIPHTHONG_ARROW_SHOW_ALL_ALPHA,
            "",
        ),
    ],
)
def test_css_var_matches_python(
    built_dist: tuple[Path, Path], css_var: str, py_value, suffix: str
) -> None:
    """Each baked CSS custom property must equal the corresponding
    Python constant. Drift would let desktop and web render the
    chart with subtly different fonts / strokes / alphas."""
    layout_css = built_dist[1].read_text(encoding="utf-8")
    # Match ``--var: <value><suffix>;`` allowing for whitespace.
    pattern = re.compile(rf"{re.escape(css_var)}:\s*([^;]+);")
    match = pattern.search(layout_css)
    assert match is not None, (
        f"CSS var {css_var} not found in dist/layout.css; verify "
        f"build.py emits it from chart_style.py"
    )
    raw = match.group(1).strip()
    if suffix:
        assert raw.endswith(suffix), (
            f"CSS var {css_var} = {raw!r} missing expected "
            f"suffix {suffix!r}"
        )
        raw = raw[: -len(suffix)]
    actual = float(raw)
    expected = float(py_value)
    assert abs(actual - expected) < 1e-6, (
        f"CSS var {css_var} = {actual} drifted from chart_style "
        f"= {expected}"
    )


def test_title_padding_relay(built_dist: tuple[Path, Path]) -> None:
    """The title-padding tuple bakes as a 4-value CSS shorthand
    ``top right bottom left``; verify all four match."""
    layout_css = built_dist[1].read_text(encoding="utf-8")
    pattern = re.compile(r"--vowel-chart-title-padding:\s*([^;]+);")
    match = pattern.search(layout_css)
    assert (
        match is not None
    ), "no --vowel-chart-title-padding in dist/layout.css"
    parts = [p.strip() for p in match.group(1).split()]
    expected = chart_style.VOWEL_CHART_TITLE_PADDING_PX
    assert len(parts) == 4, f"expected 4 padding components, got {parts!r}"
    for part, exp in zip(parts, expected, strict=True):
        assert part.endswith("px"), f"padding component {part!r} not px"
        assert int(part[:-2]) == exp, (
            f"padding component {part} drifted from chart_style "
            f"value {exp}"
        )
