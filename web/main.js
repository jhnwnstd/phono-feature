/**
 * Web app entry point.
 *
 * Boots Pyodide, mounts the phonology engine bundle, renders an
 * inlined bootstrap inventory before Pyodide finishes loading, then
 * wires UI events to bridge calls into api.py.
 */

const NODE_IDS = Object.freeze({
    statusbar: "statusbar",
    loadingStatus: "loading-status",
    loadingOverlay: "loading-overlay",
    inventoryPicker: "inventory-picker",
    renameBtn: "rename-btn",
    uploadBtn: "upload-btn",
    uploadInput: "upload-input",
    segPanel: "seg-panel",
    featPanel: "feat-panel",
    segGrid: "seg-grid",
    featList: "feat-list",
    segClearBtn: "seg-clear-btn",
    featClearBtn: "feat-clear-btn",
    analysisPane: "analysis-pane",
    analysisSelection: "analysis-selection",
    analysisTabClass: "analysis-tab-class",
    analysisTabFeatures: "analysis-tab-features",
    analysisTabContrasts: "analysis-tab-contrasts",
    analysisContentClass: "analysis-content-class",
    analysisContentFeatures: "analysis-content-features",
    analysisContentContrasts: "analysis-content-contrasts",
    themeBtn: "theme-btn",
    cbBtn: "cb-btn",
    bugBtn: "bug-btn",
    statusbarBrand: "statusbar-brand",
    renameDialog: "rename-dialog",
    renameForm: "rename-form",
    renameInput: "rename-input",
    renameError: "rename-error",
    renameCancel: "rename-cancel",
    renameSave: "rename-save",
    builderBtn: "builder-btn",
    setupDialog: "setup-dialog",
    setupForm: "setup-form",
    setupNameInput: "setup-name-input",
    setupSegmentsInput: "setup-segments-input",
    setupFeaturesInput: "setup-features-input",
    setupPresetPicker: "setup-preset-picker",
    setupError: "setup-error",
    // PHOIBLE picker dialog (separate from the setup dialog). PHOIBLE
    // is a LOAD path (parallel to ``Browse…``), not a builder
    // integration: clicking the toolbar button opens this picker,
    // user picks a language + inventory, the engine swaps. After
    // load the inventory is fully the user's; the Builder is the
    // post-load edit surface, not a step in this picker's flow.
    phoibleBtn: "phoible-btn",
    phoiblePicker: "phoible-picker",
    phoiblePickerForm: "phoible-picker-form",
    phoibleLoading: "phoible-loading",
    phoibleActive: "phoible-active",
    phoibleSearch: "phoible-search",
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
const nodes = Object.create(null);

/** Validate every required DOM id and cache the elements. */
function initNodes() {
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

const setStatus = (msg) => {
    // Mirror the message into ``title`` so the full string is
    // hoverable when the grid clips the visible text via
    // ``text-overflow: ellipsis`` on a narrow viewport.
    nodes.statusbar.textContent = msg;
    nodes.statusbar.title = msg;
};
const setLoadingStatus = (msg) => { nodes.loadingStatus.textContent = msg; };

const mark = (name) => performance.mark(name);
function measure(label, start, end) {
    try {
        performance.measure(label, start, end);
    } catch {
        /* a missing mark means an earlier phase failed; skip */
    }
}

function printBootMeasures() {
    const rows = performance
        .getEntriesByType("measure")
        .map((e) => ({ phase: e.name, ms: Math.round(e.duration) }));
    console.table(rows);
}

function printResourceSummary() {
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

/**
 * Fetch wrapper that throws on non-2xx and uses an AbortController
 * for timeout so the underlying request is actually cancelled, not
 * just the wait promise.
 */
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
async function fetchJson(url, opts) { return (await fetchOk(url, opts)).json(); }
async function fetchText(url, opts) { return (await fetchOk(url, opts)).text(); }
async function fetchBytes(url, opts) {
    return new Uint8Array(await (await fetchOk(url, opts)).arrayBuffer());
}

/**
 * Reject after `ms` if `promise` hasn't settled. Used for non-fetch
 * promises that own their own internal I/O (loadPyodide); fetch
 * uses AbortController directly via fetchOk.
 */
function withTimeout(promise, ms, label) {
    let timer;
    const stall = new Promise((_, reject) => {
        timer = setTimeout(
            () => reject(new Error(`${label} timed out after ${ms} ms`)),
            ms,
        );
    });
    return Promise.race([promise, stall]).finally(() => clearTimeout(timer));
}

/**
 * Bounded LRU cache of inventory JSON text keyed by URL. Re-selecting
 * a previously-loaded inventory becomes a no-network hit; the bound
 * prevents the per-session upload pile-up from growing unbounded.
 */
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

async function fetchInventoryText(file) {
    const cached = _cacheGet(file);
    if (cached !== undefined) return cached;
    const text = await fetchText(file);
    _cacheSet(file, text);
    return text;
}

/**
 * Pyodide bridge call. Converts plain-JS args to PyProxy, converts
 * the result back to plain JS, and destroys every PyProxy involved
 * (PyProxies aren't garbage-collected; each leak grows with click
 * count over a session).
 */
function callBridge(fnName, ...args) {
    // Guard pyodide too: toPy below dereferences state.pyodide
    // before the bridge null-check would otherwise catch the issue.
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

/** Top-level UI mode. Values match the desktop's Mode StrEnum. */
const MODE = Object.freeze({
    SEG_TO_FEAT: "seg_to_feat",
    FEAT_TO_SEG: "feat_to_seg",
});

/** Baked at build time from ``mode_logic.mode_status_text`` so the
 *  pre-bridge fallback can't drift from the canonical Python.
 *  ``web/scripts/build.py:_build_status_text_payload`` writes the
 *  inline ``<script id="status-text">`` block consumed here. The
 *  freeze keeps the object immutable so a future bug can't reach
 *  back and edit a string in place. */
const STATUS_TEXT = Object.freeze(readInlineJson("status-text", {}));

function readInlineJson(elementId, fallback) {
    const el = document.getElementById(elementId);
    if (!el) return fallback;
    try {
        return JSON.parse(el.textContent || "null") ?? fallback;
    } catch (e) {
        console.warn(`inline JSON ${elementId} parse failed:`, e);
        return fallback;
    }
}

function statusTextForMode(mode) {
    return state.bridge
        ? callBridge("get_mode_status_text", mode)
        : (STATUS_TEXT[mode] || STATUS_TEXT.no_engine || "");
}

/**
 * Feature-spec maps use a null prototype because feature names come
 * from user-uploaded inventories: a hostile key like "__proto__"
 * mustn't reach Object.prototype.
 */
function emptyFeatureSpec() { return Object.create(null); }
function cloneFeatureSpec(spec) {
    return Object.assign(Object.create(null), spec);
}

const state = {
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
    seg_buttons: new Map(),  // seg -> HTMLButtonElement
    feat_rows: new Map(),    // feat -> { row, badge, plus, minus }
};

let BUNDLED_INVENTORIES = [];

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

function assetUrl(name) {
    if (_ASSET_MANIFEST === null) {
        const el = document.getElementById("asset-manifest");
        _ASSET_MANIFEST = el ? JSON.parse(el.textContent) : {};
    }
    return _ASSET_MANIFEST[name] || _DEFAULT_ASSET_URLS[name];
}

const PYODIDE_BOOT_TIMEOUT_MS = 30_000;
const LOCAL_FETCH_TIMEOUT_MS = 10_000;

const PYODIDE_BOOTSTRAP_URL =
    "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js";
const PYODIDE_BOOTSTRAP_SRI =
    "sha384-i3R37b3tF+HWudsUf1VSEOY2YxwSNMqY8DQa9Z0O3xh+NkJ9o+yjcGyIi5huj+nB";

/**
 * Inject pyodide.js as a <script> tag and resolve when loadPyodide
 * is callable. Loaded dynamically (not via a static <script> in
 * index.html) so the bootstrap render path isn't blocked behind a
 * CDN fetch.
 */
function loadPyodideScript() {
    if (typeof loadPyodide === "function") return Promise.resolve();
    return new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = PYODIDE_BOOTSTRAP_URL;
        s.integrity = PYODIDE_BOOTSTRAP_SRI;
        s.crossOrigin = "anonymous";
        s.onload = () => {
            // onload fires when the tag has executed, not when the
            // global is guaranteed defined. A 200/SRI-valid response
            // that exports the wrong shape would otherwise produce a
            // confusing TypeError later.
            if (typeof loadPyodide !== "function") {
                reject(new Error(
                    "pyodide.js loaded but loadPyodide global is missing"
                ));
                return;
            }
            resolve();
        };
        s.onerror = () => reject(new Error("pyodide.js failed to load"));
        document.head.appendChild(s);
    });
}

const PREFERRED_DEFAULT_INVENTORY = "inventories/general_features.json";

/** Boot Pyodide + the engine bundle. `prerendered` indicates that
 *  applyBootstrap already painted the default inventory's DOM; in
 *  that case the loading overlay drops earlier (right after WASM
 *  compile), and the inventory load skips a redundant re-render. */
async function bootPyodide({ prerendered = false } = {}) {
    mark("boot:start");

    setLoadingStatus("Loading inventory list…");
    mark("manifest:start");
    BUNDLED_INVENTORIES = await fetchJson(assetUrl("inventories_manifest"));
    if (!BUNDLED_INVENTORIES.length) {
        throw new Error(
            "no inventories in inventories.json; check the build script"
        );
    }
    populateInventoryPicker();
    mark("manifest:end");

    setLoadingStatus("Loading the Python runtime…");
    mark("pyodide:start");
    mark("bundle-fetch:start");
    // Overlap three independent boot lanes: pyodide.js download,
    // python bundle download, WASM compile. Without this they
    // serialized and added ~1-2 s to cold boot.
    const bundleBytesPromise = fetchBytes(assetUrl("python_bundle"));
    await loadPyodideScript();
    const pyodidePromise = withTimeout(
        // packages: [] skips automatic load of pyodide-py / distutils.
        loadPyodide({ packages: [] }),
        PYODIDE_BOOT_TIMEOUT_MS,
        "Pyodide startup",
    );
    const [pyodide, bundleBytes] = await Promise.all([
        pyodidePromise, bundleBytesPromise,
    ]);
    state.pyodide = pyodide;
    mark("pyodide:end");
    mark("bundle-fetch:end");

    if (prerendered) {
        // Reveal the pre-rendered UI. The remaining ~170 ms of
        // bundle mount + bridge init + inventory sync is shorter
        // than human reaction-to-click time, so the user reaches a
        // ready bridge by the time they decide what to click. The
        // 90 ms yield lets the browser commit the overlay-hide as a
        // paint frame before the synchronous pyimport blocks the
        // main thread, and pads the reveal-to-ready gap to ~220 ms.
        mark("overlay-hide");
        nodes.loadingOverlay.classList.add("hidden");
        setStatus("Almost ready…");
        await new Promise((r) => setTimeout(r, 90));
    }

    setLoadingStatus("Mounting Python sources…");
    mark("bundle:start");
    mountPythonBundle(pyodide, bundleBytes);
    mark("bundle:end");

    setLoadingStatus("Initializing the bridge…");
    mark("bridge:start");
    state.bridge = pyodide.pyimport("api");
    mark("bridge:end");

    // Sync the Python palette state with what the page restored
    // from localStorage. The CSS-vars layer (data-theme / data-cb
    // on <html>) is restored by wireThemeToggle / wireColorblindToggle
    // BEFORE the bridge attaches, so segment buttons and borders
    // pick up the right colours on first paint. The bridge,
    // however, defaults to (light, standard) in Python; without
    // this sync the analysis HTML (which Python renders with
    // ``C['accent']`` etc. baked in) would use the default palette
    // even though the rest of the page is in colorblind / dark
    // mode. Pyodide hasn't cached any analysis yet (we're pre-
    // inventory-load) so no invalidation is needed beyond the call.
    _syncBridgePaletteToStoredState();

    enableBridgeGatedControls();
    setLoadingStatus("Loading default inventory…");
    mark("inventory:start");
    const defaultItem = pickDefaultInventory(BUNDLED_INVENTORIES);
    if (prerendered) {
        // DOM is already populated by applyBootstrap; just sync the
        // engine state so subsequent bridge calls operate on a
        // matching inventory.
        const text = await fetchInventoryText(defaultItem.file);
        callBridge("load_inventory_json", text, defaultItem.label);
        const hasPending =
            state.selected_segments.length > 0
            || Object.keys(state.selected_features).length > 0;
        if (hasPending) scheduleAnalysis();
    } else {
        await loadBundledInventory(defaultItem);
    }
    mark("inventory:end");

    // Idempotent: prerendered path hid the overlay early; the
    // non-prerendered path hides it here once the DOM is ready.
    nodes.loadingOverlay.classList.add("hidden");
    setStatus(statusTextForMode(state.mode));

    mark("boot:end");
    measure("Manifest fetch", "manifest:start", "manifest:end");
    measure("Pyodide load", "pyodide:start", "pyodide:end");
    measure("Python bundle mount", "bundle:start", "bundle:end");
    measure("Bridge init", "bridge:start", "bridge:end");
    measure("Default inventory", "inventory:start", "inventory:end");
    measure("Total boot", "boot:start", "boot:end");
    measure("Reveal -> ready", "overlay-hide", "boot:end");
    printBootMeasures();
    printResourceSummary();
}

/**
 * Pick the preferred default inventory from the manifest, falling
 * back to manifest[0]. Compares against the un-hashed PREFERRED_*
 * constant since the build hashes filenames for cache-busting.
 */
function pickDefaultInventory(manifest) {
    // The build hashes filenames for cache-busting
    // (``name.116857c74f.json``); strip the hash so the comparison
    // against the un-hashed ``PREFERRED_DEFAULT_INVENTORY`` constant
    // works regardless of the bake's current cache key.
    const ASSET_HASH_RE = /\.[0-9a-f]{10}(\.[^./]+)$/;
    const preferred = manifest.find(
        (m) => m.file.replace(ASSET_HASH_RE, "$1")
            === PREFERRED_DEFAULT_INVENTORY,
    );
    return preferred ?? manifest[0];
}

const BUNDLE_FS_PATH = "/home/pyodide/python_bundle.zip";

/**
 * Mount the build-emitted python_bundle.zip onto sys.path via
 * zipimport. Python imports each module lazily on first use.
 */
function mountPythonBundle(pyodide, bundleBytes) {
    validatePythonBundleBytes(bundleBytes);
    pyodide.FS.writeFile(BUNDLE_FS_PATH, bundleBytes);
    pyodide.runPython(
        "import sys\n"
        + `if ${JSON.stringify(BUNDLE_FS_PATH)} not in sys.path:\n`
        + `    sys.path.insert(0, ${JSON.stringify(BUNDLE_FS_PATH)})\n`
    );
}

/**
 * Fail fast if the bundle isn't a zip (truncated, served as an
 * error page, wrong file). Zip files start with "PK\x03\x04".
 */
function validatePythonBundleBytes(bytes) {
    if (!(bytes instanceof Uint8Array) || bytes.length < 4) {
        throw new Error("python bundle is empty or not bytes");
    }
    const isZip = bytes[0] === 0x50 && bytes[1] === 0x4B
        && bytes[2] === 0x03 && bytes[3] === 0x04;
    if (!isZip) {
        const head = [...bytes.slice(0, 4)]
            .map((b) => b.toString(16))
            .join(" ");
        throw new Error(`python bundle doesn't look like a zip (first bytes: ${head})`);
    }
    return bytes;
}

const BRIDGE_GATED_NODES = [
    "inventoryPicker",
    "uploadBtn",
    "renameBtn",
    "builderBtn",
    "phoibleBtn",
];

/**
 * Toolbar controls that call into Python start disabled in HTML
 * and are re-enabled only after the bridge attaches. Keyboard tab
 * focus could otherwise activate them before Pyodide is ready.
 */
function enableBridgeGatedControls() {
    for (const key of BRIDGE_GATED_NODES) nodes[key].disabled = false;
}

/**
 * Render the default inventory from the inlined bootstrap JSON.
 * Lets the UI paint at ~100 ms instead of waiting ~5 s for Pyodide.
 * Returns false (and logs) if the inline block is absent, parses
 * fail, or the shape doesn't match what the renderers expect; the
 * caller then falls back to the bridge-driven render path.
 */
function applyBootstrap() {
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
    state.inventory_name = info.name;
    state.segments = info.segments;
    state.features = info.features;
    renderSegmentGrid(info.groups, info.vowel_chart);
    renderFeaturePanel(info.feature_groups);
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
    // ``title`` + structured ``cols`` (with grid_col / grid_col_span)
    // landed when chart geometry moved to the shared SSOT. Reject any
    // stale-cache bootstrap missing them; the bridge will repopulate.
    if (typeof info.vowel_chart.title !== "string") return false;
    if (!Array.isArray(info.vowel_chart.cols)) return false;
    if (info.vowel_chart.cols.length > 0) {
        const col0 = info.vowel_chart.cols[0];
        if (typeof col0?.grid_col !== "number") return false;
    }
    // ``silhouette`` landed when the chart silhouette became
    // inventory-adaptive; an older cached bootstrap without it
    // would paint the canonical Close-to-Open trapezoid even when
    // the inventory's populated rows imply something narrower.
    const sil = info.vowel_chart.silhouette;
    if (!sil || typeof sil.top_y !== "number") return false;
    return true;
}

async function loadBundledInventory(item) {
    const text = await fetchInventoryText(item.file);
    await loadInventoryText(text, item.label);
}

/**
 * Adopt a bridge-returned inventory summary as the active state and
 * paint the panels. Shared by the load-from-text and create-new
 * paths so both produce identical post-load UI state.
 */
function applyInventoryInfo(info) {
    state.inventory_name = info.name;
    state.segments = info.segments;
    state.features = info.features;
    state.selected_segments = [];
    state.selected_features = emptyFeatureSpec();
    renderSegmentGrid(info.groups, info.vowel_chart);
    renderFeaturePanel(info.feature_groups);
    clearAnalysisTabs();
}

async function loadInventoryText(text, sourceLabel) {
    try {
        const info = callBridge("load_inventory_json", text, sourceLabel);
        applyInventoryInfo(info);
        const loadedTpl = STATUS_TEXT.inventory_loaded_template
            || "{name}: {n_segments} segments, {n_features} features.";
        setStatus(
            loadedTpl
                .replace("{name}", info.name)
                .replace("{n_segments}", String(info.segments.length))
                .replace("{n_features}", String(info.features.length))
        );
        prewarmCommonAnalyses();
    } catch (e) {
        const issues = e.message ? [e.message] : ["unknown error"];
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
        const failTpl = STATUS_TEXT.load_failed_template
            || "Cannot load {fname}: {issue}";
        setStatus(
            failTpl
                .replace("{fname}", sourceLabel || "inventory")
                .replace("{issue}", issues[0])
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

function prewarmCommonAnalyses() {
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
            callBridge("analyze_segments", [targets[i]]);
        } catch {
            /* bridge may go away during teardown; silently skip */
        }
        i++;
        idle(step);
    }
    idle(step);
}

function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;",
        '"': "&quot;", "'": "&#39;",
    })[c]);
}

/**
 * Rasterize ``text`` as a canvas-alpha mask and return a data URL
 * plus the natural (CSS-px) width and height.
 *
 * Drawn at devicePixelRatio for crisp rendering on HiDPI screens.
 * Uses solid black on transparent so the result is purely an alpha
 * mask; the displaying element supplies the actual colour via
 * ``background-color: currentColor``. The literal text passed in
 * is what gets drawn (no normalisation) so segments come through
 * with their original Unicode code points (IPA ɡ U+0261, not ASCII
 * g U+0067, etc.).
 */
// Span-width ceiling for segment-button labels. Matches the
// ``--seg-btn-min-w`` token in style.css (33px button outline,
// minus 3px of internal breathing room). Wide glyphs are rendered
// at a smaller font size so they sit inside the button instead of
// pushing the grid out of alignment.
const SEG_LABEL_MAX_W = 30;

