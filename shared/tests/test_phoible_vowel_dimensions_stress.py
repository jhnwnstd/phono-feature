"""Whole-PHOIBLE vowel-chart sizing stress suite.

Iterates every PHOIBLE inventory that has vowels (~2700) and pins
hard caps on the chart's natural data dimensions. The suite is the
regression backstop for the sizing pipeline: a future bake schema
change, placement-policy tweak, or natural-size computation
regression that pushes any one inventory past the caps surfaces
here with the failing language named.

These caps are calibrated against the current PHOIBLE 2.0 snapshot
(verified empirically):

- **Width**: max observed across 3020 inventories is **302 px**;
  the ``VOWEL_NATURAL_W = 440 px`` container floor honours every
  one with headroom.
- **Height**: max observed is **931 px** on !XU/UPSID (46 vowels
  with one 12-entry cell stack). The pathological-cell density
  tier (``data-cell-density="ultra"`` for 10+ entries) tightens
  the renderer's box budget for those cases; the underlying
  geometry still reports the worst case so the pane's
  ``overflow: auto`` parent takes the scrollbar when needed.

Skipped when the PHOIBLE bake snapshot is absent.
"""

from __future__ import annotations

import pytest

from phonology_shared.chart.vowels import (
    build_vowel_chart_geometry,
    detect_vowel_profile,
)
from phonology_shared.theory.feature_engine import FeatureEngine

try:
    from phonology_shared.editor.phoible_provider import (
        PhoibleProvider,
        materialize_phoible_inventory,
    )
except ImportError:  # pragma: no cover - dev-only path
    pytest.skip("phoible_provider unavailable", allow_module_level=True)


# Hard caps. Any single inventory exceeding these breaks the test
# and names the offender so we know whether to bump the cap or fix
# upstream. Calibrated against the current snapshot's worst cases
# plus a safety margin.
_NATURAL_WIDTH_HARD_CAP_PX = 400
_NATURAL_HEIGHT_HARD_CAP_PX = 1100
_MAX_CELL_STACK_HARD_CAP = 14


@pytest.fixture(scope="module")
def provider() -> PhoibleProvider:
    try:
        return PhoibleProvider()
    except FileNotFoundError as exc:  # pragma: no cover
        pytest.skip(f"PHOIBLE snapshot not baked: {exc}")
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"PHOIBLE provider unavailable: {exc}")


@pytest.fixture(scope="module")
def all_inventory_ids(provider: PhoibleProvider) -> list[str]:
    return list(provider._inventories)  # type: ignore[attr-defined]


def _label_for(provider: PhoibleProvider, inv_id: str) -> str:
    desc = provider.descriptor(inv_id)
    if desc is None:
        return inv_id
    return f"{desc.language_name}/{desc.source_short}"


