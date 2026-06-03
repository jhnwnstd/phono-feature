"""Qt-free view-model helpers shared by desktop and web frontends.

This module keeps pure presentation-state derivation in the desktop
source tree so the web build can relay it directly instead of
re-implementing the same logic inside ``web/api.py`` or ``main.js``.

Current responsibilities:

* Inventory summary shaping for the web app's initial paint.
* SEG-mode analysis summaries (shared/contrastive features,
  suggested extensions, pre-rendered analysis HTML).
* FEAT-mode analysis summaries (matching segments + HTML).
* Explicit segment-button and feature-row visual state payloads.

The desktop still owns actual widget mutation. This module only turns
engine state into plain dict/list payloads that either frontend can
consume.

Bridge contracts owned here:

* :py:data:`AnalysisTabsPayload` -- the four-tab analysis payload
  the desktop's ``AnalysisPanel.set_sections`` and the web's
  ``setAnalysisTabs`` both consume. Required keys are pinned by
  :py:data:`ANALYSIS_TABS_REQUIRED_KEYS`; valid ``class_state``
  values are pinned by :py:data:`ANALYSIS_TABS_VALID_CLASS_STATES`.
  ``test_view_models`` enforces both for SEG and FEAT modes on
  every shipped inventory.
* :py:func:`validate_analysis_tabs_payload` -- the runtime guard
  the web bridge calls in ``web/api.py:analyze_segments`` and
  ``analyze_features``. A future shared-module refactor that
  drops or renames a key raises a structured ``ValueError`` at
  the bridge boundary instead of producing silent ``undefined``
  reads on the JS side.
* ``contrasts_enabled`` is mode-driven, not selection-driven: True
  for SEG mode, False for FEAT mode. Pinned by
  ``test_analysis_tabs_contrasts_enabled_is_mode_driven``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, TypedDict

from phonology_engine.feature_engine import FeatureCategory
from phonology_features.gui.shared.analysis import (
    compute_contrastive,
    render_class_tab_feat,
    render_class_tab_seg,
    render_contrasts_tab_feat,
    render_contrasts_tab_seg,
    render_feat_to_seg,
    render_features_tab_feat,
    render_features_tab_seg,
    render_multi_segment,
    render_selection_summary_seg,
    render_single_segment,
)
from phonology_features.gui.shared.constants import (
    FEATURE_GROUPS,
    MINUS_SIGN,
)
from phonology_features.gui.shared.layout import distribute_feature_groups
from phonology_features.gui.shared.vowel_layout import (
    build_vowel_chart_geometry,
    detect_vowel_profile,
)

if TYPE_CHECKING:
    from phonology_engine.feature_engine import FeatureEngine


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
) -> dict[str, Any]:
    """SEG-mode analysis payload shared by desktop and web.

    Keys:

    * ``analysis_html``: pre-rendered HTML for the analysis pane.
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
        return {
            "analysis_html": "",
            "analysis_tabs": _seg_tabs(engine, [], {}, {}, []),
            "selected": [],
            "suggested": [],
            "common": {},
            "contrastive": [],
            "segment_states": default_seg_states,
            "feature_rows": default_feat_rows,
        }
    if len(segs) == 1:
        feats = engine.get_segment_features(segs[0])
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
        common = {feat: v if v != "0" else "" for feat, v in feats.items()}
        return {
            "analysis_html": render_single_segment(
                engine, segs[0], dict(feats)
            ),
            "analysis_tabs": _seg_tabs(engine, segs, common, {}, []),
            "selected": list(segs),
            "suggested": [],
            "common": common,
            "contrastive": [],
            "segment_states": seg_states,
            "feature_rows": row_states,
        }
    common = dict(engine.common_features(segs))
    contrastive = compute_contrastive(engine, segs)
    suggested = list(engine.suggest_natural_class_extension(segs))
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
        "analysis_html": render_multi_segment(
            engine,
            segs,
            common,
            contrastive,
            suggested,
        ),
        "analysis_tabs": _seg_tabs(
            engine, segs, common, contrastive, suggested
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
) -> dict[str, Any]:
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
            "analysis_html": "",
            "analysis_tabs": _feat_tabs({}, []),
            "matching": [],
            "segment_states": segment_states,
        }
    matching = engine.find_segments(spec)
    matching_set = set(matching)
    for seg in engine.segments:
        segment_states[seg] = "matched" if seg in matching_set else "unmatched"
    return {
        "analysis_html": render_feat_to_seg(spec, matching),
        "analysis_tabs": _feat_tabs(spec, matching),
        "matching": matching,
        "segment_states": segment_states,
    }


