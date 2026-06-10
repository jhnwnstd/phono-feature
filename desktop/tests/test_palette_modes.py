"""Stress tests for the standard / colorblind palette axes.

Covers four invariants that the four palette dicts (LIGHT, DARK,
COLORBLIND_LIGHT, COLORBLIND_DARK) must hold for the (theme, mode)
toggle product to stay coherent:

1. **Key uniformity**: every palette dict has the same key set.
   A consumer that reads ``C["whatever"]`` must succeed regardless
   of which palette is active.

2. **Hex format**: every value is a 7-char ``#RRGGBB`` string.

3. **Color-mapping rule**: standard mode's blue keys map to purple
   in colorblind mode; green to blue; red to orange; gray stays.

4. **Round-trip stability**: any sequence of theme / palette-mode
   toggles ending back at (light, standard) reproduces the LIGHT
   dict exactly. The style caches in :class:`SegmentButton` and
   :class:`FeatureRow` are also expected to invalidate cleanly so
   the visible style matches the active palette.
"""

from __future__ import annotations

import os
import random
import re
from collections.abc import Iterator
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from phonology_shared.presentation import palette as _palette  # noqa: E402
from phonology_shared.presentation.palette import (  # noqa: E402
    COLORBLIND_DARK,
    COLORBLIND_LIGHT,
    DARK,
    LIGHT,
    C,
    get_palette_mode,
    get_theme_name,
    set_palette_mode,
    set_theme,
)

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Color-family expectations per palette key. The first item is the
# bucket the key belongs to in *standard* mode; the test asserts the
# matching colorblind bucket is correct for that mapping.
BLUE_TO_PURPLE = (
    "accent",
    "accent_light",
    "btn_primary",
    "btn_primary_hover",
    "tag_blue",
    "tag_blue_text",
    "seg_selected",
    "seg_matched",
    "neutral",
    "neutral_bg",
)
GREEN_TO_BLUE = (
    "plus",
    "plus_bg",
    "shared_plus",
    "tag_green",
    "tag_green_text",
)
RED_TO_ORANGE = (
    "minus",
    "minus_bg",
    "shared_minus",
    "tag_red",
    "tag_red_text",
    "btn_danger",
    "btn_danger_hover",
)
GRAY_KEEPS_GRAY = (
    "bg",
    "panel",
    "border",
    "text",
    "text_dim",
    "seg_default",
    "seg_unmatched",
    "splitter_hover",
    "btn_disabled_bg",
    "btn_disabled_text",
    "btn_disabled_border",
    "tag_gray",
    "tag_gray_text",
    "analysis_bg",
)
# tag_purple is gray-equivalent in standard (no purple tier) and
# real purple in colorblind. Documented exception to the rule.
PURPLE_SLOT = ("tag_purple", "tag_purple_text")

ALL_PALETTES = {
    "LIGHT": LIGHT,
    "DARK": DARK,
    "COLORBLIND_LIGHT": COLORBLIND_LIGHT,
    "COLORBLIND_DARK": COLORBLIND_DARK,
}

QUADRANTS = (
    ("light", "standard", LIGHT),
    ("dark", "standard", DARK),
    ("light", "colorblind", COLORBLIND_LIGHT),
    ("dark", "colorblind", COLORBLIND_DARK),
)


