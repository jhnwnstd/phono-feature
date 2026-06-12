"""Qt-free view-model derivations: engine state -> presentation
payloads (dicts / lists) both UIs consume. The desktop still owns
widget mutation; the web bridge relays the same payloads through
Pyodide.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
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
    MatchMode,
    NaturalClassCompletion,
)

if TYPE_CHECKING:
    from phonology_shared.theory.feature_engine import FeatureEngine


class SegmentState(StrEnum):
    """Visual state a segment button can be in.

    Single source of truth for both clients. The desktop's
    :py:class:`phonology_features.gui.widgets.SegmentButton`
    re-exports this same enum so widget consumers and view-model
    producers share one closed set; a typo in ``"selcted"`` at any
    call site is now a mypy / AttributeError instead of silently
    routing to ``DEFAULT`` styling.

    Values are wire-stable: the web bridge reads the raw strings.
    """

    SELECTED = "selected"
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    SUGGESTED = "suggested"
    DEFAULT = "default"


class FeatureRowState(TypedDict):
    """Per-feature visual payload returned by
    :py:func:`_feature_row_state`.

    Pins the inner shape carried by ``SegmentSelectionSummary``'s
    ``feature_rows`` slot so a renamed key surfaces in mypy here
    rather than as a missing badge in the UI. ``category`` is the
    stringified :py:class:`FeatureCategory`; ``shared`` /
    ``contrastive`` are the derived presentation flags kept for
    consumers that do not yet read the category directly.
    """

    value: str
    shared: bool
    contrastive: bool
    category: str
    badge: str


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
        # The :py:class:`MatchMode` value that produced this
        # payload's class verdict (a wire-stable string ``"strict"``
        # / ``"wildcard"``). Carried on every payload so renderers
        # never confuse strict and wildcard results: the Class tab
        # uses it to badge wildcard verdicts and to pick the right
        # label for the minimal-bundle line.
        "matching_mode": str,
    },
)


class SegmentSelectionSummary(TypedDict):
    """SEG-mode payload returned by :py:func:`summarize_segment_selection`.

    Shared by desktop (``main_window._update_seg_to_feat``) and web
    (``api.analyze_segments`` then JS unpack). Pins the exact key
    set so a future drop / rename surfaces in mypy here instead of
    at a JS bridge boundary later.

    The ``matching_mode`` field carries the :py:class:`MatchMode`
    value used to produce the natural-class verdict and minimal
    bundles. Renderers consult it to label wildcard results
    distinctly.
    """

    analysis_tabs: AnalysisTabsPayload
    selected: list[str]
    suggested: list[str]
    common: dict[str, str]
    contrastive: list[str]
    segment_states: dict[str, SegmentState]
    feature_rows: dict[str, FeatureRowState]
    matching_mode: str


class FeatureQuerySummary(TypedDict):
    """FEAT-mode payload returned by :py:func:`summarize_feature_query`.

    Same single-source contract as :py:class:`SegmentSelectionSummary`.
    The ``segment_states`` map carries :py:class:`SegmentState`
    members so consumers compare against ``SegmentState.MATCHED``
    instead of bare strings.

    The ``matching_mode`` field tags the result with the
    :py:class:`MatchMode` used to compute ``matching``. Wildcard
    results carry a UI badge so they are never confused with
    strict matches.
    """

    analysis_tabs: AnalysisTabsPayload
    matching: list[str]
    segment_states: dict[str, SegmentState]
    matching_mode: str


def build_inventory_summary(
    engine: FeatureEngine,
    inventory_name: str,
    provenance: str | None = None,
    *,
    mode: MatchMode = MatchMode.STRICT,
) -> dict[str, Any]:
    """Shape the inventory summary both frontends need after a load.

    Returns the plain dict payload the web bridge exposes to JS. The
    structure is also useful to the desktop when we want a canonical,
    serializable snapshot of the current engine-backed layout state.

    ``provenance`` is an optional short label naming where the
    inventory came from (e.g. ``"PHOIBLE / Korean (Eurasian
    Phonologies)"``, ``"bundled / english_features"``,
    ``"PanPhon / IPA Help"``). Surfaced by both renderers so the
    user can tell the source after the picker dialog closes.

    ``mode`` selects between strict and wildcard semantics for the
    derived ``active_features`` list. Under wildcard, every
    inventory feature is queryable (a request relaxes against
    unspecified values), so the feature pane surfaces the full
    roster instead of the strict-only filtered list.
    """
    grouped = engine.grouped_segments
    consonant_groups: list[dict[str, Any]] = []
    vowel_segs: list[str] = []
    for manner, segs in grouped.items():
        if manner.lower() == "vowels":
            vowel_segs = list(segs)
        else:
            consonant_groups.append({"name": manner, "segments": list(segs)})
    # In STRICT mode this drops columns where every segment is ``0``
    # (a ``+f`` request would return ∅). In WILDCARD mode every
    # feature stays: a request relaxes against unspecified values
    # so the row IS interactable.
    active = list(engine.active_features_for_mode(mode))
    return {
        "name": inventory_name,
        "provenance": provenance,
        "segments": list(engine.segments),
        "features": list(engine.features),
        "active_features": active,
        "groups": consonant_groups,
        "feature_groups": _grouped_features(active),
        "vowel_chart": _vowel_chart_summary(engine, vowel_segs),
        "matching_mode": str(mode),
    }


def summarize_segment_selection(
    engine: FeatureEngine,
    segs: list[str],
    *,
    mode: MatchMode = MatchMode.STRICT,
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
    * ``matching_mode``: the :py:class:`MatchMode` value the engine
      ran under to compute ``suggested`` + the class verdict.

    The ``common``, ``contrastive``, and ``feature_categories``
    derivations are mode-INDEPENDENT (they describe the data
    distribution of the selection, not the matching policy);
    ``suggested`` and the class verdict are mode-DEPENDENT.
    """
    mode_str = str(mode)
    if not segs:
        # Only the empty-selection branch consumes the default
        # tables; allocating them on every non-empty call cost
        # ~30 ms / 1000 calls in the W1 profile for the feature
        # rows, and the segment-state dict is larger still (up to
        # ~120 keys vs ~24).
        default_seg_states = _default_segment_states(engine)
        default_feat_rows = _default_feature_rows(engine)
        empty_completion = engine.complete_to_minimal_natural_class(
            [], mode=mode
        )
        return {
            "analysis_tabs": _seg_tabs(
                engine, [], {}, {}, empty_completion, mode=mode
            ),
            "selected": [],
            "suggested": [],
            "common": {},
            "contrastive": [],
            "segment_states": default_seg_states,
            "feature_rows": default_feat_rows,
            "matching_mode": mode_str,
        }
    if len(segs) == 1:
        feats = engine.get_segment_features(segs[0])
        completion = engine.complete_to_minimal_natural_class(segs, mode=mode)
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
        seg_states[segs[0]] = SegmentState.SELECTED
        # Strict solver returns a single completion, so flatten
        # additions[0] for the seg-pane suggested highlight.
        suggested_segs = (
            completion.additions[0] if completion.additions else ()
        )
        for seg in suggested_segs:
            if seg_states.get(seg) is SegmentState.DEFAULT:
                seg_states[seg] = SegmentState.SUGGESTED
        common = {feat: v if v != "0" else "" for feat, v in feats.items()}
        return {
            "analysis_tabs": _seg_tabs(
                engine, segs, common, {}, completion, mode=mode
            ),
            "selected": list(segs),
            "suggested": list(suggested_segs),
            "common": common,
            "contrastive": [],
            "segment_states": seg_states,
            "feature_rows": row_states,
            "matching_mode": mode_str,
        }
    common = engine.common_features(segs)
    contrastive = compute_contrastive(engine, segs)
    completion = engine.complete_to_minimal_natural_class(segs, mode=mode)
    suggested = list(completion.additions[0] if completion.additions else ())
    # Seven-way classification per feature (single source of truth
    # for the semantic state, see ``FeatureCategory``). The view-
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
    # Built directly from the loop; a defaults table here would be
    # pure churn since every key is overwritten.
    seg_states = {}
    for seg in engine.segments:
        if seg in selected:
            seg_states[seg] = SegmentState.SELECTED
        elif seg in suggested_set:
            seg_states[seg] = SegmentState.SUGGESTED
        else:
            seg_states[seg] = SegmentState.DEFAULT
    return {
        "analysis_tabs": _seg_tabs(
            engine, segs, common, contrastive, completion, mode=mode
        ),
        "selected": list(segs),
        "suggested": suggested,
        "common": common,
        "contrastive": list(contrastive),
        "segment_states": seg_states,
        "feature_rows": row_states,
        "matching_mode": mode_str,
    }


