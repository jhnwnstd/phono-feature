// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Required Notice: Copyright 2026 John Winstead, https://github.com/jhnwnstd/phono-feature
/**
 * Loading an inventory and adopting its payload into the UI: the
 * pre-bridge bootstrap render, bundled-inventory fetch, source
 * citation, analysis prewarming and the lazy PHOIBLE payload fetch.
 */
import {
    analysisSpecRowsPerCol,
    clearAnalysisTabs,
    renderFeaturePanel,
    setAnalysisTabs,
} from "./analysis.js";
import { STATUS_TEXT, _formatTpl, emptyFeatureSpec } from "./config.js";
import {
    bridgeErrorMessage,
    callBridge,
    fetchInventoryText,
    nodes,
    setStatus,
} from "./infra.js";
import { escapeHtml, openDialog } from "./measure.js";
import { renderSegmentsWithVisibility } from "./segments.js";
import { assetUrl, state } from "./state.js";


/**
 * Render the default inventory from the inlined bootstrap JSON.
 * Lets the UI paint at ~100 ms instead of waiting ~5 s for Pyodide.
 * Returns false (and logs) if the inline block is absent, parses
 * fail, or the shape doesn't match what the renderers expect; the
 * caller then falls back to the bridge-driven render path.
 */
export function applyBootstrap() {
    const el = document.getElementById("bootstrap");
    if (!el) return false;
    let info;
    try {
        info = JSON.parse(el.textContent);
    } catch (e) {
            console.error("bootstrap parse failed; falling back to bridge", e);
        return false;
    }
    if (!_isValidBootstrap(info)) {
            console.error("bootstrap shape invalid; falling back to bridge", info);
        return false;
    }
    _adoptInventoryState(info);
    // Paint the no-selection analysis hints ("Click a segment...")
    // baked into the bootstrap so they land with the first frame
    // instead of after Pyodide boots. The bridge-ready pass repaints
    // the identical payload, which setAnalysisTabs skips. Tolerant of
    // an older cached bootstrap without the field: the bridge fills it
    // in then.
    if (info.analysis_tabs) setAnalysisTabs(info.analysis_tabs);
    return true;
}

function _isValidBootstrap(info) {
    if (!info || typeof info !== "object") return false;
    if (typeof info.name !== "string") return false;
    if (!Array.isArray(info.segments)) return false;
    if (!Array.isArray(info.features)) return false;
    if (!Array.isArray(info.groups)) return false;
    if (!Array.isArray(info.feature_groups)) return false;
    if (!info.vowel_chart || typeof info.vowel_chart !== "object") return false;
    if (!Array.isArray(info.vowel_chart.cells)) return false;
    // Cell shape is ``{row, col, segs: [{seg, ...}]}`` since the
    // collision-grouping refactor. An older cached bootstrap would
    // have the flat shape and silently render empty vowels; reject
    // it here so the bridge path takes over.
    if (info.vowel_chart.cells.length > 0) {
        const c0 = info.vowel_chart.cells[0];
        if (!Array.isArray(c0?.segs)) return false;
    }
    // ``title`` + structured ``cols`` with projected chart_x landed
    // when chart geometry moved to the shared SSOT. Reject any
    // stale-cache bootstrap missing them; the bridge will repopulate.
    if (typeof info.vowel_chart.title !== "string") return false;
    if (!Array.isArray(info.vowel_chart.cols)) return false;
    if (info.vowel_chart.cols.length > 0) {
        const col0 = info.vowel_chart.cols[0];
        if (typeof col0?.chart_x !== "number") return false;
    }
    // ``silhouette`` landed when the chart silhouette became
    // inventory-adaptive; an older cached bootstrap without it
    // would paint the canonical Close-to-Open trapezoid even when
    // the inventory's populated rows imply something narrower.
    const sil = info.vowel_chart.silhouette;
    if (!sil || typeof sil.top_y !== "number") return false;
    return true;
}

export async function loadBundledInventory(item) {
    const text = await fetchInventoryText(item.file);
    await loadInventoryText(text, item.label);
}

/**
 * Adopt the FEATURE-PANE slice of an inventory summary: the active
 * feature list, the glossary-link map its rows are built from, and the
 * pane render.
 *
 * Split out because two paths need it and only ONE of them wants swap
 * semantics. A match-mode toggle must rebuild the feature pane
 * (wildcard surfaces the all-0 features strict drops) while KEEPING
 * the selection, so it cannot call the swap routine below. Before this
 * existed it hand-rolled a partial copy of these lines and omitted
 * ``featureGlossary``, so wildcard-only features rendered without
 * their glossary link on web while the desktop linked them. Any future
 * payload field the pane reads belongs HERE, so both callers pick it
 * up instead of one of them silently missing it.
 * Guarded by ``run_wildcard_glossary_link_check`` in smoke.py.
 */
