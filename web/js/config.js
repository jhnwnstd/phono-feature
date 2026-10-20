// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Required Notice: Copyright 2026 John Winstead, https://github.com/jhnwnstd/phono-feature
/**
 * Build-time constants the page carries as inert JSON.
 *
 * Tier 0 leaf: imports nothing. ``index.html`` ships each table as a
 * non-executable ``<script type="application/json">`` block that
 * ``build.py`` fills from the shared Python source, so the frozen
 * values here are the canonical Python output rather than literals
 * that can drift. Every module-init read that crosses a module
 * boundary resolves here, which is why this file has to stay a leaf.
 */


// Payloads baked from Python into inline <script> blocks by
// web/scripts/build.py so the pre-bridge fallback can't drift.
// CHART_STYLE defaults must match the Python source (not pre-relay
// literals) so the missing-block path renders identically.
export const STATUS_TEXT = Object.freeze(readInlineJson("status-text", {}));
export const HELP_TEXT = Object.freeze(readInlineJson("help-text", {}));
export const CHART_STYLE = Object.freeze(
    readInlineJson("chart-style", {
        vowel_cell_dense_threshold: 5,
        vowel_cell_ultra_threshold: 10,
        vowel_btn_min_h_px: 14,
        silhouette_corner_radius_frac: 0.024,
    }),
);

// Top-level UI mode. Values relayed from mode_logic.Mode; the
// hardcoded fallback fires only when the inlined JSON is absent.
// shared/tests/test_relay_smoke.py pins every Python member here.
export const MODE = Object.freeze(
    STATUS_TEXT.mode_values || {
        SEG_TO_FEAT: "seg_to_feat",
        FEAT_TO_SEG: "feat_to_seg",
    },
);

export function readInlineJson(elementId, fallback) {
    const el = document.getElementById(elementId);
    if (!el) return fallback;
    try {
        return JSON.parse(el.textContent || "null") ?? fallback;
    } catch (e) {
        console.warn(`inline JSON ${elementId} parse failed:`, e);
        return fallback;
    }
}

/**
 * Feature-spec maps use a null prototype because feature names come
 * from user-uploaded inventories: a hostile key like "__proto__"
 * mustn't reach Object.prototype.
 */
export function emptyFeatureSpec() { return Object.create(null); }
export function cloneFeatureSpec(spec) {
    return Object.assign(Object.create(null), spec);
}

/** Build an <option> with a value and visible text. */
export function makeOption(value, text) {
    const o = document.createElement("option");
    o.value = value;
    o.textContent = text;
    return o;
}

// Inventory upload cap shared with the engine's post-check via the
// inline ``<script id="limits">`` block baked by build.py. Reading
// the cap from the bake guarantees JS and Python agree on which
// files are out of bounds; without this a 20 MB file would pass
// the JS gate then fail in Pyodide with a confusing generic error.
// ``MAX_INVENTORY_BYTES`` is the resolved value used by the upload
// handler; the fallback below survives a missing inline block (e.g.
// dev server serving a stale build) so the cap is at worst stale,
// never absent.
export const LIMITS = Object.freeze(
    readInlineJson("limits", {
        max_inventory_file_bytes: 5 * 1024 * 1024,
        max_features: 40,
        max_segments: 180,
        max_vowels: 50,
        max_consonants: 135,
        max_name_length: 256,
    }),
);
export const MAX_INVENTORY_BYTES = LIMITS.max_inventory_file_bytes;

// Both UIs read these status templates from STATUS_TEXT (baked
// from shared/render/mode_logic.py) so the desktop and web
// editors surface byte-identical wording on undo / redo / add /
// remove. Fallbacks mirror the Python literals.
export function _pluralS(n) {
    return n === 1 ? "" : "s";
}

export function _formatTpl(key, fallback, vars) {
    let tpl = STATUS_TEXT[key] || fallback;
    for (const [name, value] of Object.entries(vars)) {
        tpl = tpl.split(`{${name}}`).join(String(value));
    }
    return tpl;
}
