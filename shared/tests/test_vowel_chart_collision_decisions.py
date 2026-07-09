"""Pin the shared cell-classification and silhouette-shape decisions
that BOTH the desktop and the web vowel-chart renderers consume.

Why this exists: the desktop renders multi-segment cells using
QVBoxLayout / QHBoxLayout, which lay children out in flow without
absolute positioning. The web renders the same cells with CSS flex;
a regression in the per-child styling (e.g. the cell-anchor positioning
class accidentally applied to flex items) would yank every child to
the same spot and visually overlap the segments: the schwa /
rhotic-schwa overlap bug. These tests pin the shared payload so any
divergence shows up here first instead of in the rendered chart.

The web's ``main.js`` ``_buildVowelCellStack`` and
``_buildVowelCellPair`` consume ``cell.entries`` and
``cell.display_kind`` directly from this payload; the desktop's
``VowelChartWidget._build_cell`` consumes the same. Asserting the
payload's structure is the closest you can get to a cross-UI parity
test without driving Qt and a browser in the same process.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from phonology_shared.chart.vowel_space_geometry import (
    VowelChartGeometry,
    build_vowel_chart_geometry,
)
from phonology_shared.chart.vowels import (
    VowelCellDisplayKind,
    detect_vowel_profile,
)
from phonology_shared.data.inventory import Inventory
from phonology_shared.theory.feature_engine import FeatureEngine

INVENTORIES_DIR = (
    Path(__file__).resolve().parents[2] / "desktop" / "inventories"
)


def _geometry(inventory_name: str) -> VowelChartGeometry:
    path = INVENTORIES_DIR / inventory_name
    if not path.exists():
        pytest.skip(f"missing inventory: {inventory_name}")
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    engine = FeatureEngine(Inventory.parse(raw, source=str(path)))
    vowels = [
        s for s in engine.segments if engine.segments[s].get("Syllabic") == "+"
    ]
    feats = {s: dict(engine.segments[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, feats)
    # Mirror the live renderer (view_models): diphthong final-state
    # bundles live in metadata.segment_secondary, so the geometry can
    # exclude contour vowels from cells and draw them as the diphthong
    # strip instead of placing them as monophthongs.
    secondary = engine.inventory.metadata.get("segment_secondary")
    return build_vowel_chart_geometry(
        vowels, profile, feats, segment_secondary=secondary
    )


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
    (the contrast is rhoticity, not duration). Display kind stays
    STACK so renderers stack vertically rather than placing the two
    segments side-by-side.
    """
    geom = _geometry("english_features.json")
    cell = _find_cell_with(geom, "ə")
    assert cell is not None
    assert len(cell.entries) >= 2
    assert cell.display_kind != VowelCellDisplayKind.LONG_PAIR, (
        "schwa/ɚ are not a Long-contrast pair; the cell must NOT "
        "render as LONG_PAIR side-by-side"
    )


# ---------------------------------------------------------------------------
# Long-pair classification (the side-by-side case)
# ---------------------------------------------------------------------------


def test_long_pair_classification_is_consistent_across_renderers() -> None:
    """Inventories with explicit ``Long`` contrasts produce cells
    whose ``display_kind == LONG_PAIR`` exactly when the two
    entries differ only on ``Long``. Both UIs receive the same
    classification; this test pins it so a renderer-side split is
    caught by the shared payload first.
    """
    # Walk every bundled inventory; for every multi-entry cell,
    # LONG_PAIR must match the "only ``Long`` differs"
    # criterion explicitly.
    for inv in sorted(INVENTORIES_DIR.glob("*.json")):
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
            is_long_pair = cell.display_kind == VowelCellDisplayKind.LONG_PAIR
            assert is_long_pair is differs_only_on_long, (
                f"{inv.name}: cell {cell.entries}; LONG_PAIR="
                f"{is_long_pair} but differs_only_on_long="
                f"{differs_only_on_long}; the shared classification is "
                f"out of sync with the criterion the renderers expect"
            )


# ---------------------------------------------------------------------------
# Silhouette back edge: asymmetric pull-in
# ---------------------------------------------------------------------------