function rasterizeText(text, font, maxWidth) {
    const measure = document.createElement("canvas").getContext("2d");
    // 3-px padding all around so antialias edges + accent marks
    // aren't clipped on either side. Drives both the canvas size
    // and the ``maxWidth`` fit check below.
    const AA_PAD = 6;
    let activeFont = font;
    // When the caller passes ``maxWidth`` (seg-buttons do; feature
    // labels don't), pick the largest font size at which the
    // glyph's natural rendered width fits within the box. Wide
    // segments like /k+͡x+/ go down a few points; ordinary /p/
    // /tʃ/ pass through untouched.
    if (maxWidth != null) {
        const sizeMatch = font.match(/(\d+(?:\.\d+)?)px\s+(.+)/);
        if (sizeMatch) {
            const origSize = parseFloat(sizeMatch[1]);
            const rest = sizeMatch[2];
            // Pulled from the Python-driven CSS variable so the
            // JS-side font-shrink floor and the Python predicate
            // ``font_below_min`` consult the same number. Falls back
            // to 8 if the CSS variable is absent (pre-bridge boot
            // window before layout.css attaches).
            const cssMin = getComputedStyle(
                document.documentElement,
            ).getPropertyValue("--font-size-min-px").trim();
            const MIN_SIZE = parseFloat(cssMin) || 8;
            for (let size = origSize; size >= MIN_SIZE; size -= 0.5) {
                measure.font = `${size}px ${rest}`;
                const probe = measure.measureText(text);
                const pLeft = probe.actualBoundingBoxLeft ?? 0;
                const pRight = probe.actualBoundingBoxRight
                    ?? probe.width;
                const natW = Math.max(probe.width, pLeft + pRight);
                activeFont = `${size}px ${rest}`;
                if (natW + AA_PAD <= maxWidth) break;
            }
        }
    }
    measure.font = activeFont;
    const m = measure.measureText(text);
    // ---- Optical (ink-bounding-box) centering ---------------------
    //
    // The canvas wraps the glyph's PAINTED bounding box (the "ink
    // bbox") plus a small antialias margin on all four sides. The
    // glyph is drawn so the ink bbox sits dead-centre in the
    // canvas. Because the span inherits the canvas dimensions and
    // the seg button flex-centres the span, the ink centre lines up
    // with the button centre for every glyph -- regardless of
    // whether the glyph has a descender (``p``), an ascender (``t``),
    // a tie-bar combining mark (``t͡ʃ``), or neither (``o``).
    //
    // This is the IPA-chart-cell / icon-font convention: each cell
    // is a self-contained symbol, not a character in running text,
    // so optical centering reads more even than baseline alignment
    // across cells. The trade-off (no shared baseline across
    // adjacent buttons) is the right trade for this surface.
    //
    // Measurement notes:
    // ``actualBoundingBoxLeft/Right`` are distances from the text
    // origin to the painted-pixel edges (positive = away from
    // origin; ``Left`` going left, ``Right`` going right). For
    // ``textAlign = "left"`` the origin is at the start of advance,
    // and the painted area runs from (origin - left) to
    // (origin + right) horizontally. ``actualBoundingBoxAscent/
    // Descent`` are analogous vertical distances from the baseline.
    const left = m.actualBoundingBoxLeft ?? 0;
    const right = m.actualBoundingBoxRight ?? m.width;
    const ascent = m.actualBoundingBoxAscent ?? 10;
    const descent = m.actualBoundingBoxDescent ?? 2;
    const inkW = left + right;
    const inkH = ascent + descent;
    // Canvas wraps the ink bbox with ``AA_HALF`` padding all around.
    // (``AA_PAD`` from the font-shrink section is the TOTAL extra
    // dimension; half on each side here.)
    const AA_HALF = AA_PAD / 2;
    const w = Math.max(1, Math.ceil(inkW) + AA_PAD);
    const h = Math.max(1, Math.ceil(inkH) + AA_PAD);
    const dpr = window.devicePixelRatio || 1;
    const canvas = document.createElement("canvas");
    canvas.width = Math.ceil(w * dpr);
    canvas.height = Math.ceil(h * dpr);
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.font = activeFont;
    ctx.fillStyle = "#000";
    ctx.textBaseline = "alphabetic";
    ctx.textAlign = "left";
    // Origin chosen so the painted area exactly fills
    // ``[AA_HALF, w - AA_HALF]`` horizontally and
    // ``[AA_HALF, h - AA_HALF]`` vertically. Painted area:
    //   horizontal: [xOrigin - left, xOrigin + right]
    //   vertical:   [yBaseline - ascent, yBaseline + descent]
    // Setting ``xOrigin = AA_HALF + left`` makes the left painted
    // edge exactly ``AA_HALF`` (= padding) from the canvas's left
    // edge; the right edge falls at ``AA_HALF + inkW`` = canvas
    // right edge minus ``AA_HALF``. Same on the vertical axis.
    ctx.fillText(text, AA_HALF + left, AA_HALF + ascent);
    return { dataUrl: canvas.toDataURL(), width: w, height: h };
}

/**
 * Create a non-copyable, theme-reactive label element for the
 * given text. Returns a ``<span class="rasterized-text">`` whose
 * mask-image encodes the glyph shape; the actual paint colour
 * comes from ``currentColor`` so the parent's theme cascade
 * handles dark/light swaps without re-rendering the canvas.
 *
 * The text never appears in the DOM, so drag-select-and-copy
 * yields nothing. Screen readers fall back to the host element's
 * ``aria-label`` (this span carries ``aria-hidden="true"``).
 */
function createRasterizedLabel(text, font, maxWidth) {
    const { dataUrl, width, height } = rasterizeText(text, font, maxWidth);
    const span = document.createElement("span");
    span.className = "rasterized-text";
    span.setAttribute("aria-hidden", "true");
    span.style.width = width + "px";
    span.style.height = height + "px";
    span.style.setProperty("--mask-url", `url("${dataUrl}")`);
    return span;
}

/**
 * Render the segments pane. Vowel chart is a floated trapezoid in
 * the top-right; consonant groups stack below as flow content. If
 * the pane would overflow after layout settles, rebalance moves
 * the bottom groups into a 2-column spillover at the bottom.
 */
function renderSegmentGrid(groups, vowelChart) {
    const grid = nodes.segGrid;
    grid.innerHTML = "";
    state.seg_buttons.clear();
    if (vowelChart && vowelChart.cells && vowelChart.cells.length) {
        const vowels = document.createElement("div");
        vowels.className = "seg-vowels";
        // Growth policy: the slot stays at the canonical
        // ``--vowel-natural-w`` when the inventory's content fits.
        // When a row needs more horizontal room (a Long-pair cell
        // sharing its backness slot with another cell, etc.), the
        // shared geometry reports a larger ``natural_data_width_px``
        // and the slot grows to fit. No shrinking yet -- sparse
        // inventories keep the canonical slot so the consonant
        // pane's flow remains stable.
        if (typeof vowelChart.natural_data_width_px === "number") {
            const chromeW = 60 + 8 + 4;
            const naturalSlotW = vowelChart.natural_data_width_px + chromeW;
            const canonicalSlotW =
                parseInt(
                    getComputedStyle(document.documentElement)
                        .getPropertyValue("--vowel-natural-w"),
                    10,
                ) || 380;
            if (naturalSlotW > canonicalSlotW) {
                vowels.style.width = `${naturalSlotW}px`;
            }
        }
        vowels.appendChild(_buildVowelChart(vowelChart));
        grid.appendChild(vowels);
    }
    for (const group of groups) {
        grid.appendChild(_buildConsonantGroup(group));
    }
    relayoutSegments();
}

// Cached signature of the last successful relayout pass. When the
// grid width, vowel-chart width, row count, and per-row segment
// counts are all unchanged, the math below would produce the same
// answer -- we early-return. Catches: (a) double-firing at startup
// (renderSegmentGrid + the initial resize listener), (b) idempotent
// re-runs on pane activation when width didn't actually change.
let _lastRelayoutKey = "";

/** Single entry point for any code path that changes the segments
 *  pane width or contents: re-runs the per-group column pass and
 *  the spillover rebalance. Always defers to the next frame so
 *  layout has flushed before measuring; same-state calls early-
 *  return via ``_lastRelayoutKey`` so call-site centralisation
 *  doesn't multiply startup work. */
function relayoutSegments() {
    const grid = nodes.segGrid;
    if (!grid) return;
    const run = () => {
        const vowelsEl = grid.querySelector(".seg-vowels");
        const rows = [...grid.querySelectorAll(".seg-row")];
        const key = [
            grid.clientWidth,
            vowelsEl ? vowelsEl.offsetWidth : 0,
            rows.length,
            rows.map(
                (r) => r.querySelectorAll(".seg-btn").length,
            ).join(","),
        ].join("|");
        if (key === _lastRelayoutKey) return;
        _lastRelayoutKey = key;
        applyPerGroupSegmentColumns();
        rebalanceSegmentSpillover();
    };
    if ("requestAnimationFrame" in window) {
        window.requestAnimationFrame(run);
    } else {
        run();
    }
}

/** Pick a column count per consonant group that avoids one-button
 *  orphan rows. Mirrors the desktop's per-group ``best_segment_n_cols``
 *  pass in ``SegmentGridWidget._do_relayout``: same Python helper, two
 *  call sites. Inline ``grid-template-columns`` per ``.seg-row``
 *  switches that row from the default ``flex-wrap`` to a grid with the
 *  computed count; default CSS still applies between layout passes for
 *  the brief window before this runs. */
function applyPerGroupSegmentColumns() {
    const grid = nodes.segGrid;
    if (!grid) return;
    const rows = [...grid.querySelectorAll(".seg-row")];
    if (rows.length === 0) return;
    const sample = rows[0].querySelector(".seg-btn");
    if (!sample) return;
    // Source of truth for the per-button stride: the CSS variables
    // baked from ``constants.BTN_W`` / ``constants.BTN_GAP`` by
    // ``web/scripts/build.py``. The numeric fallbacks are belt-and-
    // suspenders for the pre-bridge boot window before layout.css
    // is attached; in steady state the var() read wins.
    const rootCS = getComputedStyle(document.documentElement);
    const cssBtnW = parseFloat(
        rootCS.getPropertyValue("--seg-btn-w"),
    );
    const cssGap = parseFloat(
        rootCS.getPropertyValue("--seg-btn-gap"),
    );
    const btnW = sample.offsetWidth || cssBtnW || 33;
    const gapPx = Number.isFinite(cssGap) ? cssGap : 4;
    // Consonant rows wrap around the floated vowel chart; use the
    // narrower "alongside vowels" width as the conservative ceiling
    // so groups above the float don't overflow horizontally.
    const vowelsEl = grid.querySelector(".seg-vowels");
    const vowelsW = vowelsEl ? vowelsEl.offsetWidth + 16 : 0;
    const consonantW = Math.max(btnW, grid.clientWidth - vowelsW);
    const maxCols = Math.max(
        1,
        Math.floor((consonantW + gapPx) / (btnW + gapPx)),
    );
    const sizes = rows.map(
        (r) => r.querySelectorAll(".seg-btn").length,
    );
    const groupCols = state.bridge
        ? callBridge("best_segment_n_cols_for_groups", sizes, maxCols)
        : sizes.map((n) => _fallbackBestNCols(n, maxCols));
    for (let i = 0; i < rows.length; i++) {
        rows[i].style.display = "grid";
        // Fixed tracks (not minmax-to-max-content): all seg-buttons
        // are the same width by design; wide glyphs shrink via the
        // rasterizer rather than letting their column expand and
        // breaking the matrix alignment.
        rows[i].style.gridTemplateColumns =
            `repeat(${groupCols[i]}, ${btnW}px)`;
    }
}

/** Local mirror of ``best_segment_n_cols`` for the pre-bridge window.
 *  Once Pyodide is live the Python implementation is the only source
 *  of truth; this keeps the algorithm identical for the brief gap. */
function _fallbackBestNCols(groupSize, maxCols) {
    if (groupSize <= 0) return 1;
    if (maxCols <= 1) return 1;
    if (groupSize <= maxCols) return groupSize;
    for (let n = maxCols; n > 1; n--) {
        const r = groupSize % n;
        if (r === 0 || r >= 2) return n;
    }
    return maxCols;
}

/**
 * Move overflowing consonant groups into a 2-column spillover
 * sub-grid at the bottom of the segments pane. Only fires when
 * the natural single-column flow exceeds the panel's clientHeight
 * (typically only with the General IPA inventory).
 *
 * #seg-grid is itself the .panel-body, so the spillover lives
 * INSIDE it (not as a sibling) to inherit the same content-area
 * padding and align with the consonant rows above.
 */
function rebalanceSegmentSpillover() {
    const grid = nodes.segGrid;
    if (!grid) return;

    let spillover = grid.querySelector(".seg-spillover");
    if (!spillover) {
        spillover = document.createElement("div");
        spillover.className = "seg-spillover";
    }
    // Reset to the pristine single-column state before measuring.
    while (spillover.firstChild) grid.appendChild(spillover.firstChild);
    if (spillover.parentElement) spillover.remove();

    const available = grid.clientHeight;
    if (grid.scrollHeight <= available) return;

    const consonants = [...grid.querySelectorAll(
        ":scope > .seg-group:not(.vowel-chart-group)",
    )];
    if (consonants.length === 0) return;
    // Single source of truth for the partition decision: the desktop
    // and web both call ``partition_groups_for_spillover`` in
    // ``phonology_shared.presentation.layout``. JS measures the heights and
    // available area; the bridge function computes ``main_count``.
    const heights = consonants.map((el) => el.offsetHeight);
    const mainCount = state.bridge
        ? callBridge("partition_segment_spillover", heights, available)
        : _fallbackPartitionSpillover(heights, available);
    if (mainCount >= consonants.length) return;
    grid.appendChild(spillover);
    for (let i = mainCount; i < consonants.length; i++) {
        spillover.appendChild(consonants[i]);
    }
}

/** Local mirror of ``partition_groups_for_spillover`` for the brief
 *  window between first paint and bridge bootstrap. Once the bridge
 *  is live, ``callBridge`` is the canonical source. */
function _fallbackPartitionSpillover(heights, available, nCols = 2) {
    const n = heights.length;
    if (n === 0 || available <= 0) return n;
    const fits = (mainCount) => {
        let h = 0;
        for (let i = 0; i < mainCount; i++) h += heights[i];
        const spill = heights.slice(mainCount);
        for (let i = 0; i < spill.length; i += nCols) {
            h += Math.max(...spill.slice(i, i + nCols));
        }
        return h <= available;
    };
    let mainCount = n;
    while (mainCount > 0 && !fits(mainCount)) mainCount -= 1;
    return mainCount;
}

function _buildConsonantGroup(group) {
    const groupEl = document.createElement("div");
    groupEl.className = "seg-group";
    const header = document.createElement("div");
    header.className = "seg-group-header";
    header.textContent = group.name.toUpperCase();
    groupEl.appendChild(header);
    const row = document.createElement("div");
    row.className = "seg-row";
    for (const seg of group.segments) {
        row.appendChild(_buildSegmentButton(seg));
    }
    groupEl.appendChild(row);
    return groupEl;
}

/**
 * Build a single segment button. No per-button click handler:
 * a single delegated listener on #seg-grid (wireSegmentDelegation)
 * dispatches by data-seg.
 */
function _buildSegmentButton(seg, extraAttrs) {
    const btn = document.createElement("button");
    btn.className = "seg-btn";
    btn.type = "button";
    btn.dataset.seg = seg;
    btn.dataset.state = "default";
    btn.setAttribute("aria-pressed", "false");
    btn.setAttribute("aria-label", `/${seg}/`);
    // Rasterize the glyph as a canvas-alpha mask: the literal
    // codepoint passed in (IPA ɡ U+0261 etc.) is what gets drawn,
    // and the result lives in CSS-mask space rather than the DOM
    // text content, so drag-select-and-copy yields nothing.
    // ``SEG_LABEL_MAX_W`` matches ``--seg-btn-min-w`` in style.css
    // minus a small breathing margin. The rasterizer downscales the
    // font when the glyph's natural width would overflow the
    // fixed-width button (the consonant grid wants uniform cells).
    btn.appendChild(
        createRasterizedLabel(
            seg,
            '14px "Noto Sans Mono", monospace',
            SEG_LABEL_MAX_W,
        ),
    );
    if (extraAttrs) {
        for (const [k, v] of Object.entries(extraAttrs)) {
            if (k.startsWith("data-")) btn.setAttribute(k, v);
        }
    }
    state.seg_buttons.set(seg, btn);
    return btn;
}

/**
 * Build the IPA vowel trapezoid: 6 height rows × 6 backness-
 * rounding columns. Row/column placement comes from Python
 * (gui.vowel_layout.vowel_grid_pos) so it matches the desktop's
 * VowelChartWidget cell-for-cell.
 */
