"""Python bridge between JS and the phonology engine.

Loaded into Pyodide at startup. Maintains one ``engine`` global per
loaded inventory; JS calls the module-level functions, which return
plain-Python types that Pyodide proxies to JS as dicts/lists/strings.

The HTML renderers live in ``phonology_features.gui.analysis`` (in
the desktop's source tree). The build script copies those files into
the web bundle under the same package path, so the imports resolve
identically to the desktop. One source of truth; edits to the
desktop renderer automatically flow to the next web build.
"""

from __future__ import annotations

import json
from typing import Any

from phonology_engine.feature_engine import FeatureEngine
from phonology_engine.inventory import Inventory, ValidationError

# These come from the copies the build step laid down. Resolves to
# the same code the desktop loads from gui/analysis.py.
from phonology_features.gui.analysis import (
    compute_contrastive,
    render_feat_to_seg,
    render_multi_segment,
    render_single_segment,
)
from phonology_features.gui.constants import FEATURE_GROUPS
from phonology_features.gui.layout import distribute_feature_groups
from phonology_features.gui.palette import set_theme
from phonology_features.gui.vowel_layout import (
    COL_LABELS as VOWEL_COL_LABELS,
    ROW_LABELS as VOWEL_ROW_LABELS,
    detect_vowel_profile,
    vowel_grid_pos,
)

# Single engine instance per loaded inventory. JS never sees the
# engine directly; all access goes through the functions below.
_engine: FeatureEngine | None = None
_inventory_name: str = ""


def _require_engine() -> FeatureEngine:
    if _engine is None:
        raise RuntimeError("no inventory loaded")
    return _engine


def load_inventory_json(
    json_text: str, source_label: str = "uploaded"
) -> dict:
    """Parse a JSON inventory string, swap to it, return basic info
    for the UI to render the segment grid and feature list.

    Raises ``ValidationError`` with the same shape as ``Inventory.load``
    so JS can surface the issues list.
    """
    global _engine, _inventory_name
    raw = json.loads(json_text)
    inventory = Inventory.parse(raw, source=source_label)
    _engine = FeatureEngine(inventory)
    _inventory_name = inventory.name or source_label
    return _summarize_engine(_engine)


def _summarize_engine(engine: FeatureEngine) -> dict:
    """Shape of what JS needs to populate the panels on every fresh
    inventory load.
    """
    grouped = engine.grouped_segments
    # Split the manner-class buckets into two streams: the "Vowels"
    # group renders as an IPA trapezoid; everything else renders as
    # the consonant flow-grid the web already had.
    consonant_groups: list[dict] = []
    vowel_segs: list[str] = []
    for manner, segs in grouped.items():
        if manner.lower() == "vowels":
            vowel_segs = list(segs)
        else:
            consonant_groups.append({"name": manner, "segments": list(segs)})
    return {
        "name": _inventory_name,
        "segments": list(engine.segments),
        "features": list(engine.features),
        "groups": consonant_groups,
        "feature_groups": _grouped_features(list(engine.features)),
        "vowel_chart": _vowel_chart(engine, vowel_segs),
    }


def _vowel_chart(engine: FeatureEngine, vowel_segs: list[str]) -> dict:
    """Compute the IPA-style vowel trapezoid layout.

    Returns ``{rows, cols, cells}`` where ``cells`` is a list of
    ``{seg, row, col, confidence, reason}`` per vowel. JS uses this
    to mount each vowel button into the right cell of a CSS grid.

    Placement runs through ``gui.vowel_layout.vowel_grid_pos`` so
    the chart matches the desktop's VowelChartWidget exactly.
    """
    norm_feats = {seg: dict(engine.segments[seg]) for seg in vowel_segs}
    profile = detect_vowel_profile(vowel_segs, norm_feats)
    cells: list[dict] = []
    for seg in vowel_segs:
        placement = vowel_grid_pos(norm_feats[seg], profile)
        cells.append({
            "seg": seg,
            "row": placement.row,
            "col": placement.col,
            "confidence": placement.confidence.name.lower(),
            "reason": placement.reason,
        })
    return {
        "rows": list(VOWEL_ROW_LABELS),
        "cols": list(VOWEL_COL_LABELS),
        "cells": cells,
    }