def test_silhouette_back_edge_at_reserved_extent() -> None:
    """Silhouette back-edge TOP sits at ``back + extent`` where the
    extent is the canonical pair-outer reserve GROWN just enough to
    wrap the widest back-most cell (the outline is the hard boundary
    for the buttons; single-button inventories keep the canonical
    33 px). ``back_right_pixel_offset`` remains the shared render-time
    hook for future tweaks but stays ``0`` so the rendered top edge
    is purely ``top_right * dw``.

    THE BACK EDGE STAYS VERTICAL for EVERY inventory. The dorsal
    boundary is a strong articulatory / phonological anchor -- it
    holds at ``back_anchor`` across every row, whether the inventory
    is a classic trapezoid or a lone-low-vowel converged wedge.
    Only the FRONT boundary tapers inward as height lowers.
    """
    from phonology_shared.chart.vowel_space import _CANONICAL_CONTENT_W_PX
    from phonology_shared.chart.vowel_space import (
        _BACKNESS_X,
        _PAIR_OUTER_EXTENT,
    )

    canonical_extent_px = _PAIR_OUTER_EXTENT * _CANONICAL_CONTENT_W_PX
    # Every inventory whose low row populates two or more backness
    # columns keeps the classic trapezoid shape (back_anchor_at_bottom
    # is None). Lone-low inventories converge the front side while
    # the back stays vertical.
    for name in (
        "english_features.json",
        "hayes_features.json",
        "spanish_features.json",
    ):
        geom = _geometry(name)
        sil = geom.silhouette
        assert sil.cell_outer_extent_px >= canonical_extent_px - 1
        expected_back_edge = _BACKNESS_X["back"] + (
            sil.cell_outer_extent_px / _CANONICAL_CONTENT_W_PX
        )
        assert sil.top_right == pytest.approx(expected_back_edge, abs=1e-6)
        assert sil.bottom_right == pytest.approx(expected_back_edge, abs=1e-6), (
            f"{name}: back edge must stay vertical "
            f"(top_right={sil.top_right}, "
            f"bottom_right={sil.bottom_right})"
        )
        assert sil.back_right_pixel_offset == 0, (
            f"{name}: back_right_pixel_offset should be the hook "
            f"default (0), not an inventory-driven snap value"
        )


def test_vowel_silhouette_editor_matches_per_inventory_back_edge() -> None:
    """``vowel_silhouette()`` (the canonical editor used by
    ``build.py`` for the pre-load CSS bake) lands the back edge at
    the same normalised extent the per-inventory editor produces,
    so the bake and the runtime path stay byte-aligned.
    """
    from phonology_shared.chart.vowel_space_geometry import vowel_silhouette
    from phonology_shared.chart.vowel_space import (
        _BACKNESS_X,
        _PAIR_OUTER_EXTENT,
    )
    from phonology_shared.chart.vowels import VowelChartShape

    sil = vowel_silhouette(VowelChartShape.TRAPEZOID)
    assert sil.top_right == pytest.approx(
        _BACKNESS_X["back"] + _PAIR_OUTER_EXTENT, abs=1e-6
    )
    assert sil.back_right_pixel_offset == 0


def test_silhouette_front_edge_tracks_extent_not_vowel_identity() -> None:
    """The front (left) edge is the front anchor minus the reserved
    FRONT extent: it never adapts to which front vowel happens to be
    present, only to how WIDE the front-most cells are (the outline
    is the hard boundary for the buttons, so wide edge cells grow
    the reserved extent; see ``_grow_outline_extent``). Pins that
    the corners stay a pure function of the shrunken widths plus
    the per-side extent fields.
    """
    from phonology_shared.chart.vowel_space import _CANONICAL_CONTENT_W_PX
    from phonology_shared.chart.vowel_space import _BACKNESS_X

    geom = _geometry("hayes_features.json")
    sil = geom.silhouette
    back = _BACKNESS_X["back"]
    front = _BACKNESS_X["front"]
    front_extent_px = sil.front_cell_outer_extent_px or (
        sil.cell_outer_extent_px
    )
    front_extent = front_extent_px / _CANONICAL_CONTENT_W_PX
    expected_top_left = back + sil.top_width * (front - back) - front_extent
    expected_bottom_left = (
        back + sil.bottom_width * (front - back) - front_extent
    )
    assert sil.top_left == pytest.approx(expected_top_left, abs=1e-6)
    assert sil.bottom_left == pytest.approx(expected_bottom_left, abs=1e-6)


def test_silhouette_back_edge_is_vertical_for_every_inventory() -> None:
    """The silhouette's right edge is VERTICAL
    (``top_right == bottom_right``) for EVERY inventory. The dorsal
    boundary is a strong articulatory / phonological anchor -- it
    holds at ``back_anchor`` across every row, whether the inventory
    is a classic trapezoid, a lone-low-central converged wedge
    (Spanish, Japanese, ...), or a lone-low-back inventory (German,
    Turkish). Only the FRONT boundary tapers inward as height lowers.
    """
    for inv in sorted(INVENTORIES_DIR.glob("*.json")):
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
        sil = geom.silhouette
        assert sil.bottom_right == pytest.approx(sil.top_right, abs=1e-6), (
            f"{inv.name}: silhouette back edge must be vertical "
            f"(top_right={sil.top_right}, "
            f"bottom_right={sil.bottom_right})"
        )


# ---------------------------------------------------------------------------
# Display-kind classifier: the generalisation of ``is_long_pair`` that
# the shared bridge sends to both renderers. The tests below pin the
# pure-Python classifier; the renderer-side tests live in their own
# files but consume the same :py:class:`VowelCellDisplayKind` values
# verified here.

# ---------------------------------------------------------------------------


