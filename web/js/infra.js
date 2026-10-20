// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Required Notice: Copyright 2026 John Winstead, https://github.com/jhnwnstd/phono-feature
/**
 * DOM node registry, status bar, performance marks, fetch helpers and
 * the Pyodide bridge call wrapper.
 *
 * The plumbing every feature module sits on. ``nodes`` is populated
 * once by ``initNodes`` from ``NODE_IDS`` so a typo in an element id
 * fails loudly at boot instead of silently yielding undefined later.
 */
import { state } from "./state.js";


const NODE_IDS = Object.freeze({
    statusbar: "statusbar",
    statusbarSource: "statusbar-source",
    loadingStatus: "loading-status",
    loadingOverlay: "loading-overlay",
    inventoryPicker: "inventory-picker",
    uploadBtn: "upload-btn",
    uploadInput: "upload-input",
    segPanel: "seg-panel",
    featPanel: "feat-panel",
    segGrid: "seg-grid",
    featList: "feat-list",
    segFilterBtn: "seg-filter-btn",
    segClassPopover: "seg-class-popover",
    segClearBtn: "seg-clear-btn",
    featClearBtn: "feat-clear-btn",
    analysisPane: "analysis-pane",
    analysisTabClass: "analysis-tab-class",
    analysisTabFeatures: "analysis-tab-features",
    analysisTabContrasts: "analysis-tab-contrasts",
    analysisContentClass: "analysis-content-class",
    analysisContentFeatures: "analysis-content-features",
    analysisContentContrasts: "analysis-content-contrasts",
    themeBtn: "theme-btn",
    cbBtn: "cb-btn",
    matchModeBtn: "match-mode-btn",
    bugBtn: "bug-btn",
    statusbarBrand: "statusbar-brand",
    sourceDialog: "source-dialog",
    sourceCitation: "source-citation",
    sourceDialogClose: "source-dialog-close",
    segTitle: "seg-title",
    featTitle: "feat-title",
    helpDialog: "help-dialog",
    helpDialogTitle: "help-dialog-title",
    helpDialogBody: "help-dialog-body",
    helpDialogClose: "help-dialog-close",
    editorBtn: "editor-btn",
    setupDialog: "setup-dialog",
    setupForm: "setup-form",
    setupNameInput: "setup-name-input",
    setupSegmentsInput: "setup-segments-input",
    setupFeaturesInput: "setup-features-input",
    setupPresetPicker: "setup-preset-picker",
    setupError: "setup-error",
    // PHOIBLE picker (separate from setup): LOAD path, not editor.
    phoibleBtn: "phoible-btn",
    phoiblePicker: "phoible-picker",
    phoiblePickerForm: "phoible-picker-form",
    phoibleLoading: "phoible-loading",
    phoibleActive: "phoible-active",
    phoibleSearch: "phoible-search",
    phoibleHint: "phoible-hint",
    phoibleResults: "phoible-results",
    phoibleInventories: "phoible-inventories",
    phoibleRadios: "phoible-radios",
    phoiblePreview: "phoible-preview",
    phoibleSummary: "phoible-summary",
    phoibleSegments: "phoible-segments",
    phoibleError: "phoible-error",
    phoibleCancel: "phoible-cancel",
    phoibleLoad: "phoible-load",
    setupCancel: "setup-cancel",
    setupCreate: "setup-create",
    editorView: "editor-view",
    editorExitBtn: "editor-exit-btn",
    editorNewBtn: "editor-new-btn",
    editorSaveAsBtn: "editor-save-as-btn",
    editorAddSegBtn: "editor-add-seg-btn",
    editorAddFeatBtn: "editor-add-feat-btn",
    editorRemoveSegBtn: "editor-remove-seg-btn",
    editorRemoveFeatBtn: "editor-remove-feat-btn",
    editorNameInput: "editor-name-input",
    editorFileLabel: "editor-file-label",
    editorSourceBtn: "editor-source-btn",
    editorSourceDialog: "editor-source-dialog",
    editorSourceTextarea: "editor-source-textarea",
    editorSourceCancel: "editor-source-cancel",
    editorCapCounter: "editor-cap-counter",
    editorGridScroll: "editor-grid-scroll",
    editorGridCorner: "editor-grid-corner",
    editorGridCols: "editor-grid-cols",
    editorGridRows: "editor-grid-rows",
    editorGridData: "editor-grid-data",
    editorStatus: "editor-status",
    labelPromptDialog: "label-prompt-dialog",
    labelPromptForm: "label-prompt-form",
    labelPromptTitle: "label-prompt-title",
    labelPromptLabel: "label-prompt-label",
    labelPromptInput: "label-prompt-input",
    labelPromptError: "label-prompt-error",
    labelPromptCancel: "label-prompt-cancel",
    labelPromptSubmit: "label-prompt-submit",
});
export const nodes = Object.create(null);