def _grouped_features(features: list[str]) -> list[dict]:
    """Bucket the inventory's active features into FEATURE_GROUPS
    cards (Major Class, Laryngeal, Manner, Place, etc.), matching
    the desktop's feature-panel layout. Features that don't fit any
    group land in an "Other" bucket at the end.

    The cards are pre-distributed into left/right columns using the
    SAME algorithm the desktop uses
    (``gui.layout.distribute_feature_groups``). The web renderer
    just reads ``column`` to decide which DOM column to mount each
    card under; no duplicated layout logic on the JS side.
    """
    present = set(features)
    cards: list[dict] = []
    placed: set[str] = set()
    for group_name, group_feats in FEATURE_GROUPS:
        in_inv = [f for f in group_feats if f in present]
        if in_inv:
            cards.append({"name": group_name, "features": in_inv})
            placed.update(in_inv)
    leftovers = [f for f in features if f not in placed]
    if leftovers:
        cards.append({"name": "Other", "features": leftovers})
    sizes = {c["name"]: len(c["features"]) for c in cards}
    group_order = [c["name"] for c in cards]
    left_names, right_names = distribute_feature_groups(
        sizes, group_order=group_order
    )
    column_of = {name: 0 for name in left_names}
    column_of.update({name: 1 for name in right_names})
    for card in cards:
        card["column"] = column_of.get(card["name"], 0)
    return cards


def serialize_current_inventory() -> str:
    """Round-trip the active inventory to JSON for download."""
    engine = _require_engine()
    return json.dumps(
        engine.inventory.to_json_dict(), indent=2, ensure_ascii=False
    )


def get_current_inventory_name() -> str:
    return _inventory_name or "inventory"


def set_active_theme(name: str) -> None:
    """Switch the renderer palette so subsequent HTML output uses
    the right chip colors. JS handles the surrounding CSS variables;
    this exists for the chip backgrounds embedded in analysis HTML."""
    set_theme(name)


# ----------------------------------------------------------------------
# Selection-driven analysis. ``segs`` is a JS array; Pyodide proxies
# it to Python. Functions return dicts that JS can read directly.
# ----------------------------------------------------------------------
def analyze_segments(segs: list[str]) -> dict:
    """Seg-to-feat update. Returns the full state JS needs to paint
    the panels and analysis pane.
    """
    engine = _require_engine()
    if not segs:
        return {
            "analysis_html": "",
            "feature_display": {},
            "segment_states": {seg: "default" for seg in engine.segments},
        }
    selected_set = set(segs)
    if len(segs) == 1:
        feats = engine.get_segment_features(segs[0])
        feature_display = {
            feat: {"value": v if v != "0" else "", "shared": True}
            for feat, v in feats.items()
        }
        segment_states = {
            seg: "selected" if seg in selected_set else "default"
            for seg in engine.segments
        }
        analysis_html = render_single_segment(engine, segs[0], dict(feats))
        return {
            "analysis_html": analysis_html,
            "feature_display": feature_display,
            "segment_states": segment_states,
        }
    common = engine.common_features(list(segs))
    contrastive = compute_contrastive(engine, list(segs))
    feature_display = {}
    for feat in engine.features:
        if feat in common:
            feature_display[feat] = {"value": common[feat], "shared": True}
        elif feat in contrastive:
            feature_display[feat] = {"value": "", "contrastive": True}
        else:
            feature_display[feat] = {"value": "", "shared": False}
    is_nc, _ = engine.is_natural_class(list(segs))
    suggested: list[str] = []
    if not is_nc and common:
        extension = engine.find_segments(common, underspec_compatible=True)
        suggested = [s for s in extension if s not in selected_set]
    suggested_set = set(suggested)
    segment_states = {}
    for seg in engine.segments:
        if seg in selected_set:
            segment_states[seg] = "selected"
        elif seg in suggested_set:
            segment_states[seg] = "suggested"
        else:
            segment_states[seg] = "default"
    analysis_html = render_multi_segment(
        engine, list(segs), common, contrastive, suggested
    )
    return {
        "analysis_html": analysis_html,
        "feature_display": feature_display,
        "segment_states": segment_states,
    }


def analyze_features(spec: dict[str, str]) -> dict:
    """Feat-to-seg update. ``spec`` is ``{feature_name: '+' | '-'}``.
    Returns the matching segments and analysis HTML.
    """
    engine = _require_engine()
    if not spec:
        return {
            "analysis_html": "",
            "segment_states": {seg: "default" for seg in engine.segments},
            "matching": [],
        }
    matching = engine.find_segments(dict(spec))
    matching_set = set(matching)
    segment_states = {
        seg: "matched" if seg in matching_set else "unmatched"
        for seg in engine.segments
    }
    analysis_html = render_feat_to_seg(dict(spec), matching)
    return {
        "analysis_html": analysis_html,
        "segment_states": segment_states,
        "matching": matching,
    }


def validation_issues_from_error(exc: Any) -> list[str]:
    """Convenience for JS catching a ValidationError raised from
    ``load_inventory_json``. The exception's ``issues`` tuple is the
    canonical human-readable list."""
    if isinstance(exc, ValidationError):
        return list(exc.issues)
    return [str(exc)]