function _buildVowelChart(chart) {
    const groupEl = document.createElement("div");
    groupEl.className = "seg-group vowel-chart-group";

    // Outer rectangular UI space. Three rows (title, column
    // headers, body) and two columns (row labels, data area). Only
    // the data area gets the trapezoid silhouette and
    // absolutely-positioned cells; labels and the title stay in
    // the rectangular chrome.
    const chartEl = document.createElement("div");
    chartEl.className = "vowel-chart";
    chartEl.setAttribute("role", "grid");
    chartEl.setAttribute("aria-label", "IPA vowel chart");

    // Title sits in row 1, column 2 only -- centered over the data
    // area, NOT over the row-label gutter. Mirrors the desktop's
    // manual ``move(dx + (dw - tw) // 2, 0)`` placement; the
    // shared ``VowelChartGeometry`` documents this as the contract
    // both UIs must honour.
    const titleEl = document.createElement("div");
    titleEl.className = "vowel-chart-title";
    // ``chart.title`` comes from shared vowel_layout.VOWEL_CHART_TITLE
    // so the desktop and web charts always agree on the heading.
    titleEl.textContent = chart.title;
    chartEl.appendChild(titleEl);

    const corner = document.createElement("div");
    corner.className = "vowel-chart-corner";
    chartEl.appendChild(corner);

    // Column headers (Front/Central/Back). Positioned absolutely
    // at x=0%, 50%, 100% so they align with the data cells at the
    // TOP row (the widest row of the trapezoid). For lower rows
    // the cells migrate inward; the headers do not move.
    const headersEl = document.createElement("div");
    headersEl.className = "vowel-chart-cols";
    chart.cols.forEach((col) => {
        const colHeader = document.createElement("div");
        colHeader.className = "vowel-chart-col-label";
        colHeader.textContent = col.label;
        // ``col.chart_x`` is the column's backness anchor (front /
        // central / back) projected into the data-area's [0, 1]
        // coordinate space. Sitting the header there keeps it
        // aligned with the cells in the widest row of the
        // trapezoid.
        colHeader.style.left = (col.chart_x * 100) + "%";
        headersEl.appendChild(colHeader);
    });
    chartEl.appendChild(headersEl);

    // Row labels: emitted into the data area below so each label can
    // sit just outside the silhouette's SLANTED left edge at its
    // chart_y -- following the trapezoid inward as it shrinks. The
    // empty placeholder in grid column 1 keeps the chart's left
    // gutter wide enough to host the label text (which overflows
    // leftward out of the data area into this reserved track).
    const labelsEl = document.createElement("div");
    labelsEl.className = "vowel-chart-row-labels";
    chartEl.appendChild(labelsEl);

    // Trapezoid data area. The CSS pseudo-element draws the
    // silhouette (clip-path keyed off data-shape); each cell drops
    // at chart_x/chart_y already projected through the shape, so
    // the cells follow the silhouette exactly.
    //
    // Per-render silhouette: layout.css bakes a canonical
    // ``--vowel-trapezoid-*`` / ``--vowel-triangle-*`` fallback,
    // but the bridge payload's ``silhouette`` carries the actual
    // inventory-adapted corners (an inventory with no Open vowels
    // ends up with a wider bottom edge, etc.). Setting the CSS
    // custom properties on the data element overrides the
    // canonical defaults for this chart only.
    const dataEl = document.createElement("div");
    dataEl.className = "vowel-chart-data";
    if (chart.shape) {
        dataEl.setAttribute("data-shape", chart.shape);
    }
    const sil = chart.silhouette;
    if (sil) {
        const shape = sil.shape || chart.shape || "trapezoid";
        const setPct = (name, value) => {
            dataEl.style.setProperty(
                `--vowel-${shape}-${name}`,
                `${(value * 100).toFixed(3)}%`
            );
        };
        setPct("top-y", sil.top_y);
        setPct("bottom-y", sil.bottom_y);
        setPct("top-left", sil.top_left);
        setPct("bottom-left", sil.bottom_left);
        // Back edge: ``top_right`` is the back ANCHOR (normalised);
        // ``back_right_pixel_offset`` captures the fixed-pixel
        // pair-shift that the percentage alone cannot represent at
        // arbitrary data-area widths. Same formula on the desktop
        // (``dx + sil.top_right * dw + sil.back_right_pixel_offset``)
        // so the line lands on the same vowel button in both UIs.
        // The asymmetric snap-to-back-vowel-centre logic lives in
        // ``build_vowel_chart_geometry``; we just add.
        const backRightCalc =
            `calc(${(sil.top_right * 100).toFixed(3)}% + ${sil.back_right_pixel_offset}px)`;
        dataEl.style.setProperty(`--vowel-${shape}-top-right`, backRightCalc);
        dataEl.style.setProperty(
            `--vowel-${shape}-bottom-right`,
            backRightCalc,
        );
    }
    // Per-row labels go INSIDE the data area so the slanted left
    // edge is the natural alignment reference (``right: 100%`` is
    // the data area's right edge; ``right: calc(100% - L%)`` puts
    // the label's right edge at fraction ``L`` from the left, i.e.
    // on the silhouette's left edge at this row). Labels overflow
    // leftward out of the data area into the empty labels gutter
    // (``.vowel-chart-row-labels`` in grid column 1), so the
    // reserved track keeps them legible.
    const silTopY = sil ? sil.top_y : 0;
    const silBotY = sil ? sil.bottom_y : 1;
    const silTopLeft = sil ? sil.top_left : 0;
    const silBotLeft = sil ? sil.bottom_left : 0;
    const silSpanY = silBotY - silTopY;
    _appendVowelHeightTierBands(dataEl, chart, silTopY, silBotY);
    for (const row of chart.rows) {
        const rowLabel = document.createElement("div");
        rowLabel.className = "vowel-chart-row-label";
        rowLabel.textContent = row.label;
        let leftNorm;
        if (silSpanY > 0) {
            const t = Math.min(
                1, Math.max(0, (row.chart_y - silTopY) / silSpanY)
            );
            leftNorm = silTopLeft + (silBotLeft - silTopLeft) * t;
        } else {
            leftNorm = 0;
        }
        rowLabel.style.setProperty("--row-y", String(row.chart_y));
        rowLabel.style.setProperty("--row-left", leftNorm.toFixed(5));
        dataEl.appendChild(rowLabel);
    }
    for (const cell of chart.cells) {
        // Multiple vowels can map to the same chart cell (the
        // classic case is ə / ɜ / ɚ all landing in open-mid central
        // for the General inventory). The bridge groups them into
        // ``cell.segs``, sorted by descending placement confidence.
        const segs = cell.segs;
        if (!Array.isArray(segs) || segs.length === 0) continue;
        let target;
        if (segs.length === 1) {
            target = _buildVowelCellButton(segs[0]);
        } else {
            // ``display_kind`` is the shared classifier's choice for
            // how to arrange multiple entries inside one chart slot.
            // PAIR kinds (long / nasal / rhotic / phonation / tone)
            // render horizontally; CONTRAST_SET renders as a 2x2
            // grid; STACK falls back to a vertical column. The
            // ``is_long_pair`` fallback keeps cached bootstrap
            // payloads working until the next CSS bake refresh.
            const kind = cell.display_kind || (cell.is_long_pair ? "long_pair" : "stack");
            switch (kind) {
                case "long_pair":
                case "nasal_pair":
                case "rhotic_pair":
                case "phonation_pair":
                case "tone_pair":
                    target = _buildVowelCellPair(segs, kind);
                    break;
                case "contrast_set":
                    target = _buildVowelCellContrastSet(segs);
                    break;
                default:
                    target = _buildVowelCellStack(segs);
            }
        }
        // Position concern: backness anchor projected through the
        // chart silhouette. Display concern: fixed-pixel shift so
        // rounded/unrounded mates stay exactly tangent regardless
        // of how narrow the row becomes. ``--pair-side`` is the
        // signed multiplier; the per-mate shift is half a button
        // width plus half the within-pair gap, expressed as a CSS
        // calc against ``--seg-btn-w`` / ``--vowel-pair-gap`` so a
        // future bump to either constant flows through.
        target.style.left = (cell.chart_x * 100) + "%";
        target.style.top = (cell.chart_y * 100) + "%";
        target.style.setProperty("--pair-side", String(cell.pair_side));
        dataEl.appendChild(target);
    }
    _appendVowelDiphthongArrows(dataEl, chart);
    chartEl.appendChild(dataEl);

    groupEl.appendChild(chartEl);
    return groupEl;
}

/** Overlay a single ``<svg>`` on the vowel data area with one
 *  arrow per diphthong: a curved Bezier from the primary cell to
 *  the secondary cell, with a small chevron arrowhead at the end.
 *
 *  The SVG sits in the same SVG coordinate system as the data
 *  area's CSS percentages (viewBox 0 to 100); cell endpoints come
 *  from the cell array's normalized ``chart_x`` / ``chart_y``.
 *  ``pointer-events: none`` so the arrows do not block clicks on
 *  underlying vowel buttons. The control point lifts the curve
 *  outward from the chord so two arrows in opposite directions
 *  do not overlap on a straight line. */
/** Overlay faint horizontal bands behind the vowel data area, one
 *  per populated height tier (Close, Near-close, ..., Open). Bands
 *  are tiled so each row's band spans the midpoints between its
 *  ``chart_y`` and its neighbours' (with the top of the topmost
 *  band clamped to the silhouette top and the bottom of the
 *  bottommost band clamped to the silhouette bottom). Alternate
 *  bands carry the tint; same-tier rows alternate so the
 *  visual rhythm reads as ``every other row is shaded`` regardless
 *  of which subset of the 7 tiers is populated.
 *
 *  Bands sit inside a single container with the silhouette
 *  clip-path so the tints follow the trapezoid edges instead of
 *  bleeding into the row-label gutter. The container is the first
 *  child of ``dataEl`` so the silhouette ``::before`` / ``::after``
 *  pseudo-elements (and the cells above them) still paint on top. */
function _appendVowelHeightTierBands(dataEl, chart, silTopY, silBotY) {
    const rows = chart.rows;
    if (!Array.isArray(rows) || rows.length === 0) return;
    const ys = rows.map((r) => r.chart_y);
    const container = document.createElement("div");
    container.className = "vowel-chart-row-bands";
    container.setAttribute("aria-hidden", "true");
    for (let i = 0; i < rows.length; i++) {
        const y = ys[i];
        const above = i > 0 ? (y + ys[i - 1]) / 2 : silTopY;
        const below = i < rows.length - 1 ? (y + ys[i + 1]) / 2 : silBotY;
        const band = document.createElement("div");
        band.className = "vowel-chart-row-band";
        if (i % 2 === 0) {
            band.classList.add("vowel-chart-row-band-tinted");
        }
        band.style.top = `${(above * 100).toFixed(3)}%`;
        band.style.height = `${((below - above) * 100).toFixed(3)}%`;
        container.appendChild(band);
    }
    // Prepend so the bands sit BEHIND row labels, cells, and the
    // diphthong arrow overlay (which all share the data area).
    dataEl.insertBefore(container, dataEl.firstChild);
}

function _appendVowelDiphthongArrows(dataEl, chart) {
    const arrows = chart.diphthongs;
    if (!Array.isArray(arrows) || arrows.length === 0) return;
    // Map ``(row, col) -> (chart_x, chart_y)`` so the arrows can
    // look up endpoints without an O(N*M) scan per diphthong.
    const cellByKey = new Map();
    for (const cell of chart.cells) {
        cellByKey.set(`${cell.row},${cell.col}`, cell);
    }
    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("class", "vowel-diphthong-arrows");
    svg.setAttribute("viewBox", "0 0 100 100");
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("aria-hidden", "true");
    for (const d of arrows) {
        const a = cellByKey.get(`${d.primary_row},${d.primary_col}`);
        const b = cellByKey.get(`${d.secondary_row},${d.secondary_col}`);
        if (!a || !b) continue;
        const ax = a.chart_x * 100;
        const ay = a.chart_y * 100;
        const bx = b.chart_x * 100;
        const by = b.chart_y * 100;
        // Control point: midpoint nudged perpendicular to the
        // chord. A small constant arc rise keeps the curve subtle
        // even on long arrows and visible on short ones.
        const mx = (ax + bx) / 2;
        const my = (ay + by) / 2;
        const dx = bx - ax;
        const dy = by - ay;
        const len = Math.hypot(dx, dy) || 1;
        const lift = Math.min(8, len * 0.18);
        const nx = -dy / len;
        const ny = dx / len;
        const cx = mx + nx * lift;
        const cy = my + ny * lift;
        const path = document.createElementNS(svgNS, "path");
        path.setAttribute("d", `M ${ax} ${ay} Q ${cx} ${cy} ${bx} ${by}`);
        path.setAttribute("class", "vowel-diphthong-arrow");
        svg.appendChild(path);
        // Arrowhead: a small triangle at the end, oriented along the
        // curve's tangent at the endpoint (approximated by the
        // control-point-to-endpoint direction).
        const tx = bx - cx;
        const ty = by - cy;
        const tlen = Math.hypot(tx, ty) || 1;
        const ux = tx / tlen;
        const uy = ty / tlen;
        // Perpendicular for arrowhead wings.
        const px = -uy;
        const py = ux;
        const headLen = 2.5;
        const headHalfW = 1.4;
        const tipX = bx;
        const tipY = by;
        const baseX = bx - ux * headLen;
        const baseY = by - uy * headLen;
        const leftX = baseX + px * headHalfW;
        const leftY = baseY + py * headHalfW;
        const rightX = baseX - px * headHalfW;
        const rightY = baseY - py * headHalfW;
        const head = document.createElementNS(svgNS, "path");
        head.setAttribute(
            "d",
            `M ${tipX} ${tipY} L ${leftX} ${leftY} L ${rightX} ${rightY} Z`,
        );
        head.setAttribute("class", "vowel-diphthong-arrowhead");
        svg.appendChild(head);
    }
    dataEl.appendChild(svg);
}

/** Build a single vowel-cell button from an IPA segment string. */
function _buildVowelCellButton(seg) {
    const btn = _buildSegmentButton(seg);
    btn.classList.add("vowel-chart-cell");
    return btn;
}

/** Build a stacked vertical container for a vowel-chart cell that
 *  holds multiple vowels. Mirrors the desktop's
 *  :py:meth:`VowelChartWidget._build_cell` collision-cell handling:
 *  the entries arrive sorted by descending placement confidence,
 *  so the highest-confidence vowel sits on top.
 *
 *  Children are PLAIN ``_buildSegmentButton`` results (no
 *  ``.vowel-chart-cell`` class). The cell class carries
 *  ``position: absolute`` + ``transform: translate(-50%, -50%)`` so
 *  the outer cell can sit on its (chart_x, chart_y) anchor; putting
 *  it on each child would yank the buttons out of the flex flow and
 *  pile them on top of each other (the schwa / rhotic-schwa overlap
 *  bug). The desktop's QVBoxLayout does the right thing
 *  automatically because Qt's layout managers do not rely on
 *  absolute positioning. */
function _buildVowelCellStack(segs) {
    const cell = document.createElement("div");
    cell.className = "vowel-chart-cell vowel-chart-cell-stack";
    for (const seg of segs) {
        cell.appendChild(_buildSegmentButton(seg));
    }
    return cell;
}

/** Build a horizontal container for a vowel-chart cell whose two
 *  entries share a single vowel-space position and differ only on
 *  one in-cell-contrast feature (long / nasal / rhotic / breathy
 *  or creaky / tone). Side-by-side layout reflects that the two
 *  segments share a single vowel-space position.
 *
 *  ``kind`` is the shared classifier's ``VowelCellDisplayKind``
 *  value (``"long_pair"`` / ``"nasal_pair"`` / etc.); it lands on
 *  the container as a ``data-pair-kind`` attribute so the
 *  stylesheet (or downstream tooling) can react without
 *  re-deriving from the entries.
 *
 *  Same rule as :py:func:`_buildVowelCellStack`: children are plain
 *  segment buttons so the flex row actually distributes them
 *  side-by-side instead of overlapping. */
function _buildVowelCellPair(segs, kind) {
    const cell = document.createElement("div");
    cell.className = "vowel-chart-cell vowel-chart-cell-pair";
    if (kind) cell.dataset.pairKind = kind;
    for (const seg of segs) {
        cell.appendChild(_buildSegmentButton(seg));
    }
    return cell;
}

/** Build a 2-column grid for a vowel-chart cell whose 3-4 entries
 *  differ on more than one in-cell-contrast feature (e.g. a 2x2
 *  long x nasal set). Three entries: first spans both columns on
 *  row 0; the remaining two land side-by-side on row 1. Four
 *  entries: pure 2x2 in input order, row-major.
 *
 *  Children are plain segment buttons; the grid layout is driven
 *  by the ``.vowel-chart-cell-contrast-set`` class so the same
 *  positioning rules apply as the other cell kinds. */
function _buildVowelCellContrastSet(segs) {
    const cell = document.createElement("div");
    cell.className = "vowel-chart-cell vowel-chart-cell-contrast-set";
    cell.dataset.cellSize = String(segs.length);
    for (const seg of segs) {
        cell.appendChild(_buildSegmentButton(seg));
    }
    return cell;
}

function onSegmentClicked(seg) {
    activateMode(MODE.SEG_TO_FEAT);
    const idx = state.selected_segments.indexOf(seg);
    const wasSelected = idx >= 0;
    if (wasSelected) {
        state.selected_segments.splice(idx, 1);
    } else {
        state.selected_segments.push(seg);
    }
    // Optimistic visual flip so the click feels instant; the
    // bridge-driven runSegToFeat reconciles after the debounce
    // (possibly upgrading other buttons to suggested/matched).
    const btn = state.seg_buttons.get(seg);
    if (btn) {
        btn.dataset.state = wasSelected ? "default" : "selected";
        btn.setAttribute("aria-pressed", wasSelected ? "false" : "true");
    }
    scheduleAnalysis();
}

/**
 * Render the feature panel as cards distributed across two
 * columns. The Python side decides which card lands in which
 * column (via gui.layout.distribute_feature_groups); we just
 * mount each card into the column it advertises.
 */
function renderFeaturePanel(featureGroups) {
    const list = nodes.featList;
    list.innerHTML = "";
    state.feat_rows.clear();
    const columnCount = 2;
    const cols = Array.from({ length: columnCount }, () => {
        const c = document.createElement("div");
        c.className = "feat-col";
        return c;
    });
    for (const group of featureGroups) {
        const colIndex = Math.max(
            0, Math.min(columnCount - 1, group.column ?? 0),
        );
        cols[colIndex].appendChild(_buildFeatureGroup(group));
    }
    for (const c of cols) list.appendChild(c);
}

function _buildFeatureGroup(group) {
    const groupEl = document.createElement("div");
    groupEl.className = "feat-group";
    const header = document.createElement("div");
    header.className = "feat-group-header";
    header.textContent = group.name.toUpperCase();
    groupEl.appendChild(header);
    for (const feat of group.features) {
        groupEl.appendChild(_buildFeatureRow(feat));
    }
    return groupEl;
}

/**
 * Build a single feature row. No per-button click handler: a
 * single delegated listener on #feat-list (wireFeatureDelegation)
 * dispatches by data-feat + data-polarity.
 */
function _buildFeatureRow(feat) {
    const row = document.createElement("div");
    row.className = "feat-row";
    row.dataset.feat = feat;
    const name = document.createElement("div");
    name.className = "feat-name";
    name.setAttribute("aria-label", feat);
    name.appendChild(
        createRasterizedLabel(feat, '12px "Noto Sans", sans-serif')
    );
    row.appendChild(name);
    const badge = document.createElement("div");
    badge.className = "feat-badge";
    badge.setAttribute("aria-label", "·");
    badge.appendChild(
        createRasterizedLabel("·", '12px "Noto Sans", sans-serif')
    );
    row.appendChild(badge);
    const polarityButtons = {};
    for (const polarity of ["+", "−"]) {
        const btn = document.createElement("button");
        btn.className = "feat-btn";
        btn.type = "button";
        const code = polarity === "+" ? "+" : "-";
        btn.dataset.polarity = code;
        btn.setAttribute("aria-label", polarity);
        btn.appendChild(
            createRasterizedLabel(polarity, '13px "Noto Sans", sans-serif')
        );
        row.appendChild(btn);
        polarityButtons[code] = btn;
    }
    state.feat_rows.set(feat, {
        row, badge,
        plus: polarityButtons["+"],
        minus: polarityButtons["-"],
    });
    return row;
}

function onFeatureClicked(feat, polarity) {
    activateMode(MODE.FEAT_TO_SEG);
    if (state.selected_features[feat] === polarity) {
        delete state.selected_features[feat];
    } else {
        state.selected_features[feat] = polarity;
    }
    const rec = state.feat_rows.get(feat);
    if (rec) {
        const cur = state.selected_features[feat];
        rec.plus.dataset.active = cur === "+" ? "true" : "false";
        rec.minus.dataset.active = cur === "-" ? "true" : "false";
        // data-query-value drives the FEAT-mode row background via
        // CSS (mirrors the desktop's _apply_query_style).
        if (cur === "+" || cur === "-") rec.row.dataset.queryValue = cur;
        else delete rec.row.dataset.queryValue;
    }
    scheduleAnalysis();
}

function fallbackModeSwitch() {
    if (state.mode === MODE.SEG_TO_FEAT) {
        return {
            saved_seg_state: state.selected_segments.slice(),
            saved_feat_state: emptyFeatureSpec(),
            selected_segments: [],
            selected_features: emptyFeatureSpec(),
        };
    }
    return {
        saved_seg_state: [],
        saved_feat_state: cloneFeatureSpec(state.selected_features),
        selected_segments: [],
        selected_features: emptyFeatureSpec(),
    };
}

/**
 * Switch top-level mode, projecting the outgoing mode's state
 * into the incoming one (mirrors desktop's ModeController.
 * save_outgoing_state).
 *
 *   seg→feat: feat_state := common +/- features of the selection
 *   feat→seg: seg_state  := every segment matching the query
 */
function activateMode(mode) {
    if (state.mode === mode) return;
    const transition = state.bridge
        ? callBridge(
            "project_mode_switch",
            state.mode,
            mode,
            state.selected_segments,
            state.selected_features,
        )
        : fallbackModeSwitch();

    state.saved_seg_state = transition.saved_seg_state.slice();
    state.saved_feat_state = cloneFeatureSpec(transition.saved_feat_state);

    state.mode = mode;
    const isS2F = mode === MODE.SEG_TO_FEAT;
    nodes.segPanel.dataset.active = isS2F ? "true" : "false";
    nodes.featPanel.dataset.active = isS2F ? "false" : "true";

    if (isS2F) {
        state.selected_segments = transition.selected_segments.slice();
        state.selected_features = cloneFeatureSpec(transition.selected_features);
        for (const rec of state.feat_rows.values()) {
            rec.plus.dataset.active = "false";
            rec.minus.dataset.active = "false";
            delete rec.row.dataset.queryValue;
        }
        // FEAT→SEG: segment-button states are also painted by the
        // subsequent runAnalysis pass below (with ``suggested``
        // decoration on extension candidates). Skip the per-button
        // write here when the bridge will repaint to avoid a
        // brief flash through the intermediate ``default``/``selected``
        // state. The seg states will be canonical after runAnalysis.
        if (!state.bridge || !state.selected_segments.length) {
            const selectedSet = new Set(state.selected_segments);
            for (const [seg, btn] of state.seg_buttons) {
                const isSelected = selectedSet.has(seg);
                btn.dataset.state = isSelected ? "selected" : "default";
                btn.setAttribute(
                    "aria-pressed", isSelected ? "true" : "false",
                );
            }
        }
    } else {
        state.selected_features = cloneFeatureSpec(transition.selected_features);
        state.selected_segments = transition.selected_segments.slice();
        // SEG→FEAT: when the bridge will repaint segments as
        // matched/unmatched via the analysis pass below, skip the
        // intermediate ``selected → default`` write that produces
        // a visible flicker on previously-selected segments. The
        // analysis pass writes the canonical state in one paint.
        // Only do the reset when there's no query to follow up
        // with (analysis is a no-op for empty queries).
        if (!state.bridge || !Object.keys(state.selected_features).length) {
            for (const btn of state.seg_buttons.values()) {
                if (btn.dataset.state === "selected") {
                    btn.dataset.state = "default";
                    btn.setAttribute("aria-pressed", "false");
                }
            }
        }
        for (const [feat, rec] of state.feat_rows) {
            const cur = state.selected_features[feat];
            rec.plus.dataset.active = cur === "+" ? "true" : "false";
            rec.minus.dataset.active = cur === "-" ? "true" : "false";
            if (cur === "+" || cur === "-") rec.row.dataset.queryValue = cur;
            else delete rec.row.dataset.queryValue;
        }
    }

    setStatus(statusTextForMode(mode));

    // Mode switch is a discrete one-off event; bypass the 30 ms
    // click-burst debounce and paint the new mode's segment states
    // in a single synchronous pass. Without this, segments would
    // sit at their pre-switch state for 30 ms after the chrome
    // already changed -- the source of the flicker users see.
    if (state.bridge) runAnalysis();
    else clearAnalysisTabs();

    // Pane activation may change the segments-pane width via CSS
    // rules keyed off ``data-active``. Re-run the column + spillover
    // layout so the fixed-width grid tracks match the new available
    // width instead of the stale pre-toggle one. ``relayoutSegments``
    // defers to rAF and early-returns when nothing actually changed,
    // so this is safe to call unconditionally.
    relayoutSegments();
}