/** Validate every required DOM id and cache the elements. */
export function initNodes() {
    const missing = [];
    for (const [key, id] of Object.entries(NODE_IDS)) {
        const el = document.getElementById(id);
        if (el === null) missing.push(id);
        else nodes[key] = el;
    }
    if (missing.length) {
        throw new Error(`required DOM nodes missing: ${missing.join(", ")}`);
    }
}

export const STATUS_KIND = Object.freeze({
    info: "info", success: "success", warning: "warning", error: "error",
});
// Pending flash-revert timer + the persistent status it is covering.
let _statusFlashTimer = null;
let _statusFlashPrev = null;

const _setStatusText = (msg, kind) => {
    nodes.statusbar.textContent = msg;
    nodes.statusbar.title = msg;
    nodes.statusbar.dataset.kind = kind;
};

// Persistent status-bar write. ``kind`` drives a leading icon glyph.
// Cancels any pending flash-revert so a stale revert can't overwrite.
export const setStatus = (msg, kind = STATUS_KIND.info) => {
    if (_statusFlashTimer !== null) {
        clearTimeout(_statusFlashTimer);
        _statusFlashTimer = null;
        _statusFlashPrev = null;
    }
    _setStatusText(msg, kind);
};

// Flash transient status for ``ms`` then revert to the persistent
// message. Used for clipboard-copy feedback. Rapid repeat flashes
// extend the window but still revert to the original.
export const flashStatus = (msg, kind = STATUS_KIND.info, ms = 2500) => {
    if (_statusFlashTimer !== null) {
        clearTimeout(_statusFlashTimer);
    } else {
        _statusFlashPrev = {
            msg: nodes.statusbar.textContent,
            kind: nodes.statusbar.dataset.kind || STATUS_KIND.info,
        };
    }
    _setStatusText(msg, kind);
    _statusFlashTimer = setTimeout(() => {
        _statusFlashTimer = null;
        const prev = _statusFlashPrev;
        _statusFlashPrev = null;
        if (prev) _setStatusText(prev.msg, prev.kind);
    }, ms);
};
export const setLoadingStatus = (msg) => { nodes.loadingStatus.textContent = msg; };

export const mark = (name) => performance.mark(name);
export function measure(label, start, end) {
    try {
        performance.measure(label, start, end);
    } catch {
        /* a missing mark means an earlier phase failed; skip */
    }
}

export function printBootMeasures() {
    const rows = performance
        .getEntriesByType("measure")
        .map((e) => ({ phase: e.name, ms: Math.round(e.duration) }));
    console.table(rows);
}

export function printResourceSummary() {
    const INTERESTING = ["pyodide", "python_bundle", "inventories", "theme"];
    const rows = performance
        .getEntriesByType("resource")
        .filter((r) => INTERESTING.some((needle) => r.name.includes(needle)))
        .map((r) => ({
            name: new URL(r.name).pathname.split("/").pop(),
            ms: Math.round(r.duration),
            transfer_kb: Math.round((r.transferSize || 0) / 1024),
            decoded_kb: Math.round((r.decodedBodySize || 0) / 1024),
        }));
    console.table(rows);
}

