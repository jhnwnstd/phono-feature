// Web app bootstrap. Loads Pyodide, installs the phonology-engine
// wheel + the desktop-source renderer files, then wires UI events
// to call the Python bridge in api.py.
//
// All paths below are relative to the deployed site root, so they
// work both under `python -m http.server` locally and under GitHub
// Pages with a project subpath (the <base> tag handles the prefix).

// Required DOM nodes. Validated at boot via initNodes() so a
// missing ID fails fast at startup instead of as a null deref
// inside a click handler. The map's keys are the camelCase names
// used in JS; values are the DOM ids in index.html. Adding a new
// id means adding it here.
const NODE_IDS = Object.freeze({
    statusbar: "statusbar",
    loadingStatus: "loading-status",
    loadingOverlay: "loading-overlay",
    inventoryPicker: "inventory-picker",
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
});
const nodes = Object.create(null);
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

// ---------------------------------------------------------------------
// Boot timing instrumentation. Each phase brackets itself with two
// performance.mark calls; printBootMeasures() prints a table of
// phase durations to the devtools console after boot completes.
// Measure first, optimize second.
// ---------------------------------------------------------------------
const mark = (name) => performance.mark(name);
function measure(label, start, end) {
    try {
        performance.measure(label, start, end);
    } catch {
        // mark missing means an earlier phase failed; skip silently.
    }
}
function printBootMeasures() {
    const rows = performance
        .getEntriesByType("measure")
        .map((e) => ({ phase: e.name, ms: Math.round(e.duration) }));
    // eslint-disable-next-line no-console
    console.table(rows);
}

// Resource timing for the boot-critical network fetches. Pairs with
// printBootMeasures(): phase measures show where TIME goes, resource
// timing shows where BYTES come from. Use it to tell whether a slow
// boot is CDN latency, payload size, or local Python work.
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

// ---------------------------------------------------------------------
// fetch wrappers. Two responsibilities:
//
//   1. Throw a useful Error on non-2xx instead of returning an
//      HTML 404 page that .json() then parses as a mystery
//      SyntaxError.
//   2. Honor a timeout by actually CANCELLING the in-flight
//      request via AbortController, not just rejecting the wait
//      promise. Without abort, a stalled CDN keeps the socket open
//      until the browser eventually drops it; we waste connection
//      slots and the rejection only tells US to give up, not the
//      network stack.
// ---------------------------------------------------------------------
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

// ---------------------------------------------------------------------
// withTimeout: rejects if ``promise`` doesn't settle within ``ms``.
// Used for non-fetch promises that we can't abort directly
// (loadPyodide, which owns its own internal network/wasm work).
// Cancellable network requests use fetchOk's AbortController instead.
// ---------------------------------------------------------------------
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

