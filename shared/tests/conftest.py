"""Shared pytest fixtures for the ``shared/`` test suite.

The bundled-inventory corpus at ``desktop/inventories/`` is the
single source of truth most tests need a path to. Before this
fixture landed, ~14 test files each computed
``Path(__file__).resolve().parents[2] / "desktop" / "inventories"``
inline (with two name variants, ``INVENTORIES_DIR`` and
``INVENTORIES``, plus a one-off ``_find_repo_root`` helper). Tests
that just need the path now depend on the ``inventories_dir``
fixture; the repository structure has exactly one definition to
maintain.

Tests that build a ``pytest.mark.parametrize`` list from inventory
names (e.g. ``test_view_model_filter_parity``) cannot consume a
fixture at collection time and keep their hard-coded path
derivation.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def inventories_dir() -> Path:
    """Path to the bundled-inventory JSON corpus the test suite
    drives. Resolved once per session."""
    return (
        Path(__file__).resolve().parent.parent.parent
        / "desktop"
        / "inventories"
    ).resolve()
