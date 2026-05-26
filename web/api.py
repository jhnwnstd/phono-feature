"""Python bridge between JS and the phonology engine.

Imported by main.js via ``pyodide.pyimport("api")`` after the
zipped engine + renderer bundle has been mounted on sys.path.
JS calls the module-level functions; their return values are
Pyodide-converted into plain JS dicts/lists/strings.

The HTML renderers live in ``phonology_features.gui.analysis``
(the desktop's source tree). The web build copies those files
into the bundle at the same package path so imports resolve
identically here and on the desktop, keeping one source of
truth for analysis output.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from phonology_engine.feature_engine import FeatureEngine
from phonology_engine.inventory import Inventory, ValidationError
from phonology_features.gui.constants import FEATURE_GROUPS
from phonology_features.gui.inventory_setup import (
    DEFAULT_FEATURES,
    DEFAULT_SEGMENTS,
    FEATURE_PRESETS,
    suggest_filename,
    validate_setup,
)
from phonology_features.gui.layout import distribute_feature_groups
from phonology_features.gui.palette import set_theme
from phonology_features.gui.vowel_layout import COL_LABELS as VOWEL_COL_LABELS
from phonology_features.gui.vowel_layout import ROW_LABELS as VOWEL_ROW_LABELS
from phonology_features.gui.vowel_layout import (
    detect_vowel_profile,
    vowel_grid_pos,
)

_analysis_mod: Any = None


def _analysis() -> Any:
    """Lazy-load ``phonology_features.gui.analysis``.

    Importing it at module load adds ~20-30 ms to the bridge-init
    phase that ``pyimport("api")`` incurs. None of its functions
    are needed until the user makes a selection, so defer the cost
    into the first click where it's hidden under the click latency
    budget.
    """
    global _analysis_mod
    if _analysis_mod is None:
        from phonology_features.gui import analysis as _mod
        _analysis_mod = _mod
    return _analysis_mod


_engine: FeatureEngine | None = None
_inventory_name: str = ""


def _require_engine() -> FeatureEngine:
    if _engine is None:
        raise RuntimeError("no inventory loaded")
    return _engine


def load_inventory_json(
    json_text: str,
    source_label: str = "uploaded",
) -> dict[str, Any]:
    """Parse a JSON inventory, swap it in, and return the summary
    JS needs to render the segment grid and feature list.

    Raises ``ValidationError`` with the same shape as
    ``Inventory.load`` so JS can surface the issues list.
    """
    global _engine, _inventory_name
    raw = json.loads(json_text)
    inventory = Inventory.parse(raw, source=source_label)
    _engine = FeatureEngine(inventory)
    _inventory_name = inventory.name or source_label
    _invalidate_analysis_caches()
    return _summarize_engine(_engine)


def _invalidate_analysis_caches() -> None:
    """Clear the LRU caches for ``analyze_segments`` /
    ``analyze_features``.

    Required after any change that would invalidate a cached
    result: a new inventory (engine state changed) or a theme swap
    (the cached HTML embeds chip colors from the previous palette).
    """
    _analyze_segments_cached.cache_clear()
    _analyze_features_cached.cache_clear()


def _summarize_engine(engine: FeatureEngine) -> dict[str, Any]:
    """Shape the inventory summary JS needs for first paint."""
    grouped = engine.grouped_segments
    # Split the manner-class buckets: "vowels" renders as the IPA
    # trapezoid, everything else as the consonant flow-grid.
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


def _vowel_chart(
    engine: FeatureEngine,
    vowel_segs: list[str],
) -> dict[str, Any]:
    """Compute the IPA vowel trapezoid layout.

    Returns ``{rows, cols, cells}`` where ``cells`` is a list of
    ``{seg, row, col, confidence, reason}`` per vowel. JS uses
    this to mount each vowel button into the right CSS-grid cell.
    Placement runs through ``gui.vowel_layout.vowel_grid_pos`` so
    the chart matches the desktop's VowelChartWidget exactly.
    """
    seg_feats = {seg: dict(engine.segments[seg]) for seg in vowel_segs}
    profile = detect_vowel_profile(vowel_segs, seg_feats)
    cells: list[dict] = []
    for seg in vowel_segs:
        placement = vowel_grid_pos(seg_feats[seg], profile)
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


def _grouped_features(features: list[str]) -> list[dict[str, Any]]:
    """Bucket the inventory's features into named cards matching
    the desktop's feature-panel layout (Major Class, Laryngeal,
    Manner, Place, etc.). Features that don't fit any group land
    in an "Other" bucket at the end.

    Cards are pre-distributed into left/right columns by
    ``gui.layout.distribute_feature_groups`` so the web renderer
    just mounts each card into the column it advertises.
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
        sizes, group_order=group_order,
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
        engine.inventory.to_json_dict(), indent=2, ensure_ascii=False,
    )


