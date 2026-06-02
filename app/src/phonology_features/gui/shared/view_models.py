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
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
    COL_LABELS as VOWEL_COL_LABELS,
)
from phonology_features.gui.shared.vowel_layout import (
    ROW_LABELS as VOWEL_ROW_LABELS,
)
from phonology_features.gui.shared.vowel_layout import (
    compute_placements,
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
    *,
    projected_segments: list[str] | None = None,
) -> dict[str, Any]:
    """FEAT-mode analysis payload shared by desktop and web.

    ``projected_segments`` is the round-trip override: when the FEAT
    query was auto-projected from a prior seg selection (see
    :py:class:`mode_logic.ModeTransition`'s
    ``feature_query_origin == "projected"``), pass the original seg
    list here. The analysis then displays those exact segments as
    the matches, preserving the user's selection across the SEG→FEAT
    switch instead of doing a strict ``find_segments`` re-query that
    would silently drop members with ``'0'`` cells on the projected
    features. The flag flips to ``"typed"`` -- and this argument
    drops to ``None`` -- the first time the user toggles a feature
    in FEAT mode.
    """
    segment_states = _default_segment_states(engine)
    if not spec:
        return {
            "analysis_html": "",
            "analysis_tabs": _feat_tabs({}, []),
            "matching": [],
            "segment_states": segment_states,
        }
    if projected_segments is not None:
        # Preserve the user's seg selection across the mode switch.
        # We still validate against the engine's segment set so a
        # stale projection from a different inventory doesn't paint
        # a state with names the engine doesn't recognise.
        matching = [s for s in projected_segments if s in engine.segments]
    else:
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


def _seg_tabs(
    engine: FeatureEngine,
    segs: list[str],
    common: dict[str, str],
    contrastive: dict[str, dict[str, list[str]]],
    suggested: list[str],
) -> dict[str, Any]:
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
    if len(segs) >= 2:
        is_nc, _ = engine.is_natural_class(segs)
        class_state = "natural" if is_nc else "not_natural"
    else:
        class_state = "neutral"
    return {
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


def _feat_tabs(
    spec: dict[str, str],
    matching: list[str],
) -> dict[str, Any]:
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
        "class_state": "neutral",
    }


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
    """Compute the grouped vowel-chart payload used by the web UI."""
    seg_feats = {seg: dict(engine.segments[seg]) for seg in vowel_segs}
    profile = detect_vowel_profile(vowel_segs, seg_feats)
    occupied, placements = compute_placements(
        list(vowel_segs), profile, seg_feats
    )
    cells: list[dict[str, Any]] = []
    for (row, col), segs_in_cell in occupied.items():
        cells.append(
            {
                "row": row,
                "col": col,
                "segs": [
                    {
                        "seg": seg,
                        "confidence": placements[seg].confidence.name.lower(),
                        "reason": placements[seg].reason,
                    }
                    for seg in segs_in_cell
                ],
            }
        )
    return {
        "rows": list(VOWEL_ROW_LABELS),
        "cols": list(VOWEL_COL_LABELS),
        "cells": cells,
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
