"""Qt-free view-model derivations. Engine state becomes presentation
payloads (dicts and lists) both UIs consume. The desktop still owns
widget mutation. The web bridge relays the same payloads through
Pyodide.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import TYPE_CHECKING, Any, TypedDict

from phonology_shared.chart.consonants import (
    VOCOID_GROUP_NAME,
    VOWEL_GROUP_NAME,
)
from phonology_shared.chart.vowel_space_geometry import (
    build_vowel_chart_geometry,
)
from phonology_shared.chart.vowels import detect_vowel_profile
from phonology_shared.presentation.analysis import (
    compute_contrastive,
    render_class_tab_feat,
    render_class_tab_seg,
    render_contrasts_tab_feat,
    render_contrasts_tab_seg,
    render_features_tab_feat,
    render_features_tab_seg,
)
from phonology_shared.presentation.constants import (
    FEATURE_GROUPS,
    MINUS_SIGN,
)
from phonology_shared.presentation.feature_metadata import glossary_url_for
from phonology_shared.presentation.layout import distribute_feature_groups
from phonology_shared.presentation.palette import ClassState
from phonology_shared.presentation.source_link import classify_source
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
    producers share one closed set, so a typo in ``"selcted"`` at any
    call site is now a mypy / AttributeError instead of silently
    routing to ``DEFAULT`` styling.

    Values are wire-stable. The web bridge reads the raw strings.

    A ``segment_states`` map keyed by these members is always SPARSE. It
    lists only segments whose state differs from ``default_segment_state``
    and a segment absent from the map takes the default, which avoids an
    O(inventory) allocation on every selection. Consumers iterate their
    own buttons and read ``segment_states.get(seg, default_segment_state)``.
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
    stringified :py:class:`FeatureCategory`. ``shared`` and
    ``contrastive`` are the derived presentation flags kept for
    consumers that do not yet read the category directly.
    """

    value: str
    shared: bool
    contrastive: bool
    category: str
    badge: str