def summarize_feature_query(
    engine: FeatureEngine,
    spec: dict[str, str],
    *,
    mode: MatchMode = MatchMode.STRICT,
) -> FeatureQuerySummary:
    """FEAT-mode analysis payload shared by desktop and web.

    **Invariant:** ``matching`` always equals
    ``engine.find_segments(spec, mode=mode)``. Under strict, the
    matching set is the strict natural class characterised by
    the query. Under wildcard, the matching set is the wildcard
    natural class (broader; includes segments whose value is
    unspecified for queried features).
    """
    mode_str = str(mode)
    segment_states = _default_segment_states(engine)
    if not spec:
        return {
            "analysis_tabs": _feat_tabs({}, [], mode=mode),
            "matching": [],
            "segment_states": segment_states,
            "matching_mode": mode_str,
        }
    matching = engine.find_segments(spec, mode=mode)
    matching_set = set(matching)
    for seg in engine.segments:
        segment_states[seg] = (
            SegmentState.MATCHED
            if seg in matching_set
            else SegmentState.UNMATCHED
        )
    return {
        "analysis_tabs": _feat_tabs(spec, matching, mode=mode),
        "matching": matching,
        "segment_states": segment_states,
        "matching_mode": mode_str,
    }


def _seg_tabs(
    engine: FeatureEngine,
    segs: list[str],
    common: dict[str, str],
    contrastive: dict[str, dict[str, list[str]]],
    completion: NaturalClassCompletion,
    *,
    mode: MatchMode = MatchMode.STRICT,
) -> AnalysisTabsPayload:
    """Build the per-tab HTML payload for the SEG-mode analysis pane.

    Stamps the active :py:class:`MatchMode` into the payload so
    the renderer can label wildcard verdicts distinctly without
    re-deriving the mode from elsewhere.
    """
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
        "class": render_class_tab_seg(segs, completion, mode=mode),
        "features": render_features_tab_seg(engine, segs, common),
        "contrasts": render_contrasts_tab_seg(engine, segs, contrastive),
        # Tab enable/disable is mode-driven, not selection-driven. SEG
        # mode always lets the user click Contrasts; the tab body
        # carries the "select two or more segments" hint when the
        # selection isn't large enough yet.
        "contrasts_enabled": True,
        "class_state": class_state,
        "matching_mode": str(mode),
    }


