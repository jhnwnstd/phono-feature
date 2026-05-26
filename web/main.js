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
    downloadBtn: "download-btn",
    segPanel: "seg-panel",
    featPanel: "feat-panel",
    segGrid: "seg-grid",
    featList: "feat-list",
    segClearBtn: "seg-clear-btn",
    featClearBtn: "feat-clear-btn",
    analysisPane: "analysis-pane",
    analysisContent: "analysis-content",
    expandBtn: "expand-btn",
    themeBtn: "theme-btn",
    renameDialog: "rename-dialog",
    renameForm: "rename-form",
    renameInput: "rename-input",
    renameError: "rename-error",
    renameCancel: "rename-cancel",
    renameSave: "rename-save",
    newBtn: "new-btn",
    setupDialog: "setup-dialog",
    setupForm: "setup-form",
    setupNameInput: "setup-name-input",
    setupSegmentsInput: "setup-segments-input",
    setupFeaturesInput: "setup-features-input",
    setupPresetPicker: "setup-preset-picker",
    setupError: "setup-error",
    setupCancel: "setup-cancel",
    setupCreate: "setup-create",
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

const setStatus = (msg) => { nodes.statusbar.textContent = msg; };
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
    // eslint-disable-next-line no-console
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
    // eslint-disable-next-line no-console
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

const STATUS_TEXT = Object.freeze({
    [MODE.SEG_TO_FEAT]: "Click a segment to inspect its features.",
    [MODE.FEAT_TO_SEG]:
        "Toggle feature values (+/−) to find matching segments.",
});

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
    // desktop's _ModeController.saved_seg_state / saved_feat_state.
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
    setStatus(STATUS_TEXT[state.mode]);

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
    const preferred = manifest.find(
        (m) => _stripAssetHash(m.file) === PREFERRED_DEFAULT_INVENTORY,
    );
    return preferred ?? manifest[0];
}

/** "name.116857c74f.json" -> "name.json" */
function _stripAssetHash(path) {
    return path.replace(/\.[0-9a-f]{10}(\.[^./]+)$/, "$1");
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
    "downloadBtn",
    "renameBtn",
    "newBtn",
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
        // eslint-disable-next-line no-console
        console.error("bootstrap parse failed; falling back to bridge", e);
        return false;
    }
    if (!_isValidBootstrap(info)) {
        // eslint-disable-next-line no-console
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
    nodes.analysisContent.innerHTML = "";
}