const ANALYSIS_DEBOUNCE_MS = 30;

/**
 * Schedule a debounced runAnalysis. Coalesces rapid clicks so a
 * burst (toggle on/off/on) doesn't trigger N bridge calls.
 */
function scheduleAnalysis() {
    if (state.debounce_timer !== null) clearTimeout(state.debounce_timer);
    state.debounce_timer = setTimeout(() => {
        state.debounce_timer = null;
        runAnalysis();
    }, ANALYSIS_DEBOUNCE_MS);
}

const MODE_HANDLERS = Object.freeze({
    [MODE.SEG_TO_FEAT]: runSegToFeat,
    [MODE.FEAT_TO_SEG]: runFeatToSeg,
});

/**
 * Run the analysis for the current mode. Returns silently if the
 * bridge isn't attached yet: a click made before Pyodide finishes
 * has its optimistic UI flip already applied; bootPyodide triggers
 * a final analysis run once the bridge is ready.
 */
function runAnalysis() {
    if (!state.bridge) return;
    MODE_HANDLERS[state.mode](++state.analysis_token);
}

/**
 * Apply `stateFor(seg)` to every cached segment button. The
 * caller computes the new state inline from the relevant set
 * (selected/suggested/matching) instead of looking up a dict;
 * mirrors the desktop's _update_* loops, which are total by
 * construction and immune to dict-fallback ghosts.
 */
function _applySegmentStates(stateFor) {
    for (const [seg, btn] of state.seg_buttons) {
        const newState = stateFor(seg);
        if (btn.dataset.state !== newState) {
            btn.dataset.state = newState;
            const pressed = newState === "selected" || newState === "matched";
            btn.setAttribute("aria-pressed", pressed ? "true" : "false");
        }
    }
}

function _applySegmentStateMap(segmentStates) {
    _applySegmentStates((seg) => segmentStates?.[seg] ?? "default");
}

function _applyFeatureRowStates(featureRows) {
    for (const [feat, rec] of state.feat_rows) {
        const rowState = featureRows?.[feat];
        const value = rowState?.value ?? "";
        const shared = rowState?.shared === true;
        const contrastive = rowState?.contrastive === true;
        rec.row.dataset.value = value;
        rec.row.dataset.shared = shared ? "true" : "false";
        rec.row.dataset.contrastive = contrastive ? "true" : "false";
        const badgeText = rowState?.badge ?? "·";
        _setRasterizedBadge(rec.badge, badgeText);
    }
}

/** Swap a feat-row badge's rasterized label in place. */
function _setRasterizedBadge(badgeEl, text) {
    badgeEl.setAttribute("aria-label", text);
    badgeEl.replaceChildren(
        createRasterizedLabel(text, '12px "Noto Sans", sans-serif')
    );
}

function runSegToFeat(token) {
    let result;
    try {
        result = callBridge("analyze_segments", state.selected_segments);
    } catch (e) {
        _surfaceBridgeFailure("analyze_segments", e);
        return;
    }
    if (token !== state.analysis_token) return;
    setAnalysisTabs(result.analysis_tabs);
    _applySegmentStateMap(result.segment_states);
    _applyFeatureRowStates(result.feature_rows);
}

function runFeatToSeg(token) {
    let result;
    try {
        result = callBridge("analyze_features", state.selected_features);
    } catch (e) {
        _surfaceBridgeFailure("analyze_features", e);
        return;
    }
    if (token !== state.analysis_token) return;
    setAnalysisTabs(result.analysis_tabs);
    _applySegmentStateMap(result.segment_states);
}

/** Surface a bridge-call failure to the user instead of letting it
 *  halt the JS event loop with no feedback. The bridge raises
 *  ``ValidationError`` for bad inputs (validated at api.py); for
 *  any other exception the catch path here still keeps the UI
 *  responsive. The console line carries the full error for
 *  developer triage; the statusbar shows the friendlier summary.
 */
function _surfaceBridgeFailure(callName, err) {
    const msg = err && err.message ? err.message : String(err);
    console.error(`bridge ${callName} failed:`, err);
    setStatus(`Analysis failed: ${msg.split("\n")[0]}`);
}

/** Push the shared view-model's per-tab payload into the analysis
 *  pane. Mirrors the desktop ``AnalysisPanel.set_sections``: same
 *  Python source, both UIs render the same three tabs.
 *
 *  Payload keys:
 *    selection         html for the persistent header above the tabs
 *                      (empty → header hidden; query in FEAT mode is
 *                      explicit in the Features tab, so no need to
 *                      repeat it here)
 *    class             html for the Class tab body
 *    features          html for the Features tab body
 *    contrasts         html for the Contrasts tab body
 *    contrasts_enabled false → grey the Contrasts tab + snap back
 *                      to Class if it was active
 *    class_state       "natural" | "not_natural" | "neutral": colour
 *                      cue on the Class tab itself, replaces the
 *                      old "Natural class: Yes/No" text
 */
function setAnalysisTabs(tabs) {
    if (!tabs) {
        clearAnalysisTabs();
        return;
    }
    const selectionHtml = tabs.selection || "";
    nodes.analysisSelection.innerHTML = selectionHtml;
    nodes.analysisSelection.hidden = selectionHtml.length === 0;
    nodes.analysisContentClass.innerHTML = tabs["class"] || "";
    nodes.analysisContentFeatures.innerHTML = tabs.features || "";
    nodes.analysisContentContrasts.innerHTML = tabs.contrasts || "";
    const contrastsEnabled = tabs.contrasts_enabled !== false;
    nodes.analysisTabContrasts.disabled = !contrastsEnabled;
    nodes.analysisTabContrasts.setAttribute(
        "aria-disabled", contrastsEnabled ? "false" : "true",
    );
    // If the user has the Contrasts tab open but the new payload
    // disables it, snap back to Class so they land on real content.
    if (
        !contrastsEnabled
        && nodes.analysisTabContrasts.getAttribute("aria-selected") === "true"
    ) {
        activateAnalysisTab("class");
    }
    nodes.analysisTabClass.dataset.classState = tabs.class_state || "neutral";
}

/** Canonical full-reset sink for the analysis pane. After this
 *  returns, every observable visual cue (selection label, three
 *  tab bodies, Contrasts tab enable, active tab, Class tab colour
 *  state) is back to its empty baseline. Any new display cue added
 *  later must reset here too, so a regression breaks the invariant
 *  test instead of the UI. */
function clearAnalysisTabs() {
    nodes.analysisSelection.innerHTML = "";
    nodes.analysisSelection.hidden = true;
    nodes.analysisContentClass.innerHTML = "";
    nodes.analysisContentFeatures.innerHTML = "";
    nodes.analysisContentContrasts.innerHTML = "";
    nodes.analysisTabContrasts.disabled = false;
    nodes.analysisTabContrasts.removeAttribute("aria-disabled");
    nodes.analysisTabClass.dataset.classState = "neutral";
    activateAnalysisTab("class");
}

/** Switch the visible tab. Updates aria-selected on the tab buttons
 *  and the ``hidden`` attribute on the tab panels. */
