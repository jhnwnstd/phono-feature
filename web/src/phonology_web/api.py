"""Python bridge between JS and the phonology engine.

Imported by main.js via ``pyodide.pyimport("api")`` after the
zipped engine + renderer bundle has been mounted on sys.path.
JS calls the module-level functions; their return values are
Pyodide-converted into plain JS dicts/lists/strings.

The HTML renderers live in ``phonology_shared.presentation.analysis``
(the desktop's source tree). The web build copies those files
into the bundle at the same package path so imports resolve
identically here and on the desktop, keeping one source of
truth for analysis output.

Bridge contract (single source of truth for the JS side; see
``test_bridge_contract`` for the parity guard):

- Every function declared at module scope is callable from
  ``main.js`` via ``callBridge("function_name", ...args)``.
- Arguments are converted by Pyodide from JS values to Python:
  strings, numbers, booleans, lists, plain objects round-trip
  natively. ``None`` maps to ``null``.
- Return values must be JSON-serialisable plain types: ``str``,
  ``int``, ``float``, ``bool``, ``None``, ``list``, ``dict``.
  Dataclasses serialise via ``view_models.py``; enums serialise
  as their string values (``StrEnum`` already does this); sets
  are never returned (they become un-iterable PyProxies on the
  JS side). The smoke test asserts the contract end-to-end by
  round-tripping every payload through ``JSON.stringify``.
- Errors should be raised as ``ValidationError`` (caught here and
  turned into a structured JS-friendly object) or domain
  exceptions; bare ``Exception`` becomes a generic JS Error.
- No PyProxy objects leak across the bridge. If a helper needs
  to manipulate a Python-side object, it stays Python-side and
  returns a converted dict/list. The JS side never sees a
  ``__class__`` attribute on a bridge return value.
- Long-running calls (PHOIBLE load, large analysis) block the
  Pyodide main thread today. A future worker migration moves the
  entire bridge behind a postMessage boundary; the contract above
  is the boundary that migration follows, so any new bridge
  function added here MUST already obey it.

Methods (current surface; keep alphabetised when adding):
    analyze_features, analyze_segments, best_segment_n_cols_for_groups,
    confirm_remove_feature_prompt, confirm_remove_segment_prompt,
    get_cycle_ladder, get_download_filename, get_grid_state,
    get_max_undo_depth, get_mode_status_text, get_move_keys,
    get_setup_defaults, get_value_keys, load_inventory_json,
    partition_segment_spillover, phoible_is_available,
    phoible_is_ready, phoible_list_inventories, phoible_load_data,
    phoible_preview_inventory, rename_current_inventory,
    serialize_current_inventory, set_active_palette_mode,
    set_active_theme, validation_report_html.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from functools import lru_cache
from typing import Any, TypeVar, cast

from phonology_shared.data import (
    MAX_FEATURES,
    MAX_SEGMENTS,
    VALID_VALUES,
    Inventory,
    ValidationError,
    parse_inventory_json_text,
)

# ``confirm_remove_*_prompt`` are re-exported on the api module so
# main.js can resolve them via ``callBridge("confirm_remove_*", ...)``
# without a thin wrapper; static linters can't see Pyodide attribute
# access, so this import block carries a noqa for them.
from phonology_shared.editor.grid import (  # noqa: F401
    CYCLE_LADDER,
    MAX_UNDO_DEPTH,
    MOVE_KEYS,
    VALUE_KEYS,
    confirm_remove_feature_prompt,
    confirm_remove_segment_prompt,
    enforce_class_caps,
    grid_to_inventory,
    normalize_minus,
    validate_new_feature_label,
    validate_new_segment_label,
)
from phonology_shared.editor.inventory_providers import (
    InventoryDescriptor,
    InventoryProvider,
)
from phonology_shared.editor.lookup_provider import (
    LookupFeatureProvider,
    LookupTableNotAvailable,
)
from phonology_shared.editor.phoible_provider import (
    PHOIBLE_PREVIEW_SEGMENT_LIMIT,
    PhoibleProvider,
    PhoibleSnapshotNotAvailable,
    materialize_phoible_inventory,
    phoible_loaded_message,
)
from phonology_shared.editor.providers import (
    FeatureProvider,
    blank_bundle,
)
from phonology_shared.editor.setup import (
    DEFAULT_FEATURES,
    DEFAULT_SEGMENTS,
    FEATURE_PRESETS,
    infer_split,
    suggest_filename,
    validate_setup,
)
from phonology_shared.presentation.analysis import render_validation_report
from phonology_shared.presentation.layout import (
    best_segment_n_cols,
    partition_groups_for_spillover,
    plan_seg_layout,
)
from phonology_shared.presentation.mode_logic import (
    inventory_cap_status,
    mode_status_text,
    project_mode_transition,
)
from phonology_shared.presentation.palette import set_palette_mode, set_theme
from phonology_shared.presentation.view_models import (
    FeatureQuerySummary,
    SegmentSelectionSummary,
    build_inventory_summary,
    summarize_feature_query,
    summarize_segment_selection,
)
from phonology_shared.theory import FeatureEngine
from phonology_shared.theory.feature_engine import MatchMode

_engine: FeatureEngine | None = None
_inventory_name: str = ""
# Active matching mode for natural-class queries. Defaults to
# STRICT — the wildcard ("Allow underspecified") UI toggle is opt-
# in. JS persists the choice through ``localStorage`` and replays
# it via :py:func:`set_match_mode` after a reload.
_match_mode: MatchMode = MatchMode.STRICT

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
    # The parse layer caps the TOTAL segment count; the per-class
    # caps are feature-driven and live one layer up (data must not
    # import chart), so enforce them here, after the structural
    # parse, before the engine swaps in.
    enforce_class_caps(inventory.segments)
    _engine = FeatureEngine(inventory)
    _inventory_name = inventory.name or source_label
    _invalidate_analysis_caches()
    # ``source_label`` is the user-facing label the picker passed
    # (bundled inventory title / uploaded filename / PHOIBLE
    # composite). The chip shows the inventory NAME, not a
    # "source / name" composite: the source-type prefix
    # ("bundled / ") is noise the user does not need.
    provenance = source_label or "uploaded"
    return build_inventory_summary(
        _engine, _inventory_name, provenance, mode=_match_mode
    )


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


@lru_cache(maxsize=1)
def _provider_registry() -> dict[str, FeatureProvider]:
    """Return the available providers indexed by ``name``.

    The lookup provider depends on the build-baked snapshot under
    ``shared/.../editor/_panphon_table.generated.json``; a stale
    developer checkout where ``web/scripts/bake_panphon.py`` has
    never run will hit :py:class:`LookupTableNotAvailable` and the
    provider quietly drops out of the registry so the dialog
    falls back to static presets without crashing.

    Cached because the lookup provider eagerly decodes ~6.4k
    segments at construction; re-running that on every
    :py:func:`get_setup_defaults` call would dominate the
    dialog-open latency.
    """
    registry: dict[str, FeatureProvider] = {}
    try:
        provider = LookupFeatureProvider()
    except LookupTableNotAvailable:
        return registry
    registry[provider.name] = provider
    return registry


@lru_cache(maxsize=1)
def _inventory_provider_registry() -> dict[str, InventoryProvider]:
    """Return the available inventory providers indexed by ``name``.

    Sibling to :py:func:`_provider_registry`; today the only
    inventory provider is PHOIBLE. The provider boots in index-
    only mode on the web (data file is lazy-loaded), so the
    autocomplete + inventory listing are available before the
    user has fetched the data payload. ``generate`` raises until
    :py:func:`phoible_load_data` injects the data JSON.
    """
    registry: dict[str, InventoryProvider] = {}
    try:
        provider = PhoibleProvider()
    except PhoibleSnapshotNotAvailable:
        return registry
    registry[provider.name] = provider
    return registry


def get_setup_defaults() -> dict[str, Any]:
    """Return the autofill seeds, named feature presets, and any
    available bootstrap providers the web setup modal needs to
    populate its UI.

    Shared with the desktop builder via
    :py:mod:`phonology_shared.editor.setup` so both frontends offer
    the same Tab-autofill strings and the same named presets in the
    dropdown. The ``providers`` list mirrors the desktop's
    :py:func:`phonology_features.providers.available_providers`
    surface: each entry carries the provider name + display label.

    Display order in the dropdown is ``providers`` first (today:
    PanPhon, the auto-generating recommended default), then the
    static presets in their ``FEATURE_PRESETS`` insertion order
    (today: Hayes, PHOIBLE, Custom). The JS picker stitches the two
    sequences together; the order here is the contract.
    """
    providers = [
        {
            "name": provider.name,
            "label": provider.display_label(),
            "version": provider.version,
        }
        for provider in _provider_registry().values()
    ]
    return {
        "default_segments": DEFAULT_SEGMENTS,
        "default_features": DEFAULT_FEATURES,
        "presets": {
            name: list(feats) for name, feats in FEATURE_PRESETS.items()
        },
        "providers": providers,
    }


def preview_provider_features(
    provider_name: str, segments_text: str
) -> list[str]:
    """Return the feature list the named provider would emit for
    the current segments input.

    Used by the web setup dialog to populate the features textarea
    live as the user edits segments (matching the desktop dialog's
    debounced refresh). Falls back to the provider's full feature
    list when:
      - ``segments_text`` is empty (UI preview state).
      - All segments are unresolved (``generate`` returns empty
        features; the user still needs columns to edit by hand).

    Returns an empty list when the provider name is unknown so JS
    can route to the static-preset fallback without an exception
    spamming the console.
    """
    provider = _provider_registry().get(provider_name)
    if provider is None:
        return []
    segments = infer_split(segments_text)
    if not segments:
        return list(provider.feature_names())
    generated = provider.generate(segments)
    if not generated.features:
        return list(provider.feature_names())
    return list(generated.features)


# --- PHOIBLE bridge endpoints --------------------------------------------
# Sibling surface to the feature-provider endpoints above. The picker
# calls these in three stages: search the autocomplete, list the
# inventories for the chosen language, and (after the user picks one)
# either preview or generate it. ``phoible_load_data`` is the one-shot
# lazy-load handshake the web bridge uses to inject the ~5 MB data
# blob the desktop reads from disk; ``phoible_is_ready`` lets the
# dialog gate the "Create Grid" button until the fetch + load lands.


def _phoible_provider() -> InventoryProvider | None:
    return _inventory_provider_registry().get("PHOIBLE")


def phoible_is_available() -> bool:
    """Return ``True`` when a PHOIBLE provider is registered.

    The web dialog uses this at open time to decide whether to
    surface the "Load from PHOIBLE…" entry at all; a stale checkout
    with no baked index will return ``False`` and the picker hides
    the option entirely rather than showing a broken row.
    """
    return _phoible_provider() is not None


def phoible_is_ready() -> bool:
    """Return ``True`` once the PHOIBLE data payload is loaded.

    Index-only mode (the web cold path) returns ``False`` until
    :py:func:`phoible_load_data` runs. The picker uses this to
    gate the "Create Grid" submit so a user can't trigger
    ``generate`` before the data is in memory.
    """
    provider = _phoible_provider()
    return provider is not None and getattr(provider, "has_data", False)


def phoible_load_data(payload_json: str) -> bool:
    """Ingest the lazy-loaded PHOIBLE data JSON payload.

    Called once by the web dialog after the ``fetch`` of
    ``phoible_data.<hash>.json`` lands. Returns ``True`` on
    success, ``False`` when there is no PHOIBLE provider to
    receive the payload (no-op for desktop, which loads from
    disk at construction). Re-loading is idempotent and cheap.
    """
    provider = _phoible_provider()
    if provider is None:
        return False
    provider.load_data_payload(payload_json)  # type: ignore[attr-defined]
    return True


def phoible_search_languages(query: str, limit: int = 20) -> list[str]:
    """Autocomplete: return up to ``limit`` language names matching
    the substring query. Empty query returns an empty list.

    Returns ``[]`` if no PHOIBLE provider is registered so JS can
    treat the absence the same as "no results" without an extra
    feature-detect call.
    """
    provider = _phoible_provider()
    if provider is None:
        return []
    return provider.search_languages(query, limit=limit)


def _descriptor_to_dict(descriptor: InventoryDescriptor) -> dict[str, Any]:
    """Flatten an :py:class:`InventoryDescriptor` into the dict the
    JS picker consumes. Centralised so a future field rename
    surfaces here once instead of at every endpoint."""
    return {
        "id": descriptor.id,
        "language_name": descriptor.language_name,
        "glottocode": descriptor.glottocode,
        "iso": descriptor.iso_code,
        "dialect": descriptor.dialect,
        "source_short": descriptor.source_short,
        "source_description": descriptor.source_description,
        "segment_count": descriptor.segment_count,
    }


def phoible_list_inventories(language_name: str) -> list[dict[str, Any]]:
    """Return every inventory descriptor for the named language.

    Empty list for unknown languages or when no PHOIBLE provider
    is registered; the picker treats both as "nothing to show".
    """
    provider = _phoible_provider()
    if provider is None:
        return []
    return [
        _descriptor_to_dict(d)
        for d in provider.list_inventories(language_name)
    ]


def phoible_preview_inventory(inventory_id: str) -> dict[str, Any]:
    """Return a compact preview payload for the named PHOIBLE
    inventory (one round-trip cheaper than calling ``generate``
    just to inspect the segment list).

    Shape: ``{descriptor, segments, feature_count}`` where
    ``segments`` is the first
    :py:data:`PHOIBLE_PREVIEW_SEGMENT_LIMIT` IPA glyphs and
    ``feature_count`` is the number of columns the materialised
    inventory carries after the empty-column pruning step.
    """
    provider = _phoible_provider()
    if provider is None or not getattr(provider, "has_data", False):
        return {}
    descriptor = provider.descriptor(inventory_id)
    if descriptor is None:
        return {}
    generated = provider.generate(inventory_id)
    segments = list(generated.segments.keys())
    return {
        "descriptor": _descriptor_to_dict(descriptor),
        "segments": segments[:PHOIBLE_PREVIEW_SEGMENT_LIMIT],
        "segment_total": len(segments),
        "feature_count": len(generated.features),
    }


def load_phoible_inventory(inventory_id: str) -> dict[str, Any]:
    """Load a PHOIBLE inventory into the engine and return its
    summary.

    Semantically parallel to :py:func:`load_inventory_json` and the
    bundled-inventory pick path: the user is loading an existing
    inventory, not building one. The dialog never asks for a name;
    the inventory is named after the PHOIBLE language (the user can
    rename in place via the toolbar's pencil button OR overwrite
    the name on the next save). Once loaded the inventory is fully
    the user's: any edit in the Builder produces a personal copy,
    and saving routes through the same Save flow as any other
    in-memory inventory.

    Metadata stamping is light and informational, not authoritative:
    one ``feature_source`` field records the PHOIBLE provenance so a
    saved file is debuggable, but the field is plain text and the
    user can edit or delete it. There is no "phoible_inventory_id"
    lock; once loaded the inventory is detached from the database.

    Raises :py:class:`ValidationError` when the PHOIBLE provider is
    unavailable, the data payload has not been loaded, or the
    inventory id is unknown.
    """
    global _engine, _inventory_name
    provider = _phoible_provider()
    if provider is None:
        raise ValidationError(
            ("PHOIBLE provider is not available; rebuild the web bundle.",)
        )
    if not getattr(provider, "has_data", False):
        raise ValidationError(
            (
                "PHOIBLE data payload not loaded; call phoible_load_data "
                "before loading an inventory.",
            )
        )
    # Pure-logic composition (name template, metadata stamping,
    # ``Inventory.from_grid``) lives in shared so the desktop's
    # PHOIBLE picker dialog produces an identical inventory from
    # the same ``inventory_id``. Only the bridge-side platform
    # glue (global engine swap + analysis cache invalidation +
    # summary build) stays here.
    try:
        inventory = materialize_phoible_inventory(provider, inventory_id)
    except KeyError as exc:
        raise ValidationError((str(exc),)) from exc
    _engine = FeatureEngine(inventory)
    _inventory_name = inventory.name
    _invalidate_analysis_caches()
    # ``Inventory.metadata['feature_source']`` carries the bake-
    # time provenance ("PHOIBLE / Korean (Eurasian Phonologies)").
    # Mirrors the desktop ``_open_phoible_picker`` path so both
    # surfaces show the same chip text.
    feature_source = inventory.metadata.get("feature_source") or "PHOIBLE"
    provenance = f"{feature_source} / {inventory.name}"
    summary = build_inventory_summary(
        _engine, _inventory_name, provenance, mode=_match_mode
    )
    # Status-bar line composed shared-side (language + source +
    # counts) so both UIs show the identical terse message instead
    # of each wrapping the full dialect-bearing display name.
    summary["status"] = phoible_loaded_message(inventory)
    return summary


def create_new_inventory(
    raw_name: str,
    segments_text: str,
    features_text: str,
    provider_name: str | None = None,
) -> dict[str, Any]:
    """Build a new inventory from delimited text inputs.

    Runs the shared :py:func:`validate_setup` so the rules and
    error wording match the desktop's New Inventory dialog. With
    no provider, every cell starts at ``"0"`` (static-preset
    path). With a provider, the provider resolves each segment to
    a feature bundle and unresolved segments seed with all-zero
    columns; the inventory's :py:attr:`Inventory.metadata` records
    ``feature_source`` + ``feature_source_version`` for provenance
    so a downstream save round-trips the attribution. This mirrors
    the desktop builder's
    :py:meth:`InventoryBuilder._open_setup_dialog` behaviour
    one-for-one.

    Raises :py:class:`ValidationError` with the full tuple of
    issue messages when validation fails. JS surfaces the first
    via the standard ``e.message`` channel; the others can be
    requested separately via
    :py:func:`validation_issues_from_error`.
    """
    global _engine, _inventory_name
    provider: FeatureProvider | None = None
    if provider_name:
        provider = _provider_registry().get(provider_name)
        # Unknown provider name: silently fall through to the static
        # path. The dialog should never send a name we didn't list in
        # ``get_setup_defaults``; if a stale tab does, the static
        # behaviour is the safer recovery than raising.
    result = validate_setup(raw_name, segments_text, features_text)
    if not result.ok:
        raise ValidationError(tuple(issue.message for issue in result.issues))

    metadata: dict[str, Any] = {}
    if provider is not None:
        # Use the provider's resolved bundles for segments it
        # recognises; seed an all-zero bundle for the rest so the
        # grid still has a column-per-feature for the user to edit.
        generated = provider.generate(list(result.segments))
        feature_names = tuple(generated.features) or tuple(result.features)
        grid: dict[str, dict[str, str]] = {}
        for seg in result.segments:
            bundle = generated.segments.get(seg)
            if bundle is not None:
                grid[seg] = {
                    feat: bundle.get(feat, "0") for feat in feature_names
                }
            else:
                grid[seg] = dict(blank_bundle(feature_names))
        metadata["feature_source"] = provider.name
        metadata["feature_source_version"] = provider.version
        features_list = list(feature_names)
    else:
        grid = {
            seg: dict.fromkeys(result.features, "0") for seg in result.segments
        }
        features_list = list(result.features)

    inventory = Inventory.from_grid(
        name=result.name,
        features=features_list,
        segments=grid,
        metadata=metadata if metadata else None,
    )
    # Per-class caps: the total cap fires in ``validate_setup``
    # above, but vowel/consonant class is feature-driven, so it
    # cannot be known until the bundles are resolved here.
    enforce_class_caps(inventory.segments)
    _engine = FeatureEngine(inventory)
    _inventory_name = inventory.name
    _invalidate_analysis_caches()
    return build_inventory_summary(
        _engine, _inventory_name, "builder / new", mode=_match_mode
    )


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


def inventory_cap_status_for_grid(
    segments: list[str],
    features: list[str],
    cells: list[list[str]],
) -> dict[str, Any]:
    """Live vowel / consonant / total counts for the web builder's
    cap counter.

    Counts through the same shared classifier the desktop counter
    and the save-time enforcement use, so the three never disagree
    about which side a segment falls on. Unlike
    :py:func:`commit_inventory_from_grid` this does NOT validate or
    adopt anything: it classifies the in-progress grid as-is (an
    over-cap or otherwise invalid grid still gets a count so the
    counter can warn before the user tries to save), so it never
    raises on a half-built inventory.

    ``cells`` is indexed ``cells[feature_index][segment_index]``,
    matching the commit path; ``"0"`` cells are dropped so a
    segment with no positive features classifies the same way it
    would once saved.
    """
    bundles: dict[str, dict[str, str]] = {}
    for c, seg in enumerate(segments):
        bundle: dict[str, str] = {}
        for r, feat in enumerate(features):
            val = normalize_minus(cells[r][c])
            if val != "0":
                bundle[feat] = val
        bundles[seg] = bundle
    status = inventory_cap_status(bundles)
    return {
        "n_vowels": status.n_vowels,
        "n_consonants": status.n_consonants,
        "n_total": status.n_total,
        "severity": status.severity,
        "text": status.text,
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

    The active inventory's metadata (minus ``name``) is carried
    through to the rebuilt inventory: the grid cannot edit stamps
    like the PHOIBLE provenance or the diphthong
    ``vowel_secondary`` bundles, and dropping them meant a builder
    round-trip of a PHOIBLE inventory silently erased its
    diphthong arrows. Mirrors the desktop builder's
    ``_extra_metadata`` carry.

    Raises :py:class:`ValidationError` if the grid is not a valid
    inventory.
    """
    global _engine, _inventory_name
    base_metadata: dict[str, Any] | None = None
    if _engine is not None:
        base_metadata = {
            k: v for k, v in _engine.inventory.metadata.items() if k != "name"
        }
    inventory = grid_to_inventory(
        name=name,
        features=features,
        segments=segments,
        cells=cells,
        metadata=base_metadata,
    )
    _engine = FeatureEngine(inventory)
    _inventory_name = inventory.name
    _invalidate_analysis_caches()
    return build_inventory_summary(
        _engine, _inventory_name, "builder / grid", mode=_match_mode
    )


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
        match_mode=_match_mode,
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

    Kept for backward compatibility with the pre-bridge fallback
    (``_fallbackPartitionSpillover`` in main.js) and the hash-pin
    test. Live JS calls should prefer :py:func:`plan_segment_layout`
    so the spillover region uses the same 1-4 column policy the
    desktop's ``plan_seg_layout`` returns.
    """
    return partition_groups_for_spillover(heights, available, n_spillover_cols)


def plan_segment_layout(
    group_names: list[str],
    group_heights: list[int],
    group_widths: list[int],
    pane_w: int,
    pane_h: int,
    chart_rect: list[int] | None,
    min_col_w: int,
) -> dict[str, Any]:
    """JS bridge to ``layout.plan_seg_layout``. JS measures each
    consonant group's name / natural height / natural width, the
    pane's clientWidth + clientHeight, the vowel chart's pane-local
    rect (``[x, y, w, h]`` or ``None`` if absent), and the per-spill-
    column minimum width; receives the complete layout plan.

    Returned dict mirrors :py:class:`SegLayoutPlan`:

    * ``main_groups`` -- group names that stay in the main flow.
    * ``spillover_groups`` -- group names that spill below the main
      flow + chart (empty list = no spillover).
    * ``n_spillover_cols`` -- column count in the spillover region
      (1..max_spillover_cols=4).
    * ``spillover_column_assignment`` -- parallel to ``spillover_groups``;
      each entry is the destination column index (0-indexed).
    * ``spillover_rect`` -- ``[x, y, w, h]`` in pane-local pixels
      (informational; the web renderer just needs n_spillover_cols
      and column_assignment to apply ``grid-template-columns`` and
      slot each spilled group).

    Pre-relay the web bridge called the legacy
    ``partition_groups_for_spillover`` with hardcoded 2 cols + the
    fixed-pair-row scheme; desktop has migrated to ``plan_seg_layout``
    which packs 1-4 columns via LPT bin-packing. The two surfaces
    placed the same inventory differently. This function closes that
    divergence by exposing the same plan to both.
    """
    chart_rect_t: tuple[int, int, int, int] | None
    if chart_rect is None:
        chart_rect_t = None
    else:
        chart_rect_t = (
            int(chart_rect[0]),
            int(chart_rect[1]),
            int(chart_rect[2]),
            int(chart_rect[3]),
        )
    plan = plan_seg_layout(
        group_names=group_names,
        group_heights=group_heights,
        group_widths=group_widths,
        pane_w=pane_w,
        pane_h=pane_h,
        chart_rect=chart_rect_t,
        min_col_w=min_col_w,
    )
    return {
        "main_groups": list(plan.main_groups),
        "spillover_groups": list(plan.spillover_groups),
        "n_spillover_cols": plan.n_spillover_cols,
        "spillover_column_assignment": list(plan.spillover_column_assignment),
        "spillover_rect": list(plan.spillover_rect),
    }


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
def analyze_segments(segs: list[str]) -> SegmentSelectionSummary:
    """SEG-mode analysis under the active :py:class:`MatchMode`.
    Returns the per-tab ``analysis_tabs`` payload plus the inputs
    JS needs to derive each row/button's state inline (mirroring
    the desktop's _update_seg_to_feat). Cache is keyed on
    ``(selection, mode)`` so a mode toggle does not return stale
    strict results from a wildcard query (or vice versa).

    Validates that every entry of ``segs`` is a string present in
    the active inventory. A stale segment (selected before an
    inventory swap), a typo, or a non-string element gets rejected
    here so the engine never sees garbage.
    """
    engine = _require_engine()
    bad = [
        s for s in segs if not isinstance(s, str) or s not in engine.segments
    ]
    if bad:
        raise ValidationError(
            (f"unknown segment(s) in current inventory: {bad!r}",)
        )
    return _analyze_segments_cached(tuple(segs), str(_match_mode))


@lru_cache(maxsize=512)
def _analyze_segments_cached(
    segs_tuple: tuple[str, ...],
    mode_str: str,
) -> SegmentSelectionSummary:
    """SEG analysis result. ``mode_str`` is the ``MatchMode`` value
    as a wire string so it composes with ``lru_cache``'s hashability
    requirement (the enum already is hashable; using the string keeps
    the cache key human-readable in profiles)."""
    engine = _require_engine()
    mode = MatchMode(mode_str)
    return summarize_segment_selection(engine, list(segs_tuple), mode=mode)


@_translate_engine_errors
def analyze_features(spec: dict[str, str]) -> FeatureQuerySummary:
    """FEAT-mode analysis under the active :py:class:`MatchMode`.
    Returns the per-tab ``analysis_tabs`` payload plus the matching
    segment list.

    Validates that every key in ``spec`` is a feature present in
    the active inventory and every value is one of ``"+" / "-"
    / "0"``. Same boundary-hardening as
    :py:func:`analyze_segments`.

    **Display invariant:** ``matching`` always equals
    ``engine.find_segments(spec, mode=active_mode)``. Under
    strict, the highlighted segments form a strict natural class
    characterised by the query; under wildcard, they form the
    wildcard natural class (segments whose value is unspecified
    for queried features are included).
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
    return _analyze_features_cached(tuple(spec.items()), str(_match_mode))