def _feat_tabs(
    spec: dict[str, str],
    matching: list[str],
    *,
    mode: MatchMode = MatchMode.STRICT,
) -> AnalysisTabsPayload:
    """Same shape as :py:func:`_seg_tabs` but for FEAT mode. The
    Contrasts tab is never meaningful for a feature query, so
    ``contrasts_enabled`` is always False (the UI greys it out).
    """
    return {
        "selection": "",
        "class": render_class_tab_feat(spec, matching, mode=mode),
        "features": render_features_tab_feat(spec),
        "contrasts": render_contrasts_tab_feat(),
        "contrasts_enabled": False,
        "class_state": ClassState.NEUTRAL,
        "matching_mode": str(mode),
    }


#: Glyph shown in a FeatureRow's badge when the row is neutral
#: (no value picked, not contrastive). Centralised so a future
#: change touches both UIs in one edit; desktop reset()/apply
#: paths read it instead of inlining "·".
NEUTRAL_BADGE: str = "·"


def feature_row_badge(*, value: str, contrastive: bool) -> str:
    """Return the badge glyph a FeatureRow should display given its
    semantic state. Standalone (no engine needed) so renderers can
    recompute the glyph during a theme refresh without re-running
    a summary. Mirrors the ``badge`` field in
    :py:func:`_feature_row_state`.
    """
    if contrastive:
        return "±"
    if value:
        return MINUS_SIGN if value == "-" else value
    return NEUTRAL_BADGE


def _build_feature_row_state(
    value: str,
    shared: bool,
    contrastive: bool,
    category: FeatureCategory,
) -> FeatureRowState:
    """Build a single :py:class:`FeatureRowState` payload. Used by
    the module-level precomputed table; callers should not invoke
    this directly: they go through :py:func:`_feature_row_state`
    which dispatches to the table."""
    return {
        "value": value,
        "shared": shared,
        "contrastive": contrastive,
        "category": str(category),
        "badge": feature_row_badge(value=value, contrastive=contrastive),
    }


# Pre-computed FeatureRowState table. The key space is fully
# bounded: ``value`` is in {"", "+", "-"}, ``shared`` /
# ``contrastive`` are booleans, ``category`` is one of the seven
# :py:class:`FeatureCategory` members. 3 * 2 * 2 * 7 = 84 possible
# payloads. Profiling (W1: 58,300 calls / top tracemalloc site at
# 3.7 KB retained) showed the constructor was rebuilding the same
# 5-key dict tens of thousands of times per selection-summary pass;
# this table collapses every call to a dict lookup. Read-only
# semantics pinned by ``test_feature_row_state_is_cached_singleton``.
_FEATURE_ROW_STATES: dict[
    tuple[str, bool, bool, FeatureCategory], FeatureRowState
] = {
    (value, shared, contrastive, category): _build_feature_row_state(
        value, shared, contrastive, category
    )
    for value in ("", "+", "-")
    for shared in (False, True)
    for contrastive in (False, True)
    for category in FeatureCategory
}

