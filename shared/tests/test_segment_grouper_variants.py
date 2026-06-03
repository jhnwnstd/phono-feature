"""Mouth-position ordering: fronted (X+) -> base (X) -> retracted (X-).

The Front / Back feature sort tables put ``"0"`` (underspecified)
between ``"+"`` and ``"-"`` so a base ``X`` lands at its natural
mid-mouth position, putting the family in front-of-mouth ->
back-of-mouth order without any label-aware logic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from phonology_shared.engine import Inventory, FeatureEngine

HAYES = (
    Path(__file__).resolve().parents[2]
    / "desktop"
    / "inventories"
    / "hayes_features.json"
)


@pytest.fixture(scope="module")
def engine() -> FeatureEngine:
    return FeatureEngine(Inventory.load(str(HAYES)))


def _index(group: list[str], seg: str) -> int:
    assert seg in group, f"{seg!r} missing from group {group!r}"
    return group.index(seg)


def test_l_family_orders_plus_then_base_then_minus(
    engine: FeatureEngine,
) -> None:
    liquids = engine.grouped_segments["Liquids"]
    assert (
        _index(liquids, "ʟ+")
        < _index(liquids, "ʟ")
        < _index(liquids, "ʟ-")
    )


def test_velar_plosive_family_orders_plus_then_base_then_minus(
    engine: FeatureEngine,
) -> None:
    plosives = engine.grouped_segments["Plosives"]
    assert _index(plosives, "k+") < _index(plosives, "k") < _index(
        plosives, "k-"
    )
    assert _index(plosives, "ɡ+") < _index(plosives, "ɡ") < _index(
        plosives, "ɡ-"
    )


def test_velar_approximant_base_clusters_with_retracted(
    engine: FeatureEngine,
) -> None:
    """No ``ɰ+`` exists in Hayes; the bare ``ɰ`` should still land
    immediately before ``ɰ-`` because the base sort key (front=``"0"``,
    back=``"0"``) sits between ``+`` and ``-`` on both axes.
    """
    semis = engine.grouped_segments["Semivowels"]
    assert _index(semis, "ɰ") + 1 == _index(semis, "ɰ-")
