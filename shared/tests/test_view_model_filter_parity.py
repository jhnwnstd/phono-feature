"""Drift-prevention test for the active-feature filter.

The user reported a desktop / web divergence: bundled Hindi loaded
on the desktop dropped the LowerLarynx row (because every segment
is unspecified for it), while the web rendered the row. The cause
was that the desktop ran an inline active-feature filter in
``_populate_features`` while the web rendered the unfiltered
``feature_groups`` payload from ``build_inventory_summary``.

The fix lifted the filter into ``FeatureEngine.active_features``
and routed both UIs through the shared view-model. This test pins
the contract so the drift can't return:

- ``feature_groups`` in the bridge payload contains exactly
  ``engine.active_features``; never more.
- The payload also carries ``active_features`` as a top-level
  list so a renderer that needs the active set without diving
  into the grouped structure can read it directly.

Test inputs are the bundled inventories (deterministic, available
offline). Synthetic edge cases live in ``test_active_features.py``.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from _inventory_names import BUNDLED_INVENTORY_NAMES

from phonology_shared.data.inventory import Inventory
from phonology_shared.presentation.view_models import (
    build_inventory_summary,
)
from phonology_shared.theory.feature_engine import FeatureEngine


@pytest.fixture(scope="module", params=BUNDLED_INVENTORY_NAMES)
def inventory_name(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture(scope="module")
def loaded(
    inventory_name: str,
    bundled_inventory: Callable[[str], Inventory],
) -> tuple[Inventory, FeatureEngine]:
    inv = bundled_inventory(inventory_name)
    return inv, FeatureEngine(inv)


def test_feature_groups_payload_matches_active_features(
    loaded: tuple[Inventory, FeatureEngine],
) -> None:
    """The set of features in the ``feature_groups`` payload must
    equal ``engine.active_features``. Catches a regression where a
    renderer-side filter re-introduces drift, or where the shared
    view-model stops calling the filter."""
    inv, eng = loaded
    summary = build_inventory_summary(eng, inv.name or "test")
    active = set(eng.active_features)
    in_groups: set[str] = set()
    for group in summary["feature_groups"]:
        in_groups.update(group["features"])
    assert in_groups == active, (
        f"feature_groups payload features {sorted(in_groups)} != "
        f"active_features {sorted(active)}"
    )


def test_active_features_in_payload_top_level(
    loaded: tuple[Inventory, FeatureEngine],
) -> None:
    """``build_inventory_summary`` exposes ``active_features`` as a
    top-level list so renderers can read it without rebuilding the
    set from ``feature_groups``."""
    inv, eng = loaded
    summary = build_inventory_summary(eng, inv.name or "test")
    assert "active_features" in summary
    assert list(summary["active_features"]) == list(eng.active_features)


def test_features_top_level_is_complete(
    loaded: tuple[Inventory, FeatureEngine],
) -> None:
    """``summary['features']`` keeps the full inventory feature
    list (not filtered) so callers that need the raw schema can
    still get it. The filter applies only to display."""
    inv, eng = loaded
    summary = build_inventory_summary(eng, inv.name or "test")
    assert set(summary["features"]) == set(eng.features)