// Fetch wrapper: throws on non-2xx, aborts on timeout so the request
// is actually cancelled (not just the awaiting promise).
async function fetchOk(url, { timeoutMs = LOCAL_FETCH_TIMEOUT_MS } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const r = await fetch(url, { signal: controller.signal });
        if (!r.ok) {
            throw new Error(`fetch ${url}: ${r.status} ${r.statusText}`);
        }
        return r;
    } catch (e) {
        if (e.name === "AbortError") {
            throw new Error(`fetch ${url}: timed out after ${timeoutMs} ms`);
        }
        throw e;
    } finally {
        clearTimeout(timer);
    }
}
export async function fetchJson(url, opts) { return (await fetchOk(url, opts)).json(); }
async function fetchText(url, opts) { return (await fetchOk(url, opts)).text(); }
export async function fetchBytes(url, opts) {
    return new Uint8Array(await (await fetchOk(url, opts)).arrayBuffer());
}

/**
 * Reject after `ms` if `promise` hasn't settled. Used for non-fetch
 * promises that own their own internal I/O (loadPyodide); fetch
 * uses AbortController directly via fetchOk.
 */
export function withTimeout(promise, ms, label) {
    let timer;
    const stall = new Promise((_, reject) => {
        timer = setTimeout(
            () => reject(new Error(`${label} timed out after ${ms} ms`)),
            ms,
        );
    });
    return Promise.race([promise, stall]).finally(() => clearTimeout(timer));
}

// Bounded LRU of inventory JSON text keyed by URL.
const INVENTORY_CACHE_MAX = 8;
const inventoryTextCache = new Map();

function _cacheGet(file) {
    if (!inventoryTextCache.has(file)) return undefined;
    const text = inventoryTextCache.get(file);
    // Promote on hit by re-inserting at the tail.
    inventoryTextCache.delete(file);
    inventoryTextCache.set(file, text);
    return text;
}

function _cacheSet(file, text) {
    inventoryTextCache.set(file, text);
    while (inventoryTextCache.size > INVENTORY_CACHE_MAX) {
        const oldest = inventoryTextCache.keys().next().value;
        inventoryTextCache.delete(oldest);
    }
}

export async function fetchInventoryText(file) {
    const cached = _cacheGet(file);
    if (cached !== undefined) return cached;
    const text = await fetchText(file);
    _cacheSet(file, text);
    return text;
}

// Pyodide bridge call. Converts args to PyProxy, result to plain JS,
// destroys every proxy (PyProxies aren't GC'd, so they leak with click count).
export function callBridge(fnName, ...args) {
    if (!state.bridge || !state.pyodide) {
        throw new Error(`bridge not ready: ${fnName}`);
    }
    const proxies = [];
    const pyArgs = args.map((a) => {
        if (a === null || typeof a !== "object") return a;
        const p = state.pyodide.toPy(a);
        proxies.push(p);
        return p;
    });
    try {
        const result = state.bridge[fnName](...pyArgs);
        if (result && typeof result.toJs === "function") {
            // Nested finally so result.destroy runs even if toJs throws.
            try {
                return result.toJs({ dict_converter: Object.fromEntries });
            } finally {
                result.destroy();
            }
        }
        return result;
    } finally {
        for (const p of proxies) p.destroy();
    }
}

// Extract the user-facing message from a bridge error. Pyodide
// surfaces the whole traceback in ``.message``; take the last line
// and strip the ``PkgA.ErrorClass:`` prefix.
export function bridgeErrorMessage(e, fallback) {
    const raw = e && e.message ? String(e.message) : "";
    const lines = raw.split("\n").map((s) => s.trim()).filter(Boolean);
    if (lines.length === 0) return fallback;
    let last = lines[lines.length - 1];
    const m = last.match(
        /^[\w.]+(?:Error|Exception|Warning):\s*(.*)$/,
    );
    if (m) last = m[1];
    return last || fallback;
}
const LOCAL_FETCH_TIMEOUT_MS = 10_000;