// ---------------------------------------------------------------------
// In-memory cache of inventory JSON text keyed by file path. Switching
// the dropdown to a previously-loaded inventory becomes a no-network
// hit. The Python side still re-parses; if that becomes the bottleneck
// (per the boot marks), cache the parsed bridge state too.
// ---------------------------------------------------------------------
// Bounded LRU. The underlying Map preserves insertion order, so
// "least recently used" = first key. On a cache hit we promote the
// entry by re-inserting (delete + set) so it moves to the back.
// Cap at INVENTORY_CACHE_MAX entries; over the cap, drop the
// front-most key. Without this, uploading a long sequence of files
// would grow the cache without bound -- each entry is the full JSON
// text, which the file-size cap puts at ~50 MB per slot worst case.
const INVENTORY_CACHE_MAX = 8;
const inventoryTextCache = new Map();
function _cacheGet(file) {
    if (!inventoryTextCache.has(file)) return undefined;
    const text = inventoryTextCache.get(file);
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

// ---------------------------------------------------------------------
// Pyodide bridge call wrapper. Two responsibilities:
//
//   1. Convert plain-JS args (lists/dicts) into PyProxy via toPy.
//   2. Destroy every PyProxy created in this call (the args AND the
//      Python return value before/after toJs unwraps it).
//
// PyProxy objects are NOT garbage collected automatically. Every call
// site that omitted .destroy() leaked a wrapper per click; over a
// long session that grows without bound. This wrapper makes the
// cleanup automatic.
// ---------------------------------------------------------------------
function callBridge(fnName, ...args) {
    // Guard BOTH bridge and pyodide: toPy below dereferences
    // state.pyodide before we'd otherwise notice it was still null.
    // Boot order is pyodide first, bridge last, but a click handler
    // racing the boot could land here with one set and the other not.
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
            // Nested finally so result.destroy() still runs if
            // toJs() throws (e.g. a Python object the converter
            // can't handle). Previously the destroy sat AFTER the
            // toJs call and was skipped on exception, leaking the
            // proxy.
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

// Frozen enum of the two top-level UI modes. Use MODE.SEG_TO_FEAT
// everywhere instead of the bare string so a typo becomes a
// ReferenceError at parse time instead of silently mis-comparing.
// Values match the desktop's Mode StrEnum so QSettings strings
// round-trip if we ever share persistence.
const MODE = Object.freeze({
    SEG_TO_FEAT: "seg_to_feat",
    FEAT_TO_SEG: "feat_to_seg",
});

// Per-mode status-bar prompt. Single source of truth for the two
// strings; before this they were copy-pasted at the boot site, the
// mode-switch site, and the Clear site, drifting separately every
// time wording was tweaked.
const STATUS_TEXT = Object.freeze({
    [MODE.SEG_TO_FEAT]: "Click a segment to inspect its features.",
    [MODE.FEAT_TO_SEG]:
        "Toggle feature values (+/−) to find matching segments.",
});

// Feature names come from user-uploaded inventories. An adversarial
// JSON file could ship a feature named "__proto__" / "constructor"
// / "toString"; a plain {} would let those reach Object.prototype
// or look already-set when probed. Null-prototype maps avoid that
// class of confusion. Use everywhere feat-name keys mutate.
function emptyFeatureSpec() { return Object.create(null); }
function cloneFeatureSpec(spec) {
    return Object.assign(Object.create(null), spec);
}

// State managed in JS (Python holds the engine + inventory).
const state = {
    mode: MODE.SEG_TO_FEAT,
    selected_segments: [],         // ordered for analysis consistency
    selected_features: emptyFeatureSpec(),   // {feature: "+" | "-"}
    // State of each mode at the moment we leave it. Restored on
    // toggle back so flipping modes doesn't wipe your selection.
    // Matches the desktop's _saved_seg_state / _saved_feat_state.
    saved_seg_state: [],
    saved_feat_state: emptyFeatureSpec(),
    inventory_name: "",
    segments: [],
    features: [],
    debounce_timer: null,  // setTimeout handle while pending, null otherwise
    // Monotonic counter; see scheduleAnalysis / runAnalysis. Used
    // to discard stale bridge responses if a later analysis was
    // scheduled before the earlier one's DOM update landed.
    analysis_token: 0,
    pyodide: null,
    bridge: null,                  // imported api module
    // Cached node maps populated by the render functions. Iterating
    // these in the analysis hot path is ~10x cheaper than
    // querySelectorAll(".seg-btn") on every tick; the desktop's
    // _seg_buttons / _feat_rows dicts serve the same role.
    seg_buttons: new Map(),        // seg -> HTMLButtonElement
    feat_rows: new Map(),          // feat -> {row, plus, minus}
};

// Bundled inventories come from inventories.json, which is generated
// at build time by scripts/build.py from app/inventories/*.json.
// Add a new JSON file to app/inventories/ and it appears in the
// dropdown on the next build, with the label taken from metadata.name
// in the file (falling back to a Title-Cased filename).
let BUNDLED_INVENTORIES = [];

// Asset URL resolver. In built deploys the index.html ships an
// inline JSON block (<script type="application/json"
// id="asset-manifest">) that maps logical names to content-hashed
// filenames; we read it once and cache. In raw-source dev (no
// build), the block is absent and we fall back to the unhashed
// names. This is what lets a fresh push break GitHub Pages' 600 s
// asset cache: every changed bundle gets a new URL.
const _DEFAULT_ASSET_URLS = Object.freeze({
    inventories_manifest: "inventories.json",
    python_bundle: "python_bundle.json",
});
let _ASSET_MANIFEST = null;
function assetUrl(name) {
    if (_ASSET_MANIFEST === null) {
        const el = document.getElementById("asset-manifest");
        _ASSET_MANIFEST = el
            ? JSON.parse(el.textContent)
            : {};
    }
    return _ASSET_MANIFEST[name] || _DEFAULT_ASSET_URLS[name];
}

// Boot timeouts. Pyodide cold start on a fast connection is
// typically 2-5s; 30s is a generous failure threshold. Bridge
// fetches are local to the deploy, so 10s is plenty there.
const PYODIDE_BOOT_TIMEOUT_MS = 30_000;
const LOCAL_FETCH_TIMEOUT_MS = 10_000;

// Pyodide bootstrap script (the small loader that defines the
// loadPyodide global). Injected by loadPyodideScript() AFTER the
// bootstrap render has painted, so its CDN fetch doesn't hold up
// first paint. Preloaded from index.html so the bytes are usually
// already cached by the time we ask. SRI guards against a tampered
// CDN response; bump the hash when the pinned version changes.
const PYODIDE_BOOTSTRAP_URL =
    "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js";
const PYODIDE_BOOTSTRAP_SRI =
    "sha384-i3R37b3tF+HWudsUf1VSEOY2YxwSNMqY8DQa9Z0O3xh+NkJ9o+yjcGyIi5huj+nB";

function loadPyodideScript() {
    if (typeof loadPyodide === "function") return Promise.resolve();
    return new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = PYODIDE_BOOTSTRAP_URL;
        s.integrity = PYODIDE_BOOTSTRAP_SRI;
        s.crossOrigin = "anonymous";
        s.onload = () => {
            // onload fires when the script TAG has executed, not
            // when loadPyodide is guaranteed to be defined. A
            // bizarrely-corrupted CDN response (200 OK, passes SRI,
            // but exports the wrong thing) would resolve here with
            // no global; subsequent loadPyodide({...}) would throw
            // a confusing TypeError. Verify before resolving.
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

// Preferred default-inventory filename. General IPA is the
// richest demo inventory (135 segments, 30 features) and is
// what the web app should open on first visit. Falls back to
// whatever the manifest sorts first when this file isn't in
// the build.
const PREFERRED_DEFAULT_INVENTORY = "inventories/general_features.json";

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
    // Three independent boot lanes overlap here:
    //   1. pyodide.js script tag injection + load (the small
    //      loader that defines window.loadPyodide).
    //   2. python_bundle.zip download.
    //   3. (after lane 1) loadPyodide() running WASM compile.
    // Lane 2 runs concurrently with both 1 and 3. Without these
    // overlaps the bundle fetch and the pyodide.js download both
    // sat sequentially before loadPyodide(), losing ~1-2 s on
    // cold boots.
    const bundleBytesPromise = fetchBytes(assetUrl("python_bundle"));
    await loadPyodideScript();
    const pyodidePromise = withTimeout(
        // packages: [] skips the automatic load of pyodide-py /
        // distutils that we don't use; ~100-300 ms init saved.
        // Our engine is pure Python and loads explicitly below.
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

    // Reveal the pre-rendered UI here. Remaining work (bundle
    // mount + bridge init + default inventory sync) is ~170 ms;
    // we add a small yield so the total reveal-to-ready gap
    // lands around 220 ms. That's comfortably below the 250-500
    // ms human reaction-to-click window even on slower devices,
    // without making the loading screen feel longer than it
    // needs to. The fallback path (no bootstrap) still hides
    // the overlay at the end of boot since its DOM isn't
    // populated until then.
    if (prerendered) {
        mark("overlay-hide");
        nodes.loadingOverlay.classList.add("hidden");
        setStatus("Almost ready…");
        // Yield long enough that the browser commits the overlay
        // hide as a paint frame before we start the synchronous
        // pyimport call (which blocks the main thread for ~100 ms
        // now that gui.analysis is lazy-loaded). Combined with
        // bundle mount + bridge init + inventory sync, this pads
        // the reveal-to-ready gap to ~220 ms -- comfortably under
        // human reaction-to-click time on slow devices.
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
        // DOM is already populated by applyBootstrap(). Just sync
        // the engine to the same inventory so subsequent bridge
        // calls operate on a matching state -- no re-render.
        const text = await fetchInventoryText(defaultItem.file);
        callBridge("load_inventory_json", text, defaultItem.label);
        // If the user clicked something while we were booting, the
        // optimistic visual updated but scheduleAnalysis short-
        // circuited (no bridge). Trigger now.
        const hasPending =
            state.selected_segments.length > 0
            || Object.keys(state.selected_features).length > 0;
        if (hasPending) scheduleAnalysis();
    } else {
        await loadBundledInventory(defaultItem);
    }
    mark("inventory:end");

    // Idempotent: prerendered path already hid after Pyodide load;
    // fallback path needs it here once the inventory has rendered.
    nodes.loadingOverlay.classList.add("hidden");
    setStatus(STATUS_TEXT[state.mode]);

    mark("boot:end");
    measure("Manifest fetch", "manifest:start", "manifest:end");
    measure("Pyodide load", "pyodide:start", "pyodide:end");
    measure("Python bundle mount", "bundle:start", "bundle:end");
    measure("Bridge init", "bridge:start", "bridge:end");
    measure("Default inventory", "inventory:start", "inventory:end");
    measure("Total boot", "boot:start", "boot:end");
    // Reveal lag: from overlay-hide to engine-ready. This is the
    // only window where the UI is visible but bridge calls would
    // still queue. Shrink this and the perceived loading time
    // shrinks with it.
    measure("Reveal -> ready", "overlay-hide", "boot:end");
    printBootMeasures();
    printResourceSummary();
}

function pickDefaultInventory(manifest) {
    // Prefer the named default if present; falls back to the
    // first manifest entry. Centralized so the choice is
    // discoverable and not buried in bootPyodide.
    //
    // hash_assets() renames each inventory file to
    // ``name.<10-hex>.json`` for cache-busting and rewrites the
    // manifest's ``file`` field to point at the hashed name.
    // PREFERRED_DEFAULT_INVENTORY holds the un-hashed name (the
    // constant has to be stable at runtime), so we have to strip
    // the hash before comparing. Without this the lookup misses
    // and we silently fall through to manifest[0] (English,
    // alphabetically first) -- the bootstrap renders one
    // inventory's segments while the bridge loads a different
    // inventory, leaving ghost segments stuck in 'default' state
    // when the user queries features.
    const preferred = manifest.find(
        (m) => _stripAssetHash(m.file) === PREFERRED_DEFAULT_INVENTORY,
    );
    return preferred ?? manifest[0];
}

// "inventories/general_features.116857c74f.json"
//   -> "inventories/general_features.json"
function _stripAssetHash(path) {
    return path.replace(/\.[0-9a-f]{10}(\.[^./]+)$/, "$1");
}

// Mount every Python source we ship via one fetch of
// python_bundle.json. The bundle is generated by build.py
// (write_python_bundle); main.js doesn't know which files exist,
// it just lays out whatever the bundle declares and pushes the
// declared sys.path entries. Replaces the old mountPackage +
// mountRendererPackage helpers, whose file lists had to mirror
// build-side constants by hand.
// Cheap shape check on the bundle bytes before we hand them to
// Pyodide. The first 4 bytes of any ZIP file are "PK\x03\x04"
// (local file header); a bundle that doesn't start with that is
// either truncated, served as an error page, or the wrong file.
// Fails loudly at boot with a useful message rather than ENOENT
// mid-import.
function validatePythonBundleBytes(bytes) {
    if (!(bytes instanceof Uint8Array) || bytes.length < 4) {
        throw new Error("python bundle is empty or not bytes");
    }
    const isZip = bytes[0] === 0x50 && bytes[1] === 0x4B
        && bytes[2] === 0x03 && bytes[3] === 0x04;
    if (!isZip) {
        throw new Error(
            `python bundle doesn't look like a zip `
            + `(first bytes: ${[...bytes.slice(0, 4)].map(b => b.toString(16)).join(" ")})`
        );
    }
    return bytes;
}

// Mount the build-emitted zip onto sys.path via zipimport. One
// writeFile, no per-file JS string churn -- Python imports each
// module lazily on first use. Replaces the previous JSON map +
// per-file writeFile loop.
const BUNDLE_FS_PATH = "/home/pyodide/python_bundle.zip";
function mountPythonBundle(pyodide, bundleBytes) {
    validatePythonBundleBytes(bundleBytes);
    pyodide.FS.writeFile(BUNDLE_FS_PATH, bundleBytes);
    pyodide.runPython(
        "import sys\n"
        + `if ${JSON.stringify(BUNDLE_FS_PATH)} not in sys.path:\n`
        + `    sys.path.insert(0, ${JSON.stringify(BUNDLE_FS_PATH)})\n`
    );
}

// ---------------------------------------------------------------------
// Bridge-gated controls. Toolbar controls that call into Python are
// disabled at page load and re-enabled once bootPyodide finishes. The
// loading overlay covers the panels visually, but keyboard focus can
// still reach the toolbar; disabling is the only reliable guard.
// ---------------------------------------------------------------------
const BRIDGE_GATED_NODES = ["inventoryPicker", "uploadBtn", "downloadBtn"];
function enableBridgeGatedControls() {
    for (const key of BRIDGE_GATED_NODES) nodes[key].disabled = false;
}

// ---------------------------------------------------------------------
// First-paint bootstrap: render the default inventory's segments
// grid and features panel from a build-time precomputed summary,
// BEFORE Pyodide finishes loading. Without this, the user stares
// at the loading overlay for ~4 s of WASM compile; with it, the
// IPA chart paints in under ~200 ms and the bridge attaches in
// the background.
//
// The inlined block is generated by web/scripts/build.py's
// write_bootstrap() and lives at <script id="bootstrap"
// type="application/json"> in index.html. The shape is identical
// to what callBridge("load_inventory_json", ...) returns at
// runtime, so applyBootstrap() and the post-boot reconcile share
// the same rendering code.
// ---------------------------------------------------------------------
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
    // Structural validation: a malformed bootstrap (parses but
    // missing fields) would otherwise crash deep inside
    // renderSegmentGrid / renderFeaturePanel with a useless
    // "undefined is not iterable" message, freezing the page
    // before the loading overlay can hide. Failing the check here
    // returns false; bootPyodide takes the bridge-driven path
    // instead, and the user gets a normal cold-load experience.
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

// ---------------------------------------------------------------------
// Inventory loading
// ---------------------------------------------------------------------
async function loadBundledInventory(item) {
    // Inventory text is cached after first fetch so switching the
    // dropdown to a previously-loaded inventory and back is no-network.
    const text = await fetchInventoryText(item.file);
    await loadInventoryText(text, item.label);
}

async function loadInventoryText(text, sourceLabel) {
    try {
        const info = callBridge("load_inventory_json", text, sourceLabel);
        state.inventory_name = info.name;
        state.segments = info.segments;
        state.features = info.features;
        state.selected_segments = [];
        state.selected_features = emptyFeatureSpec();
        renderSegmentGrid(info.groups, info.vowel_chart);
        renderFeaturePanel(info.feature_groups);
        nodes.analysisContent.innerHTML = "";
        setStatus(`Loaded ${info.name} (${info.segments.length} segments, ${info.features.length} features).`);
        // Inventory swap invalidated the Python-side LRU cache; warm
        // the new inventory's common selections during idle time.
        prewarmCommonAnalyses();
    } catch (e) {
        const issues = e.message ? [e.message] : ["unknown error"];
        nodes.analysisContent.innerHTML =
            "<p><b>Could not load inventory:</b></p><ul>" +
            issues.map(i => `<li>${escapeHtml(i)}</li>`).join("") +
            "</ul>";
        setStatus("Load failed.");
    }
}

// Speculative pre-warm: after boot completes, run analyze_segments
// for the first N single-segment selections during idle time. Each
// pre-warm call populates the Python-side LRU cache (added in
// api.py); when the user clicks /p/, the bridge call hits the
// cache and returns in ~5 us instead of doing ~30 ms of feature
// math + HTML rendering.
//
// Runs via requestIdleCallback so it never competes with a user
// click: the moment a real click fires, scheduleAnalysis runs and
// the browser preempts the idle queue.
const PREWARM_COUNT = 10;
// Monotonic generation counter. Each call to prewarmCommonAnalyses
// bumps it; each scheduled step captures the value at start and
// bails if a newer prewarm has begun. This prevents an in-flight
// prewarm from continuing to warm the previous inventory's segments
// against the new engine after an inventory swap (the LRU cache
// was just invalidated, so those calls would do real work and
// populate the cache with results the user can't reach).
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
        if (myGen !== _prewarmGen) return;   // newer prewarm took over
        if (i >= targets.length) return;
        try {
            // Result discarded; the side effect is the Python-side
            // cache entry. callBridge handles PyProxy cleanup so
            // dropping the return value is safe.
            callBridge("analyze_segments", [targets[i]]);
        } catch {
            // Bridge may go away during teardown; silently skip.
        }
        i++;
        idle(step);
    }
    idle(step);
}

function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
}

// ---------------------------------------------------------------------
// Segment grid: consonant groups flow as wrapping rows; vowels render
// as an IPA-style trapezoid. Placement of each vowel into a chart
// cell comes from the Python bridge (gui.vowel_layout.vowel_grid_pos)
// so it matches the desktop's VowelChartWidget cell-for-cell.
// ---------------------------------------------------------------------
function renderSegmentGrid(groups, vowelChart) {
    // Vowel chart goes FIRST in the DOM so the float-right CSS
    // pushes it to the top-right corner. Consonant groups follow as
    // plain block-level siblings; each one wraps its buttons within
    // whatever width the float left available. Groups in rows that
    // share vertical space with the chart end at the chart's left
    // edge; groups that fall below the chart take the full panel
    // width. Pure float-wrap, no per-row layout logic needed.
    const grid = nodes.segGrid;
    // innerHTML = "" removes ALL children including any spillover
    // from the previous inventory, so we don't need a separate
    // cleanup pass. Spillover lives inside #seg-grid (see
    // rebalanceSegmentSpillover for why).
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
    // After the DOM lands, check if the panel overflows; if so,
    // spill the bottom consonant groups into a 2-column area. Done
    // in a requestAnimationFrame so layout has flushed and our
    // measurements are real.
    if ("requestAnimationFrame" in window) {
        window.requestAnimationFrame(rebalanceSegmentSpillover);
    } else {
        rebalanceSegmentSpillover();
    }
}

// Move overflowing consonant groups into a 2-column spillover sub-
// grid at the bottom of the segments pane. Used when an inventory
// (typically General IPA) has more consonant groups than fit in
// the single-column flow above the analysis pane. Two columns cut
// the vertical footprint roughly in half, fitting everything in
// view without forcing the panel to scroll.
//
// Algorithm:
//   1. Move any previously-spilled groups back into #seg-grid so we
//      start from a known single-column state.
//   2. Measure: does #seg-grid still overflow .panel-body?
//   3. If yes: append .seg-spillover to .panel-body and walk
//      consonant groups bottom-up, moving each into spillover until
//      grid + spillover fit, or we've moved them all.
//
// The vowel chart is never touched -- it stays floating top-right.
function rebalanceSegmentSpillover() {
    // #seg-grid IS the .panel-body of #seg-panel (one element, two
    // hats). The spillover must therefore live INSIDE #seg-grid so
    // it inherits the same content-area positioning as the
    // consonant groups above it; appending it to grid.parentElement
    // would put it outside the panel-body's 12 px padding and
    // shift it left by 12 px relative to the consonant flow.
    const grid = nodes.segGrid;
    if (!grid) return;

    let spillover = grid.querySelector(".seg-spillover");
    if (!spillover) {
        spillover = document.createElement("div");
        spillover.className = "seg-spillover";
    }
    // Step 1: pull everything back into #seg-grid in original order,
    // then drop the spillover so step 2 measures the pristine flow.
    while (spillover.firstChild) grid.appendChild(spillover.firstChild);
    if (spillover.parentElement) spillover.remove();

    // Step 2: does the grid actually overflow? scrollHeight reports
    // the FULL content size; offsetHeight clips at the panel
    // boundary when overflow:auto is active.
    const available = grid.clientHeight;
    if (grid.scrollHeight <= available) return;

    // Step 3: enable spillover (inside the grid) and walk consonants
    // bottom-up, moving each into spillover until everything fits.
    grid.appendChild(spillover);
    const consonants = grid.querySelectorAll(":scope > .seg-group:not(.vowel-chart-group)");
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

function _buildSegmentButton(seg, extraAttrs) {
    // No per-button click handler: a single delegated listener on
    // #seg-grid (wired in wireSegmentDelegation) reads data-seg off
    // the clicked button. For Hayes that's 1 listener instead of
    // ~100; smaller listener footprint and a fresh inventory load
    // doesn't have to re-register N closures.
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

// Vowel chart: 6 height rows × 6 backness-rounding columns. The
// Python side returns row/col integers per vowel; CSS Grid places
// them. Row labels (Close, Near-close, ...) appear at the left of
// each row; column labels (Front, Central, Back) span their two
// child cells (unrounded + rounded) above the grid.
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

    // Top-left corner is empty (sits above the row-label column,
    // below the column-label row).
    const corner = document.createElement("div");
    corner.className = "vowel-chart-corner";
    chartEl.appendChild(corner);

    // Column headers (Front, Central, Back) each span 2 cells.
    chart.cols.forEach((label, i) => {
        const colHeader = document.createElement("div");
        colHeader.className = "vowel-chart-col-label";
        colHeader.textContent = label;
        // Each backness label spans its unrounded + rounded cells.
        colHeader.style.gridColumn = `${i * 2 + 2} / span 2`;
        chartEl.appendChild(colHeader);
    });

    // Row labels (Close, Near-close, ...).
    chart.rows.forEach((label, r) => {
        const rowLabel = document.createElement("div");
        rowLabel.className = "vowel-chart-row-label";
        rowLabel.textContent = label;
        rowLabel.style.gridRow = r + 2;
        rowLabel.style.gridColumn = 1;
        chartEl.appendChild(rowLabel);
    });

    // Vowel cells. The IPA cell index 0-5 maps to grid columns 2-7
    // (column 1 is the row label).
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
    // Optimistic visual flip: register the press immediately so the
    // user doesn't wait the debounce + bridge round-trip to see
    // the button respond. The bridge-driven runSegToFeat reconciles
    // afterward -- possibly upgrading other buttons to suggested /
    // matched states based on the new selection.
    // Mirrors the desktop's _on_segment_clicked, which calls
    // btn.set_state(SegmentState.SELECTED) before its debounce.
    const btn = state.seg_buttons.get(seg);
    if (btn) {
        btn.dataset.state = wasSelected ? "default" : "selected";
        btn.setAttribute("aria-pressed", wasSelected ? "false" : "true");
    }
    scheduleAnalysis();
}

// ---------------------------------------------------------------------
// Feature panel: grouped into Major Class, Laryngeal, Manner, Place,
// Tongue-Root, Prosodic, plus an Other bucket for inventory-specific
// extras.
//
// Column placement is decided by Python in api.py via
// gui.layout.distribute_feature_groups (the same module the desktop
// runs through _redistribute_feature_cards). Each group dict comes
// with a ``column`` field; we just mount each one into the right
// DOM column here. Single source of truth for the placement algo.
// ---------------------------------------------------------------------
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
        const colIndex = Math.max(0, Math.min(columnCount - 1, group.column ?? 0));
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

function _buildFeatureRow(feat) {
    // Like seg buttons, no per-button click handlers: a single
    // delegated listener on #feat-list (wireFeatureDelegation)
    // walks up to the .feat-row to recover the feature name. The
    // row is stashed in state.feat_rows together with both polarity
    // buttons so the per-click visual refresh doesn't have to call
    // querySelectorAll or rely on CSS.escape for special-char feats.
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
    // Visual refresh: the two buttons + the row-level query state
    // (data-query-value drives the row background in FEAT mode via
    // CSS, mirroring the desktop's _apply_query_style). No DOM
    // query, no CSS.escape, no string interpolation.
    const rec = state.feat_rows.get(feat);
    if (rec) {
        const cur = state.selected_features[feat];
        rec.plus.dataset.active = cur === "+" ? "true" : "false";
        rec.minus.dataset.active = cur === "-" ? "true" : "false";
        if (cur === "+" || cur === "-") rec.row.dataset.queryValue = cur;
        else delete rec.row.dataset.queryValue;
    }
    scheduleAnalysis();
}

// ---------------------------------------------------------------------
// Mode toggle (visual chrome only; actual mode lives in state.mode)
// ---------------------------------------------------------------------
function activateMode(mode) {
    if (state.mode === mode) return;

    // Snapshot + PROJECT the outgoing mode's state into the
    // incoming mode's saved slot. Projection matches the desktop's
    // _ModeController.save_outgoing_state semantics:
    //   seg→feat: feat_state = common +/- features of the selection
    //   feat→seg: seg_state  = every segment matching the query
    // The engine method
    // ``FeatureEngine.project_segments_to_features`` (and the
    // existing ``find_segments``) is the single source of truth;
    // we just call it through the bridge.
    if (state.mode === MODE.SEG_TO_FEAT) {
        state.saved_seg_state = state.selected_segments.slice();
        // Re-home the bridge result on a null prototype: Python
        // dict_converter gives us a plain {} that could carry a
        // hostile __proto__ key from a user inventory.
        state.saved_feat_state = state.bridge
            ? cloneFeatureSpec(callBridge("project_segments_to_features", state.selected_segments))
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
        // Adopt the projected seg selection; clear feat-side.
        // Row data-value/shared/contrastive/badge persist -- the
        // pending scheduleAnalysis() will overwrite them with the
        // new SEG-mode analysis, and the CSS hides the FEAT-mode
        // query rules (data-query-value) when feat panel is
        // inactive. Mirrors the desktop's behavior where the row
        // display state survives panel switches and the active
        // analysis path repaints it.
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
        // Adopt the projected feat query; clear seg-side.
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

    // Re-run analysis with the restored state so the pane reflects
    // the just-activated mode immediately.
    if (state.bridge) scheduleAnalysis();
    else nodes.analysisContent.innerHTML = "";
}

// ---------------------------------------------------------------------
// Analysis (debounced to coalesce rapid clicks)
// ---------------------------------------------------------------------
// Monotonic token for in-flight analyses. Every scheduleAnalysis
// bumps it; every runAnalysis captures the current value, runs the
// (synchronous) bridge call, and checks the token is still current
// before mutating the DOM. A rapid selection change that fires a
// second runAnalysis between the first's bridge return and its DOM
// update would otherwise paint stale state. Synchronous bridge
// calls today make the window tiny, but a future Web Worker move
// (where analyze_segments becomes async) widens it; the token
// pattern works regardless.
function scheduleAnalysis() {
    if (state.debounce_timer !== null) clearTimeout(state.debounce_timer);
    state.debounce_timer = setTimeout(() => {
        // Null the handle when the timer fires so a subsequent
        // schedule doesn't pointlessly clearTimeout a fired id.
        state.debounce_timer = null;
        runAnalysis();
    }, 30);  // tightened from 80 ms; combined with the Python-side
              // LRU cache and idle prewarm, the user perceives
              // ~10-50 ms total click-to-analysis instead of ~120 ms.
}

// Mode -> analysis handler. Lookup beats if/else for two reasons:
// adding a third mode (if one ever appears) is a one-line edit, and
// the handlers compose cleanly with the token pattern -- every
// dispatch goes through one place that bumps and forwards the token.
const MODE_HANDLERS = Object.freeze({
    [MODE.SEG_TO_FEAT]: runSegToFeat,
    [MODE.FEAT_TO_SEG]: runFeatToSeg,
});

function runAnalysis() {
    // Pre-bridge clicks queue: the optimistic visual flip and
    // selection state already updated. Bail here without throwing
    // and let bootPyodide trigger us once the bridge attaches.
    if (!state.bridge) return;
    MODE_HANDLERS[state.mode](++state.analysis_token);
}

function _isStaleToken(token) {
    return token !== state.analysis_token;
}

// Apply a per-button state derivation function over every cached
// segment button. Mirrors the desktop's _update_seg_to_feat /
// _update_feat_to_seg loops: each button's state is computed
// inline from set membership, never looked up in a dict that
// might be missing keys. This is what makes the desktop immune
// to "differently muted" ghosts -- there's no fallback branch,
// every button is explicitly placed into exactly one bucket.
function _applySegmentStates(stateFor) {
    for (const [seg, btn] of state.seg_buttons) {
        const newState = stateFor(seg);
        if (btn.dataset.state !== newState) {
            btn.dataset.state = newState;
            const pressed = (newState === "selected" || newState === "matched");
            btn.setAttribute("aria-pressed", pressed ? "true" : "false");
        }
    }
}

function runSegToFeat(token) {
    const result = callBridge("analyze_segments", state.selected_segments);
    if (_isStaleToken(token)) return;
    nodes.analysisContent.innerHTML = result.analysis_html;

    // Per-button SEG state: derive from selected + suggested sets,
    // not from a dict that might be missing keys. Mirrors desktop.
    const selectedSet = new Set(state.selected_segments);
    const suggestedSet = new Set(result.suggested || []);
    _applySegmentStates((seg) =>
        selectedSet.has(seg) ? "selected"
        : suggestedSet.has(seg) ? "suggested"
        : "default"
    );

    // Per-row feature state: same desktop pattern, three explicit
    // buckets (contrastive / shared-with-value / neutral) decided
    // inline from `common` and `contrastive`. No dict-fallback,
    // every row in state.feat_rows gets exactly one bucket.
    // Mirrors desktop's _update_seg_to_feat row loop:
    //   if feat in common AND value is +/-: shared display
    //   elif feat in contrastive: contrastive display
    //   else: neutral (includes "0" / missing values)
    const common = result.common || {};
    const contrastiveSet = new Set(result.contrastive || []);
    for (const [feat, rec] of state.feat_rows) {
        const v = common[feat];                    // "+", "-", "", "0", or undefined
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
            rec.badge.textContent = "±";      // ± matches desktop
        } else {
            rec.row.dataset.value = "";
            rec.row.dataset.shared = "false";
            rec.row.dataset.contrastive = "false";
            rec.badge.textContent = "·";      // · neutral dot
        }
    }
}

function runFeatToSeg(token) {
    const result = callBridge("analyze_features", state.selected_features);
    if (_isStaleToken(token)) return;
    nodes.analysisContent.innerHTML = result.analysis_html;

    // Same desktop-style per-button derivation: matched set wins,
    // everything else is unmatched (or default when the spec is
    // empty, which gives the panel its "no query active" look).
    const matchingSet = new Set(result.matching || []);
    const hasQuery = Object.keys(state.selected_features).length > 0;
    _applySegmentStates((seg) =>
        !hasQuery ? "default"
        : matchingSet.has(seg) ? "matched"
        : "unmatched"
    );
}

// ---------------------------------------------------------------------
// Inventory upload / download
// ---------------------------------------------------------------------
// Bundled inventories are ~10-50 KB. 5 MB ceiling is ~100x the
// typical size -- enough headroom for the wildest real inventory
// while still rejecting accidentally-selected huge files before
// we read them into memory and freeze the tab.
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
            const name = callBridge("get_current_inventory_name");
            const blob = new Blob([text], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `${name}.json`;
            a.click();
            // Defer revoke past this tick: some browsers (Safari,
            // older Firefox) hadn't actually started the download
            // by the time a synchronous revoke runs.
            setTimeout(() => URL.revokeObjectURL(url), 0);
        } catch (e) {
            setStatus(`Download failed: ${e.message}`);
        }
    });
}