#: Default-state row payload: value="" / not shared / not contrastive /
#: ALL_ZERO category. Used by :py:func:`_default_feature_rows` so the
#: outer dict is fresh per call (callers mutate which key maps to
#: which state) but every value shares this single immutable payload.
_DEFAULT_FEATURE_ROW_STATE: FeatureRowState = _FEATURE_ROW_STATES[
    ("", False, False, FeatureCategory.ALL_ZERO)
]


def _feature_row_state(
    *,
    value: str = "",
    shared: bool = False,
    contrastive: bool = False,
    category: FeatureCategory = FeatureCategory.ALL_ZERO,
) -> FeatureRowState:
    """Per-row visual payload + the semantic category from the
    engine (see :py:class:`FeatureCategory`). The ``category`` is
    the authoritative semantic state; ``shared`` / ``contrastive``
    are derived presentation flags kept for backward compatibility
    with renderers that don't yet read the category.

    Returns one of 84 cached singletons (see
    :py:data:`_FEATURE_ROW_STATES`). Callers MUST NOT mutate the
    returned dict; the cache is shared across all selections.

    Renderers should prefer ``category`` over the older flags when
    they need to distinguish underspec-involved states from purely
    explicit ones (e.g. ``UNDERSPEC_CONFLICT`` vs
    ``EXPLICIT_CONFLICT``).
    """
    return _FEATURE_ROW_STATES[(value, shared, contrastive, category)]


def _default_segment_states(
    engine: FeatureEngine,
) -> dict[str, SegmentState]:
    return {seg: SegmentState.DEFAULT for seg in engine.segments}


def _default_feature_rows(
    engine: FeatureEngine,
) -> dict[str, FeatureRowState]:
    return {feat: _DEFAULT_FEATURE_ROW_STATE for feat in engine.features}


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
    # PHOIBLE-loaded inventories stamp diphthong secondary bundles
    # into ``Inventory.metadata`` so the chart renderer can draw
    # arrows between the two cells without a new bridge endpoint.
    secondary = engine.inventory.metadata.get("vowel_secondary")
    geometry = build_vowel_chart_geometry(
        list(vowel_segs),
        profile,
        seg_feats,
        vowel_secondary=secondary if isinstance(secondary, Mapping) else None,
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
                "chart_x": col.chart_x,
            }
            for col in geometry.cols
        ],
        "rows": [
            {
                "logical_row": row.logical_row,
                "label": row.label,
                "chart_y": row.chart_y,
                "tier": row.tier,
                "silhouette_left": row.silhouette_left,
                "silhouette_right": row.silhouette_right,
            }
            for row in geometry.rows
        ],
        # Height-tier bands. Renderers iterate and paint;
        # the midpoint math has already happened in the
        # geometry layer so both UIs share the same edge clamps.
        "cells": [
            {
                "row": cell.row,
                "col": cell.col,
                "chart_x": cell.chart_x,
                "chart_y": cell.chart_y,
                "pair_side": cell.pair_side,
                "segs": list(cell.entries),
                "display_kind": cell.display_kind.value,
                "contrast_features": list(cell.contrast_features),
                # Read by the web mode-toggle filter; pinned by
                # test_wire_payload_completeness.py.
                "is_diphthong": cell.is_diphthong,
                # 0.0 means use the canonical CSS --vowel-pair-shift;
                # nonzero means the geometry elevated the shift to
                # resolve a same-anchor wide-cell collision.
                "pair_shift_px": cell.pair_shift_px,
            }
            for cell in geometry.cells
        ],
        # Curved arrow endpoints (chart_x/chart_y). Row/col are
        # diagnostic; the renderer projects from the float coords.
        "diphthongs": [
            {
                "segment": d.segment,
                "primary_row": d.primary_row,
                "primary_col": d.primary_col,
                "secondary_row": d.secondary_row,
                "secondary_col": d.secondary_col,
                "primary_chart_x": d.primary_chart_x,
                "primary_chart_y": d.primary_chart_y,
                "secondary_chart_x": d.secondary_chart_x,
                "secondary_chart_y": d.secondary_chart_y,
            }
            for d in geometry.diphthongs
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
