"""Qt-free view-model derivations: engine state -> presentation
payloads (dicts / lists) both UIs consume. The desktop still owns
widget mutation; the web bridge relays the same payloads through
Pyodide.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

from phonology_shared.chart.vowels import (
    build_vowel_chart_geometry,
    detect_vowel_profile,
)
from phonology_shared.presentation.analysis import (
    compute_contrastive,
    render_class_tab_feat,
    render_class_tab_seg,
    render_contrasts_tab_feat,
    render_contrasts_tab_seg,
    render_features_tab_feat,
    render_features_tab_seg,
    render_selection_summary_seg,
)
from phonology_shared.presentation.constants import (
    FEATURE_GROUPS,
    MINUS_SIGN,
)
from phonology_shared.presentation.layout import distribute_feature_groups
from phonology_shared.presentation.palette import ClassState
from phonology_shared.theory.feature_engine import (
    FeatureCategory,
    NaturalClassCompletion,
)

if TYPE_CHECKING:
    from phonology_shared.theory.feature_engine import FeatureEngine


# AnalysisTabsPayload is the per-tab content + per-tab control flags
# the desktop's ``AnalysisPanel.set_sections`` and the web's
# ``setAnalysisTabs`` consume. Used by ``_seg_tabs`` (SEG mode) and
# ``_feat_tabs`` (FEAT mode). Functional ``TypedDict`` form so the
# Python keyword ``class`` can be a key name (the analysis pane's
# Class tab).
AnalysisTabsPayload = TypedDict(
    "AnalysisTabsPayload",
    {
        "selection": str,
        "class": str,
        "features": str,
        "contrasts": str,
        "contrasts_enabled": bool,
        "class_state": ClassState,
    },
)


class SegmentSelectionSummary(TypedDict):
    """SEG-mode payload returned by :py:func:`summarize_segment_selection`.

    Shared by desktop (``main_window._update_seg_to_feat``) and web
    (``api.analyze_segments`` then JS unpack). Pins the exact key
    set so a future drop / rename surfaces in mypy here instead of
    at a JS bridge boundary later.
    """

    analysis_tabs: AnalysisTabsPayload
    selected: list[str]
    suggested: list[str]
    common: dict[str, str]
    contrastive: list[str]
    segment_states: dict[str, str]
    feature_rows: dict[str, dict[str, Any]]


class FeatureQuerySummary(TypedDict):
    """FEAT-mode payload returned by :py:func:`summarize_feature_query`.

    Same single-source contract as :py:class:`SegmentSelectionSummary`.
    The ``segment_states`` map has values ``"matched"``,
    ``"unmatched"``, or ``"default"`` depending on engine response.
    """

    analysis_tabs: AnalysisTabsPayload
    matching: list[str]
    segment_states: dict[str, str]


def build_inventory_summary(
    engine: FeatureEngine,
    inventory_name: str,
) -> dict[str, Any]:
    """Shape the inventory summary both frontends need after a load.

    Returns the plain dict payload the web bridge exposes to JS. The
    structure is also useful to the desktop when we want a canonical,
    serializable snapshot of the current engine-backed layout state.
    """
    grouped = engine.grouped_segments
    consonant_groups: list[dict[str, Any]] = []
    vowel_segs: list[str] = []
    for manner, segs in grouped.items():
        if manner.lower() == "vowels":
            vowel_segs = list(segs)
        else:
            consonant_groups.append({"name": manner, "segments": list(segs)})
    return {
        "name": inventory_name,
        "segments": list(engine.segments),
        "features": list(engine.features),
        "groups": consonant_groups,
        "feature_groups": _grouped_features(list(engine.features)),
        "vowel_chart": _vowel_chart_summary(engine, vowel_segs),
    }


def summarize_segment_selection(
    engine: FeatureEngine,
    segs: list[str],
) -> SegmentSelectionSummary:
    """SEG-mode analysis payload shared by desktop and web.

    Keys:

    * ``analysis_tabs``: per-tab payload consumed by the desktop's
      ``AnalysisPanel.set_sections`` and the web's tab renderer.
    * ``selected``: echoed selection list.
    * ``suggested``: natural-class extension suggestions.
    * ``common``: ``{feat: value}`` display state for shared rows.
      Single-segment selections map ``"0"`` to ``""`` so callers can
      treat underspecified rows as visually neutral.
    * ``contrastive``: feature names that split the selection.
    * ``segment_states``: ``{seg: state}`` for every segment button.
    * ``feature_rows``: per-feature visual-state payloads.
    """
    default_seg_states = _default_segment_states(engine)
    default_feat_rows = _default_feature_rows(engine)
    if not segs:
        empty_completion = engine.complete_to_minimal_natural_class([])
        return {
            "analysis_tabs": _seg_tabs(engine, [], {}, {}, empty_completion),
            "selected": [],
            "suggested": [],
            "common": {},
            "contrastive": [],
            "segment_states": default_seg_states,
            "feature_rows": default_feat_rows,
        }
    if len(segs) == 1:
        feats = engine.get_segment_features(segs[0])
        completion = engine.complete_to_minimal_natural_class(list(segs))
        categories = engine.feature_categories(segs)
        row_states = _default_feature_rows(engine)
        for feat in engine.features:
            value = feats.get(feat, "0")
            cat = categories.get(feat, FeatureCategory.ALL_ZERO)
            if value in ("+", "-"):
                row_states[feat] = _feature_row_state(
                    value=value,
                    shared=True,
                    category=cat,
                )
        seg_states = _default_segment_states(engine)
        seg_states[segs[0]] = "selected"
        # ``additions`` is tuple-of-tuples (one tuple per distinct
        # minimum completion). The strict-bundle solver always
        # returns a single completion, so the seg-pane "suggested"
        # highlight flattens additions[0] onto the seg states.
        suggested_segs = (
            completion.additions[0] if completion.additions else ()
        )
        for seg in suggested_segs:
            if seg_states.get(seg) == "default":
                seg_states[seg] = "suggested"
        common = {feat: v if v != "0" else "" for feat, v in feats.items()}
        return {
            "analysis_tabs": _seg_tabs(engine, segs, common, {}, completion),
            "selected": list(segs),
            "suggested": list(suggested_segs),
            "common": common,
            "contrastive": [],
            "segment_states": seg_states,
            "feature_rows": row_states,
        }
    common = dict(engine.common_features(segs))
    contrastive = compute_contrastive(engine, segs)
    completion = engine.complete_to_minimal_natural_class(list(segs))
    suggested = list(completion.additions[0] if completion.additions else ())
    # Seven-way classification per feature (single source of truth
    # for the semantic state -- see ``FeatureCategory``). The view-
    # model surfaces the category on every row so renderers can
    # distinguish ``UNDERSPEC_CONFLICT`` from ``EXPLICIT_CONFLICT``
    # etc. without reinventing the classification.
    categories = engine.feature_categories(segs)
    row_states = {}
    for feat in engine.features:
        cat = categories.get(feat, FeatureCategory.ALL_ZERO)
        if feat in common:
            row_states[feat] = _feature_row_state(
                value=common[feat],
                shared=True,
                category=cat,
            )
        elif feat in contrastive:
            row_states[feat] = _feature_row_state(
                contrastive=True,
                category=cat,
            )
        else:
            row_states[feat] = _feature_row_state(category=cat)
    selected = set(segs)
    suggested_set = set(suggested)
    seg_states = {}
    for seg in engine.segments:
        if seg in selected:
            seg_states[seg] = "selected"
        elif seg in suggested_set:
            seg_states[seg] = "suggested"
        else:
            seg_states[seg] = "default"
    return {
        "analysis_tabs": _seg_tabs(
            engine, segs, common, contrastive, completion
        ),
        "selected": list(segs),
        "suggested": suggested,
        "common": common,
        "contrastive": list(contrastive),
        "segment_states": seg_states,
        "feature_rows": row_states,
    }


def summarize_feature_query(
    engine: FeatureEngine,
    spec: dict[str, str],
) -> FeatureQuerySummary:
    """FEAT-mode analysis payload shared by desktop and web.

    **Invariant:** ``matching`` always equals
    ``engine.find_segments(spec)``. By construction the segments
    that strictly match a feature query form a strict natural
    class characterised by the query itself; the FEAT-mode
    display contract requires every highlighted segment to belong
    to that natural class.
    """
    segment_states = _default_segment_states(engine)
    if not spec:
        return {
            "analysis_tabs": _feat_tabs({}, []),
            "matching": [],
            "segment_states": segment_states,
        }
    matching = engine.find_segments(spec)
    matching_set = set(matching)
    for seg in engine.segments:
        segment_states[seg] = "matched" if seg in matching_set else "unmatched"
    return {
        "analysis_tabs": _feat_tabs(spec, matching),
        "matching": matching,
        "segment_states": segment_states,
    }


def _seg_tabs(
    engine: FeatureEngine,
    segs: list[str],
    common: dict[str, str],
    contrastive: dict[str, dict[str, list[str]]],
    completion: NaturalClassCompletion,
) -> AnalysisTabsPayload:
    """Build the per-tab HTML payload for the SEG-mode analysis pane.

    Keys map to the three tabs the desktop and web render:
    ``"class"``, ``"features"``, ``"contrasts"``. Plus a
    ``"selection"`` line for the persistent header above the tabs,
    a ``"contrasts_enabled"`` flag that is mode-driven (True for
    SEG mode, False for FEAT) so tab availability tracks the active
    pane rather than specific selection contents, and a
    ``"class_state"`` that colours the Class tab itself: green
    ``"natural"`` when the selection forms a natural class, red
    ``"not_natural"`` when it doesn't, ``"neutral"`` for the empty
    selection.
    """
    # Class-tab background colour cue. Single-segment selections stay
    # neutral (white). Every singleton is trivially a "natural class"
    # of itself, so colouring it green would be true but uninformative
    # and just adds visual noise on every click. The cue lives on the
    # multi-segment verdict where the answer is genuinely useful.
    if len(segs) >= 2:
        class_state = (
            ClassState.NATURAL
            if completion.status == "already_natural_class"
            else ClassState.NOT_NATURAL
        )
    else:
        class_state = ClassState.NEUTRAL
    return {
        "selection": render_selection_summary_seg(segs),
        "class": render_class_tab_seg(segs, completion),
        "features": render_features_tab_seg(engine, segs, common),
        "contrasts": render_contrasts_tab_seg(engine, segs, contrastive),
        # Tab enable/disable is mode-driven, not selection-driven. SEG
        # mode always lets the user click Contrasts; the tab body
        # carries the "select two or more segments" hint when the
        # selection isn't large enough yet.
        "contrasts_enabled": True,
        "class_state": class_state,
    }


def _feat_tabs(
    spec: dict[str, str],
    matching: list[str],
) -> AnalysisTabsPayload:
    """Same shape as :py:func:`_seg_tabs` but for FEAT mode. The
    Contrasts tab is never meaningful for a feature query, so
    ``contrasts_enabled`` is always False (the UI greys it out).
    The selection header is intentionally empty: the query is
    already explicit in the Features tab below, so duplicating
    it above the tabs would just waste vertical room.
    """
    return {
        "selection": "",
        "class": render_class_tab_feat(spec, matching),
        "features": render_features_tab_feat(spec),
        "contrasts": render_contrasts_tab_feat(),
        "contrasts_enabled": False,
        "class_state": ClassState.NEUTRAL,
    }


#: Glyph shown in a FeatureRow's badge when the row is neutral
#: (no value picked, not contrastive). Centralised so a future
#: change touches both UIs in one edit; desktop reset()/apply
#: paths read it instead of inlining "·".
NEUTRAL_BADGE: str = "·"


def feature_row_badge(*, value: str, shared: bool, contrastive: bool) -> str:
    """Return the badge glyph a FeatureRow should display given its
    semantic state. Standalone (no engine needed) so renderers can
    recompute the glyph during a theme refresh without re-running
    a summary. Mirrors the ``badge`` field in
    :py:func:`_feature_row_state`.
    """
    del shared  # currently unused; kept for callsite symmetry
    if contrastive:
        return "±"
    if value:
        return MINUS_SIGN if value == "-" else value
    return NEUTRAL_BADGE


def _feature_row_state(
    *,
    value: str = "",
    shared: bool = False,
    contrastive: bool = False,
    category: FeatureCategory = FeatureCategory.ALL_ZERO,
) -> dict[str, Any]:
    """Per-row visual payload + the semantic category from the
    engine (see :py:class:`FeatureCategory`). The ``category`` is
    the authoritative semantic state; ``shared`` / ``contrastive``
    are derived presentation flags kept for backward compatibility
    with renderers that don't yet read the category.

    Renderers should prefer ``category`` over the older flags when
    they need to distinguish underspec-involved states from purely
    explicit ones (e.g. ``UNDERSPEC_CONFLICT`` vs
    ``EXPLICIT_CONFLICT``).
    """
    badge = feature_row_badge(
        value=value, shared=shared, contrastive=contrastive
    )
    return {
        "value": value,
        "shared": shared,
        "contrastive": contrastive,
        "category": str(category),
        "badge": badge,
    }


def _default_segment_states(engine: FeatureEngine) -> dict[str, str]:
    return {seg: "default" for seg in engine.segments}


def _default_feature_rows(
    engine: FeatureEngine,
) -> dict[str, dict[str, Any]]:
    return {feat: _feature_row_state() for feat in engine.features}


def _vowel_chart_summary(
    engine: FeatureEngine,
    vowel_segs: list[str],
) -> dict[str, Any]:
    """Serialize the render-ready vowel chart geometry for both UIs.

    Delegates the placement, collision-grouping, and physical-
    coordinate decisions to :py:func:`build_vowel_chart_geometry`;
    this function only flattens the dataclass tree into a
    JSON-shaped dict for the bridge. Both the Qt widget and the
    web renderer consume the same fields.

    ``rows`` lists only POPULATED height tiers (empty rows omitted).
    ``cells`` carries per-cell logical + physical coordinates and
    the segments occupying the cell; the web renderer adds 1 to
    the ``grid_*`` fields when assigning CSS grid lines (which are
    1-indexed) and the Qt renderer uses them directly.
    """
    seg_feats = {seg: dict(engine.segments[seg]) for seg in vowel_segs}
    profile = detect_vowel_profile(vowel_segs, seg_feats)
    geometry = build_vowel_chart_geometry(
        list(vowel_segs),
        profile,
        seg_feats,
    )
    sil = geometry.silhouette
    return {
        "title": geometry.title,
        "shape": geometry.shape.value,
        "natural_data_width_px": geometry.natural_data_width_px,
        "natural_data_height_px": geometry.natural_data_height_px,
        "silhouette": {
            "shape": sil.shape.value,
            "top_y": sil.top_y,
            "bottom_y": sil.bottom_y,
            "top_left": sil.top_left,
            "top_right": sil.top_right,
            "bottom_left": sil.bottom_left,
            "bottom_right": sil.bottom_right,
            "top_width": sil.top_width,
            "bottom_width": sil.bottom_width,
            "back_right_pixel_offset": sil.back_right_pixel_offset,
        },
        "cols": [
            {
                "label": col.label,
                "grid_col": col.grid_col,
                "grid_col_span": col.grid_col_span,
                "chart_x": col.chart_x,
            }
            for col in geometry.cols
        ],
        "rows": [
            {
                "logical_row": row.logical_row,
                "label": row.label,
                "grid_row": row.grid_row,
                "chart_y": row.chart_y,
            }
            for row in geometry.rows
        ],
        "cells": [
            {
                "row": cell.row,
                "col": cell.col,
                "grid_row": cell.grid_row,
                "grid_col": cell.grid_col,
                "chart_x": cell.chart_x,
                "chart_y": cell.chart_y,
                "pair_side": cell.pair_side,
                "segs": list(cell.entries),
                "is_long_pair": cell.is_long_pair,
                "display_kind": cell.display_kind.value,
                "contrast_features": list(cell.contrast_features),
            }
            for cell in geometry.cells
        ],
    }


def _grouped_features(features: list[str]) -> list[dict[str, Any]]:
    """Bucket active features into named cards + left/right columns."""
    present = set(features)
    cards: list[dict[str, Any]] = []
    placed: set[str] = set()
    for group_name, group_feats in FEATURE_GROUPS:
        in_inventory = [feat for feat in group_feats if feat in present]
        if in_inventory:
            cards.append({"name": group_name, "features": in_inventory})
            placed.update(in_inventory)
    leftovers = [feat for feat in features if feat not in placed]
    if leftovers:
        cards.append({"name": "Other", "features": leftovers})
    sizes = {card["name"]: len(card["features"]) for card in cards}
    group_order = [card["name"] for card in cards]
    left_names, right_names = distribute_feature_groups(
        sizes,
        group_order=group_order,
    )
    column_of = {name: 0 for name in left_names}
    column_of.update({name: 1 for name in right_names})
    for card in cards:
        card["column"] = column_of.get(card["name"], 0)
    return cards