function activateAnalysisTab(name) {
    const buttons = [
        ["class", nodes.analysisTabClass, nodes.analysisContentClass],
        ["features", nodes.analysisTabFeatures, nodes.analysisContentFeatures],
        [
            "contrasts",
            nodes.analysisTabContrasts,
            nodes.analysisContentContrasts,
        ],
    ];
    for (const [tabName, btn, panel] of buttons) {
        const active = tabName === name;
        btn.setAttribute("aria-selected", active ? "true" : "false");
        panel.hidden = !active;
    }
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
const LIMITS = Object.freeze(
    readInlineJson("limits", {
        max_inventory_file_bytes: 5 * 1024 * 1024,
        max_features: 40,
        max_segments: 200,
        max_name_length: 256,
    }),
);
const MAX_INVENTORY_BYTES = LIMITS.max_inventory_file_bytes;

function wireUploadDownload() {
    nodes.uploadBtn.addEventListener("click", () => nodes.uploadInput.click());
    nodes.uploadInput.addEventListener("change", async (ev) => {
        const file = ev.target.files[0];
        if (!file) return;
        if (file.size > MAX_INVENTORY_BYTES) {
            const mb = (file.size / (1024 * 1024)).toFixed(1);
            setStatus(
                `File too large (${mb} MB > `
                + `${MAX_INVENTORY_BYTES / (1024 * 1024)} MB). `
                + "Inventories are usually <50 KB; check the file."
            );
            ev.target.value = "";
            return;
        }
        const text = await file.text();
        await loadInventoryText(text, file.name);
        // An uploaded file replaces the engine state, so the
        // PHOIBLE synthetic entry (if any) no longer reflects what
        // is loaded.
        clearLoadedSyntheticOption();
        ev.target.value = "";
    });
    // Save-as lives on the editor toolbar only; the main toolbar
    // is for selecting and viewing inventories, not exporting them.
}

/**
 * Serialize the active inventory and trigger a browser download.
 * Shared by the main toolbar's "Save as..." button and the builder
 * editor's "Save as..." button so both surfaces produce identical
 * output. Filename comes from the same suggest_filename slugifier
 * the desktop Save As dialog uses.
 */
function downloadCurrentInventory() {
    try {
        const text = callBridge("serialize_current_inventory");
        const filename = callBridge("get_download_filename");
        const blob = new Blob([text], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        a.click();
        // Defer revoke past this tick: Safari and some older Firefox
        // versions have not actually started the download by the time
        // a synchronous revoke runs.
        setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (e) {
        setStatus(`Download failed: ${e.message}`);
    }
}

/**
 * Wire the pencil button to a modal dialog that renames the active
 * inventory. The bridge endpoint round-trips the new name through
 * Inventory.parse so the same validation rules as the load path
 * apply (NFC + strip + length cap). Validation errors are surfaced
 * inline inside the dialog; the modal stays open so the user can
 * correct without losing context.
 */
function wireRename() {
    const dialog = nodes.renameDialog;
    const form = nodes.renameForm;
    const input = nodes.renameInput;
    const errorBox = nodes.renameError;
    const cancelBtn = nodes.renameCancel;

    const openDialog = () => {
        input.value = state.inventory_name || "";
        errorBox.textContent = "";
        // Native <dialog>.showModal traps focus and dims with ::backdrop.
        // Fallback to show() if showModal is unavailable (very old browsers).
        if (typeof dialog.showModal === "function") {
            dialog.showModal();
        } else {
            dialog.setAttribute("open", "");
        }
        // Select-on-open so a confirming user can just retype the
        // whole name without manually selecting it first.
        requestAnimationFrame(() => input.select());
    };

    const closeDialog = () => {
        if (typeof dialog.close === "function") {
            dialog.close();
        } else {
            dialog.removeAttribute("open");
        }
    };

    nodes.renameBtn.addEventListener("click", openDialog);
    cancelBtn.addEventListener("click", closeDialog);

    form.addEventListener("submit", (ev) => {
        // method="dialog" would auto-close on submit; preventDefault
        // keeps the dialog open until the bridge confirms so a
        // validation error can be shown inline.
        ev.preventDefault();
        const newName = input.value;
        try {
            const result = callBridge("rename_current_inventory", newName);
            state.inventory_name = result.name;
            setStatus(`Renamed to ${result.name}.`);
            errorBox.textContent = "";
            closeDialog();
        } catch (e) {
            errorBox.textContent = e.message || "Rename failed.";
            input.focus();
        }
    });
}

/**
 * Wire the New-inventory setup dialog and return its ``open()``
 * trigger. The dialog itself owns its inputs and submit handling;
 * callers (the builder editor's New button) invoke ``open()`` to
 * show it.
 *
 * The preset dropdown and Tab-autofill seeds come from the same
 * inventory_setup module the desktop builder uses, so the two
 * frontends offer identical defaults. Validation is server-side
 * (Pyodide-side) through validate_setup; the dialog stays open
 * on error so the user can correct without losing input.
 */
function wireSetupDialog() {
    const dialog = nodes.setupDialog;
    const form = nodes.setupForm;
    const nameInput = nodes.setupNameInput;
    const segInput = nodes.setupSegmentsInput;
    const featInput = nodes.setupFeaturesInput;
    const presetPicker = nodes.setupPresetPicker;
    const errorBox = nodes.setupError;

    let defaultsLoaded = false;
    let presets = Object.create(null);
    let defaultSegments = "";
    let defaultFeatures = "";
    // Sentinel prefix used in the picker's option values to mark a
    // provider entry distinct from a static preset name. Stripped
    // before any bridge call.
    const PROVIDER_PREFIX = "provider:";
    // Mirror of the desktop dialog's ``_chosen_provider`` slot:
    // non-null while the user has a PanPhon-style auto-generate
    // provider selected, null while a static preset is active.
    let chosenProvider = null;
    let providerRefreshTimer = 0;
    // 250 ms matches the desktop dialog's
    // ``_provider_refresh_timer`` debounce so live-preview behaviour
    // is the same across clients.
    const PROVIDER_REFRESH_MS = 250;

    const loadDefaultsOnce = () => {
        if (defaultsLoaded) return;
        const defaults = callBridge("get_setup_defaults");
        defaultSegments = defaults.default_segments;
        defaultFeatures = defaults.default_features;
        // Placeholder shows the seed as ghost text. Tab while empty
        // converts it into real content (see autofillOnTab below);
        // this mirrors :py:class:`_AutofillTextEdit` on the desktop,
        // which Pastes ``DEFAULT_FILL`` on Tab when the box is empty.
        segInput.placeholder = defaultSegments;
        featInput.placeholder = defaultFeatures;
        presets = defaults.presets || {};
        // Display order: providers FIRST (today PanPhon, the
        // auto-fill recommended default), then the static presets
        // (Hayes, PHOIBLE, Custom). Providers are bolded to signal
        // they auto-generate the features as the user types
        // segments; the static presets just populate the textarea
        // with a column scaffold the user fills in by hand.
        presetPicker.innerHTML = "";
        const providers = defaults.providers || [];
        for (const provider of providers) {
            const opt = document.createElement("option");
            opt.value = PROVIDER_PREFIX + provider.name;
            // Suffix carries the meaning even on rendering surfaces
            // where ``<option>`` font-weight is ignored (some older
            // WebKit), so the recommended path is unambiguous
            // regardless of native ``<select>`` styling support.
            opt.textContent = `${provider.label || provider.name} (auto-fill)`;
            opt.style.fontWeight = "600";
            presetPicker.appendChild(opt);
        }
        for (const name of Object.keys(presets)) {
            const opt = document.createElement("option");
            opt.value = name;
            opt.textContent = name;
            presetPicker.appendChild(opt);
        }
        defaultsLoaded = true;
    };

    const cancelProviderRefresh = () => {
        if (providerRefreshTimer) {
            window.clearTimeout(providerRefreshTimer);
            providerRefreshTimer = 0;
        }
    };

    const refreshProviderFeatures = () => {
        if (!chosenProvider) return;
        // The bridge falls back to the provider's full feature list
        // when segInput is empty or all-unresolved, so an empty box
        // still gives the user a preview of the columns they will
        // get; matches the desktop dialog's behaviour.
        const features = callBridge(
            "preview_provider_features",
            chosenProvider,
            segInput.value,
        );
        if (Array.isArray(features) && features.length > 0) {
            featInput.value = features.join("\n");
        }
    };

    const applyPreset = (value) => {
        cancelProviderRefresh();
        if (value && value.startsWith(PROVIDER_PREFIX)) {
            chosenProvider = value.slice(PROVIDER_PREFIX.length);
            refreshProviderFeatures();
            return;
        }
        chosenProvider = null;
        const list = presets[value];
        if (!list || list.length === 0) {
            featInput.value = "";
            return;
        }
        featInput.value = list.join("\n");
    };

    /**
     * Tab on an empty textarea pastes ``seed`` and lands the caret
     * at the end so the user can keep typing without first having
     * to clear or click. Mirrors the desktop's
     * :py:class:`_AutofillTextEdit` behavior, where Tab triggers the
     * same seed paste when the box is empty.
     *
     * Browser default for Tab in a textarea is focus advance; we
     * preventDefault only on the empty-box path so users can still
     * Tab out of a non-empty box normally.
     */
    const autofillOnTab = (textarea, getSeed) => {
        textarea.addEventListener("keydown", (ev) => {
            if (ev.key !== "Tab" || ev.shiftKey) return;
            if (textarea.value.trim() !== "") return;
            const seed = getSeed();
            if (!seed) return;
            ev.preventDefault();
            textarea.value = seed;
            // Caret to the end so the user types a continuation.
            const end = seed.length;
            textarea.setSelectionRange(end, end);
        });
    };
    autofillOnTab(segInput, () => defaultSegments);
    autofillOnTab(featInput, () => defaultFeatures);

    // Debounced provider refresh on segments edit, parallel to the
    // desktop dialog's textChanged hookup. Only fires when a
    // provider is active; static-preset users keep their hand-typed
    // features intact even as they edit segments.
    segInput.addEventListener("input", () => {
        if (!chosenProvider) return;
        cancelProviderRefresh();
        providerRefreshTimer = window.setTimeout(
            refreshProviderFeatures,
            PROVIDER_REFRESH_MS,
        );
    });

    const openDialog = () => {
        loadDefaultsOnce();
        nameInput.value = "";
        segInput.value = "";
        // Drop any leftover provider selection from a prior open;
        // applyPreset below resets it from whatever the first picker
        // option is.
        chosenProvider = null;
        cancelProviderRefresh();
        // Default to the first preset (Default(33)) on open so the
        // common case is one click. The user can switch to Custom
        // and clear if they want to start blank.
        if (presetPicker.options.length > 0) {
            presetPicker.selectedIndex = 0;
            applyPreset(presetPicker.value);
        }
        errorBox.textContent = "";
        if (typeof dialog.showModal === "function") {
            dialog.showModal();
        } else {
            dialog.setAttribute("open", "");
        }
        requestAnimationFrame(() => nameInput.focus());
    };

    const closeDialog = () => {
        if (typeof dialog.close === "function") {
            dialog.close();
        } else {
            dialog.removeAttribute("open");
        }
    };

    nodes.setupCancel.addEventListener("click", () => {
        cancelProviderRefresh();
        closeDialog();
    });
    presetPicker.addEventListener("change", () => {
        applyPreset(presetPicker.value);
    });

    form.addEventListener("submit", (ev) => {
        ev.preventDefault();
        // Editor-dirty guard: creating a new inventory swaps the
        // engine, which discards any unsaved edits the user made in
        // the editor. Prompt once before the swap so the dialog
        // submit cannot silently erase in-progress work. Matches
        // the spirit of the desktop's ``_check_unsaved`` gate
        // around :py:meth:`show_setup_dialog`.
        if (!nodes.editorView.hidden && editorState.dirty) {
            if (!confirm("Discard unsaved changes to the current inventory?")) {
                return;
            }
        }
        // Provider-driven path: flush any pending debounced
        // preview before submit so the features text reflects the
        // CURRENT segment list, not the pre-edit one. Mirrors the
        // desktop dialog's accept() which forces a refresh before
        // closing.
        if (chosenProvider) {
            cancelProviderRefresh();
            refreshProviderFeatures();
        }
        try {
            const info = callBridge(
                "create_new_inventory",
                nameInput.value,
                segInput.value,
                featInput.value,
                chosenProvider,
            );
            const sourceSuffix = chosenProvider
                ? ` via ${chosenProvider}`
                : "";
            applyInventoryInfo(info);
            setStatus(
                `Created ${info.name} `
                + `(${info.segments.length} segments, `
                + `${info.features.length} features)${sourceSuffix}.`,
            );
            errorBox.textContent = "";
            closeDialog();
            // If the builder editor is open it must re-fetch the new
            // grid; the engine swap invalidated the previous state.
            if (!nodes.editorView.hidden) {
                refreshEditorFromCurrent();
            }
        } catch (e) {
            errorBox.textContent = e.message || "Could not create inventory.";
        }
    });

    return { open: openDialog };
}


/**
 * Build one inventory-source card for the PHOIBLE picker.
 *
 * Layout per row (CSS-driven):
 *
 *   ┌────────────────────────────────────────────┐
 *   │ ◉ SPA                            40 segs   │
 *   │   Stanford Phonology Archive               │
 *   │   <dialect, if present>                    │
 *   └────────────────────────────────────────────┘
 *
 * ``onPick`` is the picker-scoped selection callback (passed in
 * rather than reached via a module global) so cards never grow a
 * hidden dependency on the most-recently-wired picker instance.
 * The radio input is the form-state carrier but the whole row is
 * the click target; ``:has(input:checked)`` in CSS paints the
 * accent border so the dot is a redundant cue, not the only one.
 */
function _buildSourceCard(inv, defaultId, onPick) {
    const radioId = "phoible-radio-" + inv.id;
    const label = document.createElement("label");
    label.className = "phoible-source-card";
    label.htmlFor = radioId;

    const input = document.createElement("input");
    input.type = "radio";
    input.name = "phoible-inventory";
    input.id = radioId;
    input.value = inv.id;
    input.checked = inv.id === defaultId;
    input.addEventListener("change", () => onPick(inv.id));

    const body = document.createElement("div");
    body.className = "phoible-source-body";

    const header = document.createElement("div");
    header.className = "phoible-source-header";
    const name = document.createElement("span");
    name.className = "phoible-source-name";
    name.textContent = inv.source_short;
    const segs = document.createElement("span");
    segs.className = "phoible-source-segs";
    segs.textContent = `${inv.segment_count} segments`;
    header.appendChild(name);
    header.appendChild(segs);
    body.appendChild(header);

    if (inv.source_description) {
        const desc = document.createElement("div");
        desc.className = "phoible-source-desc";
        desc.textContent = inv.source_description;
        body.appendChild(desc);
    }

    if (inv.dialect) {
        const dialect = document.createElement("div");
        dialect.className = "phoible-source-dialect";
        dialect.textContent = inv.dialect;
        body.appendChild(dialect);
    }

    label.appendChild(input);
    label.appendChild(body);
    return label;
}


/**
 * Wire the toolbar's PHOIBLE button and its picker dialog.
 *
 * PHOIBLE is a LOAD path, not a Builder integration: clicking the
 * button opens an inventory picker (search a language, pick a
 * source, see a preview), and submitting swaps the engine to the
 * chosen inventory. After load the inventory belongs to the user:
 * they can rename via the toolbar's pencil, edit in the Builder,
 * and Save As to keep a local copy. The Save flow does not
 * distinguish a PHOIBLE-loaded inventory from any other; a single
 * ``feature_source`` metadata field records provenance but doesn't
 * constrain identity.
 *
 * Lazy-load: the index ships in the Pyodide bundle (~95 KB
 * gzipped), but the 5 MB data payload is fetched on first open
 * via the asset-manifest hashed URL, then injected via
 * ``phoible_load_data``. Re-opens are cheap.
 *
 * The button starts disabled and only enables when the bridge
 * confirms ``phoible_is_available`` (avoids the broken-row case
 * of a stale checkout where the bake never ran).
 */
function wirePhoiblePicker() {
    const button = nodes.phoibleBtn;
    const dialog = nodes.phoiblePicker;
    const form = nodes.phoiblePickerForm;
    const loadBtn = nodes.phoibleLoad;
    const errorBox = nodes.phoibleError;
    const searchInput = nodes.phoibleSearch;

    let selectedInventoryId = null;
    let searchTimer = 0;
    // 150 ms autocomplete debounce. Short enough that the user
    // perceives the dropdown as instant; long enough that a fast
    // typist doesn't trigger a bridge call per keystroke.
    const SEARCH_DEBOUNCE_MS = 150;

    const resetState = () => {
        searchInput.value = "";
        nodes.phoibleResults.hidden = true;
        nodes.phoibleResults.innerHTML = "";
        nodes.phoibleInventories.hidden = true;
        nodes.phoibleRadios.innerHTML = "";
        nodes.phoiblePreview.hidden = true;
        errorBox.textContent = "";
        selectedInventoryId = null;
        loadBtn.disabled = true;
        if (searchTimer) {
            window.clearTimeout(searchTimer);
            searchTimer = 0;
        }
    };

    // Index of the currently keyboard-highlighted entry in the
    // autocomplete dropdown; -1 when nothing is highlighted. Reset
    // every time the result list changes so keystrokes after a
    // new query land on the freshly rendered list, not on the
    // previous (now-gone) row at the same offset.
    let highlightedIndex = -1;

    const setHighlight = (newIndex) => {
        const ul = nodes.phoibleResults;
        const items = ul.children;
        if (!items.length) {
            highlightedIndex = -1;
            return;
        }
        // Clamp + wrap. Letting ArrowDown past the end roll to the
        // top is the convention in dropdown menus; same for
        // ArrowUp past the start.
        if (newIndex < 0) newIndex = items.length - 1;
        if (newIndex >= items.length) newIndex = 0;
        if (highlightedIndex >= 0 && highlightedIndex < items.length) {
            items[highlightedIndex].classList.remove("is-highlighted");
            items[highlightedIndex].setAttribute("aria-selected", "false");
        }
        highlightedIndex = newIndex;
        const el = items[highlightedIndex];
        el.classList.add("is-highlighted");
        el.setAttribute("aria-selected", "true");
        // Scroll into view if the highlighted entry would otherwise
        // be hidden by the ul's overflow cap.
        el.scrollIntoView({ block: "nearest" });
    };

    const renderResults = (matches) => {
        const ul = nodes.phoibleResults;
        ul.innerHTML = "";
        highlightedIndex = -1;
        if (!matches || matches.length === 0) {
            ul.hidden = true;
            return;
        }
        for (const name of matches) {
            const li = document.createElement("li");
            li.textContent = name;
            li.setAttribute("role", "option");
            li.setAttribute("aria-selected", "false");
            li.addEventListener("mousedown", (ev) => {
                // mousedown (not click) so the input does not lose
                // focus before we read the selection.
                ev.preventDefault();
                pickLanguage(name);
            });
            ul.appendChild(li);
        }
        ul.hidden = false;
    };

    const pickLanguage = (languageName) => {
        searchInput.value = languageName;
        nodes.phoibleResults.hidden = true;
        const invs = callBridge("phoible_list_inventories", languageName);
        const radios = nodes.phoibleRadios;
        radios.innerHTML = "";
        if (!invs || invs.length === 0) {
            nodes.phoibleInventories.hidden = true;
            nodes.phoiblePreview.hidden = true;
            selectedInventoryId = null;
            loadBtn.disabled = true;
            return;
        }
        // Default selection: the inventory with the median segment
        // count. Avoids a stray marginal source being the user's
        // first impression. Alphabetical tiebreak is baked into the
        // bridge's list ordering.
        const sorted = invs
            .slice()
            .sort((a, b) => a.segment_count - b.segment_count);
        const defaultId = sorted[Math.floor(sorted.length / 2)].id;
        for (const inv of invs) {
            radios.appendChild(_buildSourceCard(inv, defaultId, pickInventory));
        }
        nodes.phoibleInventories.hidden = false;
        pickInventory(defaultId);
    };

    const pickInventory = (inventoryId) => {
        selectedInventoryId = inventoryId;
        const preview = callBridge("phoible_preview_inventory", inventoryId);
        if (!preview || !preview.descriptor) {
            nodes.phoiblePreview.hidden = true;
            loadBtn.disabled = true;
            return;
        }
        const { descriptor, segments, segment_total, feature_count } = preview;
        nodes.phoibleSummary.textContent =
            `${segment_total} segments · ${feature_count} features`
            + (descriptor.dialect ? ` · ${descriptor.dialect}` : "");
        const ul = nodes.phoibleSegments;
        ul.innerHTML = "";
        for (const sym of segments) {
            const li = document.createElement("li");
            li.textContent = sym;
            ul.appendChild(li);
        }
        if (segments.length < segment_total) {
            const more = document.createElement("li");
            more.textContent = `… +${segment_total - segments.length} more`;
            more.className = "phoible-segments-more";
            ul.appendChild(more);
        }
        nodes.phoiblePreview.hidden = false;
        loadBtn.disabled = false;
    };

    const closeDialog = () => {
        if (typeof dialog.close === "function") {
            dialog.close();
        } else {
            dialog.removeAttribute("open");
        }
    };

    const openDialog = async () => {
        nodes.phoibleLoading.hidden = false;
        nodes.phoibleActive.hidden = true;
        if (typeof dialog.showModal === "function") {
            dialog.showModal();
        } else {
            dialog.setAttribute("open", "");
        }
        resetState();

        // Lazy-load the data payload on first open. The index ships
        // in the bundle, so search + list work pre-load; generate
        // and preview need the data file.
        if (!callBridge("phoible_is_ready")) {
            try {
                const url = assetUrl("phoible_data");
                const resp = await fetch(url);
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const text = await resp.text();
                callBridge("phoible_load_data", text);
            } catch (e) {
                nodes.phoibleLoading.textContent =
                    `Could not load PHOIBLE data: ${e.message || e}`;
                return;
            }
        }
        nodes.phoibleLoading.hidden = true;
        nodes.phoibleActive.hidden = false;
        searchInput.focus();
    };

    // Toolbar wiring. The button gets enabled by the standard
    // BRIDGE_GATED_NODES path after Pyodide attaches; we only
    // check ``phoible_is_available`` lazily here at click time so
    // a stale checkout (no baked index) reports a friendly error
    // instead of crashing the click handler.
    button.addEventListener("click", () => {
        if (!callBridge("phoible_is_available")) {
            // Replace the friendly title in case the bake step
            // never ran.
            button.title = "PHOIBLE data is not available in this build.";
            setStatus("PHOIBLE data is not available in this build.");
            return;
        }
        openDialog();
    });

    // Autocomplete debounce.
    searchInput.addEventListener("input", () => {
        if (searchTimer) {
            window.clearTimeout(searchTimer);
        }
        const query = searchInput.value;
        searchTimer = window.setTimeout(() => {
            const matches = callBridge(
                "phoible_search_languages", query, 20,
            );
            renderResults(matches);
        }, SEARCH_DEBOUNCE_MS);
    });

    // Keyboard navigation for the autocomplete dropdown. ArrowDown
    // and ArrowUp wrap through the result list; Enter picks the
    // highlighted entry (or the first one when nothing is yet
    // highlighted but results are visible); Escape closes the
    // dropdown without committing. Default Tab behaviour is kept
    // so the user can leave the dropdown open and tab to the
    // inventory radios if they prefer.
    searchInput.addEventListener("keydown", (ev) => {
        const ul = nodes.phoibleResults;
        const items = ul.children;
        if (ev.key === "ArrowDown") {
            if (!items.length || ul.hidden) return;
            ev.preventDefault();
            setHighlight(highlightedIndex + 1);
            return;
        }
        if (ev.key === "ArrowUp") {
            if (!items.length || ul.hidden) return;
            ev.preventDefault();
            setHighlight(highlightedIndex - 1);
            return;
        }
        if (ev.key === "Enter") {
            if (ul.hidden || !items.length) return;
            ev.preventDefault();
            const target = highlightedIndex >= 0 ? highlightedIndex : 0;
            pickLanguage(items[target].textContent);
            return;
        }
        if (ev.key === "Escape") {
            if (ul.hidden) return;
            ev.preventDefault();
            ul.hidden = true;
            highlightedIndex = -1;
        }
    });

    nodes.phoibleCancel.addEventListener("click", closeDialog);

    form.addEventListener("submit", (ev) => {
        ev.preventDefault();
        if (!selectedInventoryId) return;
        // Editor-dirty guard: loading a new inventory swaps the
        // engine, which discards any unsaved edits in the Builder.
        // Mirrors the upload + setup-dialog gate.
        if (!nodes.editorView.hidden && editorState.dirty) {
            const ok = confirm(
                "Discard unsaved changes to the current inventory?",
            );
            if (!ok) return;
        }
        try {
            const info = callBridge(
                "load_phoible_inventory", selectedInventoryId,
            );
            applyInventoryInfo(info);
            // Reflect the loaded PHOIBLE inventory in the toolbar
            // dropdown so the user does not see a stale bundled
            // name sitting above the engine state.
            setLoadedSyntheticOption(info.name);
            setStatus(
                `Loaded ${info.name} `
                + `(${info.segments.length} segments, `
                + `${info.features.length} features).`,
            );
            errorBox.textContent = "";
            closeDialog();
            // If the editor is open, re-fetch its grid against the
            // new engine state.
            if (!nodes.editorView.hidden) {
                refreshEditorFromCurrent();
            }
        } catch (e) {
            errorBox.textContent = e.message || "Could not load inventory.";
        }
    });
}


// ----------------------------------------------------------------------
// Builder / editor: web-side state machine.
//
// This section (~main.js:1675-3000) is the second large state machine
// in the file and mirrors the desktop's ``InventoryBuilder``
// (``app/src/phonology_features/gui/builder/window.py``). Strategy:
//
//  * **Pure logic lives in Python** (``grid_logic.py``,
//    ``inventory_setup.py``) and is consumed via the bridge or via
//    constants fetched once at editor open (cycle ladder, value
//    keys, move keys, undo depth cap, add-label validators, remove
//    prompts, max-segments / max-features caps).
//
//  * **DOM mutation, event wiring, selection painting, keyboard
//    dispatch, and undo/redo state live in JS** because per-event
//    bridge hops would lag on rapid shift-drag and keyboard repeat.
//
//  * **Two surfaces that mirror Python logic locally** are
//    parity-tested in ``app/tests/test_jsfallback_parity.py``:
//      - ``classifyEditorSelection`` mirrors
//        ``grid_logic.classify_selection``
//      - ``SELECTION_SHAPE_REMOVE_TARGET`` mirrors
//        ``grid_logic.SELECTION_SHAPE_REMOVE_TARGET``
//    Edit either side and the parity tests catch the drift.
//
// In-memory edit state for the builder editor. Mirrors the desktop
// ``InventoryBuilder``'s ``_segments`` / ``_features`` / table-item
// values, plus selection state, anchor for shift-click range
// extension, focused cell for keyboard fallback, undo/redo stacks
// matching the desktop's ``_BulkEdit`` shape, and a ``dirty`` flag
// the Back / Save-as paths consult. ``cells`` is indexed as
// cells[feature_index][segment_index] to match the engine's
// get_grid_state shape and the shared :py:func:`grid_to_inventory`
// contract.
//
// Undo stack entries mirror ``builder.edits._BulkEdit``:
//   {cells: [{r, c, old}, ...], new: "value"}
const editorState = {
    open: false,
    name: "",
    features: [],
    segments: [],
    cells: [],
    dirty: false,
    selected: new Set(),  // "r,c" keys
    anchor: null,         // {r, c}, used by shift-click range extension
    focused: null,        // {r, c}, fallback target when no selection
    undoStack: [],
    redoStack: [],
};

// Cycle ladder, value-key map, move-key map, and the undo depth
// cap. All fetched from the bridge at the editor's first open;
// the desktop's ``cycle_value`` / ``_VALUE_KEYS`` / ``_MOVE_KEYS``
// / ``_MAX_UNDO_DEPTH`` derive from the same constants, so the
// two frontends stay in lockstep without per-click bridge cost.
let cycleLadder = null;
let valueKeys = null;
let moveKeys = null;
let maxUndoDepth = 200;  // sane default; overwritten on first open
const ZERO_VALUE = "0";

// Baked from phonology_shared.editor.grid via STATUS_TEXT so a
// Python-side glyph edit propagates without a JS change. The
// literal fallbacks keep the file usable when opened raw (without
// the build step) for dev; the baked path is canonical.
const MINUS_DISPLAY = STATUS_TEXT.minus_display || "−"; // U+2212
const MINUS_SERIALIZED = STATUS_TEXT.minus_serialized || "-"; // U+002D

// Cached cell <td> nodes keyed by row index. Populated by
// renderEditorGrid and consulted by selection-paint and bulk-cycle.
// O(1) lookup beats querySelector at the cost of a single 2D array
// rebuild per grid render.
let _cellNodes = [];
// Last-painted selection so repaintSelection only toggles the
// symmetric difference rather than every cell on the page.
let _lastPaintedSelection = new Set();

const cellKey = (r, c) => `${r},${c}`;
const parseCellKey = (key) => {
    const [r, c] = key.split(",").map(Number);
    return { r, c };
};
const cellNode = (r, c) => _cellNodes[r]?.[c] ?? null;

/** Lookup the next value in the ladder, defaulting to "0" for any
 *  value that drifted out of the ladder (defensive; mirrors the
 *  same default in :py:func:`cycle_value`). */
function nextCycleValue(current) {
    if (cycleLadder === null) return ZERO_VALUE;
    return cycleLadder[current] ?? ZERO_VALUE;
}

/** Cell-rendering normalization. The grid always shows U+2212 for
 *  the minus value (typographic symmetry with the plus glyph); the
 *  data-value attribute always carries the ASCII serialized form so
 *  CSS selectors match regardless of how the cell got its value. */
function cellDisplay(value) {
    return value === MINUS_SERIALIZED ? MINUS_DISPLAY : value;
}
function cellSerialized(value) {
    return value === MINUS_DISPLAY ? MINUS_SERIALIZED : value;
}

/**
 * Wire the builder editor. Mirrors the desktop ``InventoryBuilder``
 * window:
 *
 * * Main toolbar's "Builder" button opens the editor.
 * * Inside the editor, "New" opens the setup dialog (same dialog
 *   the desktop builder's New button shows).
 * * "Save as..." commits the current grid through
 *   commit_inventory_from_grid then triggers a download.
 * * "Back" closes the editor; if there are unsaved edits, the user
 *   is prompted to discard or stay (matches the desktop's
 *   ``_check_unsaved`` guard).
 * * The name field commits on change/Enter, going through the same
 *   rename_current_inventory bridge as the main toolbar's pencil.
 * * Plain click on an UNSELECTED cell selects just that cell. Plain
 *   click on a SELECTED cell bulk-cycles every selected cell to the
 *   clicked cell's next value. Matches desktop's
 *   ``_BulkCycleTable.mousePressEvent``.
 * * Shift-click extends the selection from the anchor as a rectangle.
 * * Ctrl/Cmd-click toggles individual cells in and out of the
 *   selection.
 * * Column / row headers select their column / row; second click
 *   on the same header clears the selection. Corner cell toggles
 *   select-all.
 * * Keyboard: Space bulk-cycles the selection (or the focused
 *   cell), 1/2/3/0 set the value directly (via the shared
 *   :py:data:`VALUE_KEYS` mapping), Esc clears the selection.
 */
function wireBuilderEditor(setupDialog) {
    const openEditor = () => {
        if (cycleLadder === null) {
            // First open: fetch the shared constants once.
            cycleLadder = callBridge("get_cycle_ladder");
            valueKeys = callBridge("get_value_keys");
            moveKeys = callBridge("get_move_keys");
            maxUndoDepth = callBridge("get_max_undo_depth");
        }
        // Reveal the view BEFORE we render & measure. The alignment
        // pass at the end of renderEditorGrid reads offsetWidth on the
        // four panes; while the view is ``hidden`` everything inside
        // it has zero width, so colgroup widths would be computed as
        // 0 and the grid would render flat. Both operations run
        // synchronously, so the user never sees a flash of the empty
        // pre-render frame.
        editorState.open = true;
        nodes.editorView.hidden = false;
        setMainChromeInert(true);
        refreshEditorFromCurrent();
        nodes.editorGridScroll.focus();
    };
    const closeEditor = () => {
        if (editorState.dirty
            && !confirm("Discard unsaved changes to the inventory?")) {
            return;
        }
        editorState.open = false;
        editorState.dirty = false;
        clearSelection();
        editorState.undoStack.length = 0;
        editorState.redoStack.length = 0;
        nodes.editorView.hidden = true;
        setMainChromeInert(false);
    };

    nodes.builderBtn.addEventListener("click", openEditor);
    nodes.editorExitBtn.addEventListener("click", closeEditor);
    nodes.editorNewBtn.addEventListener("click", setupDialog.open);
    nodes.editorSaveAsBtn.addEventListener("click", commitAndDownload);

    // Name commits on Enter or focus loss via the "change" event.
    // Local rename only; engine swap happens on Save-as alongside
    // the cell commits so a typed-then-cancelled rename does not
    // mutate the engine.
    nodes.editorNameInput.addEventListener("change", () => {
        const newName = nodes.editorNameInput.value;
        if (newName === editorState.name) return;
        editorState.name = newName;
        markEditorDirty();
        setEditorStatus(
            "Name will apply on Save as... (Back to discard).",
        );
    });

    // Single bubbled handler at the frame root. Resolves the target
    // (<td>, column <th>, row <th>, corner) inside any of the four panes.
    nodes.editorGridScroll.addEventListener("mousedown", onGridMouseDown);
    nodes.editorGridScroll.addEventListener("keydown", onGridKeyDown);
    // Scroll sync: the data pane is the scroll source; the column-
    // and row-header panes mirror its scrollLeft/scrollTop so the
    // headers track the viewport without overlaying the data.
    nodes.editorGridData.addEventListener("scroll", () => {
        nodes.editorGridCols.scrollLeft = nodes.editorGridData.scrollLeft;
        nodes.editorGridRows.scrollTop = nodes.editorGridData.scrollTop;
    });
    // The data pane has overflow:auto (so it shows scrollbars when
    // content overflows). The col/row-header panes are overflow:hidden
    // (no scrollbars). On platforms with classic scrollbars (Windows,
    // most Linux), the data pane's vertical scrollbar eats ~15px from
    // its viewport while the cols pane keeps the full width.
    // Scrollbar-gutter compensation: when the data pane shows a
    // scrollbar, the header panes need a matching transparent
    // border to keep their viewport aligned. The actual
    // application happens per-render in ``_alignHeaderPanesToData``
    // (gated on observed scrollbar presence) so the rows pane
    // doesn't carry a phantom bottom border when no horizontal
    // scrollbar is visible. That border was clipping the last
    // row label with a panel-coloured stripe.

    // +/− Segment / Feature buttons.
    nodes.editorAddSegBtn.addEventListener("click", () => {
        labelPrompt({
            title: "Add segment",
            label: "Segment symbol (IPA):",
            submitLabel: "Add",
            bridgeEndpoint: "validate_segment_label",
            existing: editorState.segments,
            onAccept: addSegmentToState,
        });
    });
    nodes.editorAddFeatBtn.addEventListener("click", () => {
        labelPrompt({
            title: "Add feature",
            label: "Feature name:",
            submitLabel: "Add",
            bridgeEndpoint: "validate_feature_label",
            existing: editorState.features,
            onAccept: addFeatureToState,
        });
    });
    nodes.editorRemoveSegBtn.addEventListener("click", removeSelectedSegment);
    nodes.editorRemoveFeatBtn.addEventListener("click", removeSelectedFeature);

    // Browser-level unsaved-changes guard for refresh / tab close.
    window.addEventListener("beforeunload", (ev) => {
        if (!editorState.dirty) return;
        ev.preventDefault();
        ev.returnValue = "";
    });
}

/**
 * Pull the active engine's grid state through the bridge and adopt
 * it as the editor's edit state. Called on editor open and after
 * any action that swaps the engine (New dialog, Save-as commit).
 */
function refreshEditorFromCurrent() {
    let snapshot;
    try {
        snapshot = callBridge("get_grid_state");
    } catch (e) {
        setEditorStatus(`Could not load grid: ${e.message}`);
        return;
    }
    editorState.name = snapshot.name;
    editorState.features = snapshot.features.slice();
    editorState.segments = snapshot.segments.slice();
    editorState.cells = snapshot.cells.map((row) => row.slice());
    editorState.dirty = false;
    // Drop undo history: edits recorded against the previous shape
    // refer to row/col indices that may no longer match the new
    // table. Matches the desktop's ``_rebuild_table`` discipline.
    editorState.undoStack.length = 0;
    editorState.redoStack.length = 0;
    clearSelection();
    editorState.focused = editorState.cells.length > 0
        && editorState.cells[0].length > 0
        ? { r: 0, c: 0 }
        : null;
    nodes.editorNameInput.value = editorState.name;
    nodes.editorFileLabel.textContent = "(unsaved)";
    renderEditorGrid();
    repaintFocused();
    setEditorStatus(
        `${editorState.segments.length} segments × `
        + `${editorState.features.length} features. `
        + "Click a cell to select; click again to cycle. "
        + "Shift-click for range, Ctrl-click to toggle.",
    );
}

/**
 * Render the editor grid from ``editorState``. Rows are features,
 * columns are segments. Stores per-cell ``<td>`` nodes in
 * ``_cellNodes`` for O(1) lookup from the selection model and
 * paint paths. Headers get ``data-col`` / ``data-row`` so the
 * bubbled click handler can resolve them without DOM walking.
 */
function renderEditorGrid() {
    const { features, segments, cells } = editorState;
    _cellNodes = [];
    _lastPaintedSelection = new Set();
    // Re-render discards previous DOM nodes; the cached focus
    // pointer is now stale. Null it so the next repaintFocused
    // does not try to remove a class from a detached node.
    _lastFocusedCell = null;

    // Corner pane: single-cell select-all toggle. Always rendered
    // so the pane reserves its grid track even when the grid is empty.
    const cornerTable = document.createElement("table");
    cornerTable.className = "editor-grid";
    const cornerBody = document.createElement("tbody");
    const cornerRow = document.createElement("tr");
    const cornerCell = document.createElement("th");
    cornerCell.dataset.corner = "true";
    cornerCell.setAttribute("aria-label", "Select all");
    cornerRow.appendChild(cornerCell);
    cornerBody.appendChild(cornerRow);
    cornerTable.appendChild(cornerBody);
    nodes.editorGridCorner.replaceChildren(cornerTable);

    // Column headers pane.
    const colsTable = document.createElement("table");
    colsTable.className = "editor-grid";
    const colsBody = document.createElement("tbody");
    const colsRow = document.createElement("tr");
    for (let c = 0; c < segments.length; c++) {
        const th = document.createElement("th");
        th.scope = "col";
        th.textContent = segments[c];
        th.dataset.col = String(c);
        colsRow.appendChild(th);
    }
    colsBody.appendChild(colsRow);
    colsTable.appendChild(colsBody);
    nodes.editorGridCols.replaceChildren(colsTable);

    // Row headers pane.
    const rowsTable = document.createElement("table");
    rowsTable.className = "editor-grid";
    const rowsBody = document.createElement("tbody");
    for (let r = 0; r < features.length; r++) {
        const tr = document.createElement("tr");
        const th = document.createElement("th");
        th.scope = "row";
        th.textContent = features[r];
        th.dataset.row = String(r);
        tr.appendChild(th);
        rowsBody.appendChild(tr);
    }
    rowsTable.appendChild(rowsBody);
    nodes.editorGridRows.replaceChildren(rowsTable);

    // Data pane.
    const dataTable = document.createElement("table");
    dataTable.className = "editor-grid";
    const dataBody = document.createElement("tbody");
    for (let r = 0; r < features.length; r++) {
        const rowNodes = [];
        const tr = document.createElement("tr");
        for (let c = 0; c < segments.length; c++) {
            const td = document.createElement("td");
            td.dataset.row = String(r);
            td.dataset.col = String(c);
            paintCell(td, cells[r][c]);
            tr.appendChild(td);
            rowNodes.push(td);
        }
        dataBody.appendChild(tr);
        _cellNodes.push(rowNodes);
    }
    dataTable.appendChild(dataBody);
    nodes.editorGridData.replaceChildren(dataTable);

    // Match header column widths to data column widths and header
    // row heights to data row heights. Cell content drives the data
    // pane's natural sizing; the column-headers and row-headers
    // panes get explicit pixel sizes so they line up with it.
    _alignHeaderPanesToData();
}

/** Probe the rendered scrollbar width once. Returns 0 on platforms
 *  that use overlay scrollbars (macOS default, headless Chromium),
 *  positive pixel value on classic-scrollbar platforms. */
function _measureScrollbarWidth() {
    const probe = document.createElement("div");
    probe.style.cssText =
        "position:absolute;top:-9999px;left:-9999px;width:100px;"
        + "height:100px;overflow:scroll;visibility:hidden";
    document.body.appendChild(probe);
    const w = probe.offsetWidth - probe.clientWidth;
    probe.remove();
    return w;
}

/** Make all four panes share one grid. Each column gets the max of
 *  (data column natural width, header column natural width); we
 *  install a ``<colgroup>`` of explicit widths on BOTH the cols-pane
 *  and data-pane tables and switch them to ``table-layout: fixed``,
 *  which is the only reliable way to make two separate tables share
 *  column widths; setting ``style.width`` on individual cells is
 *  treated as a hint and ignored when other cells in the column are
 *  narrower. Without this, an IPA digraph like ``t͡ʃ`` expands its
 *  header cell past the 32px min-width while the data cell below
 *  stays at 32px, drifting every subsequent column out of alignment.
 *  Row heights are simpler: explicit ``<tr>.style.height`` works in
 *  both layout modes. Called after each render. */
function _alignHeaderPanesToData() {
    const dataTable = nodes.editorGridData.querySelector("table");
    if (!dataTable) return;
    const colsTable = nodes.editorGridCols.querySelector("table");
    // Tear down any prior colgroup / fixed layout so we re-measure
    // natural widths after a segment add / remove / rename.
    dataTable.style.tableLayout = "";
    if (colsTable) colsTable.style.tableLayout = "";
    dataTable.querySelectorAll("colgroup").forEach((c) => c.remove());
    colsTable?.querySelectorAll("colgroup").forEach((c) => c.remove());
    void dataTable.offsetWidth;

    const firstRow = dataTable.querySelector("tr");
    const colHeaders = nodes.editorGridCols.querySelectorAll("th");
    const dataCells = firstRow ? firstRow.querySelectorAll("td") : [];
    const widths = [];
    const n = Math.min(colHeaders.length, dataCells.length);
    for (let c = 0; c < n; c++) {
        widths.push(Math.max(dataCells[c].offsetWidth, colHeaders[c].offsetWidth));
    }
    const makeColgroup = () => {
        const cg = document.createElement("colgroup");
        for (const w of widths) {
            const col = document.createElement("col");
            col.style.width = `${w}px`;
            cg.appendChild(col);
        }
        return cg;
    };
    if (widths.length) {
        dataTable.insertBefore(makeColgroup(), dataTable.firstChild);
        if (colsTable) {
            colsTable.insertBefore(makeColgroup(), colsTable.firstChild);
        }
        // ``table-layout: fixed`` honors colgroup widths only when the
        // table itself has an explicit width; without one Chrome falls
        // back to the cells' min-width floor and the colgroup is
        // ignored. Set the table width to the column-sum so both
        // tables resolve to the same pixel grid.
        const totalWidth = widths.reduce((a, b) => a + b, 0);
        dataTable.style.tableLayout = "fixed";
        dataTable.style.width = `${totalWidth}px`;
        if (colsTable) {
            colsTable.style.tableLayout = "fixed";
            colsTable.style.width = `${totalWidth}px`;
        }
        // Belt-and-braces: also stamp the width on the first row's
        // cells so any caller that re-measures cell widths gets the
        // post-alignment value, not the min-width floor.
        for (let c = 0; c < widths.length; c++) {
            const px = `${widths[c]}px`;
            if (dataCells[c]) dataCells[c].style.width = px;
            if (colHeaders[c]) colHeaders[c].style.width = px;
        }
    }

    const rowHeaders = nodes.editorGridRows.querySelectorAll("tr");
    const dataRows = dataTable.querySelectorAll("tr");
    for (const tr of rowHeaders) tr.style.height = "";
    for (const tr of dataRows) tr.style.height = "";
    void dataTable.offsetHeight;
    for (let r = 0; r < rowHeaders.length && r < dataRows.length; r++) {
        const h = Math.max(dataRows[r].offsetHeight, rowHeaders[r].offsetHeight);
        const px = `${h}px`;
        rowHeaders[r].style.height = px;
        dataRows[r].style.height = px;
    }

    // Apply scrollbar-gutter compensation conditionally on the
    // data pane's ACTUAL scrollbar visibility. The previous
    // implementation stamped both borders unconditionally at
    // ``wireBuilderEditor`` time, leaving a phantom panel-coloured
    // stripe at the bottom of the rows pane that clipped the last
    // row label whenever no horizontal scrollbar was visible.
    // Recomputed after every render because adding / removing a
    // segment can flip either scrollbar's visibility.
    const sbw = _measureScrollbarWidth();
    const dp = nodes.editorGridData;
    const hasVScroll = sbw > 0 && dp.scrollHeight > dp.clientHeight;
    const hasHScroll = sbw > 0 && dp.scrollWidth > dp.clientWidth;
    nodes.editorGridCols.style.borderRight = hasVScroll
        ? `${sbw}px solid transparent`
        : "";
    nodes.editorGridRows.style.borderBottom = hasHScroll
        ? `${sbw}px solid transparent`
        : "";
}

/** Paint a single cell from its raw value (display or serialized
 *  minus both accepted). Used by both the full render and the
 *  click-to-cycle path so the visual is consistent. */
function paintCell(td, rawValue) {
    td.textContent = cellDisplay(rawValue);
    td.dataset.value = cellSerialized(rawValue);
}

/** Mark the edit state dirty, updating the file-label indicator
 *  exactly once on the first edit so the toggle is cheap. */
function markEditorDirty() {
    if (editorState.dirty) return;
    editorState.dirty = true;
    nodes.editorFileLabel.textContent = "(modified)";
}

// Selection model ------------------------------------------------------

function clearSelection() {
    editorState.selected.clear();
    editorState.anchor = null;
    repaintSelection();
}

function selectSingleCell(r, c) {
    editorState.selected.clear();
    editorState.selected.add(cellKey(r, c));
    editorState.anchor = { r, c };
    editorState.focused = { r, c };
    repaintSelection();
    repaintFocused();
}

function extendSelectionTo(r, c) {
    if (editorState.anchor === null) {
        selectSingleCell(r, c);
        return;
    }
    const { r: ar, c: ac } = editorState.anchor;
    const r0 = Math.min(ar, r);
    const r1 = Math.max(ar, r);
    const c0 = Math.min(ac, c);
    const c1 = Math.max(ac, c);
    editorState.selected.clear();
    for (let i = r0; i <= r1; i++) {
        for (let j = c0; j <= c1; j++) {
            editorState.selected.add(cellKey(i, j));
        }
    }
    editorState.focused = { r, c };
    repaintSelection();
    repaintFocused();
}

function toggleCellSelection(r, c) {
    const k = cellKey(r, c);
    if (editorState.selected.has(k)) {
        editorState.selected.delete(k);
    } else {
        editorState.selected.add(k);
    }
    // Anchor advances to the toggled cell so a follow-up shift-click
    // extends from this position (matches Qt's QTableWidget behavior).
    editorState.anchor = { r, c };
    editorState.focused = { r, c };
    repaintSelection();
    repaintFocused();
}

function selectColumn(c) {
    const numRows = editorState.features.length;
    editorState.selected.clear();
    for (let r = 0; r < numRows; r++) {
        editorState.selected.add(cellKey(r, c));
    }
    editorState.anchor = { r: 0, c };
    editorState.focused = { r: 0, c };
    repaintSelection();
    // Update the focus indicator so the dashed outline lands on a
    // cell in the new column (the anchor for subsequent shift+arrow
    // extension). Without this the previously-focused cell would
    // keep its outline even though logical focus moved here.
    repaintFocused();
}

function selectRow(r) {
    const numCols = editorState.segments.length;
    editorState.selected.clear();
    for (let c = 0; c < numCols; c++) {
        editorState.selected.add(cellKey(r, c));
    }
    editorState.anchor = { r, c: 0 };
    editorState.focused = { r, c: 0 };
    repaintSelection();
    repaintFocused();
}

function selectAll() {
    const numRows = editorState.features.length;
    const numCols = editorState.segments.length;
    editorState.selected.clear();
    for (let r = 0; r < numRows; r++) {
        for (let c = 0; c < numCols; c++) {
            editorState.selected.add(cellKey(r, c));
        }
    }
    editorState.anchor = { r: 0, c: 0 };
    editorState.focused = { r: 0, c: 0 };
    repaintSelection();
    repaintFocused();
}

/** Diff-based selection repaint: toggle .is-selected only on cells
 *  whose membership actually changed. O(symmetric difference) per
 *  selection change, not O(grid size). Also refreshes the
 *  remove-segment / remove-feature button enabled states so they
 *  reflect the current selection shape. */
function repaintSelection() {
    for (const key of _lastPaintedSelection) {
        if (editorState.selected.has(key)) continue;
        const { r, c } = parseCellKey(key);
        cellNode(r, c)?.classList.remove("is-selected");
    }
    for (const key of editorState.selected) {
        if (_lastPaintedSelection.has(key)) continue;
        const { r, c } = parseCellKey(key);
        cellNode(r, c)?.classList.add("is-selected");
    }
    _lastPaintedSelection = new Set(editorState.selected);
    updateRemoveButtonStates();
}

/**
 * Classify the current selection by shape. Mirrors the shared
 * Python :py:func:`grid_logic.classify_selection`; both editors
 * must produce the same shape for the same selection so the
 * ``− Segment`` / ``− Feature`` enable rules stay in lockstep.
 *
 * Inlined in JS rather than called via the bridge because every
 * selection change (shift+drag, header click) fires this; a
 * per-call Pyodide bridge hop would add visible lag on rapid drags.
 * The Python tests in app/tests/test_grid_logic.py pin the shape
 * contract; if a desktop / web divergence ever surfaces it would
 * land here.
 *
 * Returns ``"empty" | "single_cell" | "single_column" |
 *           "single_row" | "full_grid" | "rectangle" | "irregular"``
 * along with the row / column indices when the shape names one.
 */
function classifyEditorSelection() {
    const numRows = editorState.features.length;
    const numCols = editorState.segments.length;
    const sel = editorState.selected;
    const n = sel.size;
    if (n === 0) return { kind: "empty" };
    if (n === 1) {
        const { r, c } = parseCellKey(sel.values().next().value);
        return { kind: "single_cell", row: r, column: c };
    }
    let theCol = null;
    let theRow = null;
    let sameCol = true;
    let sameRow = true;
    let rMin = Infinity, rMax = -Infinity, cMin = Infinity, cMax = -Infinity;
    for (const key of sel) {
        const { r, c } = parseCellKey(key);
        if (theCol === null) theCol = c;
        else if (c !== theCol) sameCol = false;
        if (theRow === null) theRow = r;
        else if (r !== theRow) sameRow = false;
        if (r < rMin) rMin = r;
        if (r > rMax) rMax = r;
        if (c < cMin) cMin = c;
        if (c > cMax) cMax = c;
    }
    if (numRows > 0 && sameCol && n === numRows) {
        return { kind: "single_column", column: theCol };
    }
    if (numCols > 0 && sameRow && n === numCols) {
        return { kind: "single_row", row: theRow };
    }
    if (numRows > 0 && numCols > 0 && n === numRows * numCols) {
        return { kind: "full_grid" };
    }
    const rectSize = (rMax - rMin + 1) * (cMax - cMin + 1);
    if (n === rectSize) return { kind: "rectangle" };
    return { kind: "irregular" };
}

/** Resolve the column / row indices for the "single column" /
 *  "single row" shapes so the remove handlers can grab them. */
function getSingleSelectedColumn() {
    const shape = classifyEditorSelection();
    return shape.kind === "single_column" ? shape.column : null;
}
function getSingleSelectedRow() {
    const shape = classifyEditorSelection();
    return shape.kind === "single_row" ? shape.row : null;
}

/** Map a selection shape to which remove button (if any) should
 *  be enabled. Mirrors the shared Python
 *  :py:data:`SELECTION_SHAPE_REMOVE_TARGET` table. */
const SELECTION_SHAPE_REMOVE_TARGET = Object.freeze({
    "single_column": "segment",
    "single_row": "feature",
});

function updateRemoveButtonStates() {
    const shape = classifyEditorSelection();
    const target = SELECTION_SHAPE_REMOVE_TARGET[shape.kind] ?? null;
    nodes.editorRemoveSegBtn.disabled = target !== "segment";
    nodes.editorRemoveFeatBtn.disabled = target !== "feature";
}

// Keyboard focus indicator -------------------------------------------

// Last-painted focused cell, kept as a separate handle so the
// repaint can clear the previous mark without scanning every cell.
let _lastFocusedCell = null;

function repaintFocused() {
    if (_lastFocusedCell !== null) {
        cellNode(_lastFocusedCell.r, _lastFocusedCell.c)
            ?.classList.remove("is-focused");
    }
    const f = editorState.focused;
    if (f !== null) {
        cellNode(f.r, f.c)?.classList.add("is-focused");
    }
    _lastFocusedCell = f === null ? null : { r: f.r, c: f.c };
}

// Edit primitive -----------------------------------------------------

/**
 * Apply ``value`` to every ``(r, c)`` in ``targets``, capture the
 * previous values, and push the batch onto the undo stack. Skips
 * cells whose value is already ``value`` (cheap no-op). Marks the
 * edit state dirty when at least one cell actually changed.
 *
 * Single source of truth for in-editor cell mutations: every path
 * that writes cell values goes through here so undo / redo see
 * every change in the same shape. Mirrors the desktop's
 * ``_BulkEdit`` lifecycle (commit + push + cap).
 */
function commitEdit(targets, value) {
    const cells = [];
    const normalizedNew = cellSerialized(value);
    for (const { r, c } of targets) {
        const cur = editorState.cells[r][c];
        if (cellSerialized(cur) === normalizedNew) continue;
        cells.push({ r, c, old: cur });
        editorState.cells[r][c] = value;
        paintCell(cellNode(r, c), value);
    }
    if (cells.length === 0) return;
    pushUndoEdit({ cells, new: value });
    markEditorDirty();
}

function pushUndoEdit(edit) {
    editorState.undoStack.push(edit);
    if (editorState.undoStack.length > maxUndoDepth) {
        editorState.undoStack.shift();
    }
    // New edit invalidates any redo history; same convention as
    // most editors (no redo into a divergent timeline).
    editorState.redoStack.length = 0;
}

function applyEdit(edit, useOld) {
    for (const { r, c, old } of edit.cells) {
        const value = useOld ? old : edit.new;
        editorState.cells[r][c] = value;
        paintCell(cellNode(r, c), value);
    }
}

// Both UIs read these status templates from STATUS_TEXT (baked
// from shared/render/mode_logic.py) so the desktop and web
// builders surface byte-identical wording on undo / redo / add /
// remove. Fallbacks mirror the Python literals.
function _pluralS(n) {
    return n === 1 ? "" : "s";
}

function _formatTpl(key, fallback, vars) {
    let tpl = STATUS_TEXT[key] || fallback;
    for (const [name, value] of Object.entries(vars)) {
        tpl = tpl.split(`{${name}}`).join(String(value));
    }
    return tpl;
}

function undo() {
    const edit = editorState.undoStack.pop();
    if (edit === undefined) {
        setEditorStatus(STATUS_TEXT.undo_nothing_message || "Nothing to undo.");
        return;
    }
    applyEdit(edit, true);
    editorState.redoStack.push(edit);
    markEditorDirty();
    const n = edit.cells.length;
    setEditorStatus(_formatTpl(
        "undid_template",
        "Undid {n} cell change{plural}.",
        { n, plural: _pluralS(n) },
    ));
}

function redo() {
    const edit = editorState.redoStack.pop();
    if (edit === undefined) {
        setEditorStatus(STATUS_TEXT.redo_nothing_message || "Nothing to redo.");
        return;
    }
    applyEdit(edit, false);
    editorState.undoStack.push(edit);
    markEditorDirty();
    const n = edit.cells.length;
    setEditorStatus(_formatTpl(
        "redid_template",
        "Redid {n} cell change{plural}.",
        { n, plural: _pluralS(n) },
    ));
}

// Mouse handling -------------------------------------------------------

/**
 * Dispatch a mousedown inside the grid table to the right handler.
 * Distinguishes:
 *
 * * Corner cell (data-corner): select-all toggle.
 * * Column header (data-col on a <th>): select that column.
 * * Row header (data-row on a <th>): select that row.
 * * Cell (<td> with data-row + data-col): apply selection-and-cycle
 *   logic per :py:meth:`_BulkCycleTable.mousePressEvent` semantics.
 */
function onGridMouseDown(ev) {
    if (ev.button !== 0) return;
    const target = ev.target;
    if (!(target instanceof HTMLElement)) return;
    if (!nodes.editorGridScroll.contains(target)) return;
    const th = target.closest("th");
    if (th !== null) {
        ev.preventDefault();
        if (th.dataset.corner) {
            onCornerClicked();
            return;
        }
        if (th.dataset.col !== undefined) {
            const col = Number.parseInt(th.dataset.col, 10);
            onColumnHeaderClicked(col, ev);
            return;
        }
        if (th.dataset.row !== undefined) {
            const row = Number.parseInt(th.dataset.row, 10);
            onRowHeaderClicked(row, ev);
            return;
        }
        return;
    }
    const td = target.closest("td");
    if (td === null) return;
    const r = Number.parseInt(td.dataset.row, 10);
    const c = Number.parseInt(td.dataset.col, 10);
    if (Number.isNaN(r) || Number.isNaN(c)) return;
    ev.preventDefault();
    nodes.editorGridScroll.focus();
    onCellClicked(r, c, ev);
}

function onCellClicked(r, c, ev) {
    if (ev.shiftKey) {
        extendSelectionTo(r, c);
        return;
    }
    if (ev.ctrlKey || ev.metaKey) {
        toggleCellSelection(r, c);
        return;
    }
    // Plain click. The desktop rule (see ``_BulkCycleTable``):
    // click on a selected cell -> bulk-cycle; click on an unselected
    // cell -> select that cell (no cycle on the selecting click).
    if (editorState.selected.has(cellKey(r, c))) {
        const next = nextCycleValue(editorState.cells[r][c]);
        commitEdit(selectionTargets(), next);
        return;
    }
    selectSingleCell(r, c);
}

/** Cells targeted by selection-aware operations (value keys, bulk
 *  cycle). Returns the selection if non-empty, else the focused
 *  cell as a single-element list, else empty. */
function selectionTargets() {
    if (editorState.selected.size > 0) {
        return [...editorState.selected].map(parseCellKey);
    }
    if (editorState.focused !== null) {
        return [editorState.focused];
    }
    return [];
}

/** Toggle a single column's selection. Matches the desktop's
 *  ``_on_col_header_clicked``: first click selects the column,
 *  second click on the same column clears.
 */
function onColumnHeaderClicked(c, ev) {
    // Shift+click extends the column selection from the anchor's
    // column to the clicked one (full columns inclusive). Mirrors
    // Qt's QTableWidget native shift-on-header behavior the
    // desktop gets for free.
    if (ev?.shiftKey && editorState.anchor !== null) {
        extendSelectionToColumn(c);
        return;
    }
    // Plain click on the already-selected column: toggle off.
    const numRows = editorState.features.length;
    const isAlreadyColumn = editorState.selected.size === numRows
        && [...editorState.selected].every((k) => {
            const { c: kc } = parseCellKey(k);
            return kc === c;
        });
    if (isAlreadyColumn) {
        clearSelection();
        return;
    }
    selectColumn(c);
}

function onRowHeaderClicked(r, ev) {
    if (ev?.shiftKey && editorState.anchor !== null) {
        extendSelectionToRow(r);
        return;
    }
    const numCols = editorState.segments.length;
    const isAlreadyRow = editorState.selected.size === numCols
        && [...editorState.selected].every((k) => {
            const { r: kr } = parseCellKey(k);
            return kr === r;
        });
    if (isAlreadyRow) {
        clearSelection();
        return;
    }
    selectRow(r);
}

/** Extend the selection to span full columns from the anchor's
 *  column to ``targetCol``. New selection = every cell in those
 *  columns. Focus / anchor move to ``targetCol`` so subsequent
 *  shift+click extends from there.
 */
function extendSelectionToColumn(targetCol) {
    const numRows = editorState.features.length;
    if (numRows === 0) return;
    const anchorCol = editorState.anchor?.c ?? targetCol;
    const c0 = Math.min(anchorCol, targetCol);
    const c1 = Math.max(anchorCol, targetCol);
    editorState.selected.clear();
    for (let c = c0; c <= c1; c++) {
        for (let r = 0; r < numRows; r++) {
            editorState.selected.add(cellKey(r, c));
        }
    }
    editorState.anchor = { r: 0, c: anchorCol };
    editorState.focused = { r: 0, c: targetCol };
    repaintSelection();
    repaintFocused();
}

function extendSelectionToRow(targetRow) {
    const numCols = editorState.segments.length;
    if (numCols === 0) return;
    const anchorRow = editorState.anchor?.r ?? targetRow;
    const r0 = Math.min(anchorRow, targetRow);
    const r1 = Math.max(anchorRow, targetRow);
    editorState.selected.clear();
    for (let r = r0; r <= r1; r++) {
        for (let c = 0; c < numCols; c++) {
            editorState.selected.add(cellKey(r, c));
        }
    }
    editorState.anchor = { r: anchorRow, c: 0 };
    editorState.focused = { r: targetRow, c: 0 };
    repaintSelection();
    repaintFocused();
}

/** Desktop ``_on_corner_clicked``: select-all when nothing is fully
 *  selected, clear when everything is. */
function onCornerClicked() {
    const total = editorState.features.length * editorState.segments.length;
    if (total > 0 && editorState.selected.size === total) {
        clearSelection();
    } else {
        selectAll();
    }
}

// Keyboard handling ----------------------------------------------------

/**
 * Editor keydown router. Mirrors the desktop ``_handle_table_key``:
 *
 * * Ctrl/Cmd+Z = undo, Ctrl/Cmd+Shift+Z or Ctrl/Cmd+Y = redo.
 * * Space cycles the selection (or focused cell).
 * * 1/2/3/0 set the value via the shared :py:data:`VALUE_KEYS`.
 * * h/j/k/l and 4/5/6/8 move the focused cell via the shared
 *   :py:data:`MOVE_KEYS`.
 * * Esc clears the selection.
 */
function onGridKeyDown(ev) {
    if (ev.ctrlKey || ev.metaKey) {
        // Modifier-bound shortcuts; check these first so plain-key
        // handlers below don't fire on Ctrl-1 etc.
        const lower = ev.key.toLowerCase();
        if (lower === "z" && ev.shiftKey) {
            ev.preventDefault();
            redo();
            return;
        }
        if (lower === "z") {
            ev.preventDefault();
            undo();
            return;
        }
        if (lower === "y") {
            ev.preventDefault();
            redo();
            return;
        }
        return;
    }
    if (ev.key === "Escape") {
        ev.preventDefault();
        clearSelection();
        return;
    }
    if (ev.key === " " || ev.key === "Spacebar") {
        ev.preventDefault();
        bulkCycleFromFocused();
        return;
    }
    if (valueKeys !== null && Object.hasOwn(valueKeys, ev.key)) {
        ev.preventDefault();
        applyValueToSelection(valueKeys[ev.key]);
        return;
    }
    if (moveKeys !== null && Object.hasOwn(moveKeys, ev.key)) {
        ev.preventDefault();
        if (ev.shiftKey) {
            extendSelectionInDirection(moveKeys[ev.key]);
        } else {
            moveFocused(moveKeys[ev.key]);
        }
    }
}

/** Move the focused cell by ``(dr, dc)``, clamping at the grid
 *  edges. Arrowing past the top edge selects the current column;
 *  past the left edge selects the current row, the same hit as clicking
 *  the corresponding header. Within the cell grid, mirrors the
 *  desktop's clamped navigation in :py:meth:`_handle_table_key`,
 *  which routes through ``QTableWidget.setCurrentCell`` and that
 *  call clears the prior selection and selects the new cell alone. */
function moveFocused([dr, dc]) {
    const numRows = editorState.features.length;
    const numCols = editorState.segments.length;
    if (numRows === 0 || numCols === 0) return;
    const cur = editorState.focused ?? { r: 0, c: 0 };
    const r = cur.r + dr;
    const c = cur.c + dc;
    if (r < 0 && c >= 0 && c < numCols) {
        selectColumn(c);
        return;
    }
    if (c < 0 && r >= 0 && r < numRows) {
        selectRow(r);
        return;
    }
    const newR = Math.max(0, Math.min(numRows - 1, r));
    const newC = Math.max(0, Math.min(numCols - 1, c));
    selectSingleCell(newR, newC);
    cellNode(newR, newC)?.scrollIntoView({
        block: "nearest", inline: "nearest",
    });
}

/** Shift+Arrow extension: move the focused cell by ``(dr, dc)``
 *  and grow the selection rectangle from the anchor to the new
 *  focused cell. Mirrors Qt's QTableWidget shift+arrow handling
 *  which the desktop delegates to natively. The web side reaches
 *  the same end state by routing through :py:func:`extendSelectionTo`. */
function extendSelectionInDirection([dr, dc]) {
    const target = _clampMoveTarget(dr, dc);
    if (target === null) return;
    // First shift+arrow with no prior anchor: treat the current
    // focused cell as the anchor so the rectangle has somewhere to
    // grow from. Matches Qt's "no current selection -> start one"
    // behavior on shift+arrow.
    if (editorState.anchor === null) {
        const seed = editorState.focused ?? { r: 0, c: 0 };
        editorState.anchor = seed;
    }
    extendSelectionTo(target.r, target.c);
    cellNode(target.r, target.c)?.scrollIntoView({
        block: "nearest", inline: "nearest",
    });
}

/** Resolve the (dr, dc) step into a clamped (r, c) target, or
 *  null if the grid is empty. Shared by plain-move and
 *  shift-extend so both clamp identically. */
function _clampMoveTarget(dr, dc) {
    const numRows = editorState.features.length;
    const numCols = editorState.segments.length;
    if (numRows === 0 || numCols === 0) return null;
    const cur = editorState.focused ?? { r: 0, c: 0 };
    const r = Math.max(0, Math.min(numRows - 1, cur.r + dr));
    const c = Math.max(0, Math.min(numCols - 1, cur.c + dc));
    return { r, c };
}

/** Compute the next value from the focused cell (or anchor as
 *  fallback) and apply it to every selected cell. Single-cell
 *  fallback when there's no selection: cycle the focused cell
 *  alone, matching desktop's anchor-only path in
 *  :py:meth:`_cycle_selection_from`. */
function bulkCycleFromFocused() {
    const anchor = editorState.focused
        ?? editorState.anchor
        ?? cellFromFirstSelected();
    if (anchor === null) return;
    const next = nextCycleValue(editorState.cells[anchor.r][anchor.c]);
    const targets = editorState.selected.size === 0
        ? [anchor]
        : [...editorState.selected].map(parseCellKey);
    commitEdit(targets, next);
}

function cellFromFirstSelected() {
    const first = editorState.selected.values().next().value;
    return first === undefined ? null : parseCellKey(first);
}

// Add / remove segments and features --------------------------------

/**
 * Add a new segment column to the edit state. Called by the
 * label-prompt's onAccept after the shared validator has run, so
 * ``seg`` is already trimmed and known to be non-duplicate.
 * Mutates editorState in place and re-renders the grid (which
 * also clears any stale selection that referenced the old shape).
 */
function addSegmentToState(seg) {
    editorState.segments.push(seg);
    for (const row of editorState.cells) {
        row.push(ZERO_VALUE);
    }
    renderEditorGrid();
    clearSelection();
    markEditorDirty();
    setEditorStatus(_formatTpl(
        "added_segment_template", "Added segment '{seg}'.", { seg },
    ));
}

function addFeatureToState(feat) {
    editorState.features.push(feat);
    editorState.cells.push(
        Array.from({ length: editorState.segments.length }, () => ZERO_VALUE),
    );
    renderEditorGrid();
    clearSelection();
    markEditorDirty();
    setEditorStatus(_formatTpl(
        "added_feature_template", "Added feature '{feat}'.", { feat },
    ));
}

function removeSelectedSegment() {
    const c = getSingleSelectedColumn();
    if (c === null) return;
    const seg = editorState.segments[c];
    // Confirm prompt text comes from the shared Python so the web
    // wording matches the desktop's ``ask_question`` body exactly.
    const prompt = callBridge("confirm_remove_segment_prompt", seg);
    if (!confirm(prompt)) return;
    editorState.segments.splice(c, 1);
    for (const row of editorState.cells) {
        row.splice(c, 1);
    }
    renderEditorGrid();
    clearSelection();
    markEditorDirty();
    setEditorStatus(_formatTpl(
        "removed_segment_template", "Removed segment '{seg}'.", { seg },
    ));
}

function removeSelectedFeature() {
    const r = getSingleSelectedRow();
    if (r === null) return;
    const feat = editorState.features[r];
    const prompt = callBridge("confirm_remove_feature_prompt", feat);
    if (!confirm(prompt)) return;
    editorState.features.splice(r, 1);
    editorState.cells.splice(r, 1);
    renderEditorGrid();
    clearSelection();
    markEditorDirty();
    setEditorStatus(_formatTpl(
        "removed_feature_template", "Removed feature '{feat}'.", { feat },
    ));
}

/** Write ``value`` to the selection (or the focused cell when
 *  there is no selection). Thin wrapper over :py:func:`commitEdit`
 *  so the keyboard value-key path uses the same undo-aware
 *  primitive as click-driven edits. */
function applyValueToSelection(value) {
    const targets = selectionTargets();
    if (targets.length === 0) return;
    commitEdit(targets, value);
}

/**
 * Commit the editor's edit state through
 * commit_inventory_from_grid, swap the engine on success, then
 * trigger the standard JSON download. Refreshes both the viewer
 * (so the underlying inventory updates) and the editor (so the
 * grid reflects any canonicalization the parser applied).
 *
 * When the editor is clean (no in-progress edits) we skip the
 * commit and download the engine state directly. Avoids an
 * engine-swap-with-identical-content that would flush analysis
 * caches and clear the undo history for no reason.
 */
function commitAndDownload() {
    if (!editorState.dirty) {
        downloadCurrentInventory();
        setEditorStatus("Downloaded current inventory (no edits to commit).");
        return;
    }
    let info;
    try {
        info = callBridge(
            "commit_inventory_from_grid",
            editorState.name,
            editorState.features,
            editorState.segments,
            editorState.cells,
        );
    } catch (e) {
        setEditorStatus(`Save failed: ${e.message}`);
        return;
    }
    editorState.dirty = false;
    applyInventoryInfo(info);
    refreshEditorFromCurrent();
    downloadCurrentInventory();
    setEditorStatus(`Saved as ${info.name}.`);
}

function setEditorStatus(msg) {
    nodes.editorStatus.textContent = msg;
}

/**
 * Toggle the ``inert`` attribute on every direct child of
 * ``<body>`` except the editor itself and any open dialogs. Removes
 * those elements from the keyboard tab order and click pipeline
 * while editor mode is active, so the user cannot Tab into the
 * main toolbar's picker / pencil / Browse / Save-as and trigger an
 * engine swap that would discard editor edits.
 *
 * The HTML ``inert`` attribute is supported in all modern browsers
 * (added to the platform in 2022). Falls back gracefully to
 * tabindex manipulation on older browsers, but this codebase
 * targets evergreen browsers via Pyodide so the fallback is
 * unreachable in practice.
 */
function setMainChromeInert(on) {
    for (const child of document.body.children) {
        if (child === nodes.editorView) continue;
        // Dialogs sit in the top layer when shown via showModal();
        // they handle their own focus trapping.
        if (child.tagName === "DIALOG") continue;
        child.inert = on;
    }
}

// Label-prompt modal -------------------------------------------------

// Pending invocation state: the title / labels / handlers vary per
// call site (+ Segment vs + Feature), but the dialog itself is
// reused. ``_labelPromptPending`` is the active invocation; the
// form-submit listener is wired once and reads from it.
let _labelPromptPending = null;

/**
 * Show the shared text-input modal. Used by + Segment and
 * + Feature to gather the new label, validate it via the bridge
 * (which routes through the same validator the desktop builder
 * uses), and apply it to ``editorState`` on success.
 *
 * ``onAccept`` receives the canonical (trimmed) label string.
 */
function labelPrompt({
    title,
    label,
    submitLabel,
    bridgeEndpoint,
    existing,
    onAccept,
}) {
    nodes.labelPromptTitle.textContent = title;
    nodes.labelPromptLabel.textContent = label;
    nodes.labelPromptSubmit.textContent = submitLabel;
    nodes.labelPromptInput.value = "";
    nodes.labelPromptError.textContent = "";
    _labelPromptPending = { bridgeEndpoint, existing, onAccept };
    const dlg = nodes.labelPromptDialog;
    if (typeof dlg.showModal === "function") {
        dlg.showModal();
    } else {
        dlg.setAttribute("open", "");
    }
    requestAnimationFrame(() => nodes.labelPromptInput.focus());
}

function closeLabelPrompt() {
    const dlg = nodes.labelPromptDialog;
    if (typeof dlg.close === "function") {
        dlg.close();
    } else {
        dlg.removeAttribute("open");
    }
    _labelPromptPending = null;
}

function wireLabelPrompt() {
    nodes.labelPromptCancel.addEventListener("click", closeLabelPrompt);
    nodes.labelPromptForm.addEventListener("submit", (ev) => {
        ev.preventDefault();
        if (_labelPromptPending === null) {
            closeLabelPrompt();
            return;
        }
        const pending = _labelPromptPending;
        let canonical;
        try {
            canonical = callBridge(
                pending.bridgeEndpoint,
                nodes.labelPromptInput.value,
                pending.existing,
            );
        } catch (e) {
            nodes.labelPromptError.textContent = e.message || "Invalid label.";
            nodes.labelPromptInput.focus();
            return;
        }
        closeLabelPrompt();
        pending.onAccept(canonical);
    });
}

const THEME = Object.freeze({ LIGHT: "light", DARK: "dark" });

/** localStorage is external input: anything other than the dark
 *  sentinel reads as light. */
function normalizeTheme(value) {
    return value === THEME.DARK ? THEME.DARK : THEME.LIGHT;
}

/** Best-effort localStorage write. Persistence is a "nice to have";
 *  a quota-exceeded or storage-blocked browser (private window,
 *  iframe with storage disabled, Safari ITP eviction) must not
 *  crash the toggle. The catch logs a warning so the failure mode
 *  is observable in devtools without surfacing to the user. */
function safeStorageSet(key, value) {
    try {
        localStorage.setItem(key, value);
    } catch (e) {
        console.warn(`localStorage write failed for ${key}:`, e);
    }
}

/** Best-effort localStorage read. Some browsers (Safari Lockdown
 *  Mode, embedded contexts) throw on getItem too; treat that as
 *  "no stored value" and return null. */
function safeStorageGet(key) {
    try {
        return localStorage.getItem(key);
    } catch (e) {
        console.warn(`localStorage read failed for ${key}:`, e);
        return null;
    }
}

/**
 * Render the statusbar's "Language Doodad" brand as a rasterized
 * (non-copyable) label. Same canvas-mask trick as the segment
 * buttons: the literal text is in ``aria-label`` for screen
 * readers, but the on-screen glyphs come from a CSS mask so
 * drag-select-copy doesn't pick anything up.
 */
function wireStatusbarBrand() {
    if (!nodes.statusbarBrand) return;
    nodes.statusbarBrand.replaceChildren(
        createRasterizedLabel(
            "Language Doodad", 'italic 13px "Noto Sans", sans-serif'
        )
    );
}

/**
 * Open the project's GitHub Issues "new issue" page in a new
 * tab. The bug-report URL is the canonical place to file
 * reproducible problems; no in-app capture is attempted because
 * the user knows their environment best.
 */
function wireBugButton() {
    if (!nodes.bugBtn) return;
    nodes.bugBtn.addEventListener("click", () => {
        window.open(
            "https://github.com/jhnwnstd/features/issues/new",
            "_blank",
            "noopener,noreferrer"
        );
    });
}

const PALETTE_MODE = Object.freeze({
    STANDARD: "standard",
    COLORBLIND: "colorblind",
});

/** localStorage is external input: anything other than the
 *  colorblind sentinel reads as standard. */
function normalizePaletteMode(value) {
    return value === PALETTE_MODE.COLORBLIND
        ? PALETTE_MODE.COLORBLIND
        : PALETTE_MODE.STANDARD;
}

/**
 * Bind the colorblind-palette toggle. The active mode lives on
 * ``html[data-cb]`` so theme.css can override the standard
 * variables under that selector; ``aria-pressed`` doubles as the
 * styling hook for the button's accented "on" state. The Python
 * renderer is told via ``set_palette_mode`` so analysis-chip HTML
 * regenerates with matching colors.
 */
/** Push the user's restored theme + palette-mode (set by
 *  wireThemeToggle / wireColorblindToggle before the bridge
 *  attached) into Python. Without this, the analysis HTML renders
 *  with the default ``(light, standard)`` palette baked in, even
 *  though the CSS-vars layer is showing dark / colorblind. The
 *  desktop equivalent is the same constructor-time
 *  ``set_theme(saved_theme) + set_palette_mode(saved_mode)`` pair
 *  in :py:meth:`MainWindow.__init__`. */
function _syncBridgePaletteToStoredState() {
    const theme = normalizeTheme(safeStorageGet("theme"));
    const mode = normalizePaletteMode(safeStorageGet("palette_mode"));
    try {
        callBridge("set_active_theme", theme);
        callBridge("set_active_palette_mode", mode);
    } catch (e) {
        console.warn("palette sync to bridge failed:", e);
    }
}

function wireColorblindToggle() {
    if (!nodes.cbBtn) return;
    // aria-label and title share one source so SRs (which prefer
    // aria-label) and hover tooltips can never drift apart.
    const labelFor = (mode) => mode === PALETTE_MODE.COLORBLIND
        ? (STATUS_TEXT.palette_to_standard || "Switch to standard palette")
        : (STATUS_TEXT.palette_to_colorblind
            || "Switch to colorblind-friendly palette");
    const applyLabel = (mode) => {
        const text = labelFor(mode);
        nodes.cbBtn.title = text;
        nodes.cbBtn.setAttribute("aria-label", text);
    };
    const stored = normalizePaletteMode(safeStorageGet("palette_mode"));
    if (stored === PALETTE_MODE.COLORBLIND) {
        document.documentElement.dataset.cb = "on";
        nodes.cbBtn.setAttribute("aria-pressed", "true");
        applyLabel(PALETTE_MODE.COLORBLIND);
    } else {
        applyLabel(PALETTE_MODE.STANDARD);
    }
    nodes.cbBtn.addEventListener("click", () => {
        const cur = document.documentElement.dataset.cb === "on"
            ? PALETTE_MODE.COLORBLIND
            : PALETTE_MODE.STANDARD;
        const next = cur === PALETTE_MODE.COLORBLIND
            ? PALETTE_MODE.STANDARD
            : PALETTE_MODE.COLORBLIND;
        if (next === PALETTE_MODE.COLORBLIND) {
            document.documentElement.dataset.cb = "on";
        } else {
            delete document.documentElement.dataset.cb;
        }
        nodes.cbBtn.setAttribute(
            "aria-pressed", next === PALETTE_MODE.COLORBLIND ? "true" : "false"
        );
        applyLabel(next);
        safeStorageSet("palette_mode", next);
        if (state.bridge) {
            callBridge("set_active_palette_mode", next);
            const hasSelection =
                state.selected_segments.length > 0
                || Object.keys(state.selected_features).length > 0;
            if (hasSelection) runAnalysis();
        }
    });
}

function wireThemeToggle() {
    // aria-label, title, AND glyph share one source (shared
    // mode_logic.theme_toggle_{tooltip,glyph}) so the SR
    // announcement, hover tooltip, and visual icon can never drift
    // from each other or from the desktop button.
    const labelFor = (theme) => theme === THEME.DARK
        ? (STATUS_TEXT.theme_to_light || "Switch to light mode")
        : (STATUS_TEXT.theme_to_dark || "Switch to dark mode");
    const glyphFor = (theme) => theme === THEME.DARK
        ? (STATUS_TEXT.theme_glyph_dark || "☀")
        : (STATUS_TEXT.theme_glyph_light || "☾");
    const applyLabel = (theme) => {
        const text = labelFor(theme);
        nodes.themeBtn.title = text;
        nodes.themeBtn.setAttribute("aria-label", text);
    };
    const stored = normalizeTheme(safeStorageGet("theme"));
    if (stored === THEME.DARK) {
        document.documentElement.dataset.theme = THEME.DARK;
        nodes.themeBtn.textContent = glyphFor(THEME.DARK);
        applyLabel(THEME.DARK);
    } else {
        applyLabel(THEME.LIGHT);
    }
    nodes.themeBtn.addEventListener("click", () => {
        const cur = normalizeTheme(document.documentElement.dataset.theme);
        const next = cur === THEME.DARK ? THEME.LIGHT : THEME.DARK;
        document.documentElement.dataset.theme = next;
        nodes.themeBtn.textContent = glyphFor(next);
        applyLabel(next);
        safeStorageSet("theme", next);
        if (state.bridge) {
            callBridge("set_active_theme", next);
            // Re-run only if a selection is active; an empty pane
            // has no chip colors to refresh.
            const hasSelection =
                state.selected_segments.length > 0
                || Object.keys(state.selected_features).length > 0;
            if (hasSelection) runAnalysis();
        }
    });
}

// Synthetic option value used to mark the PHOIBLE-loaded entry in
// the toolbar dropdown. Distinct from every bundled inventory file
// path so the change handler can disambiguate.
const LOADED_OPTION_VALUE = "__loaded__";

/** Prepend (or update) a single ``<option>`` at the top of the
 *  inventory dropdown that reflects the currently loaded
 *  non-bundled inventory (today: PHOIBLE). The option lives inside
 *  an ``<optgroup>`` for visual separation; native ``<select>``
 *  styling on WebKit is limited and the optgroup is the most
 *  portable visual cue. Idempotent: re-calling with the same name
 *  just updates the label and re-selects. */
function setLoadedSyntheticOption(name) {
    const picker = nodes.inventoryPicker;
    let group = picker.querySelector(`optgroup[data-loaded]`);
    let opt;
    if (group) {
        opt = group.querySelector("option");
    } else {
        group = document.createElement("optgroup");
        group.setAttribute("data-loaded", "true");
        group.label = "Loaded";
        opt = document.createElement("option");
        opt.value = LOADED_OPTION_VALUE;
        group.appendChild(opt);
        picker.prepend(group);
    }
    opt.textContent = name;
    picker.value = LOADED_OPTION_VALUE;
}

/** Remove the synthetic ``Loaded`` optgroup if present. Called from
 *  the change handler whenever the user picks a bundled inventory
 *  so the toolbar dropdown returns to its plain shape. */
function clearLoadedSyntheticOption() {
    const group = nodes.inventoryPicker.querySelector(
        "optgroup[data-loaded]",
    );
    if (group) group.remove();
}

function wireInventoryPicker() {
    nodes.inventoryPicker.addEventListener("change", () => {
        const value = nodes.inventoryPicker.value;
        if (value === LOADED_OPTION_VALUE) {
            // The synthetic option represents the already-loaded
            // engine state; selecting it again is a no-op. The
            // event still fires (e.g. when programmatic code sets
            // the picker.value), so we early-return cleanly.
            return;
        }
        const item = BUNDLED_INVENTORIES.find((i) => i.file === value);
        if (item) {
            clearLoadedSyntheticOption();
            loadBundledInventory(item);
        }
    });
}

function populateInventoryPicker() {
    const picker = nodes.inventoryPicker;
    picker.innerHTML = "";
    for (const item of BUNDLED_INVENTORIES) {
        const opt = document.createElement("option");
        opt.value = item.file;
        opt.textContent = item.label;
        picker.appendChild(opt);
    }
    // Sync the picker's selected value to the preferred default.
    // Without this the browser auto-selects <option>[0] while
    // pickDefaultInventory loads a different inventory into the
    // engine; the dropdown label and engine state disagree.
    const preferred = pickDefaultInventory(BUNDLED_INVENTORIES);
    if (preferred) picker.value = preferred.file;
}

/** Wire the three analysis-tab buttons. Click-to-activate, with a
 *  no-op when the user clicks the already-active or a disabled tab.
 *  Tab content and the contrasts-enabled flag come from the shared
 *  Python view-model; this is purely the click-routing layer. */
function wireAnalysisTabs() {
    const targets = [
        ["class", nodes.analysisTabClass],
        ["features", nodes.analysisTabFeatures],
        ["contrasts", nodes.analysisTabContrasts],
    ];
    for (const [name, btn] of targets) {
        btn.addEventListener("click", () => {
            if (btn.disabled) return;
            if (btn.getAttribute("aria-selected") === "true") return;
            activateAnalysisTab(name);
        });
    }
}

function wireClearButtons() {
    // Wipe state synchronously before triggering the mode switch so
    // the user never sees a flash of prior analysis content during
    // the debounced reanalysis window.
    nodes.segClearBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        clearAll();
        if (state.mode !== MODE.SEG_TO_FEAT) {
            activateMode(MODE.SEG_TO_FEAT);
        } else if (state.bridge) {
            runAnalysis();
        }
    });
    nodes.featClearBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        clearAll();
        if (state.mode !== MODE.FEAT_TO_SEG) {
            activateMode(MODE.FEAT_TO_SEG);
        } else if (state.bridge) {
            runAnalysis();
        }
    });
}