// ---------------------------------------------------------------------
// Theme toggle (CSS variables + Python palette swap)
// ---------------------------------------------------------------------
const THEME = Object.freeze({ LIGHT: "light", DARK: "dark" });
// localStorage is external input. Anything other than the dark
// sentinel reads as light -- including stale or hand-edited values.
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
            // Re-run analysis only if the user has a selection; an
            // empty analysis pane has no chip colors to refresh.
            const hasSelection =
                state.selected_segments.length > 0
                || Object.keys(state.selected_features).length > 0;
            if (hasSelection) runAnalysis();
        }
    });
}

// ---------------------------------------------------------------------
// Inventory picker (bundled list + uploaded slot)
// ---------------------------------------------------------------------
function wireInventoryPicker() {
    // Picker is populated by populateInventoryPicker() AFTER the
    // build-time manifest is fetched (see bootPyodide). Wire the
    // change handler here so it survives the later DOM additions.
    nodes.inventoryPicker.addEventListener("change", () => {
        const file = nodes.inventoryPicker.value;
        const item = BUNDLED_INVENTORIES.find(i => i.file === file);
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
    // Sync the picker's selected value to the preferred default;
    // otherwise the browser auto-selects the first <option> (English,
    // alphabetically first) while pickDefaultInventory loaded the
    // actually-preferred inventory into the engine. User would see
    // the wrong inventory name in the dropdown.
    const preferred = pickDefaultInventory(BUNDLED_INVENTORIES);
    if (preferred) picker.value = preferred.file;
}

// ---------------------------------------------------------------------
// Expand/restore analysis pane
// ---------------------------------------------------------------------
function wireExpandButton() {
    nodes.expandBtn.addEventListener("click", () => {
        const pane = nodes.analysisPane;
        const expanded = pane.classList.toggle("expanded");
        nodes.expandBtn.textContent = expanded ? "⤣" : "⤢";
    });
}

// ---------------------------------------------------------------------
// Clear buttons (one per panel, both wipe the same shared state).
// Matches the desktop's "Clear means clear" semantics: each Clear
// resets both panes and the analysis pane, and activates the panel
// whose Clear was pressed.
// ---------------------------------------------------------------------
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

// ---------------------------------------------------------------------
// Clicking anywhere in a panel switches mode to that panel's mode,
// except when the click was on a button (which has its own handler).
// Equivalent to the desktop's eventFilter that listens for clicks in
// empty panel space.
// ---------------------------------------------------------------------
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

// ---------------------------------------------------------------------
// Event delegation: one click listener per container instead of one
// per button. Fewer registered closures (under Hayes: ~140 buttons
// became 2 listeners), and a fresh inventory load only has to rebuild
// DOM, not re-bind handlers. The listener walks up to the nearest
// .seg-btn / .feat-btn and reads dataset attributes for the dispatch.
// ---------------------------------------------------------------------
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

// ---------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------
// Re-run the spillover rebalance whenever the viewport changes
// size; the segments pane's available height changes with it.
// Debounced so dragging a window edge doesn't trigger the
// offsetHeight measurement loop on every pixel.
function wireSegmentSpilloverResize() {
    let timer = 0;
    window.addEventListener("resize", () => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => {
            timer = 0;
            rebalanceSegmentSpillover();
        }, 80);
    });
}

