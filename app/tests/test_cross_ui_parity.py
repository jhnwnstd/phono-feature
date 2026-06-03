"""Cross-UI parity tests.

These tests pin the contract that the shared pure-Python modules
produce output BOTH frontends (desktop Qt and web Pyodide) consume
verbatim. Drift here is precisely the failure mode the audit
identified as "two implementations, two answers": a refactor that
quietly changes the shape, key set, or value range of a shared
payload would otherwise only surface as a UI bug.

The pins here are deliberately structural (shape, key sets,
deterministic ordering) rather than HTML-byte-equal. Snapshot
tests on rendered HTML are brittle across Python/Pyodide/font
versions; structure-level invariants survive cosmetic changes
without losing their drift-detection power.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from phonology_engine.feature_engine import FeatureEngine
from phonology_engine.inventory import Inventory
from phonology_features.gui.shared.layout import distribute_feature_groups
from phonology_features.gui.shared.view_models import (
    build_inventory_summary,
)

INVENTORIES_DIR = Path(__file__).resolve().parents[1] / "inventories"
WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


def _engine(name: str) -> FeatureEngine:
    path = INVENTORIES_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    return FeatureEngine(Inventory.parse(raw, source=str(path)))


# ---------------------------------------------------------------------------
# build_inventory_summary: the bridge payload both UIs read on load
# ---------------------------------------------------------------------------


_REQUIRED_INVENTORY_SUMMARY_KEYS = frozenset(
    {
        "name",
        "segments",
        "features",
        "groups",
        "feature_groups",
        "vowel_chart",
    }
)


@pytest.mark.parametrize(
    "fname",
    ["english_features.json", "hayes_features.json", "general_features.json"],
)
def test_inventory_summary_keys_complete(fname: str) -> None:
    """Every required top-level key is present for every bundled
    inventory. The web's ``_validateInfo`` in main.js consumes
    these keys; a missing one would fail validation and the bridge
    bootstrap would fall back to the synchronous path."""
    engine = _engine(fname)
    summary = build_inventory_summary(engine, fname)
    assert set(summary.keys()) == _REQUIRED_INVENTORY_SUMMARY_KEYS, (
        f"build_inventory_summary({fname}) keys={sorted(summary.keys())}"
        f" expected {sorted(_REQUIRED_INVENTORY_SUMMARY_KEYS)}"
    )


def test_inventory_summary_is_deterministic() -> None:
    """Calling ``build_inventory_summary`` twice on the same engine
    must produce equal output. A non-determinism here (e.g. a set
    iteration leaked into a list) would mean cache invalidation,
    bridge memoisation, or service-worker caching could silently
    desync the desktop and web views."""
    engine = _engine("hayes_features.json")
    a = build_inventory_summary(engine, "Hayes")
    b = build_inventory_summary(engine, "Hayes")
    assert a == b


def test_inventory_summary_vowel_chart_has_consumer_keys() -> None:
    """The web's ``_buildVowelChart`` reads ``cols``, ``rows``,
    ``cells`` from the vowel_chart payload; each cell exposes
    ``grid_row``, ``grid_col``, and ``segs`` with prebaked
    tooltips. Pin those keys so a future ``vowel_layout``
    refactor cannot quietly rename a field."""
    engine = _engine("general_features.json")
    summary = build_inventory_summary(engine, "General")
    chart = summary["vowel_chart"]
    assert set(chart.keys()) >= {"cols", "rows", "cells"}
    if chart["cells"]:
        cell = chart["cells"][0]
        assert {"row", "col", "grid_row", "grid_col", "segs"} <= set(cell)
        if cell["segs"]:
            entry = cell["segs"][0]
            assert {"seg", "confidence", "reason", "tooltip"} <= set(entry)


# ---------------------------------------------------------------------------
# distribute_feature_groups: the LPT pin that controls column layout
# ---------------------------------------------------------------------------


def test_distribute_feature_groups_deterministic() -> None:
    """Same input → same output. The LPT-greedy algorithm has a
    secondary order tied to insertion order; if a future refactor
    swapped that for a set, the column assignment could silently
    flip across runs."""
    sizes = {
        "Major Class": 4,
        "Place": 8,
        "Manner": 6,
        "Voicing": 1,
        "Tongue": 5,
        "Other": 3,
    }
    out_a = distribute_feature_groups(sizes)
    out_b = distribute_feature_groups(sizes)
    assert out_a == out_b


def test_distribute_feature_groups_respects_pins() -> None:
    """LEFT_PINS / RIGHT_PINS land in their columns regardless of
    the size-driven LPT order. This is the invariant that keeps
    Major Class / Place on the left and Manner on the right across
    every inventory."""
    sizes = {
        "Major Class": 1,  # smallest possible, but pinned LEFT
        "Manner": 1,  # smallest possible, but pinned RIGHT
        "Place": 8,
        "Other": 5,
    }
    left, right = distribute_feature_groups(sizes)
    assert "Major Class" in left
    assert "Place" in left
    assert "Manner" in right


def test_distribute_feature_groups_drops_empty_groups() -> None:
    """A group with size 0 is omitted; empty cards must not
    render. Web and desktop both rely on this."""
    sizes = {"Major Class": 4, "Empty": 0, "Manner": 2}
    left, right = distribute_feature_groups(sizes)
    assert "Empty" not in left
    assert "Empty" not in right


# ---------------------------------------------------------------------------
# bootstrap.json: the pre-bridge payload the web boots from
# ---------------------------------------------------------------------------


def test_bootstrap_payload_shape() -> None:
    """``web/scripts/build.py`` bakes a ``bootstrap.json`` that the
    web app consumes BEFORE Pyodide is online so the segment + feature
    panels paint on first load. The schema is exactly the
    ``build_inventory_summary`` output (a flat dict, not nested), so
    a future refactor that drops or renames a top-level key would
    quietly break the pre-bridge UI.

    The bake hashes the filename for cache-busting (``bootstrap.<sha>.
    json``); resolve via ``asset-manifest.json`` so the test follows
    the canonical name. Skipped if ``web/dist/`` has not been built
    yet."""
    manifest_path = WEB_DIST / "asset-manifest.json"
    if not manifest_path.exists():
        pytest.skip(
            "web/dist/asset-manifest.json not present;"
            " run `app/.venv/bin/python web/scripts/build.py`"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bootstrap_name = manifest.get("assets", {}).get("bootstrap.json")
    assert bootstrap_name, "asset-manifest.json missing bootstrap.json mapping"
    bootstrap = WEB_DIST / bootstrap_name
    assert bootstrap.exists(), (
        f"manifest points at {bootstrap_name!r} but the file is"
        " absent under web/dist/"
    )
    payload = json.loads(bootstrap.read_text(encoding="utf-8"))
    assert set(payload.keys()) == _REQUIRED_INVENTORY_SUMMARY_KEYS, (
        "bootstrap.json must match build_inventory_summary shape;"
        f" got {sorted(payload.keys())} expected"
        f" {sorted(_REQUIRED_INVENTORY_SUMMARY_KEYS)}"
    )