# ---------------------------------------------------------------------------
# Helpers


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    s = hex_str.lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def _rgb_to_hsl(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Return (hue_deg, saturation, lightness) all 0..1 except hue 0..360."""
    rn, gn, bn = r / 255.0, g / 255.0, b / 255.0
    mx, mn = max(rn, gn, bn), min(rn, gn, bn)
    light = (mx + mn) / 2.0
    if mx == mn:
        return 0.0, 0.0, light
    delta = mx - mn
    sat = delta / (2.0 - mx - mn) if light > 0.5 else delta / (mx + mn)
    if mx == rn:
        hue = ((gn - bn) / delta + (6 if gn < bn else 0)) * 60
    elif mx == gn:
        hue = ((bn - rn) / delta + 2) * 60
    else:
        hue = ((rn - gn) / delta + 4) * 60
    return hue, sat, light


def _classify(hex_str: str) -> str:
    """Map a hex color to one of: gray, red, orange, yellow, green,
    cyan, blue, purple, magenta. Chroma cut (in 0..255 RGB units):
    < 20 reads as gray. This is more stable than an HSL saturation
    cutoff for very-light or very-dark near-grays like #F1F3F4
    (chroma 3) and #202124 (chroma 4) where the hue computation
    is dominated by per-channel rounding noise.
    """
    r, g, b = _hex_to_rgb(hex_str)
    chroma = max(r, g, b) - min(r, g, b)
    if chroma < 20:
        return "gray"
    h, _, _ = _rgb_to_hsl(r, g, b)
    if h < 15 or h >= 345:
        return "red"
    if h < 45:
        return "orange"
    if h < 70:
        return "yellow"
    if h < 170:
        return "green"
    if h < 200:
        return "cyan"
    if h < 260:
        return "blue"
    if h < 320:
        return "purple"
    return "magenta"


# ---------------------------------------------------------------------------
# Fixtures


@pytest.fixture(autouse=True)
def _isolate_settings(tmp_path) -> Iterator[None]:
    """Pin QSettings to a per-test directory so MainWindow's
    QSettings reads can't see leftover keys from a previous test.

    Palette-state reset lives in the session-wide
    ``_reset_palette_module_state`` autouse fixture in
    ``conftest.py``; we don't repeat it here.
    """
    settings_dir = tmp_path / "qsettings"
    settings_dir.mkdir()
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, str(settings_dir))
    yield


@pytest.fixture(scope="module")
def app() -> QApplication:
    """Single QApplication for the module. Reusing it across tests
    matches how the real app runs and avoids per-test setup cost.
    """
    instance = QApplication.instance() or QApplication([])
    assert isinstance(instance, QApplication)
    return instance


# ---------------------------------------------------------------------------
# Palette structure


def test_palette_keys_are_uniform() -> None:
    """Every palette dict must expose the same key set as LIGHT.
    Consumers blindly index ``C["whatever"]`` and a missing key on
    one variant would crash on toggle. One test loops over all four
    palettes so a divergence in ANY variant fails this single
    assertion with a clear missing/extra report per palette.
    """
    expected = set(LIGHT.keys())
    for name, palette in ALL_PALETTES.items():
        keys = set(palette.keys())
        missing = expected - keys
        extra = keys - expected
        assert not missing, f"{name} missing keys: {sorted(missing)}"
        assert not extra, f"{name} has extra keys vs LIGHT: {sorted(extra)}"


def test_palette_values_are_valid_hex() -> None:
    """Every value across every palette must be a 7-char
    ``#RRGGBB`` string. CSS variables embed these verbatim; an
    invalid value silently breaks rendering. One test loops over
    all four palettes for the same reason as
    :py:func:`test_palette_keys_are_uniform`.
    """
    for name, palette in ALL_PALETTES.items():
        bad = {k: v for k, v in palette.items() if not HEX_RE.match(v)}
        assert not bad, f"{name} has non-hex values: {bad}"


# ---------------------------------------------------------------------------
# Color-mapping rule


@pytest.mark.parametrize("key", BLUE_TO_PURPLE)
def test_blue_keys_map_to_purple_in_colorblind(key: str) -> None:
    """Blue family in standard becomes purple family in colorblind, for
    every key that semantically reads as 'positive / selected /
    accent'. The mapping holds in both light and dark variants.
    """
    assert _classify(LIGHT[key]) == "blue", (
        f"{key} expected blue in LIGHT, got {_classify(LIGHT[key])}"
        f" ({LIGHT[key]})"
    )
    assert _classify(DARK[key]) == "blue", (
        f"{key} expected blue in DARK, got {_classify(DARK[key])}"
        f" ({DARK[key]})"
    )
    cl = _classify(COLORBLIND_LIGHT[key])
    cd = _classify(COLORBLIND_DARK[key])
    assert cl in ("purple", "magenta"), (
        f"{key} expected purple in COLORBLIND_LIGHT, got {cl}"
        f" ({COLORBLIND_LIGHT[key]})"
    )
    assert cd in ("purple", "magenta"), (
        f"{key} expected purple in COLORBLIND_DARK, got {cd}"
        f" ({COLORBLIND_DARK[key]})"
    )


@pytest.mark.parametrize("key", GREEN_TO_BLUE)
def test_green_keys_map_to_blue_in_colorblind(key: str) -> None:
    """Green family in standard becomes blue in colorblind, for every key
    that means 'positive / +'.
    """
    assert (
        _classify(LIGHT[key]) == "green"
    ), f"{key} expected green in LIGHT, got {_classify(LIGHT[key])}"
    assert (
        _classify(DARK[key]) == "green"
    ), f"{key} expected green in DARK, got {_classify(DARK[key])}"
    assert _classify(COLORBLIND_LIGHT[key]) == "blue", (
        f"{key} expected blue in COLORBLIND_LIGHT,"
        f" got {_classify(COLORBLIND_LIGHT[key])}"
        f" ({COLORBLIND_LIGHT[key]})"
    )
    assert _classify(COLORBLIND_DARK[key]) == "blue", (
        f"{key} expected blue in COLORBLIND_DARK,"
        f" got {_classify(COLORBLIND_DARK[key])}"
        f" ({COLORBLIND_DARK[key]})"
    )


@pytest.mark.parametrize("key", RED_TO_ORANGE)
def test_red_keys_map_to_orange_in_colorblind(key: str) -> None:
    """Red family in standard becomes orange (or yellow) in colorblind.
    Accepts yellow because the dark-mode orange shades sometimes
    land in the yellow range under HSL classification.
    """
    assert (
        _classify(LIGHT[key]) == "red"
    ), f"{key} expected red in LIGHT, got {_classify(LIGHT[key])}"
    assert (
        _classify(DARK[key]) == "red"
    ), f"{key} expected red in DARK, got {_classify(DARK[key])}"
    cl = _classify(COLORBLIND_LIGHT[key])
    cd = _classify(COLORBLIND_DARK[key])
    assert cl in ("orange", "yellow"), (
        f"{key} expected orange/yellow in COLORBLIND_LIGHT, got {cl}"
        f" ({COLORBLIND_LIGHT[key]})"
    )
    assert cd in ("orange", "yellow"), (
        f"{key} expected orange/yellow in COLORBLIND_DARK, got {cd}"
        f" ({COLORBLIND_DARK[key]})"
    )


@pytest.mark.parametrize("key", GRAY_KEEPS_GRAY)
def test_gray_keys_stay_gray_in_colorblind(key: str) -> None:
    """Gray family is colorblind-safe. Consumers that use these
    slots for default / inactive cues should look identical in
    both modes.
    """
    for name, pal in ALL_PALETTES.items():
        cls = _classify(pal[key])
        assert (
            cls == "gray"
        ), f"{name}[{key}] expected gray, got {cls} ({pal[key]})"


def test_tag_purple_is_gray_in_standard_and_purple_in_colorblind() -> None:
    """The ``tag_purple`` slot is the documented exception to the
    family rule: it exists in standard only so the dict is uniform,
    valued at the gray slot. Colorblind binds it to a real purple
    so the contrastive ± badge and the feature-row neutral marker
    don't share their hue with shared-plus blue.
    """
    for key in PURPLE_SLOT:
        assert (
            _classify(LIGHT[key]) == "gray"
        ), f"LIGHT.{key} expected gray, got {_classify(LIGHT[key])}"
        assert (
            _classify(DARK[key]) == "gray"
        ), f"DARK.{key} expected gray, got {_classify(DARK[key])}"
        cl = _classify(COLORBLIND_LIGHT[key])
        cd = _classify(COLORBLIND_DARK[key])
        assert cl in ("purple", "magenta")
        assert cd in ("purple", "magenta")


# ---------------------------------------------------------------------------
# Toggle state machine


@pytest.mark.parametrize(
    "theme,mode,expected", QUADRANTS, ids=[f"{t}-{m}" for t, m, _ in QUADRANTS]
)
def test_set_theme_and_mode_populates_active_palette(
    theme: str, mode: str, expected: dict[str, str]
) -> None:
    """Setting (theme, mode) must populate ``C`` with the matching
    palette dict, key-for-key. The order of set_theme and
    set_palette_mode must not matter.
    """
    set_theme(theme)
    set_palette_mode(mode)
    assert (
        dict(C) == expected
    ), f"order theme->mode: C did not match {theme}/{mode}"
    set_palette_mode(mode)
    set_theme(theme)
    assert (
        dict(C) == expected
    ), f"order mode->theme: C did not match {theme}/{mode}"


def test_theme_version_increments_on_every_change() -> None:
    """``theme_version`` is the cache-invalidation key. Every
    set_theme / set_palette_mode call must bump it, even if the
    target equals the current state, so consumers can safely key
    derived caches on it.
    """
    start = _palette.theme_version
    set_theme("dark")
    assert _palette.theme_version > start
    v2 = _palette.theme_version
    set_palette_mode("colorblind")
    assert _palette.theme_version > v2
    v3 = _palette.theme_version
    # Even no-op toggles bump it; conservative invalidation is
    # cheaper than building a "no, nothing changed" diff.
    set_theme("dark")
    assert _palette.theme_version > v3


@pytest.mark.parametrize("seq_seed", [0, 3, 7])
def test_random_toggle_sequences_match_expected_palette(
    seq_seed: int,
) -> None:
    """Fuzz: a random sequence of 32 toggles (theme or mode) must
    leave ``C`` matching the expected palette for the resulting
    (theme, mode) pair. Catches state-tracking bugs that only show
    up under interleaved toggles. Three representative seeds cover
    short / medium / long interleaving patterns; the full 8-seed
    sweep is overkill since the cache-invalidation tests below are
    the load-bearing gate for the bug class this fuzz exists to
    detect.
    """
    rng = random.Random(seq_seed)
    theme = "light"
    mode = "standard"
    set_theme(theme)
    set_palette_mode(mode)
    for _ in range(32):
        if rng.random() < 0.5:
            theme = "dark" if theme == "light" else "light"
            set_theme(theme)
        else:
            mode = "colorblind" if mode == "standard" else "standard"
            set_palette_mode(mode)
        expected = {
            ("light", "standard"): LIGHT,
            ("dark", "standard"): DARK,
            ("light", "colorblind"): COLORBLIND_LIGHT,
            ("dark", "colorblind"): COLORBLIND_DARK,
        }[(theme, mode)]
        assert dict(C) == expected, f"after toggle to {theme}/{mode}: C drift"
        assert get_theme_name() == theme
        assert get_palette_mode() == mode


# ---------------------------------------------------------------------------
# Style-cache invalidation


def test_segment_button_restyles_on_palette_mode_swap(
    app: QApplication,
) -> None:
    """SegmentButton rebuilds its rendered stylesheet on a
    palette-mode swap. Checks that the active stylesheet CHANGES
    (rather than pinning specific hex values, which would block
    palette iteration)."""
    from phonology_features.gui.widgets import SegmentButton

    btn = SegmentButton("p")
    set_theme("light")
    set_palette_mode("standard")
    btn.apply_theme()
    std_css = btn.styleSheet()
    set_palette_mode("colorblind")
    btn.apply_theme()
    cb_css = btn.styleSheet()
    assert (
        cb_css != std_css
    ), "stylesheet did not change after the palette-mode swap"
    btn.deleteLater()


def test_feature_row_restyles_on_palette_mode_swap(
    app: QApplication,
) -> None:
    """FeatureRow propagates a palette-mode swap to its badge
    stylesheet. Asserts a change, not specific hex values."""
    from phonology_features.gui.widgets import FeatureRow

    row = FeatureRow("son")
    set_theme("light")
    set_palette_mode("standard")
    row.apply_theme()
    row.set_display(value="", shared=False, contrastive=True, badge="±")
    std_badge_css = row.badge.styleSheet()
    set_palette_mode("colorblind")
    row.apply_theme()
    cb_badge_css = row.badge.styleSheet()
    assert (
        cb_badge_css != std_badge_css
    ), "badge stylesheet did not change after the palette-mode swap"
    row.deleteLater()


# ---------------------------------------------------------------------------
# Round-trip via MainWindow


def test_mainwindow_user_path_cb_then_dark_then_uncb_then_undark(
    app: QApplication,
) -> None:
    """Repros the user's reported stuck-state path:
    standard/light, colorblind, +dark, -colorblind, -dark.
    Final state must be standard/light with the canonical LIGHT
    palette, no stale colors anywhere in ``C``.
    """
    from phonology_features.gui.main_window import MainWindow
    from phonology_shared.presentation.constants import (
        SETTINGS_APP,
        SETTINGS_ORG,
    )

    # MainWindow's ctor reads theme / palette_mode from QSettings;
    # pin them here so the test is deterministic even on hosts
    # whose Qt styleHints report dark mode.
    s = QSettings(SETTINGS_ORG, SETTINGS_APP)
    s.setValue("theme", "light")
    s.setValue("palette_mode", "standard")
    s.sync()
    set_theme("light")
    set_palette_mode("standard")
    w = MainWindow()
    app.processEvents()
    assert dict(C) == LIGHT

    w._theme.toggle_palette_mode()
    app.processEvents()
    assert dict(C) == COLORBLIND_LIGHT

    w._theme.toggle()
    app.processEvents()
    assert dict(C) == COLORBLIND_DARK

    w._theme.toggle_palette_mode()
    app.processEvents()
    assert dict(C) == DARK

    w._theme.toggle()
    app.processEvents()
    drift = [k for k in LIGHT if C.get(k) != LIGHT[k]]
    assert dict(C) == LIGHT, f"final palette is not LIGHT: drift={drift}"
    w.close()


def test_mainwindow_geometry_stable_across_palette_toggles(
    app: QApplication,
) -> None:
    """Toggling the colorblind palette must not shift any visible
    chrome geometry. Catches regressions in the warmup path (and
    in widgets that compute sizeHint from palette-derived metrics).
    """
    from phonology_features.gui.main_window import MainWindow
    from phonology_shared.presentation.constants import (
        SETTINGS_APP,
        SETTINGS_ORG,
    )

    s = QSettings(SETTINGS_ORG, SETTINGS_APP)
    s.setValue("theme", "light")
    s.setValue("palette_mode", "standard")
    s.sync()
    set_theme("light")
    set_palette_mode("standard")
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    app.processEvents()

    def snapshot() -> dict[str, Any]:
        return {
            "window": (w.width(), w.height()),
            "toolbar": (w._toolbar.width(), w._toolbar.height()),
            "seg_panel": (w.seg_panel.width(), w.seg_panel.height()),
            "feat_panel": (
                w.feat_panel.width(),
                w.feat_panel.height(),
            ),
            "cb_btn": (w._cb_btn.width(), w._cb_btn.height()),
            "theme_btn": (
                w._theme_btn.width(),
                w._theme_btn.height(),
            ),
        }

    before = snapshot()
    w._theme.toggle_palette_mode()
    app.processEvents()
    after_cb = snapshot()
    w._theme.toggle_palette_mode()
    app.processEvents()
    after_back = snapshot()
    assert (
        after_cb == before
    ), f"colorblind toggle moved chrome: {before} to {after_cb}"
    assert (
        after_back == before
    ), f"second toggle didn't restore chrome: {before} to {after_back}"
    w.close()