def get_current_inventory_name() -> str:
    return _inventory_name or "inventory"


def get_download_filename() -> str:
    """Suggested download filename for the active inventory.

    Same slugifier the desktop's Save As dialog uses, so a "Save as"
    on the web produces a filename in the bundled-inventories
    convention (``my_language_features.json``) rather than the raw
    display name with spaces and punctuation.
    """
    return suggest_filename(_inventory_name or "")


def get_setup_defaults() -> dict[str, Any]:
    """Return the autofill seeds and named feature presets the
    web setup modal needs to populate its UI.

    Shared with the desktop builder via
    :py:mod:`phonology_features.gui.inventory_setup` so both
    frontends offer the same Tab-autofill strings and the same
    named presets in the dropdown.
    """
    return {
        "default_segments": DEFAULT_SEGMENTS,
        "default_features": DEFAULT_FEATURES,
        "presets": {name: list(feats) for name, feats in FEATURE_PRESETS.items()},
    }


def create_new_inventory(
    raw_name: str, segments_text: str, features_text: str
) -> dict[str, Any]:
    """Build a new all-zero inventory from delimited text inputs.

    Runs the shared :py:func:`validate_setup` so the rules and
    error wording match the desktop's New Inventory dialog. On
    success constructs an Inventory with every (segment, feature)
    cell at ``"0"`` and swaps the engine; the inventory summary
    (the same shape :py:func:`load_inventory_json` returns) is
    handed back so JS can mount the empty grid as the active view.

    Raises :py:class:`ValidationError` with the full tuple of
    issue messages when validation fails. JS surfaces the first
    via the standard ``e.message`` channel; the others can be
    requested separately via
    :py:func:`validation_issues_from_error`.
    """
    global _engine, _inventory_name
    result = validate_setup(raw_name, segments_text, features_text)
    if not result.ok:
        raise ValidationError(
            tuple(issue.message for issue in result.issues)
        )
    grid = {
        seg: dict.fromkeys(result.features, "0") for seg in result.segments
    }
    inventory = Inventory.from_grid(
        name=result.name,
        features=list(result.features),
        segments=grid,
    )
    _engine = FeatureEngine(inventory)
    _inventory_name = inventory.name
    _invalidate_analysis_caches()
    return _summarize_engine(_engine)


def rename_current_inventory(new_name: str) -> dict[str, Any]:
    """Replace the active inventory's display name.

    Round-trips through :py:meth:`Inventory.parse` so the new name is
    validated and canonicalized (NFC, strip, length cap) the same way
    the file loader would. The engine is reconstructed with the
    renamed inventory; analysis caches are invalidated because their
    cached HTML may embed the old name.

    Returns ``{"name": canonical_name}`` so the caller can update its
    own display without a follow-up query.

    Raises :py:class:`ValidationError` if the new name fails
    validation, matching the existing load path's contract.
    """
    global _engine, _inventory_name
    engine = _require_engine()
    data = engine.inventory.to_json_dict()
    metadata = data.setdefault("metadata", {})
    metadata["name"] = new_name
    inventory = Inventory.parse(data)
    _engine = FeatureEngine(inventory)
    _inventory_name = inventory.name
    _invalidate_analysis_caches()
    return {"name": inventory.name}


def set_active_theme(name: str) -> None:
    """Switch the renderer palette so subsequent HTML output uses
    the new chip colors. Invalidates the analyze_* caches because
    their cached HTML embeds colors from the previous palette.
    """
    set_theme(name)
    _invalidate_analysis_caches()