def _build_geometry(provider: PhoibleProvider, inv_id: str):
    """Materialize the inventory through the same pipeline the UI
    uses and return the chart geometry. ``None`` if the inventory
    has no vowels (the chart is not rendered)."""
    inv = materialize_phoible_inventory(provider, inv_id)
    engine = FeatureEngine(inv)
    vowels = list(engine.grouped_segments.get("Vowels", []))
    if not vowels:
        return None
    seg_feats = {s: dict(engine.normalized_segment_feats[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    secondary = inv.metadata.get("vowel_secondary")
    secondary_map = secondary if isinstance(secondary, dict) else None
    return build_vowel_chart_geometry(
        vowels, profile, seg_feats, vowel_secondary=secondary_map
    )


def test_v1_natural_width_within_hard_cap(
    provider: PhoibleProvider, all_inventory_ids: list[str]
) -> None:
    """Every PHOIBLE inventory's natural chart width fits within
    the hard cap. The container width
    (:py:data:`phonology_shared.presentation.layout.VOWEL_NATURAL_W`)
    must always exceed the natural width so the chart never needs
    horizontal scroll.
    """
    offenders: list[tuple[str, int]] = []
    for inv_id in all_inventory_ids:
        geom = _build_geometry(provider, inv_id)
        if geom is None:
            continue
        if geom.natural_data_width_px > _NATURAL_WIDTH_HARD_CAP_PX:
            offenders.append(
                (_label_for(provider, inv_id), geom.natural_data_width_px)
            )
    assert not offenders, (
        f"natural vowel-chart width exceeded "
        f"{_NATURAL_WIDTH_HARD_CAP_PX}px in {len(offenders)} "
        f"inventories: {offenders[:10]}"
    )


def test_v2_natural_height_within_hard_cap(
    provider: PhoibleProvider, all_inventory_ids: list[str]
) -> None:
    """Every PHOIBLE inventory's natural chart height fits within
    the hard cap. The container's parent must scroll if the
    allocated height is smaller, but no single chart should grow
    unboundedly. The pathological-cell density tier
    (``data-cell-density="ultra"`` for 10+ entries) tightens
    the box; the underlying geometry still reports the worst
    natural height the renderer should be prepared to host.
    """
    offenders: list[tuple[str, int]] = []
    for inv_id in all_inventory_ids:
        geom = _build_geometry(provider, inv_id)
        if geom is None:
            continue
        if geom.natural_data_height_px > _NATURAL_HEIGHT_HARD_CAP_PX:
            offenders.append(
                (_label_for(provider, inv_id), geom.natural_data_height_px)
            )
    assert not offenders, (
        f"natural vowel-chart height exceeded "
        f"{_NATURAL_HEIGHT_HARD_CAP_PX}px in {len(offenders)} "
        f"inventories: {offenders[:10]}"
    )


def test_v3_no_cell_stack_exceeds_hard_cap(
    provider: PhoibleProvider, all_inventory_ids: list[str]
) -> None:
    """No single chart cell holds more than the hard cap of
    segments. PHOIBLE's worst case is currently 12; the cap is
    set at 14 to allow modest growth on a future bake while
    catching unbounded explosions.
    """
    offenders: list[tuple[str, int]] = []
    for inv_id in all_inventory_ids:
        geom = _build_geometry(provider, inv_id)
        if geom is None or not geom.cells:
            continue
        worst = max(len(c.entries) for c in geom.cells)
        if worst > _MAX_CELL_STACK_HARD_CAP:
            offenders.append((_label_for(provider, inv_id), worst))
    assert not offenders, (
        f"single-cell stack exceeded {_MAX_CELL_STACK_HARD_CAP} "
        f"in {len(offenders)} inventories: {offenders[:10]}"
    )


def test_v4_natural_width_floor_fits_in_vowel_container(
    provider: PhoibleProvider, all_inventory_ids: list[str]
) -> None:
    """The chart container's pinned width
    (``VOWEL_NATURAL_W``) must hold every PHOIBLE inventory's
    natural data width without horizontal scroll. Catches a
    future regression where someone shrinks ``VOWEL_NATURAL_W``
    below an actual PHOIBLE need."""
    from phonology_shared.presentation.layout import VOWEL_NATURAL_W

    offenders: list[tuple[str, int]] = []
    # Account for the label-gutter chrome the chart container
    # reserves around the data area; the container's "data area"
    # is roughly ``VOWEL_NATURAL_W - VOWEL_LABEL_W`` (label gutter)
    # but we use the conservative cap to keep this from drifting
    # against an arbitrary chrome-budget refactor. If the test
    # surfaces, recompute the budget against the live constant.
    data_area_w = VOWEL_NATURAL_W - 60  # rough chrome reserve
    for inv_id in all_inventory_ids:
        geom = _build_geometry(provider, inv_id)
        if geom is None:
            continue
        if geom.natural_data_width_px > data_area_w:
            offenders.append(
                (_label_for(provider, inv_id), geom.natural_data_width_px)
            )
    assert not offenders, (
        f"natural width exceeded the chart container's data-area "
        f"budget ({data_area_w}px) in {len(offenders)} inventories: "
        f"{offenders[:10]}"
    )


def test_v5_report_size_distribution(
    provider: PhoibleProvider,
    all_inventory_ids: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Diagnostic-only: prints percentile distribution of natural
    widths, heights, and cell-stack depths so future sizing work
    has a baseline. Does not fail on any value; the hard caps
    above are the enforcement layer."""
    widths: list[int] = []
    heights: list[int] = []
    worst_cells: list[int] = []
    for inv_id in all_inventory_ids:
        geom = _build_geometry(provider, inv_id)
        if geom is None:
            continue
        widths.append(geom.natural_data_width_px)
        heights.append(geom.natural_data_height_px)
        if geom.cells:
            worst_cells.append(max(len(c.entries) for c in geom.cells))
    widths.sort()
    heights.sort()
    worst_cells.sort()

    def _pct(values: list[int], pct: float) -> int:
        if not values:
            return 0
        idx = min(len(values) - 1, int(len(values) * pct))
        return values[idx]

    with capsys.disabled():
        print(
            "\nPHOIBLE vowel chart size distribution "
            f"({len(widths)} inventories with vowels):"
        )
        print(
            f"  width:  p50={_pct(widths, 0.5)} "
            f"p90={_pct(widths, 0.9)} "
            f"p99={_pct(widths, 0.99)} "
            f"max={widths[-1]}"
        )
        print(
            f"  height: p50={_pct(heights, 0.5)} "
            f"p90={_pct(heights, 0.9)} "
            f"p99={_pct(heights, 0.99)} "
            f"max={heights[-1]}"
        )
        print(
            f"  worst-cell: p50={_pct(worst_cells, 0.5)} "
            f"p90={_pct(worst_cells, 0.9)} "
            f"max={worst_cells[-1]}"
        )
