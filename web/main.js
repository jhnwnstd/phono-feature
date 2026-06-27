/**
 * Web app entry point.
 *
 * Boots Pyodide, mounts the phonology engine bundle, renders an
 * inlined bootstrap inventory before Pyodide finishes loading, then
 * wires UI events to bridge calls into api.py.
 */

const NODE_IDS = Object.freeze({
    statusbar: "statusbar",
    statusbarSource: "statusbar-source",
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
    matchModeBtn: "match-mode-btn",
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

const STATUS_KIND = Object.freeze({
    info: "info", success: "success", warning: "warning", error: "error",
});
// Pending flash-revert timer + the persistent status it is covering.
// A transient flash (clipboard copy) restores this when it expires so
// the inventory summary is never permanently erased by a copy.
let _statusFlashTimer = null;
let _statusFlashPrev = null;

/** Low-level status-bar write (no flash bookkeeping). */
const _setStatusText = (msg, kind) => {
    nodes.statusbar.textContent = msg;
    nodes.statusbar.title = msg;
    nodes.statusbar.dataset.kind = kind;
};

/** Update the status bar. ``kind`` drives a leading icon glyph so
 *  success / error are visually distinct from informational
 *  messages without relying on a colour change alone. This is the
 *  PERSISTENT writer: it cancels any pending flash-revert so a stale
 *  revert can't later overwrite a freshly loaded inventory summary. */
const setStatus = (msg, kind = STATUS_KIND.info) => {
    if (_statusFlashTimer !== null) {
        clearTimeout(_statusFlashTimer);
        _statusFlashTimer = null;
        _statusFlashPrev = null;
    }
    _setStatusText(msg, kind);
};

/** Flash transient feedback for ``ms`` then revert to whatever
 *  persistent status was showing first. Used for clipboard-copy
 *  feedback so copying a segment never erases the inventory summary
 *  (mirrors the desktop QStatusBar: a permanent ``set_summary`` under
 *  a timed ``showMessage``; 2500 ms matches its copy timeout). Rapid
 *  repeat flashes extend the window and still revert to the original
 *  persistent message, not to a prior flash. */
const flashStatus = (msg, kind = STATUS_KIND.info, ms = 2500) => {
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

/** The user-facing message for an error thrown by a bridge call.
 *
 *  Pyodide surfaces a raised Python exception as a ``PythonError``
 *  whose ``.message`` is the WHOLE traceback ("Traceback (most
 *  recent call last): ... ModuleA.ValidationError: real message").
 *  Showing that verbatim in a dialog or status bar dumps a code
 *  traceback at the user. This pulls out the last line and strips
 *  the leading dotted exception-class prefix, leaving just the
 *  message the Python side intended. Plain JS errors (single-line
 *  ``.message``) pass straight through.
 */
function bridgeErrorMessage(e, fallback) {
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

/** Baked at build time from ``mode_logic.mode_status_text`` so the
 *  pre-bridge fallback can't drift from the canonical Python.
 *  ``web/scripts/build.py:_build_status_text_payload`` writes the
 *  inline ``<script id="status-text">`` block consumed here. The
 *  freeze keeps the object immutable so a future bug can't reach
 *  back and edit a string in place. */
const STATUS_TEXT = Object.freeze(readInlineJson("status-text", {}));

/** Vowel-chart visual policy: the stack-density thresholds and the
 *  legibility floor the renderer needs at runtime. Baked from
 *  ``shared/.../presentation/chart_style.py`` via
 *  ``_build_chart_style_block`` in ``web/scripts/build.py``.
 *  Defensive defaults match the pre-relay literals in case the
 *  inline JSON block is missing (older snapshot, offline build). */
const CHART_STYLE = Object.freeze(
    readInlineJson("chart-style", {
        vowel_cell_dense_threshold: 5,
        vowel_cell_ultra_threshold: 10,
        vowel_btn_min_h_px: 14,
    }),
);

/** Top-level UI mode. Values come from the relayed
 *  ``STATUS_TEXT.mode_values`` baked from
 *  ``mode_logic.Mode`` (single source of truth). The hardcoded
 *  fallback below is defensive only; exercised when the
 *  inlined JSON is missing (e.g., older snapshot, offline rebuild).
 *  The parity test at ``shared/tests/test_status_text_relay.py``
 *  asserts every Python ``Mode`` member appears in the baked
 *  payload, so a future rename to the Python enum trips at build
 *  time rather than at user-click time. */
const MODE = Object.freeze(
    STATUS_TEXT.mode_values || {
        SEG_TO_FEAT: "seg_to_feat",
        FEAT_TO_SEG: "feat_to_seg",
    },
);

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

/** Boot Pyodide + the engine bundle. `prerendered` indicates that
 *  applyBootstrap already painted the default inventory's DOM; in
 *  that case the loading overlay drops earlier (right after WASM
 *  compile), and the inventory load skips a redundant re-render. */
async function bootPyodide({ prerendered = false } = {}) {
    mark("boot:start");
    markBridgeGatedControlsLoading();

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
    _syncBridgeMatchModeToStoredState();

    enableBridgeGatedControls();
    // First layout pass with the bridge in. Pre-bridge the column and
    // spillover passes no-op (they need the shared planner) and the
    // prerendered path never re-renders the grid, so without this the
    // bootstrap layout would not pick up the planner until the next
    // resize. Also absorbs any resize that landed during boot.
    relayoutSegments();
    setLoadingStatus("Loading default inventory…");
    mark("inventory:start");
    const defaultItem = pickDefaultInventory(BUNDLED_INVENTORIES);
    if (prerendered) {
        // DOM is already populated by applyBootstrap, so we don't
        // re-render the panels; we sync the engine state AND reflect
        // the loaded inventory in the status bar. Without the latter
        // the "Almost ready..." boot placeholder set above would
        // linger even though an inventory is on screen (the
        // non-prerendered path sets it via loadInventoryText).
        const text = await fetchInventoryText(defaultItem.file);
        const info = callBridge("load_inventory_json", text, defaultItem.label);
        setInventoryStatus(info);
        setStatusSourceLink(info.source_url);
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
    // The status bar shows ONLY the loaded-inventory summary, which
    // both boot paths above set via ``setInventoryStatus`` (the
    // prerendered branch directly, the other through
    // loadBundledInventory). Mode hints live in the analysis pane,
    // not the bottom border.

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
    "matchModeBtn",
];

/**
 * Toolbar controls that call into Python start disabled in HTML
 * and are re-enabled only after the bridge attaches. ``data-loading``
 * differentiates the pre-bridge wait cursor from the post-bridge
 * "this action is unavailable" cursor.
 */
function markBridgeGatedControlsLoading() {
    for (const key of BRIDGE_GATED_NODES) {
        nodes[key].setAttribute("data-loading", "true");
    }
}
function enableBridgeGatedControls() {
    for (const key of BRIDGE_GATED_NODES) {
        nodes[key].disabled = false;
        nodes[key].removeAttribute("data-loading");
    }
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
    state.provenance = info.provenance || null;
    state.segments = info.segments;
    state.features = info.features;
    state.selected_segments = [];
    state.selected_features = emptyFeatureSpec();
    renderSegmentGrid(info.groups, info.vowel_chart);
    renderFeaturePanel(info.feature_groups);
    clearAnalysisTabs();
    _applyProvenanceChip(info.provenance);
    // PHOIBLE inventories carry a source-page URL; any other load
    // (bundled, uploaded, built) leaves it undefined, which hides the
    // statusbar "Source" link, so the link always reflects the
    // currently loaded inventory.
    setStatusSourceLink(info.source_url);
}

/** Show or hide the statusbar "Source" hyperlink for the loaded
 *  inventory. ``url`` is a baked phoible.org page; empty / absent
 *  hides the link (non-PHOIBLE inventories). The summary text itself
 *  is set separately via ``setStatus``; this link sits beside it at
 *  the bottom border, mirroring the desktop status bar. */
function setStatusSourceLink(url) {
    const link = nodes.statusbarSource;
    if (!link) return;
    const clean = typeof url === "string" ? url.trim() : "";
    if (!clean) {
        link.removeAttribute("href");
        link.hidden = true;
        return;
    }
    link.href = clean;
    link.title = `PHOIBLE source: ${clean}`;
    link.hidden = false;
}

/** Paint the persistent inventory-source badge next to the
 *  analysis-selection header. Reads the ``provenance`` field from
 *  the bridge payload so the user can tell where the loaded
 *  inventory came from (PHOIBLE / bundled / uploaded / builder)
 *  after the picker dialog closes. */
function _applyProvenanceChip(provenance) {
    let chip = document.getElementById("inventory-provenance");
    if (!provenance) {
        if (chip) chip.hidden = true;
        return;
    }
    if (!chip) {
        chip = document.createElement("span");
        chip.id = "inventory-provenance";
        chip.className = "inventory-provenance";
        const host = document.getElementById("analysis-selection");
        if (host && host.parentNode) {
            host.parentNode.insertBefore(chip, host);
        }
    }
    chip.textContent = provenance;
    chip.title = `Loaded from ${provenance}`;
    chip.hidden = false;
}

/** Set the bottom-border status to the loaded-inventory summary
 *  (name, segment x feature counts). The single source of truth for
 *  the inventory line: every load path routes through here so the bar
 *  cannot diverge in format or linger on a boot placeholder. */
function setInventoryStatus(info) {
    const loadedTpl = STATUS_TEXT.inventory_loaded_template
        || "{name}: {n_segments} segments × {n_features} features";
    setStatus(
        loadedTpl
            .replace("{name}", info.name)
            .replace("{n_segments}", String(info.segments.length))
            .replace("{n_features}", String(info.features.length))
    );
}

async function loadInventoryText(text, sourceLabel) {
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

/** Kick off the PHOIBLE data fetch when the browser is idle so
 *  the dialog open path doesn't pay the ~5 MB download on first
 *  click. The bridge LOAD step is left for the click path: the
 *  ~500 ms JSON parse blocks the main thread (Pyodide runs there
 *  today) and is best left until the user actually wants PHOIBLE
 *  open, where the spinner explains the brief wait. A future
 *  worker migration would let this also happen at idle. */
function schedulePhoiblePrefetch() {
    if (_phoibleDataText || _phoibleDataFetch) return;
    if (!state.bridge) return;
    try {
        if (!callBridge("phoible_is_available")) return;
        if (callBridge("phoible_is_ready")) return;
    } catch {
        return;
    }
    const idle = ("requestIdleCallback" in window)
        ? (cb) => window.requestIdleCallback(cb, { timeout: 10_000 })
        : (cb) => setTimeout(cb, 1500);
    idle(() => {
        _fetchPhoibleData().catch(() => {
            /* silent; openDialog retries on click */
        });
    });
}

/** Ensure PHOIBLE is loaded into the bridge. Single-flight: the
 *  dialog open path awaits whatever load is in progress, so a
 *  click that lands while the bridge parse is mid-flight resolves
 *  on the same call. */
function ensurePhoibleData() {
    if (_phoibleDataLoad) return _phoibleDataLoad;
    _phoibleDataLoad = (async () => {
        try {
            const text = await _fetchPhoibleData();
            callBridge("phoible_load_data", text);
        } catch (e) {
            _phoibleDataLoad = null;
            throw e;
        }
    })();
    return _phoibleDataLoad;
}

function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;",
        '"': "&quot;", "'": "&#39;",
    })[c]);
}

// Shared 2D context for canvas-based text-width measurement. One
// per page (off-DOM, kept alive in module scope) so the seg-button
// auto-shrink path doesn't allocate a fresh canvas per glyph.
const _segMeasureCtx = document.createElement("canvas").getContext("2d");
// Font family the seg-button measure + render uses. Reads the same
// CSS variable the buttons themselves consume (Charis IPA first)
// so the canvas measure agrees with the actual rendered metrics.
const _segFontFamily = (
    getComputedStyle(document.documentElement)
        .getPropertyValue("--font-ipa")
        .trim()
    || '"Noto Sans Mono", monospace'
);
// Natural seg-button label font size, read from the relayed
// ``--font-size-control`` CSS variable so the canvas font-size
// agrees with the rendered DOM font-size by construction. The
// floor matches ``--font-size-min-px`` (the
// ``constants.FONT_SIZE_MIN_PX`` Python value baked into the CSS
// relay). Falls back to the historical literals if the variables
// are missing (defensive read pattern matching the button-width
// reads in ``applyPerGroupSegmentColumns``).
const _rootCS = getComputedStyle(document.documentElement);

/** Read a ``--*`` CSS length off the document root. ``fallback``
 *  is returned only when the value is missing or unparseable;
 *  ``0`` (a valid CSS length) passes through. */
function parseCSSLength(varName, fallback) {
    const v = parseFloat(_rootCS.getPropertyValue(varName));
    return Number.isFinite(v) ? v : fallback;
}

/** ``<dialog>.showModal()`` with a graceful fallback for browsers
 *  without dialog support. Captures the previously-focused
 *  element so ``closeDialog`` can restore focus to its trigger. */
function openDialog(dialog) {
    dialog._returnFocusTo = document.activeElement;
    if (typeof dialog.showModal === "function") {
        dialog.showModal();
    } else {
        dialog.setAttribute("open", "");
        // Native <dialog> handles Escape and focus trap; the
        // fallback path needs manual Escape wiring at least.
        if (!dialog._escHandler) {
            dialog._escHandler = (ev) => {
                if (ev.key === "Escape") {
                    ev.preventDefault();
                    closeDialog(dialog);
                }
            };
            dialog.addEventListener("keydown", dialog._escHandler);
        }
    }
}

/** Symmetric counterpart for ``openDialog``. */
function closeDialog(dialog) {
    if (typeof dialog.close === "function") {
        dialog.close();
    } else {
        dialog.removeAttribute("open");
    }
    // Restore focus to whatever triggered the dialog so keyboard
    // users do not land on document.body after close.
    const target = dialog._returnFocusTo;
    if (target && typeof target.focus === "function") {
        try { target.focus(); } catch { /* ignore */ }
    }
    dialog._returnFocusTo = null;
}

/** Attach a ResizeObserver that fires ``callback`` once per
 *  observed mutation. Stored on ``dataEl`` under ``key`` so a
 *  later ``detachResizeObserver`` call (or
 *  ``_disconnectChartObservers``) can disconnect it cleanly.
 *  Idempotent: re-attaching the same key replaces the prior obs. */
function attachResizeObserver(dataEl, key, callback) {
    if (typeof ResizeObserver === "undefined") return;
    detachResizeObserver(dataEl, key);
    const obs = new ResizeObserver(() => {
        if (!dataEl.isConnected) return;
        requestAnimationFrame(() => {
            if (dataEl.isConnected) callback();
        });
    });
    obs.observe(dataEl);
    dataEl[key] = obs;
}

function detachResizeObserver(dataEl, key) {
    const prev = dataEl[key];
    if (prev) {
        prev.disconnect();
        delete dataEl[key];
    }
}

const SEG_FONT_NATURAL_PX = parseCSSLength("--font-size-control", 13);
// Seg-button shrink floor. Deliberately below the global
// ``--font-size-min-px`` (10): Charis IPA renders the widest hayes
// tie-bar affricates (``k+͡x+``, ``ɡ+͡ɣ+``) too wide to fit the 33px
// button at 10px, and a two-glyph affricate icon stays legible at 9
// (the desktop already paints every seg button at a fixed 9pt). This
// is a content-driven floor for an icon-like glyph, not body text.
const SEG_FONT_FLOOR_PX = 9;
// Inner width budget for seg-button text. ``--seg-btn-min-w`` is
// 33 px; subtract the 1.5 px border on each side and leave 1 px of
// breathing room so glyphs sit just inside the outline. Picked to
// match the empirical ``clientWidth`` of an unstyled seg-btn so
// canvas measurement and DOM layout agree on the fit boundary.
const SEG_FIT_BUDGET_PX = 30;

/** Pick the largest font-size at which ``text`` fits inside the
 *  seg-button's inner width budget. Mirrors the desktop's
 *  ``QFontMetrics`` shrink for tie-bar affricates ``k+͡x+`` /
 *  ``ɡ+͡ɣ+`` and multi-character PHOIBLE diphthongs. Returns the
 *  picked font size in CSS pixels, or ``null`` when the natural
 *  size already fits (caller skips the inline override).
 *
 *  Canvas measurement avoids DOM layout thrash and runs before the
 *  button enters the tree, so the picked size lands with the first
 *  paint. Charis IPA may not be loaded at measurement time; the
 *  fallback monospace metrics are close enough that the shrunk
 *  size still fits once Charis swaps in (``overflow: hidden`` on
 *  ``.seg-btn`` clips any residual half-pixel overrun cleanly).
 */
// Per-text font-size memo. The bounded set of glyphs that appear
// on seg-buttons across all inventories is small (~few hundred
// distinct IPA strings); rebuilding the measurement state +
// shrink-loop per render thrashes the canvas font state needlessly.
// Map is never evicted; cleared only when ``--font-ipa`` itself
// changes (which never happens at runtime today).
const _segFontSizeCache = new Map();

function _pickSegFontSize(text) {
    const cached = _segFontSizeCache.get(text);
    if (cached !== undefined) return cached;
    _segMeasureCtx.font = `${SEG_FONT_NATURAL_PX}px ${_segFontFamily}`;
    if (_segMeasureCtx.measureText(text).width <= SEG_FIT_BUDGET_PX) {
        _segFontSizeCache.set(text, null);
        return null;
    }
    for (let px = SEG_FONT_NATURAL_PX - 0.5; px >= SEG_FONT_FLOOR_PX; px -= 0.5) {
        _segMeasureCtx.font = `${px}px ${_segFontFamily}`;
        if (_segMeasureCtx.measureText(text).width <= SEG_FIT_BUDGET_PX) {
            _segFontSizeCache.set(text, px);
            return px;
        }
    }
    _segFontSizeCache.set(text, SEG_FONT_FLOOR_PX);
    return SEG_FONT_FLOOR_PX;
}

/** Re-run the per-glyph shrink for every live seg button once the IPA
 *  webfont has loaded. The first-paint shrink runs at button-build,
 *  before Charis IPA is available, so it measures the fallback
 *  monospace metrics, which are narrower than Charis. Without this
 *  pass the widest tie-bar affricates keep a size that fit the
 *  fallback but overflow once Charis swaps in. The cache is cleared
 *  first so the re-measure uses the now-loaded font. */
function _refitSegButtons() {
    _segFontSizeCache.clear();
    for (const [seg, btn] of state.seg_buttons) {
        const fit = _pickSegFontSize(seg);
        btn.style.fontSize = fit !== null ? `${fit}px` : "";
    }
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
    // with the button centre for every glyph, regardless of
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
// Memo cache for ``rasterizeText`` output, keyed on
// ``${text}|${font}|${maxWidth}``. The badge + chip glyphs that go
// through ``createRasterizedLabel`` are a tiny bounded set (``·``,
// ``+``, ``-``, mode-name letters); every analysis pass would
// otherwise allocate a fresh canvas, run measureText/fillText/
// toDataURL on the same input, and discard the result. Map never
// evicts (the bounded set is <50 entries in practice).
const _rasterCache = new Map();

function createRasterizedLabel(text, font, maxWidth) {
    const key = text + "|" + font + "|" + (maxWidth != null ? maxWidth : "");
    let cached = _rasterCache.get(key);
    if (cached === undefined) {
        cached = rasterizeText(text, font, maxWidth);
        _rasterCache.set(key, cached);
    }
    const { dataUrl, width, height } = cached;
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
/** Disconnect every ResizeObserver attached to chart data
 *  elements before the chart is destroyed. Without this the
 *  observers keep firing on detached DOM through stale closures
 *  over the OLD ``chart`` payload and leak references that prevent
 *  GC.
 *
 *  New observers should register under a ``data-*-observer``
 *  property on ``dataEl`` so they're discovered by this helper
 *  automatically.
 */
function _disconnectChartObservers(grid) {
    if (!grid) return;
    for (const dataEl of grid.querySelectorAll(".vowel-chart-data")) {
        detachResizeObserver(dataEl, "_silhouetteResizeObserver");
    }
}

function renderSegmentGrid(groups, vowelChart) {
    const grid = nodes.segGrid;
    _disconnectChartObservers(grid);
    grid.innerHTML = "";
    state.seg_buttons.clear();
    if (vowelChart && vowelChart.cells && vowelChart.cells.length) {
        const vowels = document.createElement("div");
        vowels.className = "seg-vowels";
        // Sizing policy: actual width =
        // ``max(VOWEL_CHART_W_FLOOR, natural + chrome)``. Sparse
        // inventories (Spanish 5 vowels) shrink to the floor;
        // dense ones (Hayes Universal 26 vowels) grow past it.
        // Owned LOCALLY by the web renderer; desktop has its own
        // parallel ``VOWEL_CHART_W_FLOOR`` in
        // ``desktop/.../vowel_chart.py`` so the two platforms
        // can tune independently. Chrome (row-label gutter +
        // right padding) is read from the baked CSS vars so it
        // tracks ``chart_style.py`` changes without a JS edit.
        if (typeof vowelChart.natural_data_width_px === "number") {
            const chromeW =
                parseCSSLength("--vowel-chart-row-label-gutter", 72)
                + parseCSSLength("--vowel-chart-pad-r", 12);
            const naturalSlotW =
                vowelChart.natural_data_width_px + chromeW;
            vowels.style.width =
                `${Math.max(_vowelChartWFloor(), naturalSlotW)}px`;
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
// answer; we early-return. Catches: (a) double-firing at startup
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
        // Only record the key once the bridge can actually apply the
        // layout. Pre-bridge both passes no-op (they need the shared
        // planner), so caching the key then would suppress the first
        // real pass once the bridge is in.
        if (state.bridge) _lastRelayoutKey = key;
        // Thread the already-queried row list through so the
        // column-picker doesn't re-run the same querySelectorAll.
        applyPerGroupSegmentColumns(rows);
        rebalanceSegmentSpillover();
    };
    if ("requestAnimationFrame" in window) {
        window.requestAnimationFrame(run);
    } else {
        run();
    }
}

// Per-button stride cached once at boot. Source of truth lives
// in the CSS variables baked from ``constants.BTN_W`` /
// ``constants.BTN_GAP`` by ``web/scripts/build.py``; reading them
// per relayout walks the cascade on every splitter drag. NaN
// values mean the read happened before the relay attached --
// callers fall back to the literal defaults in that case.
let _BTN_W_CSS = NaN;
let _BTN_GAP_CSS = NaN;

// Web's PLATFORM ADJUSTMENT to the shared canonical chart-width
// floor (``MIN_VOWEL_CHART_W_PX`` in layout.py, relayed as
// ``--min-vowel-chart-w`` via build.py). The architectural
// pattern: shared layer owns the canonical math; each renderer
// adds its own platform-specific offset to land at the rendered
// floor for THIS platform.
//
// Why a web-specific adjustment exists at all: CSS box model
// behaviour (border-box vs content-box rounding), CSS pixel
// snapping at sub-pixel container widths, scrollbar gutters
// reserved by ``.seg-panel``'s overflow rules. Tune this
// (NOT the shared constant) when the rendered web chart needs a
// few px more (positive) or less (negative) than the canonical.
// Set to 0 when no adjustment is needed.
//
// The rendered chart width =
//   max(MIN_VOWEL_CHART_W_PX + WEB_VOWEL_CHART_W_ADJ,
//       natural_data_width_px + chrome)
// so the floor still steps aside for inventories whose content
// needs more horizontal room.
const WEB_VOWEL_CHART_W_ADJ = 0;

function _vowelChartWFloor() {
    return parseCSSLength("--min-vowel-chart-w", 320) + WEB_VOWEL_CHART_W_ADJ;
}

function _refreshButtonStrideCache() {
    _BTN_W_CSS = parseFloat(_rootCS.getPropertyValue("--seg-btn-w"));
    _BTN_GAP_CSS = parseFloat(_rootCS.getPropertyValue("--seg-btn-gap"));
}

/** Pick a column count per consonant group that avoids one-button
 *  orphan rows. Mirrors the desktop's per-group ``best_segment_n_cols``
 *  pass in ``SegmentGridWidget._do_relayout``: same Python helper, two
 *  call sites. Inline ``grid-template-columns`` per ``.seg-row``
 *  switches that row from the default ``flex-wrap`` to a grid with the
 *  computed count; default CSS still applies between layout passes for
 *  the brief window before this runs.
 *
 *  ``rows`` may be passed in by ``relayoutSegments`` (which has
 *  already queried them); falls back to a fresh querySelectorAll
 *  for callers that don't have a row list handy. */
function applyPerGroupSegmentColumns(rows) {
    const grid = nodes.segGrid;
    if (!grid) return;
    if (!rows) rows = [...grid.querySelectorAll(".seg-row")];
    if (rows.length === 0) return;
    // Pre-bridge the rows keep the default flex-wrap layout (see the
    // note above); the orphan-avoiding column count needs the shared
    // Python helper, so defer the whole pass until the bridge is in.
    if (!state.bridge) return;
    const sample = rows[0].querySelector(".seg-btn");
    if (!sample) return;
    const btnW = sample.offsetWidth || _BTN_W_CSS || 33;
    const gapPx = Number.isFinite(_BTN_GAP_CSS) ? _BTN_GAP_CSS : 4;
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
    const groupCols = callBridge(
        "best_segment_n_cols_for_groups", sizes, maxCols,
    );
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
    // Clear any prior column assignment so re-measure starts fresh.
    spillover.style.removeProperty("--seg-spillover-cols");

    const available = grid.clientHeight;
    const consonants = [...grid.querySelectorAll(
        ":scope > .seg-group:not(.vowel-chart-group)",
    )];
    if (consonants.length === 0) return;

    // Bridge path: ``plan_segment_layout`` returns the FULL plan
    // (main_count + n_spillover_cols + per-group column assignment).
    // Pre-migration the web ran a legacy 2-col partitioner that placed
    // the same inventory differently from the desktop; the shared
    // planner is the only source now. Pre-bridge there is no plan, so
    // the consonant rows keep the CSS default layout until it is in.
    if (state.bridge) {
        const groupNames = consonants.map((el) => el.dataset.group || "");
        const heights = consonants.map((el) => el.offsetHeight);
        const widths = consonants.map((el) => el.offsetWidth);
        const chartEl = grid.querySelector(".vowel-chart-group");
        let chartRect = null;
        if (chartEl) {
            const gridBox = grid.getBoundingClientRect();
            const cBox = chartEl.getBoundingClientRect();
            chartRect = [
                Math.round(cBox.left - gridBox.left),
                Math.round(cBox.top - gridBox.top),
                Math.round(cBox.width),
                Math.round(cBox.height),
            ];
        }
        // ``min_col_w`` matches what the desktop passes: the floor
        // on a spillover column's width so a narrow pane still
        // accepts at least one column. Use the canonical segment
        // button stride.
        const segBtnW = Math.round(parseCSSLength("--seg-btn-w", 33));
        const plan = callBridge(
            "plan_segment_layout",
            groupNames,
            heights,
            widths,
            grid.clientWidth,
            available,
            chartRect,
            segBtnW,
        );
        if (!plan || plan.spillover_groups.length === 0) return;
        // Surface the column count to CSS so the spillover region
        // sizes its grid to ``repeat(N, 1fr)`` with the shared
        // ``--seg-btn-gap`` between columns.
        spillover.style.setProperty(
            "--seg-spillover-cols",
            String(plan.n_spillover_cols),
        );
        grid.appendChild(spillover);
        // Walk spillover_groups in source order so the user reads
        // column-major top-to-bottom. The bridge already sorted by
        // LPT; the column_assignment array tells us where each
        // group lands.
        const spilloverIndex = new Map();
        consonants.forEach((el, idx) => {
            spilloverIndex.set(el.dataset.group || `__idx_${idx}`, el);
        });
        for (
            let i = 0;
            i < plan.spillover_groups.length;
            i++
        ) {
            const name = plan.spillover_groups[i];
            const col = plan.spillover_column_assignment[i];
            const el = spilloverIndex.get(name);
            if (!el) continue;
            // Assign the destination column via CSS grid-column;
            // groups stack within each column in source order.
            el.style.gridColumn = String(col + 1);
            spillover.appendChild(el);
        }
        return;
    }
}

function _buildConsonantGroup(group) {
    const groupEl = document.createElement("div");
    groupEl.className = "seg-group";
    // ``dataset.group`` carries the manner-class name so
    // ``rebalanceSegmentSpillover`` can match the bridge's
    // ``spillover_groups`` list to the right DOM node when
    // reassigning groups to spillover columns.
    groupEl.dataset.group = group.name;
    const header = document.createElement("div");
    header.className = "seg-group-header";
    // Render the shared payload string verbatim; the desktop and
    // web must show the same title text. Bold + letter-spacing
    // styling comes from CSS.
    header.textContent = group.name;
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
 * Build a single segment button. Native DOM text rendering, no
 * canvas rasterization: the desktop QPushButton just sets text on
 * the button and lets Qt paint it through ``MONO_FAMILIES``; we
 * mirror that by setting ``textContent`` and letting the browser
 * shape the glyph through the CSS ``--font-ipa`` family chain
 * (Charis IPA first). Native rendering is uniformly crisper than
 * the prior canvas-rasterizer + mask-image pipeline; the
 * font-display swap also fires automatically so there's no
 * one-shot blur after Charis attaches.
 *
 * No per-button click handler: a single delegated listener on
 * #seg-grid (wireSegmentDelegation) dispatches by data-seg.
 */
function _buildSegmentButton(seg, extraAttrs) {
    const btn = document.createElement("button");
    btn.className = "seg-btn";
    btn.type = "button";
    btn.dataset.seg = seg;
    btn.dataset.state = "default";
    btn.setAttribute("aria-pressed", "false");
    // aria label template comes from shared
    // ``format_segment_accessible_label`` via STATUS_TEXT so a
    // future change to the IPA convention is one Python edit.
    btn.setAttribute(
        "aria-label",
        (STATUS_TEXT.seg_accessible_label_template || "/{seg}/").replace(
            "{seg}",
            seg,
        ),
    );
    // No browser-native ``title`` tooltip: the button's textContent
    // already shows the glyph, and a hover bubble repeating
    // ``/${seg}/`` is pure redundancy that flickers on every
    // pointer pass. ``aria-label`` keeps the slashed form for
    // screen readers and the IPA pronunciation announcement.
    btn.textContent = seg;
    // Wide glyphs (tie-bar affricates ``k+͡x+`` / ``ɡ+͡ɣ+``, PHOIBLE
    // diphthong contours ``oɛ̃``, combining-mark stacks ``o̞̜``) get
    // an inline ``font-size`` override so the glyph fits inside the
    // 33-px button outline. The desktop mirrors this via Qt's auto
    // text-fit on ``QPushButton``; the web does it with a one-shot
    // canvas measurement so the picked size lands with first paint.
    const fit = _pickSegFontSize(seg);
    if (fit !== null) {
        btn.style.fontSize = fit + "px";
    }
    if (extraAttrs) {
        for (const [k, v] of Object.entries(extraAttrs)) {
            if (k.startsWith("data-")) btn.setAttribute(k, v);
        }
    }
    state.seg_buttons.set(seg, btn);
    return btn;
}

/** Vowel-cell wrapper: same shape and size as a consonant-grid
 *  seg button so the chart's visual rhythm matches the consonant
 *  grid. The desktop's ``SegmentButton`` is single-size; the web
 *  follows suit. Multi-character PHOIBLE diphthongs that exceed
 *  the canonical button width are tracked by the CSS overflow
 *  rule on ``.seg-btn``. */
function _buildVowelSegBtn(seg) {
    return _buildSegmentButton(seg);
}

/**
 * Build the IPA vowel trapezoid: 6 height rows × 6 backness-
 * rounding columns. Row/column placement comes from Python
 * (gui.vowel_layout.vowel_grid_pos) so it matches the desktop's
 * VowelChartWidget cell-for-cell.
 */
/** Cascade: return a silhouette dict with its corner fields
 *  recomputed for the given rendered data width in pixels. Mirrors
 *  ``silhouette_for_data_width`` in
 *  ``shared/.../chart/vowels_layout.py``.
 *
 *  The cell-extent fields (``front_anchor_at_top``,
 *  ``front_anchor_at_bottom``, ``back_anchor``,
 *  ``cell_outer_extent_px``) are the source of truth. The corners
 *  are derived: ``anchor * dw + sign * extent_px`` translated
 *  back to a [0, 1] fraction. At any data width the silhouette
 *  wraps the outer cell edge flush by construction. */
function _silhouetteForDataWidth(sil, dwPx) {
    if (!sil || dwPx <= 0) return sil;
    const extentPx = sil.cell_outer_extent_px || 0;
    if (extentPx === 0) return sil;
    const extentNorm = extentPx / dwPx;
    // Per-side extents: the outline-growth pass reserves the front
    // and back edges independently (a wide back-edge group must
    // not float the front edge away from single-button front
    // cells). 0 / absent means "mirror the back extent", which is
    // the historical symmetric payload.
    const frontExtentNorm = (sil.front_cell_outer_extent_px || 0) > 0
        ? sil.front_cell_outer_extent_px / dwPx
        : extentNorm;
    const frontTop = sil.front_anchor_at_top ?? sil.top_left;
    const frontBot = sil.front_anchor_at_bottom ?? sil.bottom_left;
    const back = sil.back_anchor ?? sil.top_right;
    return {
        ...sil,
        top_left: frontTop - frontExtentNorm,
        bottom_left: frontBot - frontExtentNorm,
        top_right: back + extentNorm,
        bottom_right: back + extentNorm,
    };
}

/** Cascade: port of ``rounded_silhouette_polygon_points`` in
 *  ``shared/.../chart/vowel_geometry/outline.py``. Returns a CSS
 *  ``clip-path: polygon()`` points string with the four corners
 *  smoothed via quadratic Bezier. Must stay byte-identical to the
 *  Python helper; the test suite at
 *  ``shared/tests/test_rounded_silhouette.py`` pins the polygon
 *  output and any drift here would silently un-track the
 *  rendered silhouette. */
function _roundedSilhouettePolygonPoints(sil, radiusFrac, segmentsPerCorner) {
    const seg = segmentsPerCorner ?? 5;
    const corners = [
        [sil.top_left, sil.top_y],
        [sil.bottom_left, sil.bottom_y],
        [sil.bottom_right, sil.bottom_y],
        [sil.top_right, sil.top_y],
    ];
    const n = corners.length;
    const points = [];
    for (let i = 0; i < n; i++) {
        const prev = corners[(i - 1 + n) % n];
        const curr = corners[i];
        const nxt = corners[(i + 1) % n];
        let dxIn = prev[0] - curr[0];
        let dyIn = prev[1] - curr[1];
        const lenIn = Math.hypot(dxIn, dyIn) || 1.0;
        dxIn /= lenIn; dyIn /= lenIn;
        let dxOut = nxt[0] - curr[0];
        let dyOut = nxt[1] - curr[1];
        const lenOut = Math.hypot(dxOut, dyOut) || 1.0;
        dxOut /= lenOut; dyOut /= lenOut;
        const rIn = Math.min(radiusFrac, lenIn * 0.45);
        const rOut = Math.min(radiusFrac, lenOut * 0.45);
        const pInX = curr[0] + rIn * dxIn;
        const pInY = curr[1] + rIn * dyIn;
        const pOutX = curr[0] + rOut * dxOut;
        const pOutY = curr[1] + rOut * dyOut;
        for (let s = 0; s <= seg; s++) {
            const t = s / seg;
            const omt = 1.0 - t;
            const bx = omt * omt * pInX
                + 2.0 * omt * t * curr[0]
                + t * t * pOutX;
            const by = omt * omt * pInY
                + 2.0 * omt * t * curr[1]
                + t * t * pOutY;
            points.push(`${(bx * 100).toFixed(3)}% ${(by * 100).toFixed(3)}%`);
        }
    }
    return points.join(", ");
}

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
    chartEl.setAttribute(
        "aria-label",
        STATUS_TEXT.vowel_chart_accessible_name || "IPA vowel chart",
    );

    // Title sits in row 1, column 2 only; centered over the data
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
    // chart_y, following the trapezoid inward as it shrinks. The
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
    // Publish the geometry's natural height as a CSS custom
    // property; the CSS rule takes ``max(<floor>, var(...))`` so
    // big inventories grow past the floor without small inventories
    // collapsing below it. Setting ``minHeight`` directly used to
    // override the CSS floor for small inventories on inventory
    // swap (5-vowel Spanish reports ~100 px and collapsed the
    // chart's data area below the legible 208 px floor).
    if (typeof chart.natural_data_height_px === "number"
        && chart.natural_data_height_px > 0) {
        dataEl.style.setProperty(
            "--vowel-natural-data-h",
            chart.natural_data_height_px + "px",
        );
    }
    const sil = chart.silhouette;
    if (sil) {
        const shape = sil.shape || chart.shape || "trapezoid";
        // CASCADE: override the build-time baked
        // ``--vowel-<shape>-rounded-points`` polygon with one
        // recomputed for the ACTUAL rendered data width, so the
        // silhouette wraps the outermost cells flush regardless
        // of how wide the chart renders. The baked polygon was
        // sized for the canonical 232 px content width; the
        // chart now renders content-driven (~228-320 px) and the
        // drift between baked-polygon corners and rendered cell
        // edges is visible at the corners.
        //
        // We can't measure ``dataEl.clientWidth`` synchronously
        // (DOM not laid out yet); defer via rAF + observe
        // resize so the polygon tracks splitter drags too.
        const radiusFrac = CHART_STYLE.silhouette_corner_radius_frac
            ?? 0.018;
        const refreshPolygon = () => {
            // ``dataEl`` may have been removed from the DOM
            // between scheduling rAF and the callback firing
            // (e.g., the user swapped inventories during the
            // delay). Bail out so the closure doesn't paint
            // onto detached DOM or leak the old chart's data.
            if (!dataEl.isConnected) return;
            const dw = dataEl.clientWidth || 0;
            if (dw <= 0) return;
            const silAdj = _silhouetteForDataWidth(sil, dw);
            const polyStr = _roundedSilhouettePolygonPoints(
                silAdj, radiusFrac,
            );
            dataEl.style.setProperty(
                `--vowel-${shape}-rounded-points`, polyStr,
            );
            // Anchor the diphthong footer (label + chip strip) to the
            // trapezoid's BOTTOM-LEFT corner instead of the data area's
            // left edge: indent it by the same ``bottom_left`` fraction
            // ``silAdj`` paints the polygon's bottom-left corner from,
            // in px at the live width. Set on ``chartEl`` (the grid
            // container) so the footer grid items inherit it; recomputed
            // here on every resize alongside the polygon.
            chartEl.style.setProperty(
                "--vowel-diph-indent",
                Math.max(0, silAdj.bottom_left * dw) + "px",
            );
            // Same trigger set as the polygon (first layout +
            // every resize): re-derive the stack button heights
            // from the rows' slot budgets at the height we just
            // measured.
            _refreshVowelStackClamp(dataEl);
        };
        requestAnimationFrame(refreshPolygon);
        attachResizeObserver(
            dataEl, "_silhouetteResizeObserver", refreshPolygon,
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
    _appendVowelHeightTierBands(dataEl, chart);
    for (const row of chart.rows) {
        const rowLabel = document.createElement("div");
        rowLabel.className = "vowel-chart-row-label";
        rowLabel.textContent = row.label;
        // ``row.silhouette_left`` is baked shared-side by
        // ``silhouette_left_at_y`` so the value accounts for the
        // rounded-corner insets at the top and bottom of the
        // silhouette polygon. The label anchors to this value
        // and lands flush against the rendered silhouette edge
        // regardless of corner rounding. Fall back to the legacy
        // linear interp only if the relay payload is missing the
        // field (older bridge / offline build).
        let leftNorm;
        if (typeof row.silhouette_left === "number") {
            leftNorm = row.silhouette_left;
        } else if (silSpanY > 0) {
            const t = Math.min(
                1, Math.max(0, (row.chart_y - silTopY) / silSpanY)
            );
            leftNorm = silTopLeft + (silBotLeft - silTopLeft) * t;
        } else {
            leftNorm = 0;
        }
        // ``row.label_y`` is the shared geometry's label anchor:
        // chart_y shifted by half a button on top / bottom tiers so
        // the label centres on the anchor button row, with
        // ``row.silhouette_left`` evaluated at that SAME y so the
        // label-to-outline gap stays constant. Label placement is
        // deliberately divorced from cell positioning; falling back
        // to chart_y covers an older bridge payload.
        const labelY = typeof row.label_y === "number"
            ? row.label_y
            : row.chart_y;
        rowLabel.style.setProperty("--row-y", String(labelY));
        rowLabel.style.setProperty("--row-left", leftNorm.toFixed(5));
        dataEl.appendChild(rowLabel);
    }
    const rowTierByLogical = new Map(
        (chart.rows || []).map((r) => [r.logical_row, r.tier || "middle"]),
    );
    const slotNormByLogical = new Map(
        (chart.rows || []).map(
            (r) => [r.logical_row, r.slot_height_norm || 0],
        ),
    );
    // Only monophthongs land in cells (the shared placer skips
    // diphthongs; they are listed as chips below the chart).
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
            // grid; STACK falls back to a vertical column.
            const kind = cell.display_kind || "stack";
            switch (kind) {
                case "stack":
                    target = _buildVowelCellStack(
                        segs, slotNormByLogical.get(cell.row),
                    );
                    break;
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
                    // Unknown kind from the bridge: log + fall back so
                    // the chart still renders, but a future Python-side
                    // VowelCellDisplayKind variant addition surfaces in
                    // the console instead of silently displaying as STACK.
                    console.warn(
                        `vowel cell display_kind "${kind}" not handled `
                        + `by the web renderer; falling back to STACK. `
                        + `Update the switch in _buildVowelChart.`,
                    );
                    target = _buildVowelCellStack(
                        segs, slotNormByLogical.get(cell.row),
                    );
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
        // Hard-boundary confinement offset (px); 0 for cells the
        // outline already contains. Applied inside the transform
        // calc alongside the pair shift.
        if (cell.nudge_px) {
            target.style.setProperty("--cell-nudge", `${cell.nudge_px}px`);
        }
        // Per-cell pair shift. The geometry always populates the
        // effective value (canonical for unconflicted cells,
        // elevated when a wide-cell same-anchor collision was
        // resolved), so the renderer applies it unconditionally;
        // no "0 means canonical" sentinel to re-implement here.
        target.style.setProperty(
            "--vowel-pair-shift", `${cell.pair_shift_px}px`,
        );
        // Tag the row tier so CSS can anchor cells differently by
        // tier (top / bottom / middle / only) comes from the
        // shared geometry so the renderer never re-derives it.
        // top/bottom anchor cells so multi-entry stacks grow INTO
        // the chart; middle/only stay centred (default transform).
        // The shared classifier handles single-row inventories
        // correctly; the previous JS-side classifier misread them
        // as "top" and let cells grow downward into nothing.
        const tier = rowTierByLogical.get(cell.row);
        if (tier === "top" || tier === "bottom") {
            target.dataset.rowTier = tier;
        }
        dataEl.appendChild(target);
    }
    chartEl.appendChild(dataEl);
    _appendVowelDiphthongChipStrip(chartEl, chart);

    groupEl.appendChild(chartEl);
    return groupEl;
}

/** Below the vowel space: a "Diphthongs" label followed by one
 *  chip per diphthong segment. Each chip is a normal seg-btn, so
 *  clicking it dispatches the same selection flow as any other
 *  segment (the delegated ``#seg-grid`` handler keys off data-seg).
 *  Renders nothing when the inventory has no diphthongs. */
function _appendVowelDiphthongChipStrip(chartEl, chart) {
    const diphthongs = chart.diphthongs;
    if (!Array.isArray(diphthongs) || diphthongs.length === 0) return;
    const label = document.createElement("div");
    label.className = "vowel-diphthong-label";
    label.textContent = "Diphthongs";
    chartEl.appendChild(label);
    const strip = document.createElement("div");
    strip.className = "vowel-diphthong-chips";
    strip.setAttribute("aria-label", "Diphthongs in this inventory");
    // ``chart.diphthongs`` is the geometry's segment list (stable
    // order, no duplicates); dedup defensively anyway.
    const seen = new Set();
    for (const seg of diphthongs) {
        if (!seg || seen.has(seg)) continue;
        seen.add(seg);
        strip.appendChild(_buildSegmentButton(seg));
    }
    chartEl.appendChild(strip);
}

/** Mount the gradient backdrop for the silhouette interior.
 *  Post-redesign this is a single ``<div>`` whose CSS rule
 *  paints a top->bottom gradient (suggesting tongue lowering);
 *  the pre-redesign per-row alternating tints were replaced by
 *  one continuous fill. Skipped when the inventory has no cells
 *  (nothing to back). */
function _appendVowelHeightTierBands(dataEl, chart) {
    const cells = chart.cells;
    if (!Array.isArray(cells) || cells.length === 0) return;
    const container = document.createElement("div");
    container.className = "vowel-chart-row-bands";
    container.setAttribute("aria-hidden", "true");
    // Prepend so the gradient sits BEHIND row labels, cells, and
    // the diphthong arrow overlay (which all share the data area).
    dataEl.insertBefore(container, dataEl.firstChild);
}

/** Build a single vowel-cell button from an IPA segment string. */
function _buildVowelCellButton(seg) {
    const btn = _buildVowelSegBtn(seg);
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
function _buildVowelCellStack(segs, slotNorm) {
    const cell = document.createElement("div");
    cell.className = "vowel-chart-cell vowel-chart-cell-stack";
    // Slot-clamp metadata: the resize pass
    // (``_refreshVowelStackClamp``) re-derives this stack's
    // per-button height from its row's slot budget whenever the
    // rendered chart is shorter than the natural request.
    if (typeof slotNorm === "number" && slotNorm > 0) {
        cell.dataset.slotNorm = String(slotNorm);
        cell.dataset.stackDepth = String(segs.length);
    }
    // Density thresholds relayed from the shared
    // ``vowels_layout`` tier constants (the same ladder that
    // drives the geometry's natural-height request); the literals
    // are offline-build fallbacks only.
    const denseThreshold = CHART_STYLE.vowel_cell_dense_threshold ?? 5;
    const ultraThreshold = CHART_STYLE.vowel_cell_ultra_threshold ?? 10;
    if (segs.length >= ultraThreshold) {
        // Pathological-cell tier (PHOIBLE worst case is 12 in
        // !XU/UPSID). The standard dense tier still produces a
        // ~250 px stack at this depth; pack tighter.
        cell.dataset.cellDensity = "ultra";
    } else if (segs.length >= denseThreshold) {
        // Crowded-cell density tier: shrink so the stack stays
        // within the typical row height.
        cell.dataset.cellDensity = "dense";
    }
    // Affordance: the shrunk buttons read as "are they broken"
    // without a tooltip explaining the intentional packing. Set
    // a ``title`` on the cell so hovering anywhere over the stack
    // shows the count + the full segment list.
    if (segs.length >= denseThreshold) {
        cell.title = `${segs.length} segments share this cell: ${segs.join(" ")}`;
    }
    for (const seg of segs) {
        cell.appendChild(_buildVowelSegBtn(seg));
    }
    return cell;
}

/** Re-derive per-button heights for vowel stacks from their rows'
 *  slot budgets at the CURRENT rendered chart height. The shared
 *  geometry's row-fit invariant guarantees every slot covers its
 *  stack at natural size; rendered shorter, the density-tier height
 *  would overflow the slot and invade the neighbouring rows (top
 *  tiers hang down, bottom tiers rise up). The clamp floors at the
 *  relayed legibility minimum (``vowel_btn_min_h_px``); past the
 *  floor the panel's scrolling absorbs the overflow. Mirrors the
 *  desktop's ``setFixedHeight`` clamp in ``_layout_children``. */
function _refreshVowelStackClamp(dataEl) {
    const dh = dataEl.clientHeight || 0;
    if (dh <= 0) return;
    const minH = CHART_STYLE.vowel_btn_min_h_px ?? 14;
    const denseThreshold = CHART_STYLE.vowel_cell_dense_threshold ?? 5;
    const ultraThreshold = CHART_STYLE.vowel_cell_ultra_threshold ?? 10;
    const styles = getComputedStyle(dataEl);
    const readPx = (name, fallback) => {
        const v = parseFloat(styles.getPropertyValue(name));
        return Number.isFinite(v) ? v : fallback;
    };
    const segBtnH = readPx("--seg-btn-h", 26);
    const denseH = readPx("--vowel-cell-dense-h", segBtnH - 4);
    const ultraH = readPx("--vowel-cell-ultra-h", segBtnH - 8);
    const gap = readPx("--vowel-cell-stack-gap", 1);
    const stacks = dataEl.querySelectorAll(
        ".vowel-chart-cell-stack[data-slot-norm]",
    );
    for (const cell of stacks) {
        const slotNorm = parseFloat(cell.dataset.slotNorm);
        const depth = parseInt(cell.dataset.stackDepth, 10);
        if (!(slotNorm > 0) || !(depth > 0)) continue;
        const tierH = depth >= ultraThreshold
            ? ultraH
            : depth >= denseThreshold ? denseH : segBtnH;
        const budget = (slotNorm * dh - (depth - 1) * gap) / depth;
        const h = Math.max(minH, Math.min(tierH, Math.floor(budget)));
        if (h < tierH) {
            cell.dataset.clamped = "";
            cell.style.setProperty("--cell-btn-h", h + "px");
        } else {
            delete cell.dataset.clamped;
            cell.style.removeProperty("--cell-btn-h");
        }
    }
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
        cell.appendChild(_buildVowelSegBtn(seg));
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
        cell.appendChild(_buildVowelSegBtn(seg));
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
    //
    // Flip EVERY ``.seg-btn[data-seg=seg]`` element, not just the
    // one in ``state.seg_buttons``: the same segment can appear
    // in MULTIPLE surfaces (the consonant grid, the vowel
    // chart cell, the diphthong chip strip), and clicking any
    // one of them must light up the others so the user sees a
    // single coherent "selected" state across the chart. Pre-fix
    // clicking a diphthong cell only lit the cell button, and the
    // chip strip below the silhouette stayed default-coloured,
    // making users think the chip was inert.
    const nextState = wasSelected ? "default" : "selected";
    const nextPressed = wasSelected ? "false" : "true";
    const cssSafe = CSS.escape(seg);
    for (const btn of document.querySelectorAll(
        `.seg-btn[data-seg="${cssSafe}"]`,
    )) {
        btn.dataset.state = nextState;
        btn.setAttribute("aria-pressed", nextPressed);
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
    let totalRows = 0;
    for (const group of featureGroups) {
        const colIndex = Math.max(
            0, Math.min(columnCount - 1, group.column ?? 0),
        );
        cols[colIndex].appendChild(_buildFeatureGroup(group));
        totalRows += (group.features || []).length;
    }
    for (const c of cols) list.appendChild(c);
    applyFeatureDensity(totalRows);
}

/** Mirror of the desktop's ``MainWindow._apply_feature_density``:
 *  when the active-feature count crosses
 *  ``FEAT_COMPACT_THRESHOLD`` (relayed via LIMITS), the feature
 *  pane switches to the compact tier so Hayes-28 / Default-33 /
 *  PHOIBLE-large inventories fit without scroll. Pre-parity the
 *  web had no compact mode and relied on the panel-body
 *  scrollbar. */
function applyFeatureDensity(featureCount) {
    if (!nodes.featPanel) return;
    const threshold = LIMITS.feat_compact_threshold || 22;
    const compact = featureCount >= threshold;
    if (compact) {
        nodes.featPanel.dataset.density = "compact";
    } else {
        delete nodes.featPanel.dataset.density;
    }
}

function _buildFeatureGroup(group) {
    const groupEl = document.createElement("div");
    groupEl.className = "feat-group";
    const header = document.createElement("div");
    header.className = "feat-group-header";
    // Shared payload string verbatim: desktop and web both render
    // ``FEATURE_GROUPS`` titles as ``Major Class`` / ``Laryngeal``
    // etc. Styling is owned by CSS.
    header.textContent = group.name;
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
    // Use plain DOM text so the CSS rule
    // ``.feat-name { font-variant: small-caps }`` actually applies.
    // ``createRasterizedLabel`` paints to a canvas bitmap, and
    // canvas font shorthand support for ``small-caps`` varies
    // across browsers (notably broken in WebKit at the time of
    // writing). Feature names are short English words with no
    // copy-protection rationale (unlike IPA seg glyphs), so plain
    // DOM text is the right tier: theme reactivity comes from the
    // cascaded ``color`` token; the small-caps shaping comes from
    // the system font's OpenType ``smcp`` feature.
    name.textContent = feat;
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
        // Pre-bridge there is no engine to project the outgoing
        // selection across modes, so the target mode starts empty and
        // we only remember the raw outgoing selection. This equals
        // shared mode_logic.project_mode_transition with engine=None.
        : {
            saved_seg_state:
                state.mode === MODE.SEG_TO_FEAT
                    ? state.selected_segments.slice()
                    : [],
            saved_feat_state:
                state.mode === MODE.SEG_TO_FEAT
                    ? emptyFeatureSpec()
                    : cloneFeatureSpec(state.selected_features),
            selected_segments: [],
            selected_features: emptyFeatureSpec(),
        };

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
                const target = isSelected ? "selected" : "default";
                if (btn.dataset.state === target) continue;
                btn.dataset.state = target;
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

    // The bottom border keeps showing the loaded-inventory summary
    // across mode switches; mode hints belong to the analysis pane.

    // Mode switch is a discrete one-off event; bypass the 30 ms
    // click-burst debounce and paint the new mode's segment states
    // in a single synchronous pass. Without this, segments would
    // sit at their pre-switch state for 30 ms after the chrome
    // already changed; the source of the flicker users see.
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

// ``segmentStates`` is sparse: it lists only the segments whose state
// differs from ``defaultState`` (the payload's default_segment_state),
// so a segment absent from the map takes that baseline.
function _applySegmentStateMap(segmentStates, defaultState) {
    const fallback = defaultState ?? "default";
    _applySegmentStates((seg) => segmentStates?.[seg] ?? fallback);
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

/** Swap a feat-row badge's rasterized label in place. No-op when
 *  the badge already carries ``text``; analysis passes that land
 *  on the same row state (the common case after the engine
 *  short-circuits identical selections) skip the DOM swap entirely. */
function _setRasterizedBadge(badgeEl, text) {
    if (badgeEl.dataset.label === text) return;
    badgeEl.dataset.label = text;
    badgeEl.setAttribute("aria-label", text);
    badgeEl.replaceChildren(
        createRasterizedLabel(text, '12px "Noto Sans", sans-serif')
    );
}

// The two analysis directions run the same flow: call the bridge,
// surface a failure, drop the result if a newer request superseded
// this ``token``, then repaint tabs + segment states. They differ
// only in the bridge fn + argument and whether feature-row states
// are repainted (seg->feat owns the feature rows; feat->seg does
// not touch them).
function _runAnalysis(token, bridgeFn, arg, applyFeatureRows) {
    let result;
    try {
        result = callBridge(bridgeFn, arg);
    } catch (e) {
        _surfaceBridgeFailure(bridgeFn, e);
        return;
    }
    if (token !== state.analysis_token) return;
    setAnalysisTabs(result.analysis_tabs);
    _applySegmentStateMap(
        result.segment_states, result.default_segment_state,
    );
    if (applyFeatureRows) _applyFeatureRowStates(result.feature_rows);
}

function runSegToFeat(token) {
    _runAnalysis(token, "analyze_segments", state.selected_segments, true);
}

function runFeatToSeg(token) {
    _runAnalysis(token, "analyze_features", state.selected_features, false);
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
    setStatus(`Analysis failed: ${msg.split("\n")[0]}`, STATUS_KIND.error);
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
    // Skip ``innerHTML =`` writes when the payload is identical to
    // the prior pass; ``innerHTML =`` discards + reparses even on
    // identical strings, which is the common case when an
    // FT→ST transition lands on the same selection.
    const selectionHtml = tabs.selection || "";
    const classHtml = tabs["class"] || "";
    const featuresHtml = tabs.features || "";
    const contrastsHtml = tabs.contrasts || "";
    if (state.lastAnalysisHtml === undefined) state.lastAnalysisHtml = {};
    const last = state.lastAnalysisHtml;
    if (last.selection !== selectionHtml) {
        nodes.analysisSelection.innerHTML = selectionHtml;
        last.selection = selectionHtml;
    }
    nodes.analysisSelection.hidden = selectionHtml.length === 0;
    if (last.cls !== classHtml) {
        nodes.analysisContentClass.innerHTML = classHtml;
        last.cls = classHtml;
    }
    if (last.features !== featuresHtml) {
        nodes.analysisContentFeatures.innerHTML = featuresHtml;
        last.features = featuresHtml;
    }
    if (last.contrasts !== contrastsHtml) {
        nodes.analysisContentContrasts.innerHTML = contrastsHtml;
        last.contrasts = contrastsHtml;
    }
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
    state.lastAnalysisHtml = {};
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
        max_segments: 180,
        max_vowels: 50,
        max_consonants: 135,
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
        // An uploaded file replaces the engine state; deselect the
        // dropdown so no bundled or PHOIBLE entry claims to be the
        // loaded one. The PHOIBLE group itself stays available.
        nodes.inventoryPicker.selectedIndex = -1;
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
        setStatus(`Download failed: ${e.message}`, STATUS_KIND.error);
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

    const open = () => {
        input.value = state.inventory_name || "";
        errorBox.textContent = "";
        openDialog(dialog);
        // Select-on-open so a confirming user can just retype.
        requestAnimationFrame(() => input.select());
    };
    const close = () => closeDialog(dialog);

    nodes.renameBtn.addEventListener("click", open);
    cancelBtn.addEventListener("click", close);

    form.addEventListener("submit", (ev) => {
        // method="dialog" would auto-close on submit; preventDefault
        // keeps the dialog open until the bridge confirms so a
        // validation error can be shown inline.
        ev.preventDefault();
        const newName = input.value;
        try {
            const result = callBridge("rename_current_inventory", newName);
            state.inventory_name = result.name;
            setStatus(`Renamed to ${result.name}.`, STATUS_KIND.success);
            errorBox.textContent = "";
            close();
        } catch (e) {
            errorBox.textContent = bridgeErrorMessage(e, "Rename failed.");
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

    const open = () => {
        loadDefaultsOnce();
        nameInput.value = "";
        segInput.value = "";
        // Drop any leftover provider selection from a prior open;
        // applyPreset below resets it from whatever the first picker
        // option is.
        chosenProvider = null;
        cancelProviderRefresh();
        // Default to the first preset on open so the common case
        // is one click.
        if (presetPicker.options.length > 0) {
            presetPicker.selectedIndex = 0;
            applyPreset(presetPicker.value);
        }
        errorBox.textContent = "";
        openDialog(dialog);
        requestAnimationFrame(() => nameInput.focus());
    };
    const close = () => closeDialog(dialog);

    nodes.setupCancel.addEventListener("click", () => {
        cancelProviderRefresh();
        close();
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
            close();
            // If the builder editor is open it must re-fetch the new
            // grid; the engine swap invalidated the previous state.
            if (!nodes.editorView.hidden) {
                refreshEditorFromCurrent();
            }
        } catch (e) {
            errorBox.textContent = bridgeErrorMessage(
                e, "Could not create inventory.",
            );
        }
    });

    return { open };
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
/** Drop a leading copy of the already-chosen language from a dialect
 *  label so a card under the "Korean" search reads "(Seoul)" rather
 *  than "Korean (Seoul)": the language is already shown in the field
 *  above, so repeating it on every row is noise. Only strips a clean
 *  leading match and unwraps a fully parenthesized remainder; anything
 *  else (e.g. "Standard Korean ...") is returned unchanged. */
function _trimRedundantLanguage(dialect, language) {
    if (!dialect || !language) return dialect || "";
    const d = dialect.trim();
    const lang = language.trim();
    if (!d.toLowerCase().startsWith(lang.toLowerCase())) return d;
    let rest = d.slice(lang.length).trim();
    if (rest.startsWith("(") && rest.endsWith(")")) {
        rest = rest.slice(1, -1).trim();
    }
    return rest || d;
}

function _buildSourceCard(inv, defaultId, onPick, language) {
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

    // One muted secondary line carrying the description and dialect,
    // matching the desktop row so the two clients read identically.
    const subParts = [];
    if (inv.source_description) subParts.push(inv.source_description);
    const dialectText = _trimRedundantLanguage(inv.dialect, language);
    if (dialectText) subParts.push(dialectText);
    if (subParts.length) {
        const sub = document.createElement("div");
        sub.className = "phoible-source-sub";
        sub.textContent = subParts.join("   ·   ");
        body.appendChild(sub);
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

    // Clear the source side of the picker (inventory cards + preview)
    // back to "nothing chosen". Used when the language field is
    // emptied, when a language has no inventories, and as part of a
    // full dialog reset.
    const clearInventorySelection = () => {
        nodes.phoibleInventories.hidden = true;
        nodes.phoibleRadios.innerHTML = "";
        nodes.phoiblePreview.hidden = true;
        selectedInventoryId = null;
        loadBtn.disabled = true;
    };

    const resetState = () => {
        searchInput.value = "";
        nodes.phoibleResults.hidden = true;
        nodes.phoibleResults.innerHTML = "";
        // Empty state: the hint fills the body until the user searches.
        nodes.phoibleHint.hidden = false;
        errorBox.textContent = "";
        clearInventorySelection();
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
        // Clamp at the ends; no wrap. Rolling past the last item back
        // to the first (and vice versa) is disorienting when scanning
        // a result list, so ArrowDown stops at the bottom and ArrowUp
        // stops at the top.
        if (newIndex < 0) newIndex = 0;
        if (newIndex >= items.length) newIndex = items.length - 1;
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
            // Hide the dropdown for empty queries; show a single
            // muted entry for non-empty queries that yielded zero
            // matches so the user reads "this surfaced no matches"
            // rather than a frozen UI.
            const query = (searchInput.value || "").trim();
            if (!query) {
                ul.hidden = true;
                return;
            }
            const li = document.createElement("li");
            li.className = "phoible-empty-hint";
            li.textContent = STATUS_TEXT.empty_phoible_search_hint
                || "No PHOIBLE inventories match this query.";
            li.setAttribute("aria-disabled", "true");
            ul.appendChild(li);
            ul.hidden = false;
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
        nodes.phoibleHint.hidden = true;
        nodes.phoibleResults.hidden = true;
        const invs = callBridge("phoible_list_inventories", languageName);
        const radios = nodes.phoibleRadios;
        radios.innerHTML = "";
        if (!invs || invs.length === 0) {
            clearInventorySelection();
            return;
        }
        // Default selection: the first listed source, matching the
        // order the cards render in (the bridge already orders the
        // list by source then id, so "first" is stable and is what
        // the user sees highlighted at the top).
        const defaultId = invs[0].id;
        for (const inv of invs) {
            radios.appendChild(
                _buildSourceCard(inv, defaultId, pickInventory, languageName),
            );
        }
        nodes.phoibleInventories.hidden = false;
        pickInventory(defaultId);
        // Continue the no-mouse flow: focus the preselected radio so
        // arrow keys walk the source cards (native radio-group
        // semantics fire ``change`` -> pickInventory) and Enter
        // submits the form, which is the Load action.
        const checked = radios.querySelector("input:checked");
        if (checked) checked.focus();
    };

    const pickInventory = (inventoryId) => {
        selectedInventoryId = inventoryId;
        const preview = callBridge("phoible_preview_inventory", inventoryId);
        if (!preview || !preview.descriptor) {
            nodes.phoiblePreview.hidden = true;
            loadBtn.disabled = true;
            return;
        }
        const { segments, segment_total, feature_count } = preview;
        // Caption only what the selected source card does NOT already
        // show. The card carries the source name, segment count, and
        // dialect; the feature count is the one datum it lacks, so show
        // just that. The chips below are self-evidently the segments
        // (with a "+N more" sample cue), so no "segments" label is
        // needed and the word never appears twice on screen.
        nodes.phoibleSummary.textContent = `${feature_count} features`;
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

    const close = () => closeDialog(dialog);

    const open = async () => {
        // Open with the active panel only when PHOIBLE data is
        // ready; otherwise show the spinner while the background
        // preload finishes (or start one if none is running yet).
        const ready = callBridge("phoible_is_ready");
        nodes.phoibleLoading.hidden = ready;
        nodes.phoibleActive.hidden = !ready;
        openDialog(dialog);
        resetState();

        if (!ready) {
            try {
                await ensurePhoibleData();
            } catch (e) {
                nodes.phoibleLoading.textContent =
                    "Could not load PHOIBLE data: "
                    + bridgeErrorMessage(e, String(e));
                return;
            }
            nodes.phoibleLoading.hidden = true;
            nodes.phoibleActive.hidden = false;
        }
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
            setStatus(
                "PHOIBLE data is not available in this build.",
                STATUS_KIND.warning,
            );
            return;
        }
        open();
    });

    // Autocomplete debounce.
    searchInput.addEventListener("input", () => {
        if (searchTimer) {
            window.clearTimeout(searchTimer);
            searchTimer = 0;
        }
        const query = searchInput.value;
        if (query.trim() === "") {
            // Deleting the typed language returns the picker to its
            // empty state: the hint reappears and any half-made source
            // selection is cleared, rather than stranding stale cards.
            nodes.phoibleResults.hidden = true;
            nodes.phoibleResults.innerHTML = "";
            clearInventorySelection();
            nodes.phoibleHint.hidden = false;
            return;
        }
        // Typing means we have left the empty state; the result list (or
        // the source cards) owns the body from here.
        nodes.phoibleHint.hidden = true;
        searchTimer = window.setTimeout(() => {
            const trimmed = query.trim();
            const matches = callBridge(
                "phoible_search_languages", trimmed, 20,
            );
            // Auto-advance on an unambiguous exact match: typing a full
            // language name that is the SOLE result skips the redundant
            // one-row dropdown (which would just repeat the text already
            // in the input) and shows that language's sources directly.
            if (
                matches && matches.length === 1
                && matches[0].toLowerCase() === trimmed.toLowerCase()
            ) {
                pickLanguage(matches[0]);
                return;
            }
            renderResults(matches);
        }, SEARCH_DEBOUNCE_MS);
    });

    // Keyboard navigation for the autocomplete dropdown. ArrowDown
    // and ArrowUp move through the result list and stop at the ends
    // (no wrap); Enter picks the highlighted entry (or the first one
    // when nothing is yet highlighted but results are visible); Escape
    // closes the dropdown without committing. Default Tab behaviour is
    // kept so the user can leave the dropdown open and tab to the
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
        if (ev.key === "Home") {
            if (!items.length || ul.hidden) return;
            ev.preventDefault();
            setHighlight(0);
            return;
        }
        if (ev.key === "End") {
            if (!items.length || ul.hidden) return;
            ev.preventDefault();
            setHighlight(items.length - 1);
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

    // Source-card navigation. A native radio group WRAPS on the arrow
    // keys (past the last source rolls to the first), which the user
    // found disorienting when selecting an inventory. Intercept the
    // arrows and clamp at the ends instead, moving + checking +
    // previewing the target source. ``preventDefault`` suppresses the
    // browser's built-in wrapping radio navigation.
    nodes.phoibleRadios.addEventListener("keydown", (ev) => {
        const NAV = [
            "ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Home", "End",
        ];
        if (!NAV.includes(ev.key)) return;
        const radios = Array.from(
            nodes.phoibleRadios.querySelectorAll('input[type="radio"]')
        );
        if (radios.length < 2) return;
        ev.preventDefault();
        let idx = radios.findIndex(
            (r) => r.checked || r === document.activeElement
        );
        if (idx < 0) idx = 0;
        let next;
        if (ev.key === "Home") {
            next = 0;
        } else if (ev.key === "End") {
            next = radios.length - 1;
        } else {
            const forward = ev.key === "ArrowDown" || ev.key === "ArrowRight";
            next = forward
                ? Math.min(idx + 1, radios.length - 1)
                : Math.max(idx - 1, 0);
        }
        if (next === idx) return;
        const radio = radios[next];
        // Programmatic ``checked`` does not fire ``change``, so drive
        // the preview explicitly (same path the change handler uses).
        radio.checked = true;
        radio.focus();
        pickInventory(radio.value);
    });

    nodes.phoibleCancel.addEventListener("click", close);

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
            // Cache the loaded inventory in the toolbar dropdown's
            // PHOIBLE group so it can be reloaded later without
            // searching again.
            addPhoibleDropdownEntry(selectedInventoryId, info.name);
            // Terse shared-side composition (language + source +
            // counts); the fallback covers an older bridge without
            // the field.
            setStatus(
                info.status
                || `Loaded ${info.name} `
                + `(${info.segments.length} segments, `
                + `${info.features.length} features).`,
            );
            errorBox.textContent = "";
            close();
            // If the editor is open, re-fetch its grid against the
            // new engine state.
            if (!nodes.editorView.hidden) {
                refreshEditorFromCurrent();
            }
        } catch (e) {
            errorBox.textContent = bridgeErrorMessage(
                e, "Could not load inventory.",
            );
        }
    });
}


// ----------------------------------------------------------------------
// Builder / editor: web-side state machine.
//
// This section (~main.js:1675-3000) is the second large state machine
// in the file and mirrors the desktop's ``InventoryBuilder``
// (``desktop/src/phonology_features/gui/builder/window.py``). Strategy:
//
//  * **Pure logic lives in Python** (``editor/grid.py``,
//    ``editor/setup.py``) and is consumed via the bridge or via
//    constants fetched once at editor open (cycle ladder, value
//    keys, move keys, undo depth cap, add-label validators, remove
//    prompts, max-segments / max-features caps).
//
//  * **DOM mutation, event wiring, selection painting, keyboard
//    dispatch, and undo/redo state live in JS** because per-event
//    bridge hops would lag on rapid shift-drag and keyboard repeat.
//
//  * **Two surfaces that mirror Python logic locally** are
//    parity-tested in ``shared/tests/test_editor_mirror_parity.py``:
//      - ``classifyEditorSelection`` mirrors
//        ``editor/grid.classify_selection``
//      - ``SELECTION_SHAPE_REMOVE_TARGET`` mirrors
//        ``editor/grid.SELECTION_SHAPE_REMOVE_TARGET``
//    Edit either side and the parity test catches the drift.
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
    // Right-click a column header to rename that segment inline.
    nodes.editorGridScroll.addEventListener("contextmenu", onGridContextMenu);
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
        setEditorStatus(
            `Could not load grid: ${bridgeErrorMessage(e, "error")}`,
        );
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
    refreshEditorCapCounter();
    setEditorStatus(
        `${editorState.segments.length} segments × `
        + `${editorState.features.length} features`,
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

// Editor-grid sizing: cached arithmetic, not per-render reflow.
//
// The grid's four panes are separate tables that must resolve to one
// shared pixel column grid. Instead of rendering at natural width,
// forcing a synchronous reflow, and reading offsetWidth/offsetHeight
// for every cell on every edit, we measure glyph advance widths on a
// canvas (cached) and size columns/rows by pure arithmetic, applying
// pretext's "measure once with the font engine, then layout is
// arithmetic" idea. The per-cell box overhead (padding + collapsed
// border) and the single-line row height are page-constant, calibrated
// once from a real cell.
let _editorCellCalibration = null;
const _editorTextWidthCache = new Map();

function _calibrateEditorCell(cell) {
    const cs = getComputedStyle(cell);
    return {
        family: cs.fontFamily || "monospace",
        sizePx: parseFloat(cs.fontSize) || 13,
        // Upper bound on horizontal chrome: full padding + full declared
        // border. ``border-collapse`` makes the painted border <= this,
        // so a column is never narrower than its content needs (no clip)
        // and at most ~1px wider than the old natural width.
        chromeW:
            (parseFloat(cs.paddingLeft) || 0)
            + (parseFloat(cs.paddingRight) || 0)
            + (parseFloat(cs.borderLeftWidth) || 0)
            + (parseFloat(cs.borderRightWidth) || 0),
        // Single-line cells, so every row is the same height; measured
        // once and exact (no min-height to contaminate it).
        rowH: cell.offsetHeight,
        minW: parseFloat(cs.minWidth) || 0,
    };
}

function _editorTextWidth(text, weight, cal) {
    const font = `${weight} ${cal.sizePx}px ${cal.family}`;
    const key = `${font} ${text}`;
    const hit = _editorTextWidthCache.get(key);
    if (hit !== undefined) return hit;
    _segMeasureCtx.font = font;
    const w = _segMeasureCtx.measureText(text).width;
    _editorTextWidthCache.set(key, w);
    return w;
}

function _editorColumnWidthPx(headerText, dataWidth, cal) {
    const headerW = _editorTextWidth(headerText, "bold", cal);
    return Math.max(
        cal.minW,
        Math.ceil(Math.max(headerW, dataWidth)) + cal.chromeW,
    );
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
    // Remove any prior colgroup / fixed layout. These are WRITES (no
    // forced reflow); the old ``void dataTable.offsetWidth`` read and
    // the per-cell offsetWidth reads are gone. Widths are now cached
    // canvas arithmetic, calibrated once for the constant box overhead.
    dataTable.style.tableLayout = "";
    if (colsTable) colsTable.style.tableLayout = "";
    dataTable.querySelectorAll("colgroup").forEach((c) => c.remove());
    colsTable?.querySelectorAll("colgroup").forEach((c) => c.remove());

    const firstRow = dataTable.querySelector("tr");
    const colHeaders = [...nodes.editorGridCols.querySelectorAll("th")];
    const dataCells = firstRow ? [...firstRow.querySelectorAll("td")] : [];
    if (_editorCellCalibration === null && colHeaders.length) {
        // First call runs while the table is still in natural layout
        // (the colgroup was just removed), so the calibration cell's
        // offsetHeight is the true single-line row height. Cached after.
        _editorCellCalibration = _calibrateEditorCell(colHeaders[0]);
    }
    const cal = _editorCellCalibration;
    const dataWidth = cal
        ? Math.max(
            _editorTextWidth(MINUS_DISPLAY, "normal", cal),
            _editorTextWidth("+", "normal", cal),
            _editorTextWidth("0", "normal", cal),
        )
        : 0;
    const widths = cal
        ? colHeaders.map((th) =>
            _editorColumnWidthPx(th.textContent || "", dataWidth, cal))
        : [];
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

    // Every row is one line of text in the same font, so row height is
    // the page-constant calibrated above. Stamp it on both panes' rows
    // directly, with no reset-then-reflow and no per-row offsetHeight
    // reads.
    const rowHeaders = [...nodes.editorGridRows.querySelectorAll("tr")];
    const dataRows = [...dataTable.querySelectorAll("tr")];
    if (cal) {
        const px = `${cal.rowH}px`;
        for (const tr of rowHeaders) tr.style.height = px;
        for (const tr of dataRows) tr.style.height = px;
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
        // Mirror classify_selection in shared/editor/grid.py: in a
        // degenerate grid one selected cell is a whole column (single
        // row) or whole row (single column), so it must classify as
        // such or the remove-segment / remove-feature buttons never
        // enable for a 1-feature or 1-segment inventory. A true 1x1
        // grid stays single_cell (its last seg/feature cannot be cut).
        if (numRows === 1 && numCols > 1) {
            return { kind: "single_column", column: c };
        }
        if (numCols === 1 && numRows > 1) {
            return { kind: "single_row", row: r };
        }
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
    pushUndoEdit({ kind: "cells", cells, new: value });
    markEditorDirty();
    // A value change can flip syllabic (or another classifying
    // feature) and move a segment between vowel and consonant.
    scheduleEditorCapRefresh();
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
    // Undo / redo restores values that can reclassify segments.
    scheduleEditorCapRefresh();
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

// Structural-edit primitives -----------------------------------------
//
// Add / remove segment, add / remove feature, and rename segment are
// all undoable, sharing the one undo stack with cell edits. Each
// records enough to reconstruct the prior state (the removed column /
// row values, the old name) so undo and redo are exact inverses.
// Mirrors the desktop builder's structural-edit records.

function _insertSegmentAt(index, seg, col) {
    editorState.segments.splice(index, 0, seg);
    for (let r = 0; r < editorState.cells.length; r++) {
        editorState.cells[r].splice(index, 0, col[r] ?? ZERO_VALUE);
    }
}

function _removeSegmentAt(index) {
    const col = editorState.cells.map((row) => row[index]);
    editorState.segments.splice(index, 1);
    for (const row of editorState.cells) row.splice(index, 1);
    return col;
}

function _insertFeatureAt(index, feat, row) {
    editorState.features.splice(index, 0, feat);
    editorState.cells.splice(index, 0, row.slice());
}

function _removeFeatureAt(index) {
    const row = editorState.cells[index].slice();
    editorState.features.splice(index, 1);
    editorState.cells.splice(index, 1);
    return row;
}

/** Re-run a structural edit after undo (or re-apply on first push is
 *  not needed; the mutating handler did that). Returns true when it
 *  handled a structural kind so the caller can rebuild the grid. */
function _applyStructural(edit, revert) {
    switch (edit.kind) {
        case "segAdd":
            if (revert) _removeSegmentAt(edit.index);
            else _insertSegmentAt(edit.index, edit.seg, edit.col);
            return true;
        case "segRemove":
            if (revert) _insertSegmentAt(edit.index, edit.seg, edit.col);
            else _removeSegmentAt(edit.index);
            return true;
        case "featAdd":
            if (revert) _removeFeatureAt(edit.index);
            else _insertFeatureAt(edit.index, edit.feat, edit.row);
            return true;
        case "featRemove":
            if (revert) _insertFeatureAt(edit.index, edit.feat, edit.row);
            else _removeFeatureAt(edit.index);
            return true;
        case "segRename":
            editorState.segments[edit.index] =
                revert ? edit.oldName : edit.newName;
            return true;
        default:
            return false;
    }
}

/** Reverse an edit (undo) or re-apply it (redo). ``revert`` true =
 *  undo. Cell edits paint in place; structural edits rebuild the
 *  grid + selection + cap counter. */
function _stepEdit(edit, revert) {
    if (_applyStructural(edit, revert)) {
        renderEditorGrid();
        clearSelection();
        scheduleEditorCapRefresh();
        return;
    }
    // "cells" kind (or a legacy entry with no kind).
    applyEdit(edit, revert);
}

function _editDescription(edit) {
    switch (edit.kind) {
        case "segAdd": return `add of segment '${edit.seg}'`;
        case "segRemove": return `removal of segment '${edit.seg}'`;
        case "featAdd": return `add of feature '${edit.feat}'`;
        case "featRemove": return `removal of feature '${edit.feat}'`;
        case "segRename":
            return `rename of '${edit.oldName}' to '${edit.newName}'`;
        default: {
            const n = edit.cells.length;
            return `${n} cell change${_pluralS(n)}`;
        }
    }
}

function _undoRedoMessage(edit, isUndo) {
    if (edit.kind === undefined || edit.kind === "cells") {
        const n = edit.cells.length;
        return _formatTpl(
            isUndo ? "undid_template" : "redid_template",
            isUndo
                ? "Undid {n} cell change{plural}."
                : "Redid {n} cell change{plural}.",
            { n, plural: _pluralS(n) },
        );
    }
    return `${isUndo ? "Undid" : "Redid"} ${_editDescription(edit)}.`;
}

function undo() {
    const edit = editorState.undoStack.pop();
    if (edit === undefined) {
        setEditorStatus(STATUS_TEXT.undo_nothing_message || "Nothing to undo.");
        return;
    }
    _stepEdit(edit, true);
    editorState.redoStack.push(edit);
    markEditorDirty();
    setEditorStatus(_undoRedoMessage(edit, true));
}

function redo() {
    const edit = editorState.redoStack.pop();
    if (edit === undefined) {
        setEditorStatus(STATUS_TEXT.redo_nothing_message || "Nothing to redo.");
        return;
    }
    _stepEdit(edit, false);
    editorState.undoStack.push(edit);
    markEditorDirty();
    setEditorStatus(_undoRedoMessage(edit, false));
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
/** Right-click a column header to edit (rename) that segment inline.
 *  Mirrors the desktop builder's header double-click rename. The
 *  edit commits on blur ("clicking away sets whatever the segment
 *  currently is") or Enter, and cancels on Escape. A real change is
 *  pushed onto the undo stack so Ctrl-Z reverts it. */
function onGridContextMenu(ev) {
    const target = ev.target;
    if (!(target instanceof HTMLElement)) return;
    const th = target.closest("th[data-col]");
    if (th === null || !nodes.editorGridCols.contains(th)) return;
    ev.preventDefault();
    const c = Number(th.dataset.col);
    if (!Number.isInteger(c) || c < 0 || c >= editorState.segments.length) {
        return;
    }
    startSegmentRename(th, c);
}

function startSegmentRename(th, c) {
    if (th.querySelector("input") !== null) return;  // already editing
    const oldName = editorState.segments[c];
    const input = document.createElement("input");
    input.type = "text";
    input.className = "editor-rename-input";
    input.value = oldName;
    input.setAttribute("aria-label", `Rename segment ${oldName}`);
    th.textContent = "";
    th.appendChild(input);
    input.focus();
    input.select();
    let settled = false;
    const finish = (cancel) => {
        if (settled) return;
        settled = true;
        const proposed = cancel ? oldName : input.value.trim();
        commitSegmentRename(c, oldName, proposed);
    };
    input.addEventListener("blur", () => finish(false));
    input.addEventListener("keydown", (kev) => {
        // Keep the grid's own key handler (cycle / move / undo) from
        // also firing while the rename input has focus.
        kev.stopPropagation();
        if (kev.key === "Enter") {
            kev.preventDefault();
            input.blur();
        } else if (kev.key === "Escape") {
            kev.preventDefault();
            finish(true);
        }
    });
}

function commitSegmentRename(c, oldName, proposed) {
    // No change, empty, or a duplicate of another segment: restore the
    // header text and leave the model (and undo stack) untouched.
    const duplicate = editorState.segments.some(
        (s, i) => i !== c && s === proposed,
    );
    if (proposed === "" || proposed === oldName || duplicate) {
        renderEditorGrid();
        if (duplicate) {
            setEditorStatus(
                `Segment '${proposed}' already exists; rename cancelled.`,
            );
        }
        return;
    }
    editorState.segments[c] = proposed;
    pushUndoEdit({
        kind: "segRename", index: c, oldName, newName: proposed,
    });
    renderEditorGrid();
    clearSelection();
    markEditorDirty();
    scheduleEditorCapRefresh();
    setEditorStatus(`Renamed segment '${oldName}' to '${proposed}'.`);
    // Restore grid focus so Ctrl-Z undoes the rename immediately.
    focusEditorGrid();
}

/** Return keyboard focus to the grid after a toolbar- or
 *  context-menu-driven structural edit (add / remove / rename). The
 *  undo keydown handler is scoped to ``#editor-grid-scroll``; without
 *  this, focus stays on the toolbar button (or the rename input) and
 *  the user has to click a cell before Ctrl-Z / Ctrl-Y do anything.
 *  Restoring focus lets undo / redo work immediately after the edit. */
function focusEditorGrid() {
    nodes.editorGridScroll.focus();
}

function addSegmentToState(seg) {
    const index = editorState.segments.length;
    editorState.segments.push(seg);
    for (const row of editorState.cells) {
        row.push(ZERO_VALUE);
    }
    pushUndoEdit({
        kind: "segAdd",
        index,
        seg,
        col: editorState.cells.map(() => ZERO_VALUE),
    });
    renderEditorGrid();
    clearSelection();
    markEditorDirty();
    scheduleEditorCapRefresh();
    setEditorStatus(_formatTpl(
        "added_segment_template", "Added segment '{seg}'.", { seg },
    ));
    focusEditorGrid();
}

function addFeatureToState(feat) {
    const index = editorState.features.length;
    const row = Array.from(
        { length: editorState.segments.length }, () => ZERO_VALUE,
    );
    editorState.features.push(feat);
    editorState.cells.push(row.slice());
    pushUndoEdit({ kind: "featAdd", index, feat, row });
    renderEditorGrid();
    clearSelection();
    markEditorDirty();
    scheduleEditorCapRefresh();
    setEditorStatus(_formatTpl(
        "added_feature_template", "Added feature '{feat}'.", { feat },
    ));
    focusEditorGrid();
}

function removeSelectedSegment() {
    const c = getSingleSelectedColumn();
    if (c === null) return;
    const seg = editorState.segments[c];
    // Confirm prompt text comes from the shared Python so the web
    // wording matches the desktop's ``ask_question`` body exactly.
    const prompt = callBridge("confirm_remove_segment_prompt", seg);
    if (!confirm(prompt)) return;
    // Capture the column values BEFORE the splice so undo can restore
    // the segment with its feature values intact.
    const col = editorState.cells.map((row) => row[c]);
    editorState.segments.splice(c, 1);
    for (const row of editorState.cells) {
        row.splice(c, 1);
    }
    pushUndoEdit({ kind: "segRemove", index: c, seg, col });
    renderEditorGrid();
    clearSelection();
    markEditorDirty();
    scheduleEditorCapRefresh();
    setEditorStatus(_formatTpl(
        "removed_segment_template", "Removed segment '{seg}'.", { seg },
    ));
    // Restore grid focus so Ctrl-Z undoes the deletion immediately,
    // without the user first clicking a cell.
    focusEditorGrid();
}

function removeSelectedFeature() {
    const r = getSingleSelectedRow();
    if (r === null) return;
    const feat = editorState.features[r];
    const prompt = callBridge("confirm_remove_feature_prompt", feat);
    if (!confirm(prompt)) return;
    // Capture the row values BEFORE the splice so undo can restore the
    // feature with its per-segment values intact.
    const row = editorState.cells[r].slice();
    editorState.features.splice(r, 1);
    editorState.cells.splice(r, 1);
    pushUndoEdit({ kind: "featRemove", index: r, feat, row });
    renderEditorGrid();
    clearSelection();
    markEditorDirty();
    scheduleEditorCapRefresh();
    setEditorStatus(_formatTpl(
        "removed_feature_template", "Removed feature '{feat}'.", { feat },
    ));
    // Restore grid focus so Ctrl-Z undoes the deletion immediately,
    // without the user first clicking a cell.
    focusEditorGrid();
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
        setEditorStatus(`Save failed: ${bridgeErrorMessage(e, "error")}`);
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

// Live cap counter. Classification needs the shared Python
// ``group_segments`` (the single source the charts and the
// save-time enforcement use), so the count comes from a bridge
// call rather than a JS re-implementation. Debounced because cell
// cycling can fire in quick succession; a 120 ms coalesce keeps a
// rapid bulk edit to one round-trip without the counter visibly
// lagging the grid.
let _capRefreshTimer = null;

function scheduleEditorCapRefresh() {
    if (_capRefreshTimer !== null) clearTimeout(_capRefreshTimer);
    _capRefreshTimer = setTimeout(() => {
        _capRefreshTimer = null;
        refreshEditorCapCounter();
    }, 120);
}

function refreshEditorCapCounter() {
    const counter = nodes.editorCapCounter;
    if (!counter) return;
    if (!editorState.open || editorState.segments.length === 0) {
        counter.hidden = true;
        return;
    }
    let status;
    try {
        status = callBridge(
            "inventory_cap_status_for_grid",
            editorState.segments,
            editorState.features,
            editorState.cells,
        );
    } catch {
        // Bridge not ready (editor opened pre-boot) or a transient
        // marshalling failure: leave the last good counter in place
        // rather than blanking it.
        return;
    }
    counter.textContent = status.text;
    // ``data-severity`` drives the warn / error colour in style.css
    // (ok = default muted text). Mirrors the desktop's palette map.
    counter.dataset.severity = status.severity;
    counter.hidden = false;
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
            nodes.labelPromptError.textContent = bridgeErrorMessage(
                e, "Invalid label.",
            );
            nodes.labelPromptInput.focus();
            return;
        }
        closeLabelPrompt();
        pending.onAccept(canonical);
    });
}

/** Theme values come from the relayed ``STATUS_TEXT.theme_values``
 *  baked from ``palette.Theme`` (Python SSOT). Hardcoded fallback
 *  only fires if the inlined JSON is missing. */
const THEME = Object.freeze(
    STATUS_TEXT.theme_values || { LIGHT: "light", DARK: "dark" },
);

/** localStorage is external input: anything that isn't an
 *  acknowledged theme value falls back to LIGHT. Validates
 *  against the relayed list so a future Python addition (e.g.
 *  a high-contrast theme) is accepted automatically once baked. */
function normalizeTheme(value) {
    const known = new Set(Object.values(THEME));
    return known.has(value) ? value : THEME.LIGHT;
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

/** Palette-mode values come from the relayed
 *  ``STATUS_TEXT.palette_mode_values`` baked from
 *  ``palette.PaletteMode`` (Python SSOT). Hardcoded fallback only
 *  fires if the inlined JSON is missing. */
const PALETTE_MODE = Object.freeze(
    STATUS_TEXT.palette_mode_values || {
        STANDARD: "standard",
        COLORBLIND: "colorblind",
    },
);

/** localStorage is external input: anything that isn't an
 *  acknowledged palette-mode value falls back to STANDARD.
 *  Validates against the relayed list so a future Python addition
 *  is accepted automatically once baked. */
function normalizePaletteMode(value) {
    const known = new Set(Object.values(PALETTE_MODE));
    return known.has(value) ? value : PALETTE_MODE.STANDARD;
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

/** Matching-mode toggle ("Strict" vs. "Wildcard"). Mirrors the
 *  colorblind toggle's structure: persistent localStorage choice,
 *  aria-pressed on the button, and a bridge sync so the Python
 *  side recomputes natural-class results under the chosen
 *  semantics.
 *
 *  Wildcard mode treats a segment's ``0`` or absent value as
 *  compatible with either polarity of a requested feature, so a
 *  ``+Voice`` query returns +Voice AND 0Voice segments. The
 *  feature pane also surfaces features that are uniformly ``0``
 *  (otherwise unselectable) because those features ARE queryable
 *  under wildcard: every segment matches.
 */
const MATCH_MODE = Object.freeze(
    STATUS_TEXT.match_mode_values || {
        STRICT: "strict",
        WILDCARD: "wildcard",
    },
);

/** localStorage is external input: anything other than the
 *  wildcard sentinel reads as strict. */
function normalizeMatchMode(value) {
    return value === MATCH_MODE.WILDCARD
        ? MATCH_MODE.WILDCARD
        : MATCH_MODE.STRICT;
}

/** Push the user's restored matching mode (set by
 *  wireMatchModeToggle before the bridge attached) into Python.
 *  Without this, all natural-class results stay on strict even
 *  when the toolbar shows the wildcard toggle pressed. */
function _syncBridgeMatchModeToStoredState() {
    const mode = normalizeMatchMode(safeStorageGet("match_mode"));
    try {
        callBridge("set_match_mode", mode);
    } catch (e) {
        console.warn("match-mode sync to bridge failed:", e);
    }
}

function wireMatchModeToggle() {
    if (!nodes.matchModeBtn) return;
    // Tooltip strings come from the relayed STATUS_TEXT so a
    // wording change lands in one Python constant
    // (constants.MATCH_MODE_TOOLTIP_*) and propagates to both the
    // desktop's setToolTip and the web's title attribute. Defaults
    // keep the toggle usable in offline / pre-relay builds.
    const labelFor = (mode) => mode === MATCH_MODE.WILDCARD
        ? (STATUS_TEXT.match_mode_tooltip_wildcard_active
            || "Switch to strict matching (only explicit +/- values match).")
        : (STATUS_TEXT.match_mode_tooltip_strict_active
            || "Allow underspecified matches (wildcard).");
    const applyLabel = (mode) => {
        const text = labelFor(mode);
        nodes.matchModeBtn.title = text;
        nodes.matchModeBtn.setAttribute("aria-label", text);
    };
    const stored = normalizeMatchMode(safeStorageGet("match_mode"));
    if (stored === MATCH_MODE.WILDCARD) {
        document.documentElement.dataset.matchMode = "wildcard";
        nodes.matchModeBtn.setAttribute("aria-pressed", "true");
    }
    applyLabel(stored);
    nodes.matchModeBtn.addEventListener("click", () => {
        const cur = document.documentElement.dataset.matchMode === "wildcard"
            ? MATCH_MODE.WILDCARD
            : MATCH_MODE.STRICT;
        const next = cur === MATCH_MODE.WILDCARD
            ? MATCH_MODE.STRICT
            : MATCH_MODE.WILDCARD;
        if (next === MATCH_MODE.WILDCARD) {
            document.documentElement.dataset.matchMode = "wildcard";
        } else {
            delete document.documentElement.dataset.matchMode;
        }
        nodes.matchModeBtn.setAttribute(
            "aria-pressed", next === MATCH_MODE.WILDCARD ? "true" : "false"
        );
        applyLabel(next);
        safeStorageSet("match_mode", next);
        if (!state.bridge) return;
        // Bridge call order:
        //   1. set_match_mode flips the active mode and invalidates
        //      the analyze_* lru_caches.
        //   2. inventory_summary_for_mode rebuilds the feature-pane
        //      payload under the new mode so all-0 features appear
        //      (wildcard) / disappear (strict).
        //   3. runAnalysis re-renders the current selection under
        //      the new mode.
        callBridge("set_match_mode", next);
        // Capture BEFORE the feature-pane rebuild so a selection made
        // under the old mode still drives the re-analysis below.
        const hadSelection =
            state.selected_segments.length > 0
            || Object.keys(state.selected_features).length > 0;
        try {
            const info = callBridge("inventory_summary_for_mode", next);
            if (info) {
                // Rebuild ONLY the feature pane (the active-feature set
                // changes: all-0 features appear in wildcard / disappear
                // in strict). Do NOT call applyInventoryInfo here: that
                // is the full inventory-SWAP routine, which clears the
                // segment + feature selection, blanks the analysis, and
                // wipes the PHOIBLE provenance chip + Source link. The
                // desktop's _toggle_match_mode likewise keeps the
                // selection and only repopulates the feature rows.
                state.features = info.features;
                renderFeaturePanel(info.feature_groups);
                // Re-apply the FEAT-mode query markers from the
                // preserved selection onto the rebuilt rows (mirrors
                // activateMode's restore loop).
                if (state.mode === MODE.FEAT_TO_SEG) {
                    for (const [feat, rec] of state.feat_rows) {
                        const cur = state.selected_features[feat];
                        rec.plus.dataset.active =
                            cur === "+" ? "true" : "false";
                        rec.minus.dataset.active =
                            cur === "-" ? "true" : "false";
                        if (cur === "+" || cur === "-") {
                            rec.row.dataset.queryValue = cur;
                        } else {
                            delete rec.row.dataset.queryValue;
                        }
                    }
                }
            }
        } catch (e) {
            console.warn("match-mode inventory refresh failed:", e);
        }
        if (hadSelection) runAnalysis();
    });
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

// Option-value prefix marking the session's PHOIBLE entries in the
// toolbar dropdown. Distinct from every bundled inventory file
// path so the change handler can disambiguate.
const PHOIBLE_OPTION_PREFIX = "phoible:";

/** Session cache of PHOIBLE-loaded inventories shown in the
 *  toolbar dropdown: inventory id -> display name. Rendered as a
 *  "PHOIBLE" optgroup at the END of the picker so a once-searched
 *  inventory reloads without reopening the picker dialog, while
 *  staying visually apart from (not interspersed with) the bundled
 *  entries; saving it locally produces a regular entry through the
 *  normal flows. Not persisted across page loads. */
const phoibleDropdownEntries = new Map();

/** Rebuild the dropdown's "PHOIBLE" optgroup from the session
 *  cache. Re-appending an existing group moves it back to the end
 *  after a full picker rebuild. */
function renderPhoibleDropdownGroup() {
    const picker = nodes.inventoryPicker;
    let group = picker.querySelector("optgroup[data-phoible]");
    if (!phoibleDropdownEntries.size) {
        if (group) group.remove();
        return;
    }
    if (!group) {
        group = document.createElement("optgroup");
        group.setAttribute("data-phoible", "true");
        group.label = "PHOIBLE";
    }
    group.innerHTML = "";
    for (const [id, name] of phoibleDropdownEntries) {
        const opt = document.createElement("option");
        opt.value = PHOIBLE_OPTION_PREFIX + id;
        opt.textContent = name;
        group.appendChild(opt);
    }
    picker.appendChild(group);
}

/** Cache a picker-loaded PHOIBLE inventory in the dropdown and
 *  select its entry. Idempotent per inventory id. */
function addPhoibleDropdownEntry(inventoryId, name) {
    phoibleDropdownEntries.set(String(inventoryId), name);
    renderPhoibleDropdownGroup();
    nodes.inventoryPicker.value = PHOIBLE_OPTION_PREFIX + inventoryId;
}

function wireInventoryPicker() {
    nodes.inventoryPicker.addEventListener("change", async () => {
        const value = nodes.inventoryPicker.value;
        if (value.startsWith(PHOIBLE_OPTION_PREFIX)) {
            // Session PHOIBLE entry: reload through the bridge.
            // The data payload is already in memory, so this is a
            // cheap re-materialisation, not a new search or fetch.
            const id = value.slice(PHOIBLE_OPTION_PREFIX.length);
            try {
                const info = callBridge("load_phoible_inventory", id);
                applyInventoryInfo(info);
                setStatus(info.status || `Loaded ${info.name}.`);
            } catch (e) {
                // bridgeErrorMessage extracts the clean last line; a raw
                // PythonError.message would dump the whole traceback.
                setStatus(
                    bridgeErrorMessage(e, "Could not load inventory."),
                    STATUS_KIND.error,
                );
            }
            return;
        }
        const item = BUNDLED_INVENTORIES.find((i) => i.file === value);
        if (item) {
            // loadBundledInventory fetches the asset; without this
            // try/catch a transient fetch failure (offline, SW miss)
            // would be an unhandled rejection with no user feedback,
            // leaving the dropdown showing an inventory the engine
            // never loaded.
            try {
                await loadBundledInventory(item);
            } catch (e) {
                setStatus(
                    `Could not load ${item.label}: `
                    + bridgeErrorMessage(e, "load failed"),
                    STATUS_KIND.error,
                );
            }
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
        // Aria-label augments the visible label with the segment
        // + feature counts so screen reader users hear the same
        // metadata sighted users can glean from the status bar
        // after a load.
        const segs = item.segment_count;
        const feats = item.feature_count;
        if (typeof segs === "number" && typeof feats === "number") {
            opt.setAttribute(
                "aria-label",
                `${item.label}, ${segs} segments, ${feats} features`,
            );
        }
        picker.appendChild(opt);
    }
    // Re-append the session PHOIBLE group after the rebuild wiped
    // the picker's children.
    renderPhoibleDropdownGroup();
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
    // Clearing the selection leaves the inventory loaded, so the
    // bottom border keeps its inventory summary untouched.
}

/** Press in empty panel space activates that panel's mode.
 *  Uses ``mousedown`` (not ``click``) and accepts every button so
 *  the gesture matches the desktop's QEvent.MouseButtonPress
 *  event filter: any-button press, fires before release, no
 *  cancellable-on-drag-off behaviour. Pre-parity the web listened
 *  only for left-click on ``click`` (release-after-press), so
 *  right-clicks on empty space did nothing on web while the
 *  desktop switched modes. Right-click on empty space also gets
 *  ``preventDefault`` so the browser context menu doesn't appear
 *  over the inventory chrome. */
function wirePanelClickMode() {
    nodes.segPanel.addEventListener("mousedown", (ev) => {
        if (ev.target.closest("button")) return;
        if (ev.button === 2) ev.preventDefault();
        activateMode(MODE.SEG_TO_FEAT);
    });
    nodes.featPanel.addEventListener("mousedown", (ev) => {
        if (ev.target.closest("button")) return;
        if (ev.button === 2) ev.preventDefault();
        activateMode(MODE.FEAT_TO_SEG);
    });
    // Right-click on empty panel space: keep the contextmenu
    // suppressed even when the mousedown handler missed (some
    // browsers fire contextmenu without a preceding mousedown).
    const blockEmptyContext = (ev) => {
        if (ev.target.closest("button")) return;
        ev.preventDefault();
    };
    nodes.segPanel.addEventListener("contextmenu", blockEmptyContext);
    nodes.featPanel.addEventListener("contextmenu", blockEmptyContext);
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
    // Right-click on a segment button. Always suppress the browser
    // native context menu (no "Save image / Inspect" over the
    // inventory chrome; mirrors the desktop's
    // ``SegmentButton.contextMenuEvent`` which always calls
    // ``event.accept()``). The copy gesture only fires in
    // SEG_TO_FEAT mode; FEAT_TO_SEG is a documented no-op.
    // Pre-fix the preventDefault was nested inside the mode guard
    // so the browser menu appeared on top of the feature panel.
    nodes.segGrid.addEventListener("contextmenu", (ev) => {
        const btn = ev.target.closest(".seg-btn");
        if (!btn || !nodes.segGrid.contains(btn)) return;
        const seg = btn.dataset.seg;
        if (!seg) return;
        ev.preventDefault();
        if (state.mode !== MODE.SEG_TO_FEAT) return;
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
    // Flash (not setStatus) so the copy confirmation auto-reverts to
    // the inventory summary instead of permanently replacing it.
    const onOk = () =>
        flashStatus(tpl.replace("{seg}", seg), STATUS_KIND.success);
    const onFail = () =>
        flashStatus(`Could not copy /${seg}/`, STATUS_KIND.error);
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
    // Cache the baked --seg-btn-w / --seg-btn-gap CSS vars once
    // so the per-relayout column picker doesn't walk the cascade
    // on every splitter drag.
    _refreshButtonStrideCache();
    wireStatusbarBrand();
    wireBugButton();
    wireThemeToggle();
    wireColorblindToggle();
    wireMatchModeToggle();
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
    // The first-paint seg-button shrink measured the fallback font
    // (Charis IPA loads async), so the widest affricates are sized for
    // the narrower fallback. Re-fit once Charis is in. Idempotent and
    // safe whether or not buttons exist yet.
    if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(_refitSegButtons);
    }

    try {
        await bootPyodide({ prerendered });
        prewarmCommonAnalyses();
        // Idle-time fetch of the PHOIBLE data file so the first
        // dialog open only pays the bridge parse cost (~500 ms),
        // not the 5 MB download. Bridge load itself happens on
        // dialog open since it blocks the main thread; a future
        // worker migration would let it also happen during idle.
        schedulePhoiblePrefetch();
    } catch (e) {
            console.error(e);
        setLoadingStatus(`Failed to load: ${e.message}`);
    }
}

main();
