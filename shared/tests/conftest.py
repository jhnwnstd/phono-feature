"""Shared pytest fixtures for the ``shared/`` test suite.

The bundled-inventory corpus at ``desktop/inventories/`` is the
single source of truth most tests need a path to. Tests that just
need the path depend on the ``inventories_dir`` fixture; tests
that need a parsed :py:class:`Inventory` or constructed
:py:class:`FeatureEngine` depend on
:py:func:`bundled_inventory` / :py:func:`bundled_engine`. The
fixtures consolidate the JSON-load → parse → engine chain that
previously appeared as a per-file ``_engine`` / ``_load_bundled``
helper across five test modules.

``BUNDLED_INVENTORY_NAMES`` is the canonical list of bundled
inventory stems any test wanting per-inventory parametrisation
should import. Keeps the parametrize list in one place so a new
bundled inventory propagates to every parametrised test
automatically.

Tests that need pytest.mark.parametrize over inventory names
cannot consume a fixture at collection time; they import
``BUNDLED_INVENTORY_NAMES`` directly and parametrise against it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

# Re-export so test files can read the bundled-inventory roster
# either through the fixture chain (consumers needing the actual
# list at runtime) or directly via
# ``tests._inventory_names.BUNDLED_INVENTORY_NAMES`` (needed at
# pytest collection time -- conftest.py is not importable as a
# regular module).
from _inventory_names import BUNDLED_INVENTORY_NAMES  # noqa: F401

from phonology_shared.data.inventory import Inventory
from phonology_shared.theory.feature_engine import FeatureEngine


@pytest.fixture(scope="session")
def inventories_dir() -> Path:
    """Path to the bundled-inventory JSON corpus the test suite
    drives. Resolved once per session."""
    return (
        Path(__file__).resolve().parent.parent.parent
        / "desktop"
        / "inventories"
    ).resolve()


@pytest.fixture(scope="session")
def bundled_inventory(
    inventories_dir: Path,
) -> Callable[[str], Inventory]:
    """Return a loader that maps an inventory stem (``"hayes"``,
    ``"english"``) to a parsed :py:class:`Inventory`.

    Skips the calling test with a clear message if the named
    inventory isn't on disk (gitignored under
    :py:data:`phonology_shared.editor.providers.LookupTableProvider`'s
    bake artifacts policy). Centralises the per-file
    ``_load_bundled`` helper five test modules previously each
    defined.
    """

    def _load(name: str) -> Inventory:
        path = inventories_dir / f"{name}_features.json"
        if not path.exists():
            pytest.skip(f"{name} inventory not present (gitignored in CI)")
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        return Inventory.parse(raw, source=path.stem)

    return _load


@pytest.fixture(scope="session")
def bundled_engine(
    bundled_inventory: Callable[[str], Inventory],
) -> Callable[[str], FeatureEngine]:
    """Return a loader that maps an inventory stem to a
    constructed :py:class:`FeatureEngine`. Layers on top of
    :py:func:`bundled_inventory`."""

    def _load(name: str) -> FeatureEngine:
        return FeatureEngine(bundled_inventory(name))

    return _load
