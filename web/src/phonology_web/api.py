"""Python bridge between JS and the phonology engine.

Imported by main.js via ``pyodide.pyimport("api")`` after the
zipped engine + renderer bundle has been mounted on sys.path.
JS calls the module-level functions; their return values are
Pyodide-converted into plain JS dicts/lists/strings.

The HTML renderers live in ``phonology_features.gui.shared.analysis``
(the desktop's source tree). The web build copies those files
into the bundle at the same package path so imports resolve
identically here and on the desktop, keeping one source of
truth for analysis output.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from functools import lru_cache
from typing import Any, TypeVar, cast

from phonology_engine import (
    MAX_FEATURES,
    MAX_SEGMENTS,
    VALID_VALUES,
    FeatureEngine,
    Inventory,
    ValidationError,
    parse_inventory_json_text,
)

# ``confirm_remove_*_prompt`` are re-exported on the api module so
# main.js can resolve them via ``callBridge("confirm_remove_*", ...)``
# without a thin wrapper; static linters can't see Pyodide attribute
# access, so this import block carries a noqa for them.
from phonology_features.gui.shared.grid_logic import (  # noqa: F401
    CYCLE_LADDER,
    MAX_UNDO_DEPTH,
    MOVE_KEYS,
    VALUE_KEYS,
    confirm_remove_feature_prompt,
    confirm_remove_segment_prompt,
    grid_to_inventory,
    validate_new_feature_label,
    validate_new_segment_label,
)
from phonology_features.gui.shared.inventory_setup import (
    DEFAULT_FEATURES,
    DEFAULT_SEGMENTS,
    FEATURE_PRESETS,
    suggest_filename,
    validate_setup,
)
from phonology_features.gui.shared.layout import (
    best_segment_n_cols,
    partition_groups_for_spillover,
)
from phonology_features.gui.shared.mode_logic import (
    mode_status_text,
    project_mode_transition,
)
from phonology_features.gui.shared.palette import set_palette_mode, set_theme
from phonology_features.gui.shared.view_models import (
    build_inventory_summary,
    summarize_feature_query,
    summarize_segment_selection,
)

_engine: FeatureEngine | None = None
_inventory_name: str = ""

# Allowed values for the two-axis palette state. Kept here (not in
# palette.py) so the bridge validators can reject bad strings at
# the boundary without importing internal palette state. Both axes
# round-trip as plain strings through QSettings + localStorage so
# the membership check is a literal set.


def _require_engine() -> FeatureEngine:
    if _engine is None:
        raise ValidationError(("no inventory loaded; load one first",))
    return _engine


F = TypeVar("F", bound=Callable[..., Any])


def _translate_engine_errors(fn: F) -> F:
    """Decorator: convert raw engine exceptions to ``ValidationError``.

    The pyodide bridge passes JS-supplied arguments straight through
    to engine methods that historically raised bare ``KeyError`` /
    ``ValueError`` / ``TypeError`` on bad input. Those exceptions
    don't carry the ``.issues`` shape the JS error path expects, and
    they leak into the JS event loop as unhandled runtime errors
    (no statusbar message, no recovery). The decorator wraps every
    public bridge function so the JS caller sees the same
    ``ValidationError`` shape regardless of which layer rejected
    the input. Functions that explicitly raise ``ValidationError``
    pass through unchanged.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except ValidationError:
            raise
        except (KeyError, ValueError, TypeError) as e:
            raise ValidationError((f"{fn.__name__}: {e}",)) from e

    return cast(F, wrapper)


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
    # Single decode entry-point shared with ``Inventory.load`` so the
    # desktop file path and the web upload path enforce the same
    # JSON-level contract: duplicate keys, non-finite literals, and
    # syntax errors all surface as ``ValidationError`` with the
    # source label prepended.
    raw = parse_inventory_json_text(json_text, source_label)
    inventory = Inventory.parse(raw, source=source_label)
    _engine = FeatureEngine(inventory)
    _inventory_name = inventory.name or source_label
    _invalidate_analysis_caches()
    return build_inventory_summary(_engine, _inventory_name)