export function _adoptFeaturePaneState(info) {
    state.features = info.features;
    // Feature-name -> glossary URL, for features with an entry. Read
    // by ``_buildFeatureRow`` to render the name as a link. The ``||``
    // is defensive only: ``build_inventory_summary`` always emits the
    // key (possibly empty), and taking ``{}`` rather than keeping the
    // previous map makes the pane state exactly what THIS payload
    // says, with no carry-over to reason about.
    state.featureGlossary = info.feature_glossary || {};
    renderFeaturePanel(info.feature_groups);
}

/**
 * Adopt an inventory summary as the active state and paint the
 * segment + feature panels. Shared by the cold-boot bootstrap, the
 * load-from-text, and the create-new paths so all three land on
 * identical post-load UI state. Selection resets to empty, a no-op at
 * boot since state starts empty.
 */
function _adoptInventoryState(info) {
    state.inventory_name = info.name;
    state.segments = info.segments;
    state.selected_segments = [];
    state.selected_features = emptyFeatureSpec();
    state.hidden_segment_classes = new Set();
    state.seg_groups = info.groups;
    state.seg_vowel_chart = info.vowel_chart;
    state.seg_vocoids = info.vocoids || [];
    renderSegmentsWithVisibility();
    _adoptFeaturePaneState(info);
}

/**
 * Adopt a bridge-returned inventory summary, then paint the
 * no-selection analysis hints and the Source link. The load-from-text
 * and create-new paths both land here.
 */
export function applyInventoryInfo(info) {
    _adoptInventoryState(info);
    // Show the empty-state hints ("Click a segment…") from the start
    // rather than a blank pane (the inventory identity lives in the
    // dropdown + the statusbar, so it is not repeated above the tabs).
    renderEmptyAnalysisHints();
    // PHOIBLE inventories carry a source-page URL; any other load
    // (bundled, uploaded, built) leaves it undefined, which hides the
    // statusbar "Source" link, so the link always reflects the
    // currently loaded inventory.
    setStatusSource(info.source);
}

/**
 * The active inventory is NOT one of the listed dropdown options (it
 * was uploaded, created, renamed, or saved-as) so deselect the picker
 * rather than let it keep naming a bundled / PHOIBLE entry that is not
 * actually loaded. The active name lives in the statusbar instead.
 * Single home for this invariant: every engine-identity change that
 * does not originate from the dropdown routes through here, so a
 * picker selection can never outlive the inventory it named. (The
 * dropdown's own change handler is the one path that KEEPS its
 * selection, by not calling this.)
 */
export function markInventoryUnlisted() {
    nodes.inventoryPicker.selectedIndex = -1;
}

/** Paint the analysis pane's no-selection hints ("Click a segment to
 *  inspect it." etc.) from the shared view-model so the tabs are never
 *  blank while an inventory is loaded. Pre-bridge (boot bootstrap) the
 *  engine isn't up yet, so fall back to the empty baseline until the
 *  bridge-ready render repaints. */
export function renderEmptyAnalysisHints() {
    if (state.bridge) {
        const result = callBridge(
            "analyze_segments", state.selected_segments,
        );
        setAnalysisTabs(result.analysis_tabs);
    } else {
        clearAnalysisTabs();
    }
}

// Configure the statusbar "Source" affordance from a classified
// source descriptor {kind, href, text, label}: url/doi -> hyperlink,
// citation -> opens citation window, none/absent -> hidden.
export function setStatusSource(source) {
    const link = nodes.statusbarSource;
    if (!link) return;
    const desc = source && typeof source === "object" ? source : null;
    const kind = desc ? desc.kind : "none";
    // Reset the per-kind attributes so a re-load never inherits the
    // previous inventory's link/handler.
    link.onclick = null;
    link.onkeydown = null;
    link.removeAttribute("href");
    link.removeAttribute("role");
    link.removeAttribute("tabindex");
    if (!desc || kind === "none") {
        link.hidden = true;
        return;
    }
    link.textContent = desc.label || "Source";
    if (kind === "url" || kind === "doi") {
        link.href = desc.href;
        link.title = `Source: ${desc.href}`;
    } else {
        // Plain citation: no resolvable target. Present the element as
        // a button that opens the citation window (mouse + keyboard).
        link.title = "Show the inventory citation";
        link.setAttribute("role", "button");
        link.setAttribute("tabindex", "0");
        link.onclick = (ev) => {
            ev.preventDefault();
            openSourceCitation(desc.text);
        };
        link.onkeydown = (ev) => {
            if (ev.key === "Enter" || ev.key === " ") {
                ev.preventDefault();
                openSourceCitation(desc.text);
            }
        };
    }
    link.hidden = false;
}