function clearAll() {
    // Clear is "make the selection empty", not a distinct UI state.
    // The analysis pane is intentionally not wiped here: the caller
    // follows up with ``activateMode`` (on a mode change) or
    // ``runAnalysis`` (same mode), and the empty-selection payload
    // from the view-model produces the default placeholder text --
    // same shape as app launch.
    state.selected_segments = [];
    state.selected_features = emptyFeatureSpec();
    state.saved_seg_state = [];
    state.saved_feat_state = emptyFeatureSpec();
    for (const btn of state.seg_buttons.values()) {
        btn.dataset.state = "default";
        btn.setAttribute("aria-pressed", "false");
    }
    for (const rec of state.feat_rows.values()) {
        rec.row.dataset.value = "";
        rec.row.dataset.shared = "false";
        rec.row.dataset.contrastive = "false";
        _setRasterizedBadge(rec.badge, "·");
        rec.plus.dataset.active = "false";
        rec.minus.dataset.active = "false";
        delete rec.row.dataset.queryValue;
    }
    setStatus(statusTextForMode(state.mode));
}

/** Clicks in empty panel space activate that panel's mode. */
function wirePanelClickMode() {
    nodes.segPanel.addEventListener("click", (ev) => {
        if (ev.target.closest("button")) return;
        activateMode(MODE.SEG_TO_FEAT);
    });
    nodes.featPanel.addEventListener("click", (ev) => {
        if (ev.target.closest("button")) return;
        activateMode(MODE.FEAT_TO_SEG);
    });
}