def _invalidate_analysis_caches() -> None:
    """Clear the LRU caches for ``analyze_segments`` /
    ``analyze_features``.

    Required after any change that would invalidate a cached
    result: a new inventory (engine state changed) or a theme swap
    (the cached HTML embeds chip colors from the previous palette).
    """
    _analyze_segments_cached.cache_clear()
    _analyze_features_cached.cache_clear()


def serialize_current_inventory() -> str:
    """Round-trip the active inventory to JSON for download."""
    engine = _require_engine()
    return json.dumps(
        engine.inventory.to_json_dict(),
        indent=2,
        ensure_ascii=False,
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
    :py:mod:`phonology_features.gui.shared.inventory_setup` so both
    frontends offer the same Tab-autofill strings and the same
    named presets in the dropdown.
    """
    return {
        "default_segments": DEFAULT_SEGMENTS,
        "default_features": DEFAULT_FEATURES,
        "presets": {
            name: list(feats) for name, feats in FEATURE_PRESETS.items()
        },
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
        raise ValidationError(tuple(issue.message for issue in result.issues))
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
    return build_inventory_summary(_engine, _inventory_name)


def get_cycle_ladder() -> dict[str, str]:
    """Return the value-cycle ladder used by the editor click handler.

    Same constant the desktop builder's ``cycle_value`` reads.
    The web editor fetches this once at boot and consults it on
    every click; centralizing the source here keeps the desktop and
    web cycle order in lockstep and avoids per-click bridge cost.
    """
    return dict(CYCLE_LADDER)


def validate_segment_label(label: str, existing: list[str]) -> str:
    """Validate a new segment label and return its canonical form.

    Thin bridge wrapper over :py:func:`validate_new_segment_label`,
    passing :py:data:`MAX_SEGMENTS` so the web editor enforces the
    inventory cap at add-time rather than at save-time. Same
    validator the desktop builder uses, so error wording matches.
    """
    return validate_new_segment_label(
        label, existing, max_segments=MAX_SEGMENTS
    )


def validate_feature_label(label: str, existing: list[str]) -> str:
    """Validate a new feature label and return its canonical form.

    Bridge wrapper over :py:func:`validate_new_feature_label` with
    :py:data:`MAX_FEATURES` enforced at add-time.
    """
    return validate_new_feature_label(
        label, existing, max_features=MAX_FEATURES
    )


def get_value_keys() -> dict[str, str]:
    """Return the direct-entry keyboard shortcuts.

    Maps the typed character (the logical key, not a scancode) to
    the cell value the editor should apply. The web editor reads
    this once at boot; the desktop ``InventoryBuilder`` derives its
    Qt-flavoured dict from the same constant.
    """
    return dict(VALUE_KEYS)


def get_move_keys() -> dict[str, list[int]]:
    """Return the cell-cursor navigation shortcuts.

    Maps the typed character to a ``[dr, dc]`` step in the grid.
    Tuples become arrays through the Pyodide bridge so JS can
    destructure them directly. Same constant the desktop's
    ``InventoryBuilder._MOVE_KEYS`` derives from.
    """
    return {key: list(step) for key, step in MOVE_KEYS.items()}


def get_max_undo_depth() -> int:
    """Return the undo-stack depth cap shared by both editors.

    The desktop's ``_undo_stack`` enforces this cap via
    :py:data:`_MAX_UNDO_DEPTH`; the web editor caps its own JS-side
    stack identically so behavior matches across frontends.
    """
    return MAX_UNDO_DEPTH


def get_grid_state() -> dict[str, Any]:
    """Return the active inventory in editor-grid shape.

    The web builder editor reads this on open to populate its grid:
    ``cells[feature_index][segment_index]`` mirrors the desktop
    ``InventoryBuilder``'s ``rows = features, cols = segments``
    table layout. Missing values default to ``"0"`` (same semantics
    as :py:meth:`Inventory.feature_value`).

    Round-trips with :py:func:`commit_inventory_from_grid`: take
    the cells out, edit them, hand the result back.
    """
    engine = _require_engine()
    segments = list(engine.segments)
    features = list(engine.features)
    cells = [
        [engine.segments[seg].get(feat, "0") for seg in segments]
        for feat in features
    ]
    return {
        "name": _inventory_name or engine.inventory.name,
        "features": features,
        "segments": segments,
        "cells": cells,
    }


def commit_inventory_from_grid(
    name: str,
    features: list[str],
    segments: list[str],
    cells: list[list[str]],
) -> dict[str, Any]:
    """Build and adopt a new inventory from web-builder grid state.

    Calls the shared :py:func:`grid_to_inventory` (the same path the
    desktop builder's Save uses), which folds U+2212 minus to ASCII,
    omits ``"0"`` cells, and routes through
    :py:meth:`Inventory.from_grid` for validation. On success
    replaces the active engine and returns the standard summary
    that JS uses to repaint the viewer.

    ``cells`` is indexed as ``cells[feature_index][segment_index]``.

    Raises :py:class:`ValidationError` if the grid is not a valid
    inventory.
    """
    global _engine, _inventory_name
    inventory = grid_to_inventory(
        name=name,
        features=features,
        segments=segments,
        cells=cells,
    )
    _engine = FeatureEngine(inventory)
    _inventory_name = inventory.name
    _invalidate_analysis_caches()
    return build_inventory_summary(_engine, _inventory_name)


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


@_translate_engine_errors
def set_active_theme(name: str) -> None:
    """Switch the renderer palette so subsequent HTML output uses
    the new chip colors. Invalidates the analyze_* caches because
    their cached HTML embeds colors from the previous palette.

    Unknown values raise via shared :py:func:`set_theme` and the
    ``_translate_engine_errors`` wrapper turns the ``ValueError``
    into a ``ValidationError`` for JS.
    """
    set_theme(name)
    _invalidate_analysis_caches()


@_translate_engine_errors
def set_active_palette_mode(mode: str) -> None:
    """Switch between standard and colorblind palettes. Mirrors
    ``set_active_theme`` for the perpendicular axis; analysis HTML
    embeds chip colors so cached output must regenerate.
    """
    set_palette_mode(mode)
    _invalidate_analysis_caches()


@_translate_engine_errors
def project_segments_to_features(segs: list[str]) -> dict[str, str]:
    """Mode-switch projection (SEG -> FEAT): the feature query
    that represents the current segment selection. Empty list maps
    to empty dict.
    """
    engine = _require_engine()
    if not segs:
        return {}
    return engine.project_segments_to_features(list(segs))


@_translate_engine_errors
def project_features_to_segments(spec: dict[str, str]) -> list[str]:
    """Mode-switch projection (FEAT -> SEG): the segments matching
    the current feature query. Empty dict maps to empty list.
    """
    engine = _require_engine()
    if not spec:
        return []
    return engine.find_segments(dict(spec))


@_translate_engine_errors
def project_mode_switch(
    current_mode: str,
    target_mode: str,
    selected_segments: list[str],
    selected_features: dict[str, str],
) -> dict[str, Any]:
    """Full top-level mode-transition projection shared with desktop.

    Returns the remembered cross-mode state PLUS the state that should
    be active immediately after the switch in the target mode.

    Mode strings are validated through :py:class:`Mode` (a StrEnum
    that raises ``ValueError`` on a typo); the decorator translates
    that to ``ValidationError`` so JS gets a clean error path on a
    bad mode string instead of a raw stack trace in the console.
    """
    # ``project_mode_transition`` calls ``Mode(...)`` internally;
    # the decorator translates the ``ValueError`` for a bad string.
    transition = project_mode_transition(
        current_mode,
        target_mode,
        selected_segments=list(selected_segments),
        selected_features=dict(selected_features),
        engine=_require_engine(),
    )
    return {
        "saved_seg_state": transition.saved_seg_state,
        "saved_feat_state": transition.saved_feat_state,
        "selected_segments": transition.selected_segments,
        "selected_features": transition.selected_features,
    }


def get_mode_status_text(mode: str) -> str:
    """Per-mode helper text shared with the desktop status bar."""
    return mode_status_text(mode, has_engine=_engine is not None)


def partition_segment_spillover(
    heights: list[int],
    available: int,
    n_spillover_cols: int = 2,
) -> int:
    """JS bridge to the shared spillover partition. JS measures each
    consonant group's natural height + the pane's clientHeight, hands
    them here, and applies the returned main-flow count to the DOM.
    Same function the desktop calls during ``set_groups`` so a
    threshold change lands on both UIs at once.
    """
    return partition_groups_for_spillover(heights, available, n_spillover_cols)


def best_segment_n_cols_for_groups(
    group_sizes: list[int],
    max_cols: int,
) -> list[int]:
    """Vectorised JS bridge to ``best_segment_n_cols``. JS hands in
    each consonant group's segment count + the pane's max column
    count; gets back the best per-group column count to use for its
    ``grid-template-columns`` rule. Same algorithm desktop runs in
    :py:meth:`SegmentGridWidget._do_relayout`, so a group with 13
    segments lays out as 2+11 or 3+5+5 — never 12+1 — on either UI.
    """
    return [best_segment_n_cols(n, max_cols) for n in group_sizes]


@_translate_engine_errors
def analyze_segments(segs: list[str]) -> dict[str, Any]:
    """SEG-mode analysis. Returns ``analysis_html`` + the inputs
    JS needs to derive each row/button's state inline (mirroring
    the desktop's _update_seg_to_feat).

    Cache hit on a repeated selection returns in ~5 us; a fresh
    selection takes ~30 ms for the feature math + HTML render.
    Cache is invalidated by ``load_inventory_json`` and
    ``set_active_theme``.

    Validates that every entry of ``segs`` is a string present in
    the active inventory. A stale segment (selected before an
    inventory swap), a typo, or a non-string element gets rejected
    here so the engine never sees garbage. Without this guard a
    stale segment raises ``KeyError`` inside the engine and surfaces
    in JS as a raw runtime error.
    """
    engine = _require_engine()
    bad = [
        s for s in segs if not isinstance(s, str) or s not in engine.segments
    ]
    if bad:
        raise ValidationError(
            (f"unknown segment(s) in current inventory: {bad!r}",)
        )
    return _analyze_segments_cached(tuple(segs))


@lru_cache(maxsize=256)
def _analyze_segments_cached(segs_tuple: tuple[str, ...]) -> dict[str, Any]:
    """SEG analysis result; computed by the shared desktop helpers."""
    engine = _require_engine()
    return summarize_segment_selection(engine, list(segs_tuple))


@_translate_engine_errors
def analyze_features(spec: dict[str, str]) -> dict[str, Any]:
    """FEAT-mode analysis. Returns ``analysis_html`` + the
    matching segment list. JS derives matched/unmatched state per
    button inline (mirroring _update_feat_to_seg).

    Validates that every key in ``spec`` is a feature present in
    the active inventory and every value is one of ``"+" / "-"
    / "0"``. Same boundary-hardening as
    :py:func:`analyze_segments`.

    **Display invariant:** ``matching`` always equals
    ``engine.find_segments(spec)``, so the highlighted segments
    in the segment pane always form a strict natural class
    characterised by the active query.
    """
    engine = _require_engine()
    bad_keys = [
        k for k in spec if not isinstance(k, str) or k not in engine.features
    ]
    if bad_keys:
        raise ValidationError(
            (f"unknown feature(s) in current inventory: {bad_keys!r}",)
        )
    bad_values = {k: v for k, v in spec.items() if v not in VALID_VALUES}
    if bad_values:
        raise ValidationError(
            (
                f"invalid feature value(s) {bad_values!r}; expected one "
                f"of {sorted(VALID_VALUES)}",
            )
        )
    return _analyze_features_cached(tuple(spec.items()))


@lru_cache(maxsize=256)
def _analyze_features_cached(
    spec_items: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    engine = _require_engine()
    return summarize_feature_query(engine, dict(spec_items))


def validation_issues_from_error(exc: Any) -> list[str]:
    """Extract the canonical human-readable issues list from a
    ``ValidationError`` raised by ``load_inventory_json``.
    """
    if isinstance(exc, ValidationError):
        return list(exc.issues)
    return [str(exc)]