# AnalysisTabsPayload is the per-tab content plus per-tab control flags
# the desktop's ``AnalysisPanel.set_sections`` and the web's
# ``setAnalysisTabs`` consume. Used by ``_seg_tabs`` (SEG mode) and
# ``_feat_tabs`` (FEAT mode). Functional ``TypedDict`` form so the
# Python keyword ``class`` can be a key name (the analysis pane's
# Class tab).
AnalysisTabsPayload = TypedDict(
    "AnalysisTabsPayload",
    {
        "class": str,
        "features": str,
        "contrasts": str,
        "contrasts_enabled": bool,
        "class_state": ClassState,
        # Wire-stable MatchMode string ("strict" | "wildcard") that
        # produced this payload; renderers badge wildcard verdicts.
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
    distinctly. ``segment_states`` is sparse, per :py:class:`SegmentState`.

    ``contrastive`` is the NARROW list of feature names where the
    selection reaches BOTH polarities (i.e. ``FeatureCategory``
    ``EXPLICIT_CONFLICT`` or ``UNDERSPEC_CONFLICT``). It drives the
    ± badge on feature rows in the panel above the tabs. Features
    that only PARTIALLY contrast (``UNDERSPEC_PLUS`` / ``UNDERSPEC_MINUS``
    -- a ``+/0`` or ``-/0`` split) do NOT appear here; they surface
    only inside the Contrasts tab HTML, in a separately labeled
    "Underspecified contrasts:" block. The Contrasts tab body is
    therefore a SUPERSET of this list -- an intentional asymmetry so
    the badge stays strict while the tab tells the fuller story.
    """

    analysis_tabs: AnalysisTabsPayload
    selected: list[str]
    suggested: list[str]
    common: dict[str, str]
    contrastive: list[str]
    segment_states: dict[str, SegmentState]
    default_segment_state: SegmentState
    feature_rows: dict[str, FeatureRowState]
    matching_mode: str


class FeatureQuerySummary(TypedDict):
    """FEAT-mode payload returned by :py:func:`summarize_feature_query`.

    Same single-source contract as :py:class:`SegmentSelectionSummary`.
    The ``segment_states`` map carries :py:class:`SegmentState`
    members so consumers compare against ``SegmentState.MATCHED``
    instead of bare strings. It is sparse the same way, listing the
    matched segments while ``default_segment_state`` is ``UNMATCHED``
    (or ``DEFAULT`` for an empty query), so absent segments take that
    baseline without an entry per inventory segment.

    The ``matching_mode`` field tags the result with the
    :py:class:`MatchMode` used to compute ``matching``. Wildcard
    results carry a UI badge so they are never confused with
    strict matches.
    """

    analysis_tabs: AnalysisTabsPayload
    matching: list[str]
    segment_states: dict[str, SegmentState]
    default_segment_state: SegmentState
    matching_mode: str


def build_inventory_summary(
    engine: FeatureEngine,
    inventory_name: str,
    *,
    mode: MatchMode = MatchMode.STRICT,
) -> dict[str, Any]:
    """Shape the inventory summary both frontends need after a load.

    Returns the plain dict payload the web bridge exposes to JS. The
    structure is also useful to the desktop when we want a canonical,
    serializable snapshot of the current engine-backed layout state.

    ``mode`` selects between strict and wildcard semantics for the
    derived ``active_features`` list. Under wildcard, every
    inventory feature is queryable (a request relaxes against
    unspecified values), so the feature pane surfaces the full
    roster instead of the strict-only filtered list.
    """
    grouped = engine.grouped_segments
    consonant_groups: list[dict[str, Any]] = []
    vowel_segs: list[str] = []
    vocoid_segs: list[str] = []
    for manner, segs in grouped.items():
        if manner == VOWEL_GROUP_NAME:
            vowel_segs = list(segs)
        elif manner == VOCOID_GROUP_NAME:
            # Vowel-like catch-all rendered as a flat list under the
            # vowel chart, not in the consonant area.
            vocoid_segs = list(segs)
        else:
            # Includes the consonant-area catch-all (Contoids), which
            # renders as an ordinary manner-class flat list.
            consonant_groups.append({"name": manner, "segments": list(segs)})
    # In STRICT mode this drops columns where every segment is ``0``
    # (a ``+f`` request would return ∅). In WILDCARD mode every
    # feature stays, since a request relaxes against unspecified values
    # so the row IS interactable.
    active = list(engine.active_features_for_mode(mode))
    return {
        "name": inventory_name,
        "segments": list(engine.segments),
        "features": list(engine.features),
        "active_features": active,
        "groups": consonant_groups,
        "feature_groups": _grouped_features(active),
        # Map of feature-name to INLP glossary URL, for the features
        # that have a distinctive-feature entry. The UIs render those
        # names as glossary links. Names absent here stay plain text.
        "feature_glossary": {
            feat: url
            for feat in active
            if (url := glossary_url_for(feat)) is not None
        },
        "vowel_chart": _vowel_chart_summary(engine, vowel_segs),
        # Vowel-like segments that fit no class, rendered as a flat list
        # under the vowel chart. Usually empty.
        "vocoids": vocoid_segs,
        "matching_mode": str(mode),
        # Classified inventory source (URL / DOI / citation / none) so
        # both frontends render the [Source] affordance from one rule.
        # PHOIBLE and bundled inventories both populate ``metadata
        # .source``. An inventory without one yields kind "none".
        "source": classify_source(
            engine.inventory.metadata.get("source")
        ).as_dict(),
    }


def summarize_segment_selection(
    engine: FeatureEngine,
    segs: list[str],
    *,
    mode: MatchMode = MatchMode.STRICT,
    rows_per_column: int | None = None,
) -> SegmentSelectionSummary:
    """SEG-mode analysis payload shared by desktop and web.

    ``common``, ``contrastive``, and the feature categories describe the
    data distribution of the selection and are mode-independent.
    ``suggested`` and the class verdict are mode-dependent. Single-segment
    selections map ``"0"`` to ``""`` in ``common`` so callers can treat
    underspecified rows as visually neutral. ``segment_states`` is sparse
    and lists only the selected and suggested segments.

    Contrasts tab semantics are asymmetric to the wire ``contrastive``
    list: ``compute_contrastive`` returns TWO maps (``contrastive_map``
    for features whose selection reaches both polarities, ``underspec_map``
    for ``+/0`` and ``-/0`` splits). Only ``contrastive_map`` keys reach
    the wire's :py:data:`SegmentSelectionSummary.contrastive` list and
    therefore the ± feature-row badge; the underspec map surfaces only
    inside the Contrasts tab HTML. This keeps the badge strict about
    what "contrastive" means while letting the tab body show partial
    contrasts users would otherwise be blind to.
    """
    completion = engine.complete_to_minimal_natural_class(segs, mode=mode)
    suggested = list(completion.additions[0] if completion.additions else ())

    if not segs:
        common: dict[str, str] = {}
        contrastive_map: dict[str, dict[str, list[str]]] = {}
        underspec_map: dict[str, dict[str, list[str]]] = {}
        feature_rows: dict[str, FeatureRowState] = _default_feature_rows(
            engine
        )
    elif len(segs) == 1:
        feats = engine.get_segment_features(segs[0])
        categories = engine.feature_categories(segs)
        feature_rows = _default_feature_rows(engine)
        for feat in engine.features:
            cat = categories.get(feat, FeatureCategory.ALL_ZERO)
            value = feats.get(feat, "0")
            if cat is FeatureCategory.EXPLICIT_CONFLICT:
                # A single-segment "conflict" is a CONTOUR feature. The
                # segment's own value sequence reaches both polarities
                # (the engine caches are tier-true), so the row renders
                # the set (± badge), never one phase's collapsed value.
                # Queries and this readout both answer from the same
                # membership caches, so they cannot disagree.
                feature_rows[feat] = _feature_row_state(
                    contrastive=True, category=cat
                )
            elif value in ("+", "-"):
                feature_rows[feat] = _feature_row_state(
                    value=value, shared=True, category=cat
                )
        common = {feat: v if v != "0" else "" for feat, v in feats.items()}
        contrastive_map = {}
        underspec_map = {}
    else:
        common = engine.common_features(segs)
        contrastive_map, underspec_map = compute_contrastive(engine, segs)
        categories = engine.feature_categories(segs)
        feature_rows = {}
        for feat in engine.features:
            cat = categories.get(feat, FeatureCategory.ALL_ZERO)
            if feat in common:
                feature_rows[feat] = _feature_row_state(
                    value=common[feat], shared=True, category=cat
                )
            elif feat in contrastive_map:
                # Only the ``+/-`` (both polarities reached) map drives
                # the ± feature-row badge above the tabs; the
                # underspec-only map surfaces in the tinted "Underspecified
                # contrasts:" block inside the Contrasts tab but does not
                # promote its features to ± in the Feature panel.
                feature_rows[feat] = _feature_row_state(
                    contrastive=True, category=cat
                )
            else:
                feature_rows[feat] = _feature_row_state(category=cat)

    # Sparse. Selected segments win over suggested ones. Every other
    # segment takes the DEFAULT baseline via ``default_segment_state``.
    seg_states = {seg: SegmentState.SELECTED for seg in segs}
    for seg in suggested:
        seg_states.setdefault(seg, SegmentState.SUGGESTED)

    return {
        "analysis_tabs": _seg_tabs(
            engine,
            segs,
            common,
            contrastive_map,
            underspec_map,
            completion,
            mode=mode,
            rows_per_column=rows_per_column,
        ),
        "selected": list(segs),
        "suggested": suggested,
        "common": common,
        # Wire ``contrastive`` stays NARROW: only features whose
        # selection reaches both polarities. Underspec-only features
        # surface inside the Contrasts tab HTML but never gain the
        # ± feature-row badge, matching the design decision to keep
        # the panel above the tabs strict about what "contrastive"
        # means.
        "contrastive": list(contrastive_map),
        "segment_states": seg_states,
        "default_segment_state": SegmentState.DEFAULT,
        "feature_rows": feature_rows,
        "matching_mode": str(mode),
    }


def summarize_feature_query(
    engine: FeatureEngine,
    spec: dict[str, str],
    *,
    mode: MatchMode = MatchMode.STRICT,
) -> FeatureQuerySummary:
    """FEAT-mode analysis payload shared by desktop and web.

    ``matching`` always equals ``engine.find_segments(spec, mode=mode)``.
    Under strict it is the strict natural class characterised by the
    query. Under wildcard it is the wildcard natural class, which is
    broader and includes segments whose value is unspecified for the
    queried features. An empty query yields an empty match and a
    ``DEFAULT`` baseline. ``segment_states`` is sparse and lists the
    matched segments.
    """
    matching = engine.find_segments(spec, mode=mode) if spec else []
    return {
        "analysis_tabs": _feat_tabs(spec, matching, mode=mode),
        "matching": matching,
        "segment_states": {seg: SegmentState.MATCHED for seg in matching},
        "default_segment_state": (
            SegmentState.DEFAULT if not spec else SegmentState.UNMATCHED
        ),
        "matching_mode": str(mode),
    }


def _seg_tabs(
    engine: FeatureEngine,
    segs: list[str],
    common: dict[str, str],
    contrastive: dict[str, dict[str, list[str]]],
    underspec: dict[str, dict[str, list[str]]],
    completion: NaturalClassCompletion,
    *,
    mode: MatchMode = MatchMode.STRICT,
    rows_per_column: int | None = None,
) -> AnalysisTabsPayload:
    """Build the per-tab HTML payload for the SEG-mode analysis pane.

    ``contrastive`` and ``underspec`` are the two maps returned by
    :py:func:`compute_contrastive`. Both feed the Contrasts tab body
    (as separate labeled tables); only ``contrastive`` also flows out
    as the wire's narrow ``SegmentSelectionSummary.contrastive`` list.

    Stamps the active :py:class:`MatchMode` into the payload so the
    renderer can label wildcard verdicts distinctly without re-deriving
    the mode from elsewhere.
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
        "class": render_class_tab_seg(
            segs, completion, mode=mode, rows_per_column=rows_per_column
        ),
        "features": render_features_tab_seg(engine, segs, common),
        "contrasts": render_contrasts_tab_seg(
            engine, segs, contrastive, underspec
        ),
        # Tab enable/disable is mode-driven, not selection-driven. SEG
        # mode always lets the user click Contrasts. The tab body carries
        # the "select two or more segments" hint when the selection is
        # not large enough yet.
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
        "class": render_class_tab_feat(spec, matching, mode=mode),
        "features": render_features_tab_feat(spec),
        "contrasts": render_contrasts_tab_feat(),
        "contrasts_enabled": False,
        "class_state": ClassState.NEUTRAL,
        "matching_mode": str(mode),
    }


#: Glyph shown in a FeatureRow's badge when the row is neutral
#: (no value picked, not contrastive). Centralised so a future
#: change touches both UIs in one edit. Desktop reset()/apply
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
    the module-level precomputed table. Callers should not invoke
    this directly. They go through :py:func:`_feature_row_state`
    which dispatches to the table."""
    return {
        "value": value,
        "shared": shared,
        "contrastive": contrastive,
        "category": str(category),
        "badge": feature_row_badge(value=value, contrastive=contrastive),
    }


# Pre-computed FeatureRowState table. The key space is fully bounded.
# ``value`` is in {"", "+", "-"}, ``shared`` and ``contrastive`` are
# booleans, and ``category`` is one of the seven FeatureCategory
# members, so there are 3 * 2 * 2 * 7 = 84 possible payloads. Building
# them once collapses every _feature_row_state call to a dict lookup on
# the hot selection-summary path. The payloads are shared singletons, so
# callers must never mutate them.
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

#: Default-state row payload. value="" / not shared / not contrastive /
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
    """Per-row visual payload plus the semantic category from the
    engine (see :py:class:`FeatureCategory`). The ``category`` is
    the authoritative semantic state. ``shared`` and ``contrastive``
    are derived presentation flags kept for backward compatibility
    with renderers that do not yet read the category.

    Returns one of 84 cached singletons (see
    :py:data:`_FEATURE_ROW_STATES`). Callers MUST NOT mutate the
    returned dict, since the cache is shared across all selections.

    Renderers should prefer ``category`` over the older flags when
    they need to distinguish underspec-involved states from purely
    explicit ones (e.g. ``UNDERSPEC_CONFLICT`` vs
    ``EXPLICIT_CONFLICT``).
    """
    return _FEATURE_ROW_STATES[(value, shared, contrastive, category)]


def _default_feature_rows(
    engine: FeatureEngine,
) -> dict[str, FeatureRowState]:
    return {feat: _DEFAULT_FEATURE_ROW_STATE for feat in engine.features}


def _vowel_chart_summary(
    engine: FeatureEngine,
    vowel_segs: list[str],
) -> dict[str, Any]:
    """Serialize the render-ready vowel chart geometry for both UIs.

    Delegates the placement, collision-grouping, and physical
    coordinate decisions to :py:func:`build_vowel_chart_geometry`.
    This function only flattens the dataclass tree into a JSON-shaped
    dict for the bridge. Both the Qt widget and the web renderer
    consume the same fields.

    ``rows`` lists only POPULATED height tiers (empty rows omitted).
    ``cells`` carries per-cell logical and physical coordinates and
    the segments occupying the cell. The web renderer adds 1 to the
    ``grid_*`` fields when assigning CSS grid lines (which are
    1-indexed) and the Qt renderer uses them directly.
    """
    seg_feats = {seg: dict(engine.segments[seg]) for seg in vowel_segs}
    profile = detect_vowel_profile(vowel_segs, seg_feats)
    # PHOIBLE-loaded inventories stamp diphthong secondary bundles
    # into ``Inventory.metadata`` so the geometry can tell contour
    # vowels apart (listed as chips below the chart) without a new
    # bridge endpoint.
    secondary = engine.inventory.metadata.get("segment_secondary")
    geometry = build_vowel_chart_geometry(
        list(vowel_segs),
        profile,
        seg_feats,
        segment_secondary=(
            secondary if isinstance(secondary, Mapping) else None
        ),
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
            "bottom_width": sil.bottom_width,
            # Cascade source fields. Let the web recompute the four
            # corners at its LIVE data width (the
            # ``_silhouetteForDataWidth`` port in main.js) so the
            # outline hugs the outermost button flush at any width,
            # exactly as the desktop does. Without these the JS cascade
            # gates off ``cell_outer_extent_px == 0`` and silently
            # no-ops, leaving the web on the canonical-width corners
            # while desktop width-corrects (a small outline drift at
            # off-canonical widths).
            "front_anchor_at_top": sil.front_anchor_at_top,
            "front_anchor_at_bottom": sil.front_anchor_at_bottom,
            "back_anchor": sil.back_anchor,
            # Canonical apex position for a converged bottom
            # (front=0.15 / central=0.5 / back=0.85), or ``None`` under
            # classic trapezoid. Triggered by the LOWEST populated row
            # containing cells in exactly one backness slot (fires
            # today only when that slot is central). The JS mirror in
            # ``_silhouetteForDataWidth`` feeds it through the shared
            # ``_apexBackColumnAtBottom`` policy so Python and JS stay
            # bit-for-bit. Under the current ``_BACK_APEX_PULL = 0.0``
            # the back edge stays vertical for every inventory; the
            # field travels the wire so the two ports agree by
            # construction if the pull is ever raised, and so the
            # projection layer knows when to apply the lone-central
            # bottom warp.
            "back_anchor_at_bottom": sil.back_anchor_at_bottom,
            "cell_outer_extent_px": sil.cell_outer_extent_px,
            "front_cell_outer_extent_px": sil.front_cell_outer_extent_px,
            "back_right_pixel_offset": sil.back_right_pixel_offset,
        },
        "cols": [
            {
                "label": col.label,
                "chart_x": col.chart_x,
                "chart_x_bottom": col.chart_x_bottom,
            }
            for col in geometry.cols
        ],
        "rows": [
            {
                "logical_row": row.logical_row,
                "label": row.label,
                "chart_y": row.chart_y,
                # ``chart_y`` is the row's cell CENTRE for every row;
                # renderers uniformly centre-anchor. ``label_y`` is an
                # alias for ``chart_y`` (kept while the JS bridge is
                # in flight so a not-yet-rebuilt web bundle can still
                # look it up without a KeyError).
                "label_y": row.label_y,
                "silhouette_left": row.silhouette_left,
                # Row's share of the silhouette span. The renderer's
                # slot clamp derives per-button heights from it when
                # the rendered chart is shorter than the natural
                # request, so deep stacks shrink instead of invading
                # the neighbouring rows.
                "slot_height_norm": row.slot_height_norm,
            }
            for row in geometry.rows
        ],
        "cells": [
            {
                "row": cell.row,
                "col": cell.col,
                "chart_x": cell.chart_x,
                "chart_y": cell.chart_y,
                "pair_side": cell.pair_side,
                "segs": list(cell.entries),
                "display_kind": cell.display_kind.value,
                # Feature-aligned 2x2 grid coords per entry for a
                # CONTRAST_SET (parallel to ``segs``). [] otherwise.
                "grid": [list(pos) for pos in cell.grid],
                # ``(col_span, row_span)`` per entry, parallel to
                # ``grid``. Defaults to ``[1, 1]`` per entry; only
                # non-trivial for the base-and-variants layout, where
                # the base spans multiple rows in the left column.
                # [] when ``grid`` is empty.
                "spans": [list(pos) for pos in cell.spans],
                # Always the effective pair-side displacement. The
                # geometry elevates it to resolve same-anchor
                # wide-cell collisions.
                "pair_shift_px": cell.pair_shift_px,
                # Hard-boundary confinement offset (px) applied on
                # top of the pair shift so the button box stays
                # inside the outline.
                "nudge_px": cell.nudge_px,
            }
            for cell in geometry.cells
        ],
        # Diphthong segment names. Renderers list them as labelled
        # chips below the vowel space. They are not placed in cells.
        "diphthongs": list(geometry.diphthongs),
    }


def _grouped_features(features: list[str]) -> list[dict[str, Any]]:
    """Bucket active features into named cards plus left/right columns."""
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
    column_of = dict.fromkeys(left_names, 0)
    column_of.update(dict.fromkeys(right_names, 1))
    for card in cards:
        card["column"] = column_of.get(card["name"], 0)
    return cards