/**
 * Single delegated listener per container instead of one per
 * button. Fewer closures registered and a fresh inventory load
 * only rebuilds DOM, not handlers.
 */
function wireSegmentDelegation() {
    nodes.segGrid.addEventListener("click", (ev) => {
        const btn = ev.target.closest(".seg-btn");
        if (!btn || !nodes.segGrid.contains(btn)) return;
        const seg = btn.dataset.seg;
        if (seg) onSegmentClicked(seg);
    });
    // Right-click copies the segment symbol. Mirrors the desktop
    // ``SegmentButton.contextMenuEvent`` -> MainWindow handler.
    // Gated to SEG_TO_FEAT mode because in FEAT_TO_SEG the buttons
    // are display-only and a copy would be surprising. ev.preventDefault
    // suppresses the browser context menu so the user doesn't see a
    // phantom menu after the copy.
    nodes.segGrid.addEventListener("contextmenu", (ev) => {
        const btn = ev.target.closest(".seg-btn");
        if (!btn || !nodes.segGrid.contains(btn)) return;
        const seg = btn.dataset.seg;
        if (!seg || state.mode !== MODE.SEG_TO_FEAT) return;
        ev.preventDefault();
        copySegmentToClipboard(seg);
    });
}

/** Copy a segment symbol to the OS clipboard with status-bar
 *  feedback. Uses the async Clipboard API where available (HTTPS
 *  + permission grant); falls back to the document.execCommand
 *  path on older browsers / file:// contexts where the async API
 *  is blocked. Either way the user gets a status message so the
 *  copy isn't silent.
 */
