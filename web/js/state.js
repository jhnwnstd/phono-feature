// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Required Notice: Copyright 2026 John Winstead, https://github.com/jhnwnstd/phono-feature
/**
 * The single mutable app-state object plus the bundled-inventory
 * roster and asset-URL resolution.
 *
 * Only ``state`` is shared mutable data, and it is mutated through
 * plain property writes, never rebound, so every module reads the same
 * object. ``BUNDLED_INVENTORIES`` is the one rebound binding; it is
 * assigned in ``boot.js`` and read through the live binding here.
 */
import {
    MODE,
    STATUS_TEXT,
    emptyFeatureSpec,
    readInlineJson,
} from "./config.js";


export const state = {
    mode: MODE.SEG_TO_FEAT,
    selected_segments: [],
    selected_features: emptyFeatureSpec(),
    // Cross-mode projections: snapshot the outgoing mode's state on
    // every mode toggle so flipping back restores it. Mirrors the
    // desktop's ModeController.saved_seg_state / saved_feat_state.
    saved_seg_state: [],
    saved_feat_state: emptyFeatureSpec(),
    inventory_name: "",
    segments: [],
    features: [],
    debounce_timer: null,
    analysis_token: 0,
    pyodide: null,
    bridge: null,
    // Cached DOM node maps. Iterating these is ~10x cheaper than
    // querySelectorAll in the analysis hot path.
    seg_buttons: new Map(),  // seg -> HTMLButtonElement[] (one per placement)
    feat_rows: new Map(),    // feat -> { row, badge, plus, minus }
    // Segment-class visibility. ``seg_groups`` / ``seg_vowel_chart``
    // cache the last load's UNFILTERED payload so toggling a class
    // re-renders from memory without a bridge round-trip;
    // ``hidden_segment_classes`` holds the class labels the user has
    // hidden via the filter popover. Resets to all-shown on every
    // inventory change (display-state-reset convention): class sets
    // differ between inventories, so a hidden label must not leak
    // across a swap.
    hidden_segment_classes: new Set(),
    seg_groups: [],
    seg_vowel_chart: null,
    // Vowel-like segments that fit no class; rendered as a flat strip
    // under the vowel chart. Usually empty (vocoids almost always match
    // a class), but carried so they are never silently dropped.
    seg_vocoids: [],
};

// Display label for the vowel group; mirrors the shared
// ``VOWEL_GROUP_NAME`` in chart/consonants.py. The bridge renders
// vowels as a chart (not a ``.seg-group``), so this label is not in
// ``info.groups``; the filter popover appends it and hiding it drops
// the whole vowel chart.
export const VOWEL_CLASS_LABEL = "Vowels";
// Mirrors the shared ``VOCOID_GROUP_NAME``: vowel-like segments that fit
// no class, shown as a flat strip under the vowel chart.
export const VOCOID_CLASS_LABEL = "Vocoids";

// Bundled-inventory roster, replaced wholesale once the manifest
// lands. An ES module binding cannot be assigned from outside the
// module that declares it, so ``boot.js`` hands the fetched list to
// ``setBundledInventories`` instead of rebinding the export; every
// reader sees the new array through the live binding.
export let BUNDLED_INVENTORIES = [];

export function setBundledInventories(manifest) {
    BUNDLED_INVENTORIES = manifest;
    return BUNDLED_INVENTORIES;
}

/**
 * Resolve a logical asset name (e.g. "python_bundle") to its hashed
 * URL. The asset manifest is inlined into index.html by the build;
 * dev runs without a build fall back to unhashed names.
 */
const _DEFAULT_ASSET_URLS = Object.freeze({
    inventories_manifest: "inventories.json",
    python_bundle: "python_bundle.json",
});
let _ASSET_MANIFEST = null;

export function assetUrl(name) {
    if (_ASSET_MANIFEST === null) {
        _ASSET_MANIFEST = readInlineJson("asset-manifest", {});
    }
    return _ASSET_MANIFEST[name] || _DEFAULT_ASSET_URLS[name];
}

// Built from ``STATUS_TEXT.default_inventory_stem`` (relayed from
// the ``DEFAULT_INVENTORY_STEM`` Python constant). Keeps the runtime
// default-pick aligned with the build-time bootstrap precompute so
// the two cannot drift to different files. Falls back to a shipped
// stem if the relay key is missing (e.g. an older snapshot built
// before the relay landed); the literal must name a TRACKED
// inventory so the fallback path cannot itself land on a stem the
// manifest omits.
const PREFERRED_DEFAULT_INVENTORY = (
    "inventories/" + (STATUS_TEXT.default_inventory_stem || "hayes_features")
    + ".json"
);

// Pick the preferred default inventory (manifest[0] on fallback).
// Strips the build's cache-busting hash before comparing against
// PREFERRED_DEFAULT_INVENTORY.
export function pickDefaultInventory(manifest) {
    const ASSET_HASH_RE = /\.[0-9a-f]{10}(\.[^./]+)$/;
    const preferred = manifest.find(
        (m) => m.file.replace(ASSET_HASH_RE, "$1")
            === PREFERRED_DEFAULT_INVENTORY,
    );
    return preferred ?? manifest[0];
}