def _make_classifier_feats(
    pairs: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    """Wrap ``pairs`` so :py:func:`_classify_vowel_cell_display` reads
    each segment's feature bundle directly. Tests build small
    inventories without going through ``Inventory.parse`` because the
    classifier is feature-bundle-pure: no engine state is needed.
    """
    return pairs


def test_classify_long_pair_returns_long_pair_kind() -> None:
    """The long-only case still produces ``LONG_PAIR`` and a
    ``contrast_features`` tuple with just ``("long",)``. The existing
    desktop and web LONG_PAIR rendering path stays driven by this
    kind value.
    """
    from phonology_shared.chart.vowel_space_geometry.classifier import (
        classify_display_kind as _classify_vowel_cell_display,
    )
    from phonology_shared.chart.vowels import VowelCellDisplayKind

    feats = _make_classifier_feats(
        {
            "i": {"high": "+", "long": "-"},
            "iː": {"high": "+", "long": "+"},
        }
    )
    kind, contrast, ordered, grid, _ = _classify_vowel_cell_display(
        ("i", "iː"), feats
    )
    assert kind == VowelCellDisplayKind.LONG_PAIR
    assert contrast == ("long",)
    # Marked (+long) goes on the right.
    assert ordered == ("i", "iː")


def test_classify_nasal_pair() -> None:
    from phonology_shared.chart.vowel_space_geometry.classifier import (
        classify_display_kind as _classify_vowel_cell_display,
    )
    from phonology_shared.chart.vowels import VowelCellDisplayKind

    feats = _make_classifier_feats(
        {
            "o": {"high": "-", "low": "-", "nasal": "-"},
            "õ": {"high": "-", "low": "-", "nasal": "+"},
        }
    )
    kind, contrast, ordered, grid, _ = _classify_vowel_cell_display(
        ("o", "õ"), feats
    )
    assert kind == VowelCellDisplayKind.NASAL_PAIR
    assert contrast == ("nasal",)
    assert ordered == ("o", "õ")


def test_classify_rhotic_pair_with_aliases() -> None:
    """The data-boundary alias map maps ``r-colored`` / ``rcolored``
    / ``rhotacized`` to the canonical ``rhotic`` key. Feeding any of
    those spellings into :py:func:`Inventory.parse` and round-tripping
    through :py:func:`detect_vowel_profile` -> classifier produces a
    ``RHOTIC_PAIR``.
    """
    from phonology_shared.chart.vowel_space_geometry.classifier import (
        classify_display_kind as _classify_vowel_cell_display,
    )
    from phonology_shared.chart.vowels import VowelCellDisplayKind
    from phonology_shared.data.inventory import normalize_feature_bundle

    raw_a = {"High": "-", "Low": "-", "R-Colored": "-"}
    raw_b = {"High": "-", "Low": "-", "Rhotacized": "+"}
    norm_a = normalize_feature_bundle(raw_a)
    norm_b = normalize_feature_bundle(raw_b)
    assert "rhotic" in norm_a
    assert "rhotic" in norm_b
    feats = _make_classifier_feats({"ə": norm_a, "ɚ": norm_b})
    kind, contrast, ordered, grid, _ = _classify_vowel_cell_display(
        ("ə", "ɚ"), feats
    )
    assert kind == VowelCellDisplayKind.RHOTIC_PAIR
    assert contrast == ("rhotic",)
    assert ordered == ("ə", "ɚ")


def test_classify_phonation_pair() -> None:
    from phonology_shared.chart.vowel_space_geometry.classifier import (
        classify_display_kind as _classify_vowel_cell_display,
    )
    from phonology_shared.chart.vowels import VowelCellDisplayKind

    feats = _make_classifier_feats(
        {
            "a": {"high": "-", "low": "+", "breathy": "-", "creaky": "-"},
            "a̤": {"high": "-", "low": "+", "breathy": "+", "creaky": "-"},
        }
    )
    kind, contrast, ordered, grid, _ = _classify_vowel_cell_display(
        ("a", "a̤"), feats
    )
    assert kind == VowelCellDisplayKind.PHONATION_PAIR
    assert contrast == ("breathy",)
    # modal on left, marked on right.
    assert ordered == ("a", "a̤")


def test_classify_phonation_pair_phoible_spread_glottis() -> None:
    """A plain / breathy contrast encoded the PHOIBLE way (``spreadgl``,
    the glottal-state feature, not the ``breathy`` canonical) links as a
    PHONATION_PAIR just the same. This is the roster fix: the phonation
    features a source actually encodes drive the capsule, so an inventory
    like !Xoo no longer stacks its breathy vowels anonymously."""
    from phonology_shared.chart.vowel_space_geometry.classifier import (
        classify_display_kind as _classify_vowel_cell_display,
    )
    from phonology_shared.chart.vowels import VowelCellDisplayKind

    feats = _make_classifier_feats(
        {
            "a": {"high": "-", "low": "+", "spreadgl": "-"},
            "a̤": {"high": "-", "low": "+", "spreadgl": "+"},
        }
    )
    # Marked member FIRST in input order, so the modal-first reordering is
    # actually exercised: a classifier that merely preserves input order
    # fails here (the original hand-rolled swap only knew breathy/creaky
    # and silently kept a spreadgl pair in input order).
    kind, contrast, ordered, _, _ = _classify_vowel_cell_display(
        ("a̤", "a"), feats
    )
    assert kind == VowelCellDisplayKind.PHONATION_PAIR
    assert contrast == ("spreadgl",)
    assert ordered == ("a", "a̤")


def test_classify_phonation_dimension_groups_several_features() -> None:
    """A plain / breathy / creaky cell differs on TWO features (``spreadgl``
    and ``constrgl``) but ONE dimension (phonation), so it reads as a single
    horizontal phonation capsule, not a 2x2 or a stack. This is the general
    rule: features that encode the same secondary contrast collapse to one
    dimension however many there are. Base (modal) orders first."""
    from phonology_shared.chart.vowel_space_geometry.classifier import (
        classify_display_kind as _classify_vowel_cell_display,
    )
    from phonology_shared.chart.vowels import VowelCellDisplayKind

    feats = _make_classifier_feats(
        {
            "a": {"low": "+", "spreadgl": "-", "constrgl": "-"},
            "a̤": {"low": "+", "spreadgl": "+", "constrgl": "-"},
            "a̰": {"low": "+", "spreadgl": "-", "constrgl": "+"},
        }
    )
    kind, contrast, ordered, _, _ = _classify_vowel_cell_display(
        ("a̤", "a", "a̰"), feats
    )
    assert kind == VowelCellDisplayKind.PHONATION_PAIR
    assert contrast == ("constrgl", "spreadgl")
    assert ordered[0] == "a"  # base (unmarked) first


def test_classify_many_dimension_cell_uses_base_and_variants_layout() -> None:
    """A cell whose entries are 1 BASE + N MONOFACTOR variants across
    several secondary dimensions (a !Xoo /a/ quality: plain +
    pharyngealised + breathy + creaky + nasal) renders as a CONTRAST_SET
    with the base spanning the left column and the variants packed
    row-first into the remaining columns.

    This is the layout the !Xun / !Xoo inventories need: they carry
    5-6 phonation-family variants per vowel, which no clean pair or
    2x2 can express, but which reads as a single pill when we give the
    base its own column and lay the variants beside it. Falls back to
    the contrast-aware STACK only when a variant is multi-marked or
    when there is no unique base."""
    from phonology_shared.chart.vowel_space_geometry.classifier import (
        classify_display_kind as _classify_vowel_cell_display,
    )
    from phonology_shared.chart.vowels import VowelCellDisplayKind

    feats = _make_classifier_feats(
        {
            "a": {
                "low": "+",
                "rtr": "-",
                "spreadgl": "-",
                "constrgl": "-",
                "nasal": "-",
            },
            "aˤ": {
                "low": "+",
                "rtr": "+",
                "spreadgl": "-",
                "constrgl": "-",
                "nasal": "-",
            },
            "a̤": {
                "low": "+",
                "rtr": "-",
                "spreadgl": "+",
                "constrgl": "-",
                "nasal": "-",
            },
            "a̰": {
                "low": "+",
                "rtr": "-",
                "spreadgl": "-",
                "constrgl": "+",
                "nasal": "-",
            },
            "ã": {
                "low": "+",
                "rtr": "-",
                "spreadgl": "-",
                "constrgl": "-",
                "nasal": "+",
            },
        }
    )
    entries = ("aˤ", "a̤", "a", "a̰", "ã")
    kind, contrast, ordered, grid, spans = _classify_vowel_cell_display(
        entries, feats
    )
    assert kind == VowelCellDisplayKind.CONTRAST_SET
    assert contrast == ("constrgl", "nasal", "rtr", "spreadgl")
    # Base first, then variants grouped by DIMENSION (larger groups
    # first): constrgl / spreadgl are both PHONATION_PAIR so a̰ and
    # a̤ land at consecutive fill slots (top, left) — clustered
    # around the base — before the singleton nasal and pharyngeal
    # variants get the remaining slots.
    assert ordered == ("a", "a̰", "a̤", "ã", "aˤ")
    # Base at (1, 1). Fill order: top, left, right, bottom.
    # The left and right cardinals span all 3 rows because no
    # corner variants are present in this 4-var case.
    assert grid == ((1, 1), (1, 0), (0, 0), (2, 0), (1, 2))
    assert spans == ((1, 1), (1, 1), (1, 3), (1, 3), (1, 1))


def test_classify_grid_slot_collision_falls_back_to_stack() -> None:
    """Two entries that differ on a contrast feature only as ``-`` vs
    ``0`` are a genuine contrast to the DETECTOR but identical to the
    aligned grid's ``+``-binning, so they would land on ONE capsule slot
    and paint on top of each other. The classifier must detect the
    collision and fall back to the contrast-aware stack instead of
    emitting a double-booked CONTRAST_SET."""
    from phonology_shared.chart.vowel_space_geometry.classifier import (
        classify_display_kind as _classify_vowel_cell_display,
    )
    from phonology_shared.chart.vowels import VowelCellDisplayKind

    feats = _make_classifier_feats(
        {
            "e1": {"low": "+", "long": "-", "nasal": "-"},
            "e2": {"low": "+", "long": "0", "nasal": "-"},
            "e3": {"low": "+", "long": "+", "nasal": "-"},
            "e4": {"low": "+", "long": "-", "nasal": "+"},
        }
    )
    kind, contrast, ordered, grid, _ = _classify_vowel_cell_display(
        ("e1", "e2", "e3", "e4"), feats
    )
    assert kind == VowelCellDisplayKind.STACK
    assert contrast == ("long", "nasal")  # contrast-aware, not ()
    assert grid == ()
    assert set(ordered) == {"e1", "e2", "e3", "e4"}


def test_pair_kind_cells_report_their_true_button_width() -> None:
    """A PAIR-kind cell lays EVERY entry in one horizontal row, so its
    button width is its entry count: a 3-entry phonation capsule is 3
    wide and a 4-way set is 4 wide. The width used to be hardcoded to 2,
    which under-reserved the row (18 real PHOIBLE cells) and could
    overlap a neighbouring cell."""
    from phonology_shared.chart.vowel_space_geometry.cell_boxes import (
        horizontal_button_count,
    )
    from phonology_shared.chart.vowels import VowelCellDisplayKind

    kinds = VowelCellDisplayKind
    assert horizontal_button_count(kinds.PHONATION_PAIR, ("a", "b"), ()) == 2
    assert (
        horizontal_button_count(kinds.PHONATION_PAIR, ("a", "b", "c"), ()) == 3
    )
    assert (
        horizontal_button_count(kinds.LONG_PAIR, ("a", "b", "c", "d"), ()) == 4
    )
    assert horizontal_button_count(kinds.STACK, ("a", "b", "c"), ()) == 1
    # CONTRAST_SET spans its grid column extent; canonical 2 without one.
    assert (
        horizontal_button_count(
            kinds.CONTRAST_SET,
            ("a", "b", "c"),
            ((0, 0), (1, 0), (2, 0)),
        )
        == 3
    )
    assert horizontal_button_count(kinds.CONTRAST_SET, ("a", "b"), ()) == 2


def test_classify_position_difference_is_a_featureless_stack() -> None:
    """A cell whose entries differ on a POSITION feature (here ``high``)
    still stacks with NO contrast features: the 2-D quadrilateral genuinely
    cannot resolve it, so there is no secondary dimension to name. This is
    the honesty valve the contrast-aware stack must not swallow."""
    from phonology_shared.chart.vowel_space_geometry.classifier import (
        classify_display_kind as _classify_vowel_cell_display,
    )
    from phonology_shared.chart.vowels import VowelCellDisplayKind

    feats = _make_classifier_feats(
        {
            "e": {"high": "-", "low": "-", "nasal": "-"},
            "i": {"high": "+", "low": "-", "nasal": "+"},
        }
    )
    kind, contrast, _, _, _ = _classify_vowel_cell_display(("e", "i"), feats)
    assert kind == VowelCellDisplayKind.STACK
    assert contrast == ()


def test_classify_tone_pair() -> None:
    from phonology_shared.chart.vowel_space_geometry.classifier import (
        classify_display_kind as _classify_vowel_cell_display,
    )
    from phonology_shared.chart.vowels import VowelCellDisplayKind

    feats = _make_classifier_feats(
        {
            "ā": {"high": "-", "low": "+", "tone": "H"},
            "à": {"high": "-", "low": "+", "tone": "L"},
        }
    )
    kind, contrast, _, _, _ = _classify_vowel_cell_display(("ā", "à"), feats)
    assert kind == VowelCellDisplayKind.TONE_PAIR
    assert contrast == ("tone",)


def test_classify_pharyngeal_pair() -> None:
    """A plain + pharyngealised (retracted-tongue-root) vowel pair links
    as a PHARYNGEAL_PAIR when the source data encodes the RTR contrast
    (e.g. Archi i / iˤ, if the record sets ``rtr``). Ordered plain-left,
    marked-right like the other pairs."""
    from phonology_shared.chart.vowel_space_geometry.classifier import (
        classify_display_kind as _classify_vowel_cell_display,
    )
    from phonology_shared.chart.vowels import VowelCellDisplayKind

    feats = _make_classifier_feats(
        {
            "i": {"high": "+", "front": "+", "rtr": "-"},
            "iˤ": {"high": "+", "front": "+", "rtr": "+"},
        }
    )
    kind, contrast, ordered, _, _ = _classify_vowel_cell_display(
        ("iˤ", "i"), feats
    )
    assert kind == VowelCellDisplayKind.PHARYNGEAL_PAIR
    assert contrast == ("rtr",)
    assert ordered == ("i", "iˤ")  # plain left, pharyngealised right


def test_classify_long_plus_nasal_is_contrast_set() -> None:
    """Four entries differing on long and nasal -> CONTRAST_SET with
    both features in the sorted contrast tuple.
    """
    from phonology_shared.chart.vowel_space_geometry.classifier import (
        classify_display_kind as _classify_vowel_cell_display,
    )
    from phonology_shared.chart.vowels import VowelCellDisplayKind

    feats = _make_classifier_feats(
        {
            "a": {"long": "-", "nasal": "-", "high": "-", "low": "+"},
            "aa": {"long": "+", "nasal": "-", "high": "-", "low": "+"},
            "aN": {"long": "-", "nasal": "+", "high": "-", "low": "+"},
            "aaN": {"long": "+", "nasal": "+", "high": "-", "low": "+"},
        }
    )
    kind, contrast, ordered, grid, _ = _classify_vowel_cell_display(
        ("a", "aa", "aN", "aaN"), feats
    )
    assert kind == VowelCellDisplayKind.CONTRAST_SET
    assert contrast == ("long", "nasal")
    assert ordered == ("a", "aa", "aN", "aaN")
    # Complete set -> feature-aligned 2x2 (no empty quadrant to centre a
    # base around): columns = long (short left, long right), rows = nasal
    # (oral top, nasal bottom). Parallel to ``ordered``.
    assert grid == ((0, 0), (1, 0), (0, 1), (1, 1))


def test_classify_multi_mark_variant_uses_base_and_variants() -> None:
    """A 3-entry length x nasal set whose "biggest" variant carries
    BOTH pluses (Dzongkha's u / uː / ũː: plain, +long, +long+nasal)
    still fires base-and-variants: the base ``u`` anchors the layout
    and the two variants (one mono, one compound) stack on the right.
    Aligned 2x2 is reserved for COMPLETE 4-entry sets under the
    current classifier, so 3-entry partial sets always route through
    the base-and-variants branch with the base spanning the left
    column top-to-bottom."""
    from phonology_shared.chart.vowel_space_geometry.classifier import (
        classify_display_kind as _classify_vowel_cell_display,
    )
    from phonology_shared.chart.vowels import VowelCellDisplayKind

    feats = _make_classifier_feats(
        {
            "u": {"high": "+", "back": "+", "long": "-", "nasal": "-"},
            "uː": {"high": "+", "back": "+", "long": "+", "nasal": "-"},
            "ũː": {"high": "+", "back": "+", "long": "+", "nasal": "+"},
        }
    )
    kind, contrast, ordered, grid, spans = _classify_vowel_cell_display(
        ("uː", "ũː", "u"), feats
    )
    assert kind == VowelCellDisplayKind.CONTRAST_SET
    assert contrast == ("long", "nasal")
    # Base first, then variants (mono uː before compound ũː by
    # n_pluses ascending); base spans the left column top-to-bottom.
    assert ordered == ("u", "uː", "ũː")
    assert grid == ((0, 0), (1, 0), (1, 1))
    assert spans == ((1, 2), (1, 1), (1, 1))


def test_classify_partial_contrast_set_prefers_aligned_2x2_when_it_fits() -> None:
    """A 3-entry set with a BASE + 2 STRICT monofactor variants
    (u plain, uː long-only, ũ nasal-only) fits cleanly into a
    feature-aligned 2x2 (three quadrants populated, one empty).
    The classifier prefers this over the base-and-variants layout
    because the aligned 2x2 keeps the axes named by feature -- the
    ``long`` axis reads left-to-right, the ``nasal`` axis reads
    top-to-bottom, and each cell reads as a feature bundle.
    Base-and-variants is the fallback for cases where the 2x2
    collides or exceeds four entries."""
    from phonology_shared.chart.vowel_space_geometry.classifier import (
        classify_display_kind as _classify_vowel_cell_display,
    )
    from phonology_shared.chart.vowels import VowelCellDisplayKind

    feats = _make_classifier_feats(
        {
            "u": {"high": "+", "back": "+", "long": "-", "nasal": "-"},
            "uː": {"high": "+", "back": "+", "long": "+", "nasal": "-"},
            "ũ": {"high": "+", "back": "+", "long": "-", "nasal": "+"},
        }
    )
    kind, contrast, ordered, grid, spans = _classify_vowel_cell_display(
        ("uː", "ũ", "u"), feats
    )
    assert kind == VowelCellDisplayKind.CONTRAST_SET
    assert contrast == ("long", "nasal")
    # Aligned 2x2 reading order: sorted by (row, col). u lands at
    # (0, 0), uː at (1, 0), ũ at (0, 1). All spans (1, 1).
    assert ordered == ("u", "uː", "ũ")
    assert grid == ((0, 0), (1, 0), (0, 1))
    assert spans == ((1, 1), (1, 1), (1, 1))


def test_pair_ordering_puts_marked_on_right() -> None:
    """For each PAIR kind, ``entries[1]`` is the ``+``-valued
    member of the contrast feature; this is the renderer's
    canonical "marked on right" convention.
    """
    from phonology_shared.chart.vowel_space_geometry.classifier import (
        classify_display_kind as _classify_vowel_cell_display,
    )
    from phonology_shared.chart.vowels import VowelCellDisplayKind

    # Input order intentionally reversed for each case so the
    # classifier has to reorder.
    cases = [
        (
            VowelCellDisplayKind.LONG_PAIR,
            "long",
            {"a": {"long": "+"}, "b": {"long": "-"}},
        ),
        (
            VowelCellDisplayKind.NASAL_PAIR,
            "nasal",
            {"a": {"nasal": "+"}, "b": {"nasal": "-"}},
        ),
        (
            VowelCellDisplayKind.RHOTIC_PAIR,
            "rhotic",
            {"a": {"rhotic": "+"}, "b": {"rhotic": "-"}},
        ),
    ]
    for expected_kind, feat, feats in cases:
        kind, contrast, ordered, grid, _ = _classify_vowel_cell_display(
            ("a", "b"), feats
        )
        assert kind == expected_kind, f"{expected_kind}: got {kind}"
        assert contrast == (feat,)
        # Marked (+) member must end up at index 1.
        assert ordered == (
            "b",
            "a",
        ), f"{expected_kind}: expected marked on right; got {ordered}"


def test_classify_stack_for_three_position_differences() -> None:
    """3 entries differing on a non-display feature still produce
    STACK (the classifier never silently upgrades position
    differences to a display contrast).
    """
    from phonology_shared.chart.vowel_space_geometry.classifier import (
        classify_display_kind as _classify_vowel_cell_display,
    )
    from phonology_shared.chart.vowels import VowelCellDisplayKind

    feats = _make_classifier_feats(
        {
            "a": {"high": "-", "low": "+"},
            "b": {"high": "-", "low": "-"},
            "c": {"high": "+", "low": "-"},
        }
    )
    kind, contrast, _, _, _ = _classify_vowel_cell_display(("a", "b", "c"), feats)
    assert kind == VowelCellDisplayKind.STACK
    assert contrast == ()


def test_view_model_serializes_display_kind() -> None:
    """The presentation bridge exposes ``display_kind`` and
    ``contrast_features`` on every cell payload so the web renderer
    can switch on them without re-deriving from entries.
    """
    from phonology_shared.presentation.view_models import (
        _vowel_chart_summary,
    )

    path = INVENTORIES_DIR / "english_features.json"
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    engine = FeatureEngine(Inventory.parse(raw, source=str(path)))
    vowels = [
        s for s in engine.segments if engine.segments[s].get("Syllabic") == "+"
    ]
    payload = _vowel_chart_summary(engine, vowels)
    assert "cells" in payload
    for cell_payload in payload["cells"]:
        assert "display_kind" in cell_payload
        assert "contrast_features" in cell_payload
        # display_kind serializes as a string (StrEnum value).
        assert isinstance(cell_payload["display_kind"], str)
        assert isinstance(cell_payload["contrast_features"], list)


def test_inventory_alias_collapses_rcolored_to_rhotic() -> None:
    """The data-boundary alias map folds the descriptive ``r-colored``
    and synonyms onto the canonical IPA-distinctive-feature name
    ``rhotic``; ``breathy voice`` -> ``breathy``;
    ``creaky_voice`` -> ``creaky``.
    """
    from phonology_shared.data.inventory import normalize_feature_key

    assert normalize_feature_key("r-colored") == "rhotic"
    assert normalize_feature_key("r_colored") == "rhotic"
    assert normalize_feature_key("R Coloured") == "rhotic"
    assert normalize_feature_key("rhotacized") == "rhotic"
    assert normalize_feature_key("breathy voice") == "breathy"
    assert normalize_feature_key("breathy_voice") == "breathy"
    assert normalize_feature_key("creaky voice") == "creaky"
    # Canonical names pass through unchanged.
    assert normalize_feature_key("rhotic") == "rhotic"
    assert normalize_feature_key("breathy") == "breathy"
    assert normalize_feature_key("creaky") == "creaky"


def test_bundled_inventories_placement_stable_under_extensions() -> None:
    """No bundled inventory uses any of the new placement features
    (rtr, raised, lowered, advanced, retracted, centralized,
    peripheral). The (row, col) of every vowel must match the
    pre-extension snapshot, so the extension is a strict no-op for
    current users.

    The snapshot is inlined as a hardcoded dict rather than living
    in a fixture file so the regression baseline travels with the
    test and any future placement change is forced through a
    deliberate snapshot update.
    """
    snapshot = _PLACEMENT_SNAPSHOT
    for inv in sorted(INVENTORIES_DIR.glob("*.json")):
        if inv.name.startswith("_") or inv.name.startswith("."):
            continue
        if inv.name not in snapshot:
            continue
        geom = _geometry(inv.name)
        actual: dict[str, list[int]] = {}
        for cell in geom.cells:
            for seg in cell.entries:
                actual[seg] = [cell.row, cell.col]
        expected = snapshot[inv.name]
        assert actual == expected, (
            f"{inv.name}: placement drift from pre-extension snapshot. "
            f"Expected {sorted(expected.items())}, "
            f"got {sorted(actual.items())}"
        )


# Pre-extension snapshot of (row, col) per vowel per bundled inventory.
# Captured before the placement-layer extensions landed; the
# regression test above asserts every entry still matches. If a
# deliberate placement change is needed, regenerate this dict with
# a small script and review the diff before approving.
_PLACEMENT_SNAPSHOT: dict[str, dict[str, list[int]]] = {
    "english_features.json": {
        "e": [2, 0],
        "i": [0, 0],
        "o": [2, 5],
        "u": [0, 5],
        "æ": [6, 0],
        "ɑ": [6, 4],
        "ɔ": [4, 5],
        "ə": [4, 2],
        "ɚ": [4, 2],
        "ɛ": [4, 0],
        "ɪ": [1, 0],
        "ʊ": [1, 5],
        "ʌ": [4, 4],
    },
    "german_features.json": {
        "eː": [2, 0],
        "iː": [0, 0],
        "oː": [2, 5],
        "uː": [0, 5],
        "yː": [0, 1],
        "øː": [2, 1],
        "œ": [4, 1],
        "ɑ": [6, 4],
        "ɑː": [6, 4],
        "ɔ": [4, 5],
        "ɛ": [4, 0],
        "ɪ": [1, 0],
        "ʊ": [1, 5],
        "ʏ": [1, 1],
    },
    "hayes_features.json": {
        "a": [6, 2],
        "e": [2, 0],
        "i": [0, 0],
        "o": [2, 5],
        "u": [0, 5],
        "y": [0, 1],
        "æ": [6, 0],
        "ø": [2, 1],
        "œ": [4, 1],
        "ɑ": [6, 4],
        "ɒ": [6, 5],
        "ɔ": [4, 5],
        "ɘ": [2, 2],
        "ə": [4, 2],
        "ɛ": [4, 0],
        "ɞ": [4, 3],
        "ɤ": [2, 4],
        "ɨ": [0, 2],
        "ɪ": [1, 0],
        "ɯ": [0, 4],
        "ɵ": [2, 3],
        "ɶ": [6, 1],
        "ʉ": [0, 3],
        "ʊ": [1, 5],
        "ʌ": [4, 4],
        "ʏ": [1, 1],
    },
    "hindi_features.json": {
        "eː": [2, 0],
        "iː": [0, 0],
        "oː": [2, 5],
        "uː": [0, 5],
        "æː": [6, 0],
        "ɑː": [6, 4],
        "ɔː": [4, 5],
        "ə": [4, 2],
        "ɛː": [4, 0],
        "ɪ": [1, 0],
        "ʊ": [1, 5],
    },
    "ilokano_features.json": {
        "a": [6, 2],
        "e": [2, 0],
        "i": [0, 0],
        "o": [2, 5],
        "u": [0, 5],
        "ɯ": [0, 4],
    },
    "indonesian_features.json": {
        "a": [6, 2],
        "e": [2, 0],
        "i": [0, 0],
        "o": [2, 5],
        "u": [0, 5],
        "ə": [4, 2],
    },
    "japanese_features.json": {
        "a": [6, 2],
        "aː": [6, 2],
        "e": [2, 0],
        "eː": [2, 0],
        "i": [0, 0],
        "iː": [0, 0],
        "o": [2, 5],
        "oː": [2, 5],
        "ɯ": [0, 4],
        "ɯː": [0, 4],
    },
    "korean_features.json": {
        "a": [6, 2],
        "e": [2, 0],
        "i": [0, 0],
        "o": [2, 5],
        "u": [0, 5],
        "ɯ": [0, 4],
        "ʌ": [4, 4],
    },
    "lango_features.json": {
        "a": [5, 2],
        "e": [2, 0],
        "i": [0, 0],
        "o": [2, 5],
        "u": [0, 5],
        "ɔ": [4, 5],
        "ə": [2, 2],
        "ɛ": [4, 0],
        "ɪ": [1, 0],
        "ʊ": [1, 5],
    },
    "lomongo_features.json": {
        "a": [6, 2],
        "e": [2, 0],
        "i": [0, 0],
        "m̩": [4, 2],
        "n̩": [4, 2],
        "o": [2, 5],
        "u": [0, 5],
        "ŋ̩": [0, 2],
        "ɔ": [4, 5],
        "ɛ": [4, 0],
    },
    "mandarin_chinese_features.json": {
        "a": [6, 2],
        "i": [0, 0],
        "u": [0, 5],
        "y": [0, 1],
        "ə": [3, 2],
        "ɚ": [3, 2],
    },
    "maximalist_vowels.json": {
        "a": [6, 0],
        "e": [2, 0],
        "e̞": [3, 0],
        "i": [0, 0],
        "o": [2, 5],
        "o̞": [3, 5],
        "u": [0, 5],
        "y": [0, 1],
        "ä": [6, 2],
        "æ": [5, 0],
        "ø": [2, 1],
        "ø̞": [3, 1],
        "œ": [4, 1],
        "ɐ": [5, 7],
        "ɑ": [6, 4],
        "ɒ": [6, 5],
        "ɔ": [4, 5],
        "ɘ": [2, 2],
        "ə": [3, 7],
        "ɛ": [4, 0],
        "ɜ": [4, 2],
        "ɞ": [4, 3],
        "ɤ": [2, 4],
        "ɤ̞": [3, 4],
        "ɨ": [0, 2],
        "ɪ": [1, 0],
        "ɯ": [0, 4],
        "ɵ": [2, 3],
        "ɶ": [6, 1],
        "ʉ": [0, 3],
        "ʊ": [1, 5],
        "ʌ": [4, 4],
        "ʏ": [1, 1],
    },
    "modern_standard_arabic_features.json": {
        "a": [6, 2],
        "aː": [6, 2],
        "i": [0, 0],
        "iː": [0, 0],
        "u": [0, 5],
        "uː": [0, 5],
    },
    "spanish_features.json": {
        "a": [6, 2],
        "e": [3, 0],
        "i": [0, 0],
        "o": [3, 5],
        "u": [0, 5],
    },
    "tobabatak_features.json": {
        "a": [6, 2],
        "e": [2, 0],
        "i": [0, 0],
        "o": [2, 5],
        "u": [0, 5],
    },
    "turkish_features.json": {
        "e": [2, 0],
        "i": [0, 0],
        "o": [2, 5],
        "u": [0, 5],
        "y": [0, 1],
        "ø": [2, 1],
        "ɑ": [6, 4],
        "ɯ": [0, 4],
    },
}
