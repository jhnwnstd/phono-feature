"""Tests for :py:mod:`phonology_features.gui.view_models`.

The module is pure-Python and is relayed into the web bundle, so
these tests lock in the shared payload shapes without needing Qt or
Pyodide.
"""

from __future__ import annotations

import json
from pathlib import Path

from phonology_engine.feature_engine import FeatureEngine
from phonology_engine.inventory import Inventory
from phonology_features.gui.view_models import (
    build_inventory_summary,
    summarize_feature_query,
    summarize_segment_selection,
)

INVENTORIES_DIR = Path(__file__).resolve().parents[1] / "inventories"


def _engine(name: str) -> FeatureEngine:
    path = INVENTORIES_DIR / name
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    return FeatureEngine(Inventory.parse(raw, source=str(path)))


def test_build_inventory_summary_groups_colliding_vowels() -> None:
    engine = _engine("general_features.json")
    summary = build_inventory_summary(engine, "General")
    target = next(
        cell
        for cell in summary["vowel_chart"]["cells"]
        if cell["row"] == 3 and cell["col"] == 2
    )
    assert {entry["seg"] for entry in target["segs"]} == {"ə", "ɜ", "ɚ"}


def test_summarize_segment_selection_single_maps_zero_to_empty() -> None:
    engine = _engine("hayes_features.json")
    summary = summarize_segment_selection(engine, ["b"])
    assert summary["selected"] == ["b"]
    assert summary["suggested"] == []
    assert summary["contrastive"] == []
    assert summary["common"]["Voice"] == "+"
    assert summary["common"]["Back"] == ""
    assert "/b/" in summary["analysis_html"]


def test_summarize_segment_selection_multi_matches_engine() -> None:
    engine = _engine("hayes_features.json")
    segs = ["b", "d", "ɡ"]
    summary = summarize_segment_selection(engine, segs)
    assert summary["selected"] == segs
    assert summary["common"]["Voice"] == "+"
    assert "LABIAL" in summary["contrastive"]
    assert summary["suggested"] == engine.suggest_natural_class_extension(segs)


def test_summarize_feature_query_matches_engine() -> None:
    engine = _engine("hayes_features.json")
    spec = {"Voice": "+"}
    summary = summarize_feature_query(engine, spec)
    assert summary["matching"] == engine.find_segments(spec)
    assert "+Voice" in summary["analysis_html"]