def project_segments_to_features(segs: list[str]) -> dict[str, str]:
    """Mode-switch projection (SEG -> FEAT): the feature query
    that represents the current segment selection. Empty list maps
    to empty dict.
    """
    engine = _require_engine()
    if not segs:
        return {}
    return engine.project_segments_to_features(list(segs))


def project_features_to_segments(spec: dict[str, str]) -> list[str]:
    """Mode-switch projection (FEAT -> SEG): the segments matching
    the current feature query. Empty dict maps to empty list.
    """
    engine = _require_engine()
    if not spec:
        return []
    return engine.find_segments(dict(spec))


def analyze_segments(segs: list[str]) -> dict[str, Any]:
    """SEG-mode analysis. Returns ``analysis_html`` + the inputs
    JS needs to derive each row/button's state inline (mirroring
    the desktop's _update_seg_to_feat).

    Cache hit on a repeated selection returns in ~5 us; a fresh
    selection takes ~30 ms for the feature math + HTML render.
    Cache is invalidated by ``load_inventory_json`` and
    ``set_active_theme``.
    """
    return _analyze_segments_cached(tuple(segs))


@lru_cache(maxsize=256)
def _analyze_segments_cached(segs_tuple: tuple[str, ...]) -> dict[str, Any]:
    """SEG analysis result. Keys returned to JS:

    * ``analysis_html``: pre-rendered HTML for the analysis pane.
    * ``selected``: input list, echoed back.
    * ``suggested``: natural-class extension suggestions (empty
      for single-seg selections or genuine natural classes).
    * ``common``: ``{feat: value}`` for features where every
      selected segment shares the same value. Values include
      ``"0"`` / ``""``; JS decides which to display as a +/- chip
      vs. neutral.
    * ``contrastive``: feature names that split cleanly across
      the selection.

    No precomputed ``feature_display`` dict: a dict-with-fallback
    pattern silently produced neutral-state ghosts whenever a feat
    was missing. JS now derives each row's state inline from
    ``common`` and ``contrastive``, matching the desktop pattern.
    """
    engine = _require_engine()
    segs = list(segs_tuple)
    if not segs:
        return {
            "analysis_html": "",
            "selected": [],
            "suggested": [],
            "common": {},
            "contrastive": [],
        }
    analysis = _analysis()
    if len(segs) == 1:
        feats = engine.get_segment_features(segs[0])
        # Map "0" to "" so JS sees a neutral slot for unspecified
        # features (desktop set_display("", shared=True) -> neutral).
        common = {feat: v if v != "0" else "" for feat, v in feats.items()}
        analysis_html = analysis.render_single_segment(
            engine, segs[0], dict(feats),
        )
        return {
            "analysis_html": analysis_html,
            "selected": list(segs),
            "suggested": [],
            "common": common,
            "contrastive": [],
        }
    common_raw = engine.common_features(segs)
    contrastive_raw = analysis.compute_contrastive(engine, segs)
    suggested = engine.suggest_natural_class_extension(segs)
    analysis_html = analysis.render_multi_segment(
        engine, segs, common_raw, contrastive_raw, suggested,
    )
    return {
        "analysis_html": analysis_html,
        "selected": list(segs),
        "suggested": list(suggested),
        "common": dict(common_raw),
        "contrastive": list(contrastive_raw),
    }


def analyze_features(spec: dict[str, str]) -> dict[str, Any]:
    """FEAT-mode analysis. Returns ``analysis_html`` + the
    matching segment list. JS derives matched/unmatched state per
    button inline (mirroring _update_feat_to_seg).
    """
    return _analyze_features_cached(tuple(spec.items()))


@lru_cache(maxsize=256)
def _analyze_features_cached(
    spec_items: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    engine = _require_engine()
    spec = dict(spec_items)
    if not spec:
        return {
            "analysis_html": "",
            "matching": [],
        }
    analysis = _analysis()
    matching = engine.find_segments(spec)
    analysis_html = analysis.render_feat_to_seg(spec, matching)
    return {
        "analysis_html": analysis_html,
        "matching": matching,
    }


def validation_issues_from_error(exc: Any) -> list[str]:
    """Extract the canonical human-readable issues list from a
    ``ValidationError`` raised by ``load_inventory_json``.
    """
    if isinstance(exc, ValidationError):
        return list(exc.issues)
    return [str(exc)]