@lru_cache(maxsize=512)
def _analyze_features_cached(
    spec_items: tuple[tuple[str, str], ...],
    mode_str: str,
) -> FeatureQuerySummary:
    engine = _require_engine()
    mode = MatchMode(mode_str)
    return summarize_feature_query(engine, dict(spec_items), mode=mode)


@_translate_engine_errors
def get_match_mode() -> str:
    """Wire-stable string of the active :py:class:`MatchMode`.
    JS reads this on boot (after replaying its persisted
    preference) and uses it to drive the toolbar toggle's pressed
    state."""
    return str(_match_mode)


@_translate_engine_errors
def set_match_mode(mode_str: str) -> str:
    """Toggle the active matching mode. Accepts the wire strings
    ``"strict"`` and ``"wildcard"``; rejects anything else.
    Clears the analysis caches because cached results are mode-
    keyed (the key string is part of the lru_cache key, so the
    new mode will compute fresh — clearing is belt-and-suspenders
    for the rare case where the cache is full of stale strict
    entries we don't want to keep alive).

    Returns the canonical wire string of the new active mode so
    JS can confirm the round-trip.
    """
    global _match_mode
    try:
        mode = MatchMode(mode_str)
    except ValueError as exc:
        raise ValidationError(
            (
                f"invalid match mode {mode_str!r}; expected one of "
                f"{[str(m) for m in MatchMode]}",
            )
        ) from exc
    _match_mode = mode
    _invalidate_analysis_caches()
    return str(_match_mode)


@_translate_engine_errors
def inventory_summary_for_mode(mode_str: str) -> dict[str, Any]:
    """Rebuild the inventory summary under ``mode_str``. The
    feature pane consumes ``active_features`` from the result,
    which differs by mode (strict drops all-``0`` columns;
    wildcard surfaces them). Called by JS after a
    :py:func:`set_match_mode` toggle so the feature pane re-renders
    with the new active-feature list. Returns the full
    :py:func:`build_inventory_summary` payload so JS can also
    refresh anything else mode-dependent."""
    engine = _require_engine()
    mode = MatchMode(mode_str)
    return build_inventory_summary(engine, _inventory_name, mode=mode)


def validation_issues_from_error(exc: Any) -> list[str]:
    """Extract the canonical human-readable issues list from a
    ``ValidationError`` raised by ``load_inventory_json``.
    """
    if isinstance(exc, ValidationError):
        return list(exc.issues)
    return [str(exc)]


def validation_report_html(issues: list[str]) -> str:
    """Render the validation-error banner shown after a failed
    inventory load. Delegates to the shared renderer so the web
    Class tab and the desktop analysis pane carry byte-identical
    markup (red heading + one paragraph per escaped issue).
    """
    return render_validation_report(issues)
