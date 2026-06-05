"""Derived index contract.

:py:class:`Inventory` exposes ``feature_index`` and ``segment_index``
as O(1) lookups so engine and chart code does not scan tuples on
every query. These tests pin the contract: indexes match iteration
order, are read-only, and round-trip through
:py:meth:`Inventory.parse` consistently.
"""

from __future__ import annotations

import pytest

from phonology_shared.data.inventory import Inventory


def _basic_inv() -> Inventory:
    return Inventory.parse(
        {
            "features": ["Voice", "Nasal", "Long"],
            "segments": {
                "p": {"Voice": "-", "Nasal": "-", "Long": "-"},
                "b": {"Voice": "+", "Nasal": "-", "Long": "-"},
                "m": {"Voice": "+", "Nasal": "+", "Long": "-"},
            },
        }
    )


def test_feature_index_matches_iteration_order() -> None:
    inv = _basic_inv()
    assert inv.feature_index["Voice"] == 0
    assert inv.feature_index["Nasal"] == 1
    assert inv.feature_index["Long"] == 2
    # Iteration-order parity.
    for i, name in enumerate(inv.features):
        assert inv.feature_index[name] == i


def test_segment_index_matches_iteration_order() -> None:
    inv = _basic_inv()
    assert inv.segment_index["p"] == 0
    assert inv.segment_index["b"] == 1
    assert inv.segment_index["m"] == 2
    for i, seg in enumerate(inv.segments):
        assert inv.segment_index[seg] == i


def test_indexes_are_read_only() -> None:
    """Both index views are :py:class:`MappingProxyType` wrappers;
    mutating them raises ``TypeError`` so engine code cannot drift
    out of sync with ``features`` / ``segments``."""
    inv = _basic_inv()
    with pytest.raises(TypeError):
        inv.feature_index["Voice"] = 99  # type: ignore[index]
    with pytest.raises(TypeError):
        inv.segment_index["p"] = 99  # type: ignore[index]


def test_indexes_complete() -> None:
    """Every declared feature and every validated segment appears
    in the matching index. No silent omissions."""
    inv = _basic_inv()
    assert set(inv.feature_index) == set(inv.features)
    assert set(inv.segment_index) == set(inv.segments)


def test_empty_inventory_indexes_empty() -> None:
    """An inventory with no segments parses fine; both indexes are
    empty proxies."""
    inv = Inventory.parse({"features": ["Voice"], "segments": {}})
    assert dict(inv.feature_index) == {"Voice": 0}
    assert dict(inv.segment_index) == {}


def test_indexes_survive_round_trip_through_parse() -> None:
    """``to_json_dict`` -> ``parse`` produces an inventory whose
    indexes match the original (modulo Untitled-Inventory naming
    when no metadata.name is set)."""
    inv = _basic_inv()
    redo = Inventory.parse(inv.to_json_dict())
    assert dict(redo.feature_index) == dict(inv.feature_index)
    assert dict(redo.segment_index) == dict(inv.segment_index)