# ---------------------------------------------------------------------------
# ANALYSIS-PANE PAYLOAD CONTRACT (Stage 3)
#
# The four-tab analysis payload is the single thing the web bridge
# carries across the Pyodide boundary AND the desktop ``AnalysisPanel``
# consumes via ``set_sections``. The shape was previously a free
# ``dict[str, Any]`` with the keys documented in comments only;
# Stage 3 promotes the comment to executable types so a future
# refactor that drops or renames a key fails CI rather than the UI.
#
# ``AnalysisTabsPayload`` is a TypedDict (not a frozen dataclass)
# because the ``class`` key collides with the Python keyword --
# dataclasses can't have a ``class`` field, but a TypedDict can via
# the functional syntax. The web bridge also consumes the payload as
# a plain dict in JS; the typed alias just describes the shape we
# already had.
# ---------------------------------------------------------------------------


#: Class-tab background-colour cue. ``"natural"`` paints green when
#: the selection is a strict natural class; ``"not_natural"`` paints
#: red when it isn't; ``"neutral"`` is the empty / single-segment
#: default. The desktop and the web read the same three-value string.
ClassState = Literal["natural", "not_natural", "neutral"]


AnalysisTabsPayload = TypedDict(
    "AnalysisTabsPayload",
    {
        # HTML for the persistent header above the tabs. Empty string
        # means "hide the header"; the desktop's ``set_sections``
        # uses that as the visibility signal.
        "selection": str,
        # HTML for each of the three tab bodies. ``class`` is a
        # Python keyword so the TypedDict uses the functional syntax
        # to keep the key name JSON-bridge friendly.
        "class": str,
        "features": str,
        "contrasts": str,
        # Tab enable/disable is MODE-driven, not selection-driven:
        # SEG always lets the user click Contrasts (the body carries
        # the "select two or more segments" hint when needed); FEAT
        # never does. Asserted by ``_seg_tabs`` and ``_feat_tabs``.
        "contrasts_enabled": bool,
        # Class-tab background colour cue (see ``ClassState``).
        "class_state": ClassState,
    },
)


#: Frozen reference set of keys both UIs read. Used by parity tests
#: and by the bridge-side validator to fail loudly when an upstream
#: refactor drops or renames a key.
ANALYSIS_TABS_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "selection",
        "class",
        "features",
        "contrasts",
        "contrasts_enabled",
        "class_state",
    }
)


#: Valid values for ``AnalysisTabsPayload["class_state"]``. Frozen
#: tuple so importers can't append to it.
ANALYSIS_TABS_VALID_CLASS_STATES: tuple[ClassState, ...] = (
    "natural",
    "not_natural",
    "neutral",
)


def validate_analysis_tabs_payload(
    payload: object,
) -> AnalysisTabsPayload:
    """Cross-boundary structural validator for the analysis-pane
    payload.

    Raises ``ValueError`` with a precise message on shape drift; on
    success, returns the payload cast to
    :py:class:`AnalysisTabsPayload`. The web bridge calls this on the
    way out of ``analyze_segments`` / ``analyze_features`` so a
    desktop-only refactor that drops or renames a key surfaces as
    a structured Pyodide error rather than silent ``undefined``
    reads on the JS side.

    The desktop does NOT need to call this on every refresh -- mypy
    catches shape drift at type-check time. The validator exists to
    bridge the Python -> JS gap where the type checker can't see the
    consumer.
    """
    if not isinstance(payload, dict):
        raise ValueError(
            f"analysis_tabs payload must be a dict, got"
            f" {type(payload).__name__}"
        )
    missing = ANALYSIS_TABS_REQUIRED_KEYS - payload.keys()
    if missing:
        raise ValueError(
            f"analysis_tabs payload missing required keys:"
            f" {sorted(missing)}"
        )
    extra = payload.keys() - ANALYSIS_TABS_REQUIRED_KEYS
    if extra:
        # An extra key is not a hard failure today (it would just be
        # ignored by both UIs), but the schema is the contract -- log
        # via ValueError so an upstream refactor that adds a field
        # has to explicitly extend ANALYSIS_TABS_REQUIRED_KEYS too.
        raise ValueError(
            f"analysis_tabs payload carries unexpected keys:"
            f" {sorted(extra)} (extend ANALYSIS_TABS_REQUIRED_KEYS"
            f" if these are intentional)"
        )
    cs = payload["class_state"]
    if cs not in ANALYSIS_TABS_VALID_CLASS_STATES:
        raise ValueError(
            f"analysis_tabs class_state must be one of"
            f" {ANALYSIS_TABS_VALID_CLASS_STATES}, got {cs!r}"
        )
    if not isinstance(payload["contrasts_enabled"], bool):
        raise ValueError(
            f"analysis_tabs contrasts_enabled must be bool, got"
            f" {type(payload['contrasts_enabled']).__name__}"
        )
    for html_key in ("selection", "class", "features", "contrasts"):
        if not isinstance(payload[html_key], str):
            raise ValueError(
                f"analysis_tabs {html_key!r} must be str, got"
                f" {type(payload[html_key]).__name__}"
            )
    # Runtime-validated cast: payload now satisfies the TypedDict
    # shape; mypy cannot prove that from the structural checks above.
    return payload  # type: ignore[return-value]


