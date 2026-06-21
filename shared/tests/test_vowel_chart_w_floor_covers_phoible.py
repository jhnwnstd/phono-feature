"""Pins each renderer's effective vowel-chart width floor.

Post-redesign the rendered chart width follows the pattern:

    shared:  MIN_VOWEL_CHART_W_PX (the canonical floor)
    web:     floor = MIN + WEB_VOWEL_CHART_W_ADJ     (web/main.js)
    desktop: floor = MIN + DESKTOP_VOWEL_CHART_W_ADJ (desktop/.../vowel_chart.py)

Both renderers default ``ADJ = 0`` (the canonical value); each
can be tuned independently for platform-specific rendering
quirks. The rendered chart width = ``max(floor, natural +
chrome)``, so the floor only kicks in for sparse inventories.

This test guards the EFFECTIVE floor (MIN + ADJ) on each
renderer against:
  1. dropping below the largest natural inventory width + chrome
     (which would clip the back-column cells of a worst-case
     inventory like Hayes Universal or Maximalist),
  2. dropping below a hard visual minimum (~280 px) where the
     trapezoid + row labels stop reading as the canonical IPA
     chart on either platform.

If either renderer's adjustment needs to change deliberately,
edit the renderer file AND the bound in this test in the same
commit.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from phonology_shared.chart.vowel_geometry import build_vowel_chart_geometry
from phonology_shared.chart.vowels import detect_vowel_profile
from phonology_shared.data.inventory import Inventory
from phonology_shared.presentation.chart_style import (
    VOWEL_CHART_PAD_R_PX,
    VOWEL_CHART_ROW_LABEL_GUTTER_PX,
)
from phonology_shared.theory.feature_engine import FeatureEngine

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUNDLED_DIR = _REPO_ROOT / "desktop" / "inventories"
_DESKTOP_VOWEL_CHART = (
    _REPO_ROOT
    / "desktop"
    / "src"
    / "phonology_features"
    / "gui"
    / "vowel_chart.py"
)
_WEB_MAIN_JS = _REPO_ROOT / "web" / "main.js"


# Hard visual minimum: below this the trapezoid + row-label gutter
# stop reading as the canonical IPA chart, regardless of inventory
# size. If a deliberate redesign loosens this, update the constant
# AND the renderer floors together.
_VISUAL_MIN_FLOOR_PX = 280

_CHROME_W_PX = VOWEL_CHART_ROW_LABEL_GUTTER_PX + VOWEL_CHART_PAD_R_PX


def _max_natural_chart_w_across_bundled() -> int:
    """Largest ``natural_data_width_px + chrome`` across every
    bundled inventory. The renderer's floor must be at least this
    large or the densest bundled inventory's back column cells
    overflow the silhouette."""
    widest = 0
    for path in sorted(_BUNDLED_DIR.glob("*_features.json")):
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        inv = Inventory.parse(raw)
        engine = FeatureEngine(inv)
        vowels = list(engine.grouped_segments.get("Vowels", []))
        if not vowels:
            continue
        seg_feats = {
            s: dict(engine.normalized_segment_feats[s]) for s in vowels
        }
        profile = detect_vowel_profile(vowels, seg_feats)
        geom = build_vowel_chart_geometry(vowels, profile, seg_feats)
        widest = max(widest, geom.natural_data_width_px + _CHROME_W_PX)
    return widest


def _read_desktop_adj() -> int:
    """Parse the desktop's ``DESKTOP_VOWEL_CHART_W_ADJ`` literal
    from ``vowel_chart.py``. Reading via import would work but
    the renderer pulls in PyQt6 at import time, which fails in
    headless test envs without ``QT_QPA_PLATFORM=offscreen``.
    Parsing the source avoids that."""
    text = _DESKTOP_VOWEL_CHART.read_text(encoding="utf-8")
    match = re.search(
        r"^DESKTOP_VOWEL_CHART_W_ADJ\s*:\s*int\s*=\s*(-?\d+)\s*$",
        text,
        re.MULTILINE,
    )
    assert match is not None, (
        "DESKTOP_VOWEL_CHART_W_ADJ literal not found in desktop's "
        "vowel_chart.py; has the constant moved or been renamed?"
    )
    return int(match.group(1))


def _read_web_adj() -> int:
    """Parse the web's ``WEB_VOWEL_CHART_W_ADJ`` literal from
    ``main.js``. Lives at module scope as
    ``const WEB_VOWEL_CHART_W_ADJ = N;``."""
    text = _WEB_MAIN_JS.read_text(encoding="utf-8")
    match = re.search(
        r"^const\s+WEB_VOWEL_CHART_W_ADJ\s*=\s*(-?\d+)\s*;?\s*$",
        text,
        re.MULTILINE,
    )
    assert match is not None, (
        "WEB_VOWEL_CHART_W_ADJ literal not found in web/main.js; "
        "has the constant moved or been renamed?"
    )
    return int(match.group(1))


def _shared_min() -> int:
    from phonology_shared.presentation.layout import MIN_VOWEL_CHART_W_PX

    return MIN_VOWEL_CHART_W_PX


def _read_desktop_floor() -> int:
    return _shared_min() + _read_desktop_adj()


def _read_web_floor() -> int:
    return _shared_min() + _read_web_adj()


def test_desktop_floor_holds_widest_bundled_inventory() -> None:
    """The desktop floor must cover the largest bundled
    inventory's natural width + chrome. If the densest inventory
    needs more horizontal room than the floor provides, the
    renderer falls back to the natural width (``max(floor,
    natural + chrome)``) and the back-column cells fit, but
    the floor SHOULD be at least this large so small + medium
    inventories also stay above the visual minimum."""
    widest = _max_natural_chart_w_across_bundled()
    floor = _read_desktop_floor()
    assert floor >= widest - 16, (
        f"desktop VOWEL_CHART_W_FLOOR={floor} is far below the "
        f"widest bundled inventory's natural+chrome={widest}. The "
        f"renderer will fall back to natural, but the floor is "
        f"meant to envelope the bundled set. Bump the floor or "
        f"document the deliberate divergence."
    )


def test_web_floor_holds_widest_bundled_inventory() -> None:
    """Same invariant for the web renderer."""
    widest = _max_natural_chart_w_across_bundled()
    floor = _read_web_floor()
    assert floor >= widest - 16, (
        f"web VOWEL_CHART_W_FLOOR={floor} is far below the "
        f"widest bundled inventory's natural+chrome={widest}. The "
        f"renderer will fall back to natural, but the floor is "
        f"meant to envelope the bundled set. Bump the floor or "
        f"document the deliberate divergence."
    )