/** Open the citation window for a plain-text inventory source. */
function openSourceCitation(text) {
    nodes.sourceCitation.textContent = text || "";
    openDialog(nodes.sourceDialog);
}

// Set the bottom-border status to the loaded-inventory summary.
// Accepts both the full summary and the flat status-only payload
// (n_segments / n_features counts).
export function setInventoryStatus(info) {
    const nSeg = info.n_segments ?? info.segments.length;
    const nFeat = info.n_features ?? info.features.length;
    setStatus(
        _formatTpl(
            "inventory_loaded_template",
            "{name}: {n_segments} segments × {n_features} features",
            { name: info.name, n_segments: nSeg, n_features: nFeat }
        )
    );
}

export async function loadInventoryText(text, sourceLabel) {
    try {
        const info = callBridge("load_inventory_json", text, sourceLabel);
        applyInventoryInfo(info);
        setInventoryStatus(info);
        prewarmCommonAnalyses();
    } catch (e) {
        const issues = [bridgeErrorMessage(e, "unknown error")];
        // Delegate to the shared renderer so the Class tab here
        // and the desktop analysis pane produce byte-identical
        // markup (red heading + escaped <p> per issue). The
        // fallback is reached only if the bridge isn't yet
        // available (pre-Pyodide boot, fetch failure, etc.).
        let errorHtml;
        try {
            errorHtml = callBridge("validation_report_html", issues);
        } catch (_) {
            const heading = STATUS_TEXT.validation_report_heading
                || "Validation errors:";
            errorHtml = `<p><b>${escapeHtml(heading)}</b></p>`
                + issues.map((i) => `<p>${escapeHtml(i)}</p>`).join("");
        }
        // Route load errors to the Class tab, the same place users
        // expect to see the primary analytical output.
        setAnalysisTabs({
            selection: "",
            class: errorHtml,
            features: "",
            contrasts: "",
            contrasts_enabled: false,
        });
        setStatus(
            _formatTpl(
                "load_failed_template",
                "Cannot load {fname}: {issue}",
                { fname: sourceLabel || "inventory", issue: issues[0] }
            )
        );
    }
}

/**
 * Speculatively warm the Python-side LRU cache for the first N
 * single-segment selections during idle time, so the user's first
 * click hits a cached analysis (~10 ms total click-to-analysis
 * instead of ~120 ms). The generation counter cancels an in-flight
 * prewarm when a new one starts (e.g. after inventory swap), so a
 * stale chain can't populate the (just-invalidated) cache.
 */
const PREWARM_COUNT = 10;
let _prewarmGen = 0;

export function prewarmCommonAnalyses() {
    if (!state.bridge) return;
    const myGen = ++_prewarmGen;
    const targets = state.segments.slice(0, PREWARM_COUNT);
    const idle = ("requestIdleCallback" in window)
        ? (cb) => window.requestIdleCallback(cb, { timeout: 1000 })
        : (cb) => setTimeout(cb, 0);
    let i = 0;
    function step() {
        if (myGen !== _prewarmGen) return;
        if (i >= targets.length) return;
        try {
            // Same rows-per-column the real click will use, so the
            // prewarmed entry is a cache hit rather than a stale-R miss.
            callBridge(
                "analyze_segments", [targets[i]], analysisSpecRowsPerCol(),
            );
        } catch {
            /* bridge may go away during teardown; silently skip */
        }
        i++;
        idle(step);
    }
    idle(step);
}

// PHOIBLE data load state. Three slots cover the lifecycle:
// - ``_phoibleDataText`` caches the fetched JSON text once any
//   path (background prefetch or dialog open) has it; the bridge
//   parse step consumes it without a second network roundtrip.
// - ``_phoibleDataFetch`` is the in-flight FETCH promise so
//   concurrent callers (background prefetch + dialog open click)
//   share a single network request.
// - ``_phoibleDataLoad`` is the in-flight BRIDGE LOAD promise so
//   the dialog open path can await whatever push is already in
//   progress without queuing a duplicate parse.
let _phoibleDataText = null;
let _phoibleDataFetch = null;
let _phoibleDataLoad = null;
// Index lazy-load state, mirroring the data slots above. The index is
// also externalized from the bundle (see build.py), so it must be
// fetched + injected before any search/list call; the picker loads it
// alongside the data.
let _phoibleIndexText = null;
let _phoibleIndexFetch = null;

/** Single-flight fetch of the PHOIBLE data file. Cheap to retry;
 *  on failure clears the promise slot so the next caller can try
 *  again. Network only; does not touch the Pyodide bridge. */