def _seg_tabs(
    engine: FeatureEngine,
    segs: list[str],
    common: dict[str, str],
    contrastive: dict[str, dict[str, list[str]]],
    suggested: list[str],
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
    selection. Colouring the tab replaces the previous "Natural
    class: Yes/No" body text (same information, less visual noise).
    """
    # Class-tab background colour cue. Single-segment selections stay
    # neutral (white). Every singleton is trivially a "natural class"
    # of itself, so colouring it green would be true but uninformative
    # and just adds visual noise on every click. The cue lives on the
    # multi-segment verdict where the answer is genuinely useful.
    class_state: ClassState
    if len(segs) >= 2:
        is_nc, _ = engine.is_natural_class(segs)
        class_state = "natural" if is_nc else "not_natural"
    else:
        class_state = "neutral"
    payload: AnalysisTabsPayload = {
        "selection": render_selection_summary_seg(segs),
        "class": render_class_tab_seg(engine, segs, suggested),
        "features": render_features_tab_seg(engine, segs, common),
        "contrasts": render_contrasts_tab_seg(engine, segs, contrastive),
        # Tab enable/disable is mode-driven, not selection-driven. SEG
        # mode always lets the user click Contrasts; the tab body
        # carries the "select two or more segments" hint when the
        # selection isn't large enough yet.
        "contrasts_enabled": True,
        "class_state": class_state,
    }
    return payload


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
    payload: AnalysisTabsPayload = {
        "selection": "",
        "class": render_class_tab_feat(spec, matching),
        "features": render_features_tab_feat(spec),
        "contrasts": render_contrasts_tab_feat(),
        "contrasts_enabled": False,
        "class_state": "neutral",
    }
    return payload


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
    if contrastive:
        badge = "±"
    elif value:
        # Engine values are ASCII ("+", "-", "0"); the badge that
        # surfaces in the UI must use U+2212 MINUS SIGN so the glyph
        # matches the polarity buttons (also U+2212) and the chips in
        # the analysis pane. Doing the translation here means both
        # desktop (FeatureRow.set_display) and web (main.js
        # _setRasterizedBadge) get the right glyph without each
        # implementing its own ASCII -> U+2212 fix.
        badge = MINUS_SIGN if value == "-" else value
    else:
        badge = "·"
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

    Delegates the placement, collision-grouping, tooltip formatting,
    and physical-coordinate decisions to
    :py:func:`build_vowel_chart_geometry`; this function only
    flattens the dataclass tree into a JSON-shaped dict for the
    bridge. Both the Qt widget and the web renderer consume the
    same fields.

    ``rows`` lists only POPULATED height tiers (empty rows omitted).
    ``cells`` carries per-cell logical + physical coordinates plus
    fully-baked tooltip strings on every entry; the web renderer
    adds 1 to the ``grid_*`` fields when assigning CSS grid lines
    (which are 1-indexed) and the Qt renderer uses them directly.
    """
    seg_feats = {seg: dict(engine.segments[seg]) for seg in vowel_segs}
    profile = detect_vowel_profile(vowel_segs, seg_feats)
    geometry = build_vowel_chart_geometry(
        list(vowel_segs),
        profile,
        seg_feats,
    )
    return {
        "cols": list(geometry.cols),
        "rows": [
            {
                "logical_row": row.logical_row,
                "label": row.label,
                "grid_row": row.grid_row,
            }
            for row in geometry.rows
        ],
        "cells": [
            {
                "row": cell.row,
                "col": cell.col,
                "grid_row": cell.grid_row,
                "grid_col": cell.grid_col,
                "segs": [
                    {
                        "seg": entry.seg,
                        "confidence": entry.confidence,
                        "reason": entry.reason,
                        "tooltip": entry.tooltip,
                    }
                    for entry in cell.entries
                ],
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