function copySegmentToClipboard(seg) {
    // Source the success message from STATUS_TEXT.clipboard_copy_template
    // (baked from mode_logic.CLIPBOARD_COPY_MESSAGE_TEMPLATE) so it
    // stays in lockstep with the desktop. The failure message is
    // web-only so it stays inline.
    const tpl = STATUS_TEXT.clipboard_copy_template
        || "Copied /{seg}/ to clipboard";
    const onOk = () => setStatus(tpl.replace("{seg}", seg));
    const onFail = () => setStatus(`Could not copy /${seg}/`);
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(seg).then(onOk, onFail);
        return;
    }
    // Legacy fallback: stage the text in a transient textarea,
    // select it, exec the copy command, remove the textarea.
    const stage = document.createElement("textarea");
    stage.value = seg;
    stage.setAttribute("readonly", "");
    stage.style.position = "fixed";
    stage.style.opacity = "0";
    document.body.appendChild(stage);
    stage.select();
    try {
        const ok = document.execCommand("copy");
        ok ? onOk() : onFail();
    } catch {
        onFail();
    } finally {
        stage.remove();
    }
}

function wireFeatureDelegation() {
    nodes.featList.addEventListener("click", (ev) => {
        const btn = ev.target.closest(".feat-btn");
        if (!btn || !nodes.featList.contains(btn)) return;
        const row = btn.closest(".feat-row");
        const feat = row?.dataset.feat;
        const polarity = btn.dataset.polarity;
        if (feat && polarity) onFeatureClicked(feat, polarity);
    });
}

const SPILLOVER_RESIZE_DEBOUNCE_MS = 80;

/** Re-run the per-group column pass + spillover rebalance on
 *  viewport resize. Debounced so a window drag doesn't trigger
 *  duplicate layouts. Delegates to ``relayoutSegments`` which
 *  handles the rAF defer + same-state early-return. */
function wireSegmentSpilloverResize() {
    let timer = 0;
    window.addEventListener("resize", () => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => {
            timer = 0;
            relayoutSegments();
        }, SPILLOVER_RESIZE_DEBOUNCE_MS);
    });
}

/**
 * Register the service worker after first load completes so the
 * registration request doesn't compete with critical-path fetches.
 * If main.js parsed slowly enough that window.load already fired,
 * register immediately instead of waiting for an event that won't
 * come.
 */
function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    const register = () => {
        navigator.serviceWorker
            .register("./sw.js", { scope: "./" })
                    .catch((e) => console.warn("SW registration failed:", e));
    };
    if (document.readyState === "complete") {
        register();
    } else {
        window.addEventListener("load", register, { once: true });
    }
}

async function main() {
    initNodes();
    wireStatusbarBrand();
    wireBugButton();
    wireThemeToggle();
    wireColorblindToggle();
    wireInventoryPicker();
    wireUploadDownload();
    wirePhoiblePicker();
    wireRename();
    // Order matters: the setup dialog must be wired before the
    // editor, because the editor's New button receives its open()
    // trigger from the dialog's wire-up return value.
    const setupDialog = wireSetupDialog();
    wireLabelPrompt();
    wireBuilderEditor(setupDialog);
    wireAnalysisTabs();
    wireClearButtons();
    wirePanelClickMode();
    wireSegmentDelegation();
    wireFeatureDelegation();
    wireSegmentSpilloverResize();
    registerServiceWorker();

    // Paint the inlined default-inventory DOM but leave the loading
    // overlay up. Dropping it now would expose a frozen-feeling UI
    // for the ~5 s of Pyodide compile; bootPyodide drops it after
    // the WASM phase, when only ~170 ms remain.
    const prerendered = applyBootstrap();
    if (prerendered) {
        mark("first-paint:bootstrap");
    }

    try {
        await bootPyodide({ prerendered });
        prewarmCommonAnalyses();
    } catch (e) {
            console.error(e);
        setLoadingStatus(`Failed to load: ${e.message}`);
    }
}

main();
