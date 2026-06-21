"""Shared pytest fixtures for the ``shared/`` test suite.

The bundled-inventory corpus at ``desktop/inventories/`` is the
single source of truth most tests need a path to. Tests that just
need the path depend on the ``inventories_dir`` fixture; tests
that need a parsed :py:class:`Inventory` or constructed
:py:class:`FeatureEngine` depend on
:py:func:`bundled_inventory` / :py:func:`bundled_engine`. The
fixtures consolidate the JSON-load to parse to engine chain that
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
# pytest collection time; conftest.py is not importable as a
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


# ---------------------------------------------------------------
# PHOIBLE corpus fixtures (lifted from the four
# ``test_phoible_*_stress.py`` files where they were previously
# duplicated verbatim).
#
# ``phoible_provider``: module-scoped singleton; constructing the
#     PhoibleProvider parses ~3 MB of baked JSON, so each test file
#     used to pay this once. Lifting to conftest lets new diagnostic
#     tests share the same instance.
#
# ``phoible_inventory_ids_full``: every inventory id in the bake
#     snapshot (~3020). Used by tests where the metric being
#     measured is sparse (diphthong coverage; tone-letter routing)
#     and a sample would miss real cases.
#
# ``phoible_inventory_ids_sample``: deterministic 200-inventory
#     random sample (seed 42). Used by tests pinning geometric or
#     feature-distribution invariants where coverage at sample size
#     200 is empirically equivalent to coverage at 3020.
#
# ``phoible_label_for`` / ``phoible_build_geometry``: helper
#     callables returned by fixtures. Test functions receive the
#     closure and use it like the inline helpers they replaced.
# ---------------------------------------------------------------


_PHOIBLE_SAMPLE_SIZE = 200
_PHOIBLE_SAMPLE_SEED = 42


@pytest.fixture(scope="module")
def phoible_provider():
    """Module-scoped :py:class:`PhoibleProvider` singleton.

    Skips the calling test with a clear message when the PHOIBLE
    bake snapshot is absent (gitignored on fresh checkouts; not
    present in CI without an explicit bake step).
    """
    try:
        from phonology_shared.editor.phoible_provider import (
            PhoibleProvider,
        )
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"phoible_provider unavailable: {exc}")
    try:
        return PhoibleProvider()
    except FileNotFoundError as exc:  # pragma: no cover
        pytest.skip(f"PHOIBLE snapshot not baked: {exc}")
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"PHOIBLE provider unavailable: {exc}")


@pytest.fixture(scope="module")
def phoible_inventory_ids_full(phoible_provider) -> list[str]:
    """Every inventory id in the bake snapshot (~3020)."""
    # ``_inventories`` is the internal dict; using it directly
    # avoids materializing 3020 descriptors on every test.
    return list(phoible_provider._inventories)  # type: ignore[attr-defined]


@pytest.fixture(scope="module")
def phoible_inventory_ids_sample(
    phoible_inventory_ids_full: list[str],
) -> list[str]:
    """Deterministic 200-inventory random sample (seed 42).

    Geometric and feature-distribution invariants reach the same
    coverage at this sample size as at the full 3020. Cuts per-
    test runtime by ~15x. Tests pinning sparse phenomena
    (diphthong endpoints, tone-letter routing) consume
    :py:func:`phoible_inventory_ids_full` instead.
    """
    import random

    if len(phoible_inventory_ids_full) <= _PHOIBLE_SAMPLE_SIZE:
        return phoible_inventory_ids_full
    rng = random.Random(_PHOIBLE_SAMPLE_SEED)
    return rng.sample(phoible_inventory_ids_full, _PHOIBLE_SAMPLE_SIZE)


@pytest.fixture(scope="module")
def phoible_label_for(phoible_provider) -> Callable[[str], str]:
    """Return a callable mapping an inventory id to a
    ``"language/source_short"`` label. Used to annotate offender
    lists so test failures name the failing inventory."""

    def _label(inv_id: str) -> str:
        desc = phoible_provider.descriptor(inv_id)
        if desc is None:
            return inv_id
        return f"{desc.language_name}/{desc.source_short}"

    return _label


@pytest.fixture(scope="module")
def phoible_build_geometry(phoible_provider) -> Callable[[str], object]:
    """Return a callable mapping an inventory id to the rendered
    vowel-chart geometry. Returns ``None`` when the inventory has
    no vowels (the chart is not rendered).

    Matches the inline ``_build_geometry`` helper the three vowel
    stress files previously each defined. Materialises the
    inventory through :py:func:`materialize_phoible_inventory`,
    constructs a :py:class:`FeatureEngine`, runs
    :py:func:`detect_vowel_profile`, and calls
    :py:func:`build_vowel_chart_geometry`.
    """
    from phonology_shared.chart.vowel_geometry import (
        build_vowel_chart_geometry,
    )
    from phonology_shared.chart.vowels import detect_vowel_profile
    from phonology_shared.editor.phoible_provider import (
        materialize_phoible_inventory,
    )

    def _build(inv_id: str):
        inv = materialize_phoible_inventory(phoible_provider, inv_id)
        engine = FeatureEngine(inv)
        vowels = list(engine.grouped_segments.get("Vowels", []))
        if not vowels:
            return None
        seg_feats = {
            s: dict(engine.normalized_segment_feats[s]) for s in vowels
        }
        profile = detect_vowel_profile(vowels, seg_feats)
        secondary = inv.metadata.get("vowel_secondary")
        secondary_map = secondary if isinstance(secondary, dict) else None
        return build_vowel_chart_geometry(
            vowels, profile, seg_feats, vowel_secondary=secondary_map
        )

    return _build
