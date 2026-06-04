"""Pin the shared cell-classification and silhouette-shape decisions
that BOTH the desktop and the web vowel-chart renderers consume.

Why this exists: the desktop renders multi-segment cells using
QVBoxLayout / QHBoxLayout, which lay children out in flow without
absolute positioning. The web renders the same cells with CSS flex;
a regression in the per-child styling (e.g. the cell-anchor positioning
class accidentally applied to flex items) would yank every child to
the same spot and visually overlap the segments -- the schwa /
rhotic-schwa overlap bug. These tests pin the shared payload so any
divergence shows up here first instead of in the rendered chart.

The web's ``main.js`` ``_buildVowelCellStack`` and
``_buildVowelCellLongPair`` consume ``cell.entries`` and
``cell.is_long_pair`` directly from this payload; the desktop's
``VowelChartWidget._build_cell`` consumes the same. Asserting the
payload's structure is the closest you can get to a cross-UI parity
test without driving Qt and a browser in the same process.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from phonology_shared.chart.vowels import (
    VowelChartGeometry,
    build_vowel_chart_geometry,
    detect_vowel_profile,
)
from phonology_shared.data.inventory import Inventory
from phonology_shared.theory.feature_engine import FeatureEngine

INVENTORIES = Path(__file__).resolve().parents[2] / "desktop" / "inventories"


def _geometry(inventory_name: str) -> VowelChartGeometry:
    path = INVENTORIES / inventory_name
    if not path.exists():
        pytest.skip(f"missing inventory: {inventory_name}")
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    engine = FeatureEngine(Inventory.parse(raw, source=str(path)))
    vowels = [
        s for s in engine.segments if engine.segments[s].get("Syllabic") == "+"
    ]
    feats = {s: dict(engine.segments[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, feats)
    return build_vowel_chart_geometry(vowels, profile, feats)


def _find_cell_with(geometry: VowelChartGeometry, seg: str):
    for cell in geometry.cells:
        if seg in cell.entries:
            return cell
    return None


# ---------------------------------------------------------------------------
# English Hayes: schwa + rhotic schwa share a cell
# ---------------------------------------------------------------------------


def test_english_schwa_and_rhotic_schwa_share_a_cell() -> None:
    """In Hayes' English inventory, both /ə/ and /ɚ/ are syllabic
    open-mid central with the only feature difference being
    [+/-coronal] (rhoticity). They share the same chart cell;
    renderers must distinguish them by laying them out separately
    (vertical stack) rather than overlapping at the same anchor.
    """
    geom = _geometry("english_features.json")
    schwa_cell = _find_cell_with(geom, "ə")
    rhotic_cell = _find_cell_with(geom, "ɚ")
    assert schwa_cell is not None, "/ə/ not placed in English chart"
    assert rhotic_cell is not None, "/ɚ/ not placed in English chart"
    assert schwa_cell is rhotic_cell, (
        "/ə/ and /ɚ/ must share a single VowelChartCell so renderers "
        "see one collision group, not two cells at the same anchor"
    )


def test_english_schwa_cell_is_not_a_long_pair() -> None:
    """The cell carries 2 entries but they're not a Long contrast
    (the contrast is rhoticity, not duration). ``is_long_pair=False``
    routes the renderer to vertical-stack mode -- both UIs must agree
    on that, hence the shared flag.
    """
    geom = _geometry("english_features.json")
    cell = _find_cell_with(geom, "ə")
    assert cell is not None
    assert len(cell.entries) >= 2
    assert cell.is_long_pair is False, (
        "schwa/ɚ are not a Long-contrast pair; cell.is_long_pair must "
        "be False so renderers stack vertically instead of placing "
        "the two segments side-by-side"
    )


# ---------------------------------------------------------------------------
# Long-pair classification (the side-by-side case)
# ---------------------------------------------------------------------------


def test_long_pair_classification_is_consistent_across_renderers() -> None:
    """Inventories with explicit ``Long`` contrasts produce
    ``is_long_pair=True`` on cells whose two entries differ only on
    ``Long``. Both UIs receive that flag; this test pins the
    classification so a web/desktop split (e.g. the web ignoring the
    flag and stacking instead) is caught by the shared payload
    before reaching either renderer.
    """
    # Walk every bundled inventory; for every multi-entry cell,
    # assert ``is_long_pair`` matches the "only ``Long`` differs"
    # criterion explicitly.
    for inv in sorted(INVENTORIES.glob("*.json")):
        if inv.name.startswith("_"):
            continue
        raw = json.loads(inv.read_text(encoding="utf-8-sig"))
        engine = FeatureEngine(Inventory.parse(raw, source=str(inv)))
        vowels = [
            s
            for s in engine.segments
            if engine.segments[s].get("Syllabic") == "+"
        ]
        if not vowels:
            continue
        feats = {s: dict(engine.segments[s]) for s in vowels}
        profile = detect_vowel_profile(vowels, feats)
        geom = build_vowel_chart_geometry(vowels, profile, feats)
        for cell in geom.cells:
            if len(cell.entries) != 2:
                continue
            a, b = cell.entries
            a_feats = {k.lower(): v for k, v in feats.get(a, {}).items()}
            b_feats = {k.lower(): v for k, v in feats.get(b, {}).items()}
            long_set = {a_feats.get("long"), b_feats.get("long")}
            differs_only_on_long = long_set == {"+", "-"} and all(
                a_feats.get(k) == b_feats.get(k)
                for k in set(a_feats) | set(b_feats)
                if k != "long"
            )
            assert cell.is_long_pair is differs_only_on_long, (
                f"{inv.name}: cell {cell.entries} -- is_long_pair="
                f"{cell.is_long_pair} but differs_only_on_long="
                f"{differs_only_on_long}; the shared classification is "
                f"out of sync with the criterion the renderers expect"
            )


# ---------------------------------------------------------------------------
# Silhouette back edge: asymmetric pull-in
# ---------------------------------------------------------------------------


def test_silhouette_back_edge_passes_through_back_rounded_when_present() -> (
    None
):
    """The new semantics: ``top_right`` is the back ANCHOR
    (normalised), and ``back_right_pixel_offset`` is the pixel offset
    from that anchor to the rendered silhouette line. For an
    inventory with a back-rounded vowel (col 5), the offset is the
    pair-shift in pixels -- the line passes through the CENTRE of
    the back-rounded mate, matching how the top / bottom horizontal
    lines pass through Close-row / Open-row button centres.
    """
    from phonology_shared.chart.vowels import (
        _BACK_COL_BUTTON_CENTRE_OFFSET_PX,
        _BACKNESS_X,
    )

    geom = _geometry("english_features.json")
    sil = geom.silhouette
    assert sil.top_right == pytest.approx(_BACKNESS_X["back"], abs=1e-6)
    assert sil.bottom_right == pytest.approx(_BACKNESS_X["back"], abs=1e-6)
    assert sil.back_right_pixel_offset == _BACK_COL_BUTTON_CENTRE_OFFSET_PX[5]


def test_silhouette_back_offset_canonical_when_no_back_vowel() -> None:
    """An inventory with no back vowel (col 4, 5, or 8) keeps the
    canonical pair-outer pixel extent so the silhouette right edge
    sits where a hypothetical back-rounded mate's outer right would
    be. ``vowel_silhouette()`` (the canonical builder used by
    ``build.py`` for the pre-load fallback) is the closest accessible
    "no back vowel" case.
    """
    from phonology_shared.chart.vowels import (
        _PAIR_OUTER_PIXEL_EXTENT,
        VowelChartShape,
        vowel_silhouette,
    )

    sil = vowel_silhouette(VowelChartShape.TRAPEZOID)
    assert sil.back_right_pixel_offset == _PAIR_OUTER_PIXEL_EXTENT


def test_silhouette_front_edge_does_not_adapt_to_front_vowels() -> None:
    """The aesthetic asymmetry: the front (left) edge stays at its
    canonical extent computed from ``top_width`` / ``bottom_width``,
    NOT pulled in to hug the frontmost present front vowel. This
    test pins that the left edge is purely a function of the shrunken
    widths (Stage 1 + Stage 2) -- no front-vowel-specific
    adaptation kicks in.
    """
    from phonology_shared.chart.vowels import (
        _BACKNESS_X,
        _PAIR_OUTER_EXTENT,
    )

    geom = _geometry("hayes_features.json")
    sil = geom.silhouette
    back = _BACKNESS_X["back"]
    front = _BACKNESS_X["front"]
    expected_top_left = (
        back + sil.top_width * (front - back) - _PAIR_OUTER_EXTENT
    )
    expected_bottom_left = (
        back + sil.bottom_width * (front - back) - _PAIR_OUTER_EXTENT
    )
    assert sil.top_left == pytest.approx(expected_top_left, abs=1e-6)
    assert sil.bottom_left == pytest.approx(expected_bottom_left, abs=1e-6)


def test_silhouette_back_edge_is_vertical_for_every_inventory() -> None:
    """Whatever back extent the adaptation picks, the right edge stays
    a vertical line: ``top_right == bottom_right``. This is the
    silhouette's structural invariant -- only the slanted left edge
    changes between top and bottom.
    """
    for inv in sorted(INVENTORIES.glob("*.json")):
        if inv.name.startswith("_"):
            continue
        raw = json.loads(inv.read_text(encoding="utf-8-sig"))
        engine = FeatureEngine(Inventory.parse(raw, source=str(inv)))
        vowels = [
            s
            for s in engine.segments
            if engine.segments[s].get("Syllabic") == "+"
        ]
        if not vowels:
            continue
        feats = {s: dict(engine.segments[s]) for s in vowels}
        profile = detect_vowel_profile(vowels, feats)
        geom = build_vowel_chart_geometry(vowels, profile, feats)
        assert geom.silhouette.top_right == pytest.approx(
            geom.silhouette.bottom_right, abs=1e-6
        ), (
            f"{inv.name}: silhouette right edge not vertical "
            f"(top_right={geom.silhouette.top_right}, "
            f"bottom_right={geom.silhouette.bottom_right})"
        )