// Register the service worker after first load completes so its
// registration request doesn't compete with critical-path fetches.
// First visit: SW installs in the background and warms caches on
// initial fetches; user gets the normal cold-load experience.
// Second visit: SW serves Pyodide WASM + the python bundle from
// local cache, dropping boot from ~5 s to under 1 s.
function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    const register = () => {
        navigator.serviceWorker
            .register("./sw.js", { scope: "./" })
            // eslint-disable-next-line no-console
            .catch((e) => console.warn("SW registration failed:", e));
    };
    // Defer to after first load so the registration request
    // doesn't compete with critical-path fetches. But if main.js
    // parsed slowly enough that window.load already fired, the
    // listener would never trigger; explicitly check readyState
    // to cover that edge case.
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
    wireExpandButton();
    wireClearButtons();
    wirePanelClickMode();
    wireSegmentDelegation();
    wireFeatureDelegation();
    wireSegmentSpilloverResize();
    registerServiceWorker();

    // Paint the default inventory from the build-time bootstrap if
    // present, but DON'T drop the loading overlay yet. Doing so
    // would expose a "visible but frozen" UI for the 4-5 s it
    // takes Pyodide to compile -- clicks would queue but feel
    // broken. The overlay drops in bootPyodide right after the
    // Pyodide WASM phase ends, when only ~170 ms of bundle mount
    // + bridge init + inventory sync remain. By the time the user
    // sees the chart and decides what to click (~250-500 ms
    // human reaction time), the bridge is already ready.
    const prerendered = applyBootstrap();
    if (prerendered) {
        mark("first-paint:bootstrap");
    }

    try {
        await bootPyodide({ prerendered });
        // Engine is ready. Speculatively warm the LRU cache for
        // the first 10 single-segment selections during idle time.
        // First-click latency drops from ~120 ms to ~10 ms when
        // the user picks any of them.
        prewarmCommonAnalyses();
    } catch (e) {
        // eslint-disable-next-line no-console
        console.error(e);
        setLoadingStatus(`Failed to load: ${e.message}`);
    }
}

main();