function _fetchPhoibleData() {
    if (_phoibleDataText) return Promise.resolve(_phoibleDataText);
    if (_phoibleDataFetch) return _phoibleDataFetch;
    _phoibleDataFetch = (async () => {
        try {
            const url = assetUrl("phoible_data");
            const resp = await fetch(url);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            _phoibleDataText = await resp.text();
            return _phoibleDataText;
        } catch (e) {
            _phoibleDataFetch = null;
            throw e;
        }
    })();
    return _phoibleDataFetch;
}

/** Single-flight fetch of the PHOIBLE index file. Same contract as
 *  _fetchPhoibleData; network only, does not touch the bridge. */
function _fetchPhoibleIndex() {
    if (_phoibleIndexText) return Promise.resolve(_phoibleIndexText);
    if (_phoibleIndexFetch) return _phoibleIndexFetch;
    _phoibleIndexFetch = (async () => {
        try {
            const url = assetUrl("phoible_index");
            const resp = await fetch(url);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            _phoibleIndexText = await resp.text();
            return _phoibleIndexText;
        } catch (e) {
            _phoibleIndexFetch = null;
            throw e;
        }
    })();
    return _phoibleIndexFetch;
}

/** Kick off the PHOIBLE data fetch when the browser is idle so
 *  the dialog open path doesn't pay the ~5 MB download on first
 *  click. The bridge LOAD step is left for the click path: the
 *  ~500 ms JSON parse blocks the main thread (Pyodide runs there
 *  today) and is best left until the user actually wants PHOIBLE
 *  open, where the spinner explains the brief wait. A future
 *  worker migration would let this also happen at idle. */
export function schedulePhoiblePrefetch() {
    if (_phoibleDataText && _phoibleIndexText) return;
    // Gate on the asset manifest, NOT a bridge call: this runs at boot
    // and must not construct the (index-deferred) PHOIBLE provider just
    // to decide whether to prefetch. A build with no baked PHOIBLE
    // assets simply lacks these manifest entries.
    if (!assetUrl("phoible_index") || !assetUrl("phoible_data")) return;
    // Skip the eager prefetch on Data Saver or slow connections. It pulls
    // ~320 KB gzip (held as ~6 MB of decoded JS text) that a visitor who
    // never opens the PHOIBLE picker never uses. The picker-open path
    // (ensurePhoibleLoaded) still fetches on demand, so gating only defers
    // the cost to actual PHOIBLE use instead of imposing it on everyone.
    const conn = navigator.connection;
    if (conn && (conn.saveData
            || conn.effectiveType === "slow-2g"
            || conn.effectiveType === "2g")) {
        return;
    }
    const idle = ("requestIdleCallback" in window)
        ? (cb) => window.requestIdleCallback(cb, { timeout: 10_000 })
        : (cb) => setTimeout(cb, 1500);
    idle(() => {
        // Both are externalized; prefetch in parallel so the dialog open
        // path doesn't pay either download on first click.
        _fetchPhoibleIndex().catch(() => {
            /* silent; openDialog retries on click */
        });
        _fetchPhoibleData().catch(() => {
            /* silent; openDialog retries on click */
        });
    });
}

/** Ensure PHOIBLE is loaded into the bridge. Single-flight: the
 *  dialog open path awaits whatever load is in progress, so a
 *  click that lands while the bridge parse is mid-flight resolves
 *  on the same call. */
export function ensurePhoibleLoaded() {
    if (_phoibleDataLoad) return _phoibleDataLoad;
    _phoibleDataLoad = (async () => {
        try {
            // Fetch index + data in parallel, then inject. The index
            // must be loaded before any search/list/generate call; each
            // bridge parse briefly blocks the main thread, which is why
            // this is deferred to picker open (behind the spinner).
            const [indexText, dataText] = await Promise.all([
                _fetchPhoibleIndex(),
                _fetchPhoibleData(),
            ]);
            callBridge("phoible_load_index", indexText);
            callBridge("phoible_load_data", dataText);
            // The bridge now owns the parsed tables in the WASM heap, so
            // the ~6 MB of JS text (held in these module slots AND in the
            // resolved fetch promises that returned it) is dead weight.
            // Drop every retainer so the JS heap reclaims it. Safe because
            // success is terminal: _phoibleDataLoad stays resolved and is
            // this function's only caller, so nothing re-reads the text;
            // a failure path keeps the cache (it throws before here).
            _phoibleIndexText = null;
            _phoibleDataText = null;
            _phoibleIndexFetch = null;
            _phoibleDataFetch = null;
        } catch (e) {
            _phoibleDataLoad = null;
            throw e;
        }
    })();
    return _phoibleDataLoad;
}