async function loadInventoryText(text, sourceLabel) {
    try {
        const info = callBridge("load_inventory_json", text, sourceLabel);
        applyInventoryInfo(info);
        setStatus(
            `Loaded ${info.name} `
            + `(${info.segments.length} segments, ${info.features.length} features).`
        );
        prewarmCommonAnalyses();
    } catch (e) {
        const issues = e.message ? [e.message] : ["unknown error"];
        nodes.analysisContent.innerHTML =
            "<p><b>Could not load inventory:</b></p><ul>"
            + issues.map((i) => `<li>${escapeHtml(i)}</li>`).join("")
            + "</ul>";
        setStatus("Load failed.");
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
        vowels.appendChild(_buildVowelChart(vowelChart));
        grid.appendChild(vowels);
    }
    for (const group of groups) {
        grid.appendChild(_buildConsonantGroup(group));
    }
    // Defer to next frame so layout has flushed before we measure.
    if ("requestAnimationFrame" in window) {
        window.requestAnimationFrame(rebalanceSegmentSpillover);
    } else {
        rebalanceSegmentSpillover();
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

    const available = grid.clientHeight;
    if (grid.scrollHeight <= available) return;

    grid.appendChild(spillover);
    const consonants = grid.querySelectorAll(
        ":scope > .seg-group:not(.vowel-chart-group)",
    );
    for (let i = consonants.length - 1; i >= 0; i--) {
        spillover.insertBefore(consonants[i], spillover.firstChild);
        if (grid.scrollHeight <= available) break;
    }
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
    btn.textContent = seg;
    if (extraAttrs) {
        for (const [k, v] of Object.entries(extraAttrs)) {
            if (k.startsWith("data-")) btn.setAttribute(k, v);
            else if (k === "title") btn.title = v;
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
    const header = document.createElement("div");
    header.className = "seg-group-header";
    header.textContent = "VOWELS";
    groupEl.appendChild(header);

    const chartEl = document.createElement("div");
    chartEl.className = "vowel-chart";
    chartEl.setAttribute("role", "grid");
    chartEl.setAttribute("aria-label", "IPA vowel chart");

    const corner = document.createElement("div");
    corner.className = "vowel-chart-corner";
    chartEl.appendChild(corner);

    chart.cols.forEach((label, i) => {
        const colHeader = document.createElement("div");
        colHeader.className = "vowel-chart-col-label";
        colHeader.textContent = label;
        // Each backness label spans its unrounded + rounded pair.
        colHeader.style.gridColumn = `${i * 2 + 2} / span 2`;
        chartEl.appendChild(colHeader);
    });

    chart.rows.forEach((label, r) => {
        const rowLabel = document.createElement("div");
        rowLabel.className = "vowel-chart-row-label";
        rowLabel.textContent = label;
        rowLabel.style.gridRow = r + 2;
        rowLabel.style.gridColumn = 1;
        chartEl.appendChild(rowLabel);
    });

    for (const cell of chart.cells) {
        const btn = _buildSegmentButton(cell.seg, {
            title: `/${cell.seg}/  [${cell.confidence}]  ${cell.reason}`,
        });
        btn.classList.add("vowel-chart-cell");
        btn.style.gridRow = cell.row + 2;
        btn.style.gridColumn = cell.col + 2;
        chartEl.appendChild(btn);
    }

    groupEl.appendChild(chartEl);
    return groupEl;
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
    name.textContent = feat;
    row.appendChild(name);
    const badge = document.createElement("div");
    badge.className = "feat-badge";
    badge.textContent = "·";
    row.appendChild(badge);
    const polarityButtons = {};
    for (const polarity of ["+", "−"]) {
        const btn = document.createElement("button");
        btn.className = "feat-btn";
        btn.type = "button";
        const code = polarity === "+" ? "+" : "-";
        btn.dataset.polarity = code;
        btn.textContent = polarity;
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
 * into the incoming one (mirrors desktop's _ModeController.
 * save_outgoing_state).
 *
 *   seg→feat: feat_state := common +/- features of the selection
 *   feat→seg: seg_state  := every segment matching the query
 */
function activateMode(mode) {
    if (state.mode === mode) return;

    if (state.mode === MODE.SEG_TO_FEAT) {
        state.saved_seg_state = state.selected_segments.slice();
        // cloneFeatureSpec re-homes the bridge result on a null
        // prototype to neutralize hostile "__proto__" / similar
        // feature keys.
        state.saved_feat_state = state.bridge
            ? cloneFeatureSpec(callBridge(
                "project_segments_to_features",
                state.selected_segments,
            ))
            : emptyFeatureSpec();
    } else {
        state.saved_feat_state = cloneFeatureSpec(state.selected_features);
        state.saved_seg_state = state.bridge
            ? callBridge("project_features_to_segments", state.selected_features)
            : [];
    }

    state.mode = mode;
    const isS2F = mode === MODE.SEG_TO_FEAT;
    nodes.segPanel.dataset.active = isS2F ? "true" : "false";
    nodes.featPanel.dataset.active = isS2F ? "false" : "true";

    if (isS2F) {
        state.selected_segments = state.saved_seg_state.slice();
        state.selected_features = emptyFeatureSpec();
        for (const rec of state.feat_rows.values()) {
            rec.plus.dataset.active = "false";
            rec.minus.dataset.active = "false";
            delete rec.row.dataset.queryValue;
        }
        const selectedSet = new Set(state.selected_segments);
        for (const [seg, btn] of state.seg_buttons) {
            const isSelected = selectedSet.has(seg);
            btn.dataset.state = isSelected ? "selected" : "default";
            btn.setAttribute("aria-pressed", isSelected ? "true" : "false");
        }
    } else {
        state.selected_features = cloneFeatureSpec(state.saved_feat_state);
        state.selected_segments = [];
        for (const btn of state.seg_buttons.values()) {
            if (btn.dataset.state === "selected") {
                btn.dataset.state = "default";
                btn.setAttribute("aria-pressed", "false");
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

    setStatus(STATUS_TEXT[mode]);

    if (state.bridge) scheduleAnalysis();
    else nodes.analysisContent.innerHTML = "";
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

function _isStaleToken(token) {
    return token !== state.analysis_token;
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

function runSegToFeat(token) {
    const result = callBridge("analyze_segments", state.selected_segments);
    if (_isStaleToken(token)) return;
    nodes.analysisContent.innerHTML = result.analysis_html;

    const selectedSet = new Set(state.selected_segments);
    const suggestedSet = new Set(result.suggested || []);
    _applySegmentStates((seg) =>
        selectedSet.has(seg) ? "selected"
            : suggestedSet.has(seg) ? "suggested"
            : "default"
    );

    // Per-row feature display: three explicit buckets matching the
    // desktop's _update_seg_to_feat. "0" / missing values fall to
    // neutral (NOT shared) so the row name doesn't render bold.
    const common = result.common || {};
    const contrastiveSet = new Set(result.contrastive || []);
    for (const [feat, rec] of state.feat_rows) {
        const v = common[feat];
        const isDisplayable = v === "+" || v === "-";
        const isContrastive = contrastiveSet.has(feat);
        if (isDisplayable) {
            rec.row.dataset.value = v;
            rec.row.dataset.shared = "true";
            rec.row.dataset.contrastive = "false";
            rec.badge.textContent = v;
        } else if (isContrastive) {
            rec.row.dataset.value = "";
            rec.row.dataset.shared = "false";
            rec.row.dataset.contrastive = "true";
            rec.badge.textContent = "±";
        } else {
            rec.row.dataset.value = "";
            rec.row.dataset.shared = "false";
            rec.row.dataset.contrastive = "false";
            rec.badge.textContent = "·";
        }
    }
}

function runFeatToSeg(token) {
    const result = callBridge("analyze_features", state.selected_features);
    if (_isStaleToken(token)) return;
    nodes.analysisContent.innerHTML = result.analysis_html;

    const matchingSet = new Set(result.matching || []);
    const hasQuery = Object.keys(state.selected_features).length > 0;
    _applySegmentStates((seg) =>
        !hasQuery ? "default"
            : matchingSet.has(seg) ? "matched"
            : "unmatched"
    );
}

// Inventories are typically 10-50 KB. 5 MB is ~100x the typical
// size: enough headroom for legitimate large inventories but
// catches accidentally-selected huge files before we freeze the
// tab reading them.
const MAX_INVENTORY_BYTES = 5 * 1024 * 1024;

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
        ev.target.value = "";
    });
    nodes.downloadBtn.addEventListener("click", () => {
        try {
            const text = callBridge("serialize_current_inventory");
            // Slugified default filename, generated by the same
            // suggest_filename the desktop's Save As dialog uses,
            // so the download lands in the bundled-inventories
            // naming convention (my_language_features.json).
            const filename = callBridge("get_download_filename");
            const blob = new Blob([text], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = filename;
            a.click();
            // Defer revoke past this tick: Safari and some older
            // Firefox versions haven't actually started the download
            // by the time a synchronous revoke runs.
            setTimeout(() => URL.revokeObjectURL(url), 0);
        } catch (e) {
            setStatus(`Download failed: ${e.message}`);
        }
    });
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
 * Wire the Builder button to a modal that builds a fresh all-zero
 * inventory from a name plus delimited segments and features. The
 * preset dropdown and Tab-autofill seeds come from the same
 * inventory_setup module the desktop builder uses, so the two
 * frontends offer identical defaults. Validation is server-side
 * (Pyodide-side) through validate_setup; the dialog stays open
 * on error so the user can correct without losing input.
 *
 * Future divergence (deliberately deferred): when the grid editor
 * lands, the desktop's "Builder" button branches: it opens the
 * grid editor on the loaded inventory when one is active, and
 * falls back to this setup dialog when none is. The web should
 * eventually do the same. For now the button only opens the
 * setup dialog regardless of state.
 */
function wireNewInventory() {
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
        // Populate the dropdown in insertion order. "Custom" empty list
        // gives the user a no-fill option.
        presetPicker.innerHTML = "";
        for (const name of Object.keys(presets)) {
            const opt = document.createElement("option");
            opt.value = name;
            opt.textContent = name;
            presetPicker.appendChild(opt);
        }
        defaultsLoaded = true;
    };

    const applyPreset = (name) => {
        const list = presets[name];
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

    const openDialog = () => {
        loadDefaultsOnce();
        nameInput.value = "";
        segInput.value = "";
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

    nodes.newBtn.addEventListener("click", openDialog);
    nodes.setupCancel.addEventListener("click", closeDialog);
    presetPicker.addEventListener("change", () => {
        applyPreset(presetPicker.value);
    });

    form.addEventListener("submit", (ev) => {
        ev.preventDefault();
        try {
            const info = callBridge(
                "create_new_inventory",
                nameInput.value,
                segInput.value,
                featInput.value,
            );
            applyInventoryInfo(info);
            setStatus(
                `Created ${info.name} `
                + `(${info.segments.length} segments, `
                + `${info.features.length} features).`,
            );
            errorBox.textContent = "";
            closeDialog();
        } catch (e) {
            errorBox.textContent = e.message || "Could not create inventory.";
        }
    });
}

const THEME = Object.freeze({ LIGHT: "light", DARK: "dark" });

/** localStorage is external input: anything other than the dark
 *  sentinel reads as light. */
function normalizeTheme(value) {
    return value === THEME.DARK ? THEME.DARK : THEME.LIGHT;
}

function wireThemeToggle() {
    const stored = normalizeTheme(localStorage.getItem("theme"));
    if (stored === THEME.DARK) {
        document.documentElement.dataset.theme = THEME.DARK;
        nodes.themeBtn.textContent = "☀";
    }
    nodes.themeBtn.addEventListener("click", () => {
        const cur = normalizeTheme(document.documentElement.dataset.theme);
        const next = cur === THEME.DARK ? THEME.LIGHT : THEME.DARK;
        document.documentElement.dataset.theme = next;
        nodes.themeBtn.textContent = next === THEME.DARK ? "☀" : "☾";
        localStorage.setItem("theme", next);
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

function wireInventoryPicker() {
    nodes.inventoryPicker.addEventListener("change", () => {
        const file = nodes.inventoryPicker.value;
        const item = BUNDLED_INVENTORIES.find((i) => i.file === file);
        if (item) loadBundledInventory(item);
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

function wireExpandButton() {
    nodes.expandBtn.addEventListener("click", () => {
        const pane = nodes.analysisPane;
        const expanded = pane.classList.toggle("expanded");
        nodes.expandBtn.textContent = expanded ? "⤣" : "⤢";
    });
}

function wireClearButtons() {
    nodes.segClearBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        activateMode(MODE.SEG_TO_FEAT);
        clearAll();
    });
    nodes.featClearBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        activateMode(MODE.FEAT_TO_SEG);
        clearAll();
    });
}

function clearAll() {
    state.selected_segments = [];
    state.selected_features = emptyFeatureSpec();
    for (const btn of state.seg_buttons.values()) {
        btn.dataset.state = "default";
        btn.setAttribute("aria-pressed", "false");
    }
    for (const rec of state.feat_rows.values()) {
        rec.row.dataset.value = "";
        rec.row.dataset.shared = "false";
        rec.row.dataset.contrastive = "false";
        rec.badge.textContent = "·";
        rec.plus.dataset.active = "false";
        rec.minus.dataset.active = "false";
        delete rec.row.dataset.queryValue;
    }
    nodes.analysisContent.innerHTML = "";
    setStatus(STATUS_TEXT[state.mode]);
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

/** Re-run the spillover rebalance on viewport resize. */
function wireSegmentSpilloverResize() {
    let timer = 0;
    window.addEventListener("resize", () => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => {
            timer = 0;
            rebalanceSegmentSpillover();
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
            // eslint-disable-next-line no-console
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
    wireThemeToggle();
    wireInventoryPicker();
    wireUploadDownload();
    wireRename();
    wireNewInventory();
    wireExpandButton();
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
        // eslint-disable-next-line no-console
        console.error(e);
        setLoadingStatus(`Failed to load: ${e.message}`);
    }
}

main();
