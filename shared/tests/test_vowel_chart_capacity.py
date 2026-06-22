"""Capacity contract: the vowel chart degrades gracefully up to and
beyond the per-class hard caps.

The app accepts user-built inventories, so the geometry must never
produce a buggy layout (buttons overlapping each other or escaping
the outline) even at the cap values: ``MAX_VOWELS`` vowels and a
mixed-tier worst case. "Displays well" is covered by the PHOIBLE
stress suites; this file pins "displays CORRECTLY" at the extremes.

Two invariants, both judged at the geometry's NATURAL size (the
size the chart asks for, where every guarantee must hold before any
render-time clamp shrinks things further):

* The ROW-FIT invariant: every row's proportional slot covers its
  tallest cell's rendered pixel height. This is what keeps a deep
  stack from spilling into the row above or below it.
* No two cell button boxes overlap by more than a rounding epsilon,
  and every box stays inside the dw-corrected silhouette.

The numbers (50 vowels = So, 133 consonants = !Xóõ) are the densest
real PHOIBLE inventories; the caps were sized to them, so the cap
boundary and the data the display logic is verified against are the
same thing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from phonology_shared.chart.vowel_geometry import (
    build_vowel_chart_geometry,
    silhouette_for_data_width,
    straight_left_at_y,
    straight_right_at_y,
)
from phonology_shared.chart.vowel_geometry.cell_boxes import (
    _cell_box_px,
    _cell_height_px,
)
from phonology_shared.chart.vowels import (
    PlacementPolicy,
    VowelProfile,
    detect_vowel_profile,
)
from phonology_shared.data.inventory import Inventory
from phonology_shared.theory.feature_engine import FeatureEngine

_OVERLAP_EPS_PX = 0.5


def _profile_for(seg_feats: dict[str, dict[str, str]]) -> VowelProfile:
    return detect_vowel_profile(list(seg_feats), seg_feats)


def _assert_no_overlap_and_contained(geom: object, label: str) -> None:
    """Pin both capacity invariants on a built geometry at natural
    size: pairwise box non-overlap, silhouette containment, and the
    row-fit slot guarantee."""
    dw = geom.natural_data_width_px  # type: ignore[attr-defined]
    dh = geom.natural_data_height_px  # type: ignore[attr-defined]
    sil = silhouette_for_data_width(geom.silhouette, dw)  # type: ignore
    tiers = {r.logical_row: r.tier for r in geom.rows}  # type: ignore
    slots = {
        r.logical_row: r.slot_height_norm for r in geom.rows  # type: ignore
    }

    # Row-fit: each row's slot pixels cover its tallest cell.
    tallest: dict[int, int] = {}
    for cell in geom.cells:  # type: ignore[attr-defined]
        h = _cell_height_px(cell)
        if h > tallest.get(cell.row, 0):
            tallest[cell.row] = h
    for row, content_px in tallest.items():
        slot_px = slots[row] * dh
        assert slot_px + 0.51 >= content_px, (
            f"{label}: row {row} slot {slot_px:.1f}px is smaller than its "
            f"tallest cell {content_px}px; the stack would invade an "
            f"adjacent row"
        )

    boxes: list[tuple[float, float, float, float, tuple[str, ...]]] = []
    for cell in geom.cells:  # type: ignore[attr-defined]
        left, top, right, bottom = _cell_box_px(cell, tiers[cell.row], dw, dh)
        boxes.append((left, top, right, bottom, cell.entries))
        for yy in (top, (top + bottom) / 2.0, bottom):
            yn = min(max(yy / dh, sil.top_y), sil.bottom_y)
            # Containment is against the STRAIGHT trapezoid edges; the
            # rounded corners are cosmetic. These vowel-only synthetics
            # are not crowded enough to hit the confinement cap, so the
            # straight edge holds within the rounding epsilon.
            edge_l = straight_left_at_y(sil, yn) * dw
            edge_r = straight_right_at_y(sil, yn) * dw
            assert left >= edge_l - 0.51, (
                f"{label}: {cell.entries} left {left:.1f} escapes outline "
                f"{edge_l:.1f}"
            )
            assert right <= edge_r + 0.51, (
                f"{label}: {cell.entries} right {right:.1f} escapes outline "
                f"{edge_r:.1f}"
            )

    for i in range(len(boxes)):
        la, ta, ra, ba, ea = boxes[i]
        for j in range(i + 1, len(boxes)):
            lb, tb, rb, bb, eb = boxes[j]
            ix = min(ra, rb) - max(la, lb)
            iy = min(ba, bb) - max(ta, tb)
            assert not (ix > _OVERLAP_EPS_PX and iy > _OVERLAP_EPS_PX), (
                f"{label}: cells {ea} and {eb} overlap by "
                f"{ix:.1f}x{iy:.1f}px"
            )


def _phoible_provider_or_skip() -> object:
    """The packaged PHOIBLE provider, or a clean skip when the bake
    snapshot is absent (gitignored on fresh checkouts). Mirrors the
    conftest ``phoible_provider`` fixture's skip semantics so these
    module-level helpers degrade the same way."""
    try:
        from phonology_shared.editor.phoible_provider import (
            default_phoible_provider,
        )
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"phoible_provider unavailable: {exc}")
    try:
        return default_phoible_provider()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"PHOIBLE snapshot not baked: {exc}")


def _phoible_vowels(name: str) -> dict[str, dict[str, str]]:
    """Materialize a named PHOIBLE inventory and return its vowel
    bundles. Skips if PHOIBLE data is unavailable in the test env."""
    from phonology_shared.editor.phoible_provider import (
        materialize_phoible_inventory,
    )

    prov = _phoible_provider_or_skip()
    for inv_id in prov._inventories:  # type: ignore[attr-defined]
        inv = materialize_phoible_inventory(prov, inv_id)
        if inv.name == name:
            eng = FeatureEngine(inv)
            vowels = eng.grouped_segments.get("Vowels", [])
            return {s: dict(eng.normalized_segment_feats[s]) for s in vowels}
    pytest.skip(f"PHOIBLE inventory {name!r} not found")
    return {}


def test_so_fifty_vowels_render_without_overlap() -> None:
    """So [PHOIBLE] is the densest real vowel inventory at exactly
    ``MAX_VOWELS``; before the pixel-weighted row distribution and
    the row-fit floor it produced cross-row button overlaps."""
    feats = _phoible_vowels("So [PHOIBLE]")
    assert len(feats) == 50, f"expected So to have 50 vowels, got {len(feats)}"
    geom = build_vowel_chart_geometry(list(feats), _profile_for(feats), feats)
    _assert_no_overlap_and_contained(geom, "So [PHOIBLE]")


@pytest.mark.parametrize("depth", [15, 25, 50])
def test_deep_single_cell_stack_stays_contained(depth: int) -> None:
    """A pathological single-cell stack just grows the chart taller;
    it must never overflow the outline or self-overlap, however deep
    (the panel scrolls to absorb the height)."""
    base = {
        "high": "+",
        "low": "-",
        "front": "+",
        "back": "-",
        "round": "-",
        "tense": "+",
    }
    # Distinct segment strings sharing one (row, col): the placer
    # stacks them in a single Close-Front cell.
    feats = {f"i{chr(0x2080 + i % 10)}{i}": dict(base) for i in range(depth)}
    geom = build_vowel_chart_geometry(
        list(feats), _profile_for(feats), feats, policy=PlacementPolicy()
    )
    assert len(geom.cells) == 1, "synthetic should collapse to one cell"
    _assert_no_overlap_and_contained(geom, f"stack-depth-{depth}")


def test_mixed_tier_rows_do_not_collide() -> None:
    """The worst case for depth-proportional row sizing: a deep ultra
    stack (12 entries, 18px buttons) one row away from shallow
    canonical rows (26px buttons). Weighting by raw depth over-feeds
    the deep row and starves the shallow ones into overlap; weighting
    by rendered pixel height plus the row-fit floor keeps them
    separate."""
    deep_base = {
        "high": "-",
        "low": "-",
        "front": "-",
        "back": "+",
        "round": "+",
        "tense": "+",
    }
    contrasts = [
        {},
        {"long": "+"},
        {"nasal": "+"},
        {"creaky": "+"},
        {"breathy": "+"},
        {"hightone": "+"},
        {"stress": "+"},
        {"long": "+", "nasal": "+"},
        {"long": "+", "creaky": "+"},
        {"nasal": "+", "creaky": "+"},
        {"long": "+", "breathy": "+"},
        {"nasal": "+", "breathy": "+"},
    ]
    feats: dict[str, dict[str, str]] = {}
    for idx, extra in enumerate(contrasts):
        feats[f"o{chr(0x2080 + idx % 10)}{idx}"] = {**deep_base, **extra}
    # Shallow canonical rows around the deep one.
    feats["i"] = {"high": "+", "front": "+", "back": "-", "round": "-"}
    feats["e"] = {"high": "-", "low": "-", "front": "+", "back": "-"}
    feats["a"] = {"high": "-", "low": "+", "front": "-", "back": "-"}
    geom = build_vowel_chart_geometry(
        list(feats), _profile_for(feats), feats, policy=PlacementPolicy()
    )
    deepest = max(len(c.entries) for c in geom.cells)
    assert (
        deepest >= 10
    ), f"expected an ultra-tier stack; deepest cell has {deepest} entries"
    _assert_no_overlap_and_contained(geom, "mixed-tier")


def test_caps_admit_the_densest_phoible_inventories() -> None:
    """The caps are sized so the densest real inventories load: So
    (50 vowels) and !Xóõ (133 consonants) must materialize and pass
    the class-cap check. This pins the cap values against the data
    they were chosen for, so lowering a cap below a shipping PHOIBLE
    inventory trips here."""
    from phonology_shared.chart.segment_classes import validate_class_caps
    from phonology_shared.editor.phoible_provider import (
        materialize_phoible_inventory,
    )

    prov = _phoible_provider_or_skip()
    seen: dict[str, int] = {}
    for inv_id in prov._inventories:  # type: ignore[attr-defined]
        inv = materialize_phoible_inventory(prov, inv_id)
        if inv.name in ("So [PHOIBLE]", "!Xóõ [PHOIBLE]"):
            messages = validate_class_caps(inv.segments)
            assert (
                messages == []
            ), f"{inv.name} should pass the class caps, got {messages}"
            seen[inv.name] = len(inv.segments)
        if len(seen) == 2:
            break
    assert set(seen) == {
        "So [PHOIBLE]",
        "!Xóõ [PHOIBLE]",
    }, f"expected both reference inventories, found {sorted(seen)}"


def test_bundled_inventories_within_caps(inventories_dir: Path) -> None:
    """Every bundled inventory stays within the per-class caps, so a
    cap change that would reject a shipped inventory fails here.

    Uses the shared ``inventories_dir`` fixture (resolved relative to
    the test file) so the path is portable across machines and CI;
    skips cleanly if the corpus is absent on a fresh checkout."""
    from phonology_shared.chart.segment_classes import validate_class_caps

    paths = sorted(
        p for p in inventories_dir.glob("*.json") if p.stem != "_schema"
    )
    if not paths:
        pytest.skip("bundled inventory corpus not present")
    for path in paths:
        inv = Inventory.load(str(path))
        messages = validate_class_caps(inv.segments)
        assert messages == [], f"{path.name}: {messages}"
