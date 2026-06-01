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
    assert {entry["seg"] for entry in target["segs"]} == {"ə", "ɜ"}


def test_summarize_segment_selection_single_maps_zero_to_empty() -> None:
    engine = _engine("hayes_features.json")
    summary = summarize_segment_selection(engine, ["b"])
    assert summary["selected"] == ["b"]
    assert summary["suggested"] == []
    assert summary["contrastive"] == []
    assert summary["common"]["Voice"] == "+"
    assert summary["common"]["Back"] == ""
    assert "/b/" in summary["analysis_html"]
    assert summary["segment_states"]["b"] == "selected"
    assert summary["segment_states"]["d"] == "default"
    assert summary["feature_rows"]["Voice"]["value"] == "+"
    assert summary["feature_rows"]["Voice"]["shared"] is True
    assert summary["feature_rows"]["Back"]["value"] == ""
    assert summary["feature_rows"]["Back"]["shared"] is False


def test_summarize_segment_selection_multi_matches_engine() -> None:
    engine = _engine("hayes_features.json")
    segs = ["b", "d", "ɡ"]
    summary = summarize_segment_selection(engine, segs)
    assert summary["selected"] == segs
    assert summary["common"]["Voice"] == "+"
    assert "LABIAL" in summary["contrastive"]
    assert summary["suggested"] == engine.suggest_natural_class_extension(segs)
    assert summary["segment_states"]["b"] == "selected"
    assert summary["feature_rows"]["Voice"]["value"] == "+"
    assert summary["feature_rows"]["Voice"]["shared"] is True
    assert summary["feature_rows"]["LABIAL"]["contrastive"] is True
    assert summary["feature_rows"]["LABIAL"]["badge"] == "±"


def test_summarize_feature_query_matches_engine() -> None:
    engine = _engine("hayes_features.json")
    spec = {"Voice": "+"}
    summary = summarize_feature_query(engine, spec)
    assert summary["matching"] == engine.find_segments(spec)
    assert "+Voice" in summary["analysis_html"]
    assert summary["segment_states"]["b"] == "matched"
    assert summary["segment_states"]["p"] == "unmatched"


# ---------------------------------------------------------------------------
# analysis_tabs payload — shared contract between the desktop's
# ``AnalysisPanel.set_sections`` and the web's ``setAnalysisTabs``.
# Both consume the same keys; these tests pin the keys + invariants
# so a rename / drop on either side breaks the build here, not later
# at runtime in one UI but not the other.
# ---------------------------------------------------------------------------


def _assert_tabs_shape(tabs: dict[str, object]) -> None:
    for key in ("selection", "class", "features", "contrasts"):
        assert key in tabs, f"missing tab key: {key}"
        assert isinstance(tabs[key], str)
    assert "contrasts_enabled" in tabs
    assert isinstance(tabs["contrasts_enabled"], bool)


def test_analysis_tabs_seg_single_disables_contrasts() -> None:
    """Single-segment SEG selection: Contrasts tab has nothing to
    show, so the payload signals the UI to grey out / disable it.
    The Class tab stays NEUTRAL (white) — every singleton is
    trivially a natural class of itself, so colouring it green
    would just add visual noise on every click."""
    engine = _engine("hayes_features.json")
    tabs = summarize_segment_selection(engine, ["b"])["analysis_tabs"]
    _assert_tabs_shape(tabs)
    assert tabs["contrasts_enabled"] is False
    assert tabs["class_state"] == "neutral"
    # Class tab carries the natural-class verdict / specs.
    assert "+Voice" in tabs["features"]
    # Selection header has the chip for /b/.
    assert "/b/" in tabs["selection"]


def test_analysis_tabs_seg_multi_natural_class() -> None:
    """Multi-segment SEG selection that IS a natural class: tab
    state goes ``"natural"`` so the UI paints the Class tab green.
    Picking every voiced obstruent in Hayes — voiced stops + voiced
    fricatives — yields a real natural class definable by the
    feature ``+Voice``."""
    engine = _engine("hayes_features.json")
    voiced = engine.find_segments({"Voice": "+"})
    tabs = summarize_segment_selection(engine, voiced)["analysis_tabs"]
    _assert_tabs_shape(tabs)
    assert tabs["class_state"] == "natural"


def test_analysis_tabs_seg_multi_enables_contrasts() -> None:
    """Multi-segment SEG: contrasting features go in the Contrasts
    tab; the flag is on. /b/ /d/ /ɡ/ aren't a natural class on
    their own in Hayes (the other voiced stops would need to be in
    the selection too), so ``class_state == "not_natural"``."""
    engine = _engine("hayes_features.json")
    segs = ["b", "d", "ɡ"]
    tabs = summarize_segment_selection(engine, segs)["analysis_tabs"]
    _assert_tabs_shape(tabs)
    assert tabs["contrasts_enabled"] is True
    assert tabs["class_state"] == "not_natural"
    assert "Contrasting features" in tabs["contrasts"]


def test_analysis_tabs_feat_disables_contrasts() -> None:
    """FEAT mode: contrasts aren't meaningful for a feature query,
    so the flag stays off regardless of how many matches there are.
    """
    engine = _engine("hayes_features.json")
    tabs = summarize_feature_query(engine, {"Voice": "+"})["analysis_tabs"]
    _assert_tabs_shape(tabs)
    assert tabs["contrasts_enabled"] is False
    assert tabs["class_state"] == "neutral"
    # The Class tab is where matching segments land in FEAT mode.
    assert "Matching" in tabs["class"]


def test_analysis_tabs_empty_selection_safe_shape() -> None:
    """Empty SEG selection still produces a well-formed payload —
    the UI can call setSections without checking for nulls."""
    engine = _engine("hayes_features.json")
    tabs = summarize_segment_selection(engine, [])["analysis_tabs"]
    _assert_tabs_shape(tabs)
    assert tabs["contrasts_enabled"] is False
    assert tabs["class_state"] == "neutral"


def test_segment_state_payload_strings_match_enum() -> None:
    """The desktop coerces ``segment_states`` strings into the
    ``SegmentState`` StrEnum via ``SegmentState(state)``. If the enum
    drifts from the strings produced here, the desktop silently raises
    ``ValueError`` on every paint. Pin every payload string at the
    enum so a rename surfaces here, not in the UI.
    """
    from phonology_features.gui.widgets import SegmentState

    enum_values = {member.value for member in SegmentState}
    assert {"default", "selected", "suggested", "matched", "unmatched"} <= (
        enum_values
    )

    engine = _engine("hayes_features.json")
    seg_list = list(engine.segments)
    seen: set[str] = set()
    seen.update(
        summarize_segment_selection(engine, [])["segment_states"].values()
    )
    seen.update(
        summarize_segment_selection(engine, seg_list[:1])[
            "segment_states"
        ].values()
    )
    seen.update(
        summarize_segment_selection(engine, seg_list[:3])[
            "segment_states"
        ].values()
    )
    seen.update(summarize_feature_query(engine, {})["segment_states"].values())
    seen.update(
        summarize_feature_query(engine, {"Voice": "+"})[
            "segment_states"
        ].values()
    )
    assert seen <= enum_values, f"Unknown segment states: {seen - enum_values}"
