"""Regression test for ``FeatureEngine.active_features``.

The active-feature filter decides which feature rows appear in both
the desktop's feature panel and the web's. Before this filter lived
on the engine, the desktop ran an inline version while the web
rendered every feature, producing the Hindi-inventory LowerLarynx
drift the user reported.

Tests:

- ``test_filter_drops_unspecified_features`` builds a synthetic
  inventory where one feature is uniformly ``0``; asserts the
  feature is absent from ``active_features`` and from the
  ``feature_groups`` payload.
- ``test_filter_keeps_minus_only_features`` builds a synthetic
  inventory where one feature is uniformly ``-``; asserts the
  feature stays in ``active_features`` because ``-`` is an
  explicit specification.
- ``test_bundled_hindi_drops_lower_larynx`` loads the bundled
  Hindi inventory and asserts ``LowerLarynx`` is dropped (matches
  the user's reported desktop behaviour) and that every retained
  feature has at least one explicit ``+`` / ``-``.
- ``test_bundled_english_keeps_all_specified_features`` regression
  against the bundled English inventory — every feature with
  explicit values must survive the filter.
"""

from __future__ import annotations

import json
from pathlib import Path

from phonology_shared.data.inventory import Inventory
from phonology_shared.presentation.view_models import (
    build_inventory_summary,
)
from phonology_shared.theory.feature_engine import FeatureEngine


def _load_bundled(inventories_dir: Path, name: str) -> Inventory:
    path = inventories_dir / f"{name}_features.json"
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    return Inventory.parse(raw, source=path.stem)


def test_filter_drops_unspecified_features() -> None:
    """A feature with value ``0`` for every segment is dropped from
    ``active_features`` and from the ``feature_groups`` payload."""
    features = ["Voice", "Sonorant", "PhantomFeat"]
    segments = {
        "p": {"Voice": "-", "Sonorant": "-", "PhantomFeat": "0"},
        "b": {"Voice": "+", "Sonorant": "-", "PhantomFeat": "0"},
    }
    inv = Inventory.from_grid(
        name="synthetic",
        features=features,
        segments=segments,
    )
    eng = FeatureEngine(inv)
    assert "PhantomFeat" not in eng.active_features
    assert "Voice" in eng.active_features
    assert "Sonorant" in eng.active_features

    summary = build_inventory_summary(eng, "synthetic")
    all_in_groups = {
        f for g in summary["feature_groups"] for f in g["features"]
    }
    assert "PhantomFeat" not in all_in_groups


def test_filter_keeps_minus_only_features() -> None:
    """A feature with all-``-`` values is RETAINED. ``-`` is an
    explicit specification; the user can still query with it."""
    features = ["Voice", "Implosive"]
    segments = {
        "p": {"Voice": "-", "Implosive": "-"},
        "b": {"Voice": "+", "Implosive": "-"},
        "t": {"Voice": "-", "Implosive": "-"},
    }
    inv = Inventory.from_grid(
        name="synthetic",
        features=features,
        segments=segments,
    )
    eng = FeatureEngine(inv)
    assert "Implosive" in eng.active_features
    assert "Voice" in eng.active_features


def test_bundled_hindi_drops_lower_larynx(inventories_dir: Path) -> None:
    """The bundled Hindi inventory has ``LowerLarynx`` uniformly
    unspecified (all segments are ``0`` because Hindi has no
    implosives). It must drop out of ``active_features`` and out
    of the ``feature_groups`` payload, matching the desktop's
    behaviour the user reported as correct.
    """
    inv = _load_bundled(inventories_dir, "hindi")
    eng = FeatureEngine(inv)
    assert (
        "LowerLarynx" not in eng.active_features
    ), "LowerLarynx is all-0 in bundled Hindi; the filter must drop it"
    # Every retained feature has at least one + or - somewhere.
    for feat in eng.active_features:
        has_explicit = any(
            bundle.get(feat) in ("+", "-") for bundle in inv.segments.values()
        )
        assert has_explicit, (
            f"{feat} is in active_features but has no +/- value in any "
            "segment; filter is over-inclusive"
        )


def test_bundled_english_keeps_all_specified_features(
    inventories_dir: Path,
) -> None:
    """Regression: every English feature with at least one explicit
    value survives the filter."""
    inv = _load_bundled(inventories_dir, "english")
    eng = FeatureEngine(inv)
    for feat in inv.features:
        has_explicit = any(
            bundle.get(feat) in ("+", "-") for bundle in inv.segments.values()
        )
        if has_explicit:
            assert (
                feat in eng.active_features
            ), f"English {feat} has explicit values but was dropped"
