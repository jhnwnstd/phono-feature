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

// Boot timeouts. Pyodide cold start on a fast connection is
// typically 2-5s; 30s is a generous failure threshold. Bridge
// fetches are local to the deploy, so 10s is plenty there.
const PYODIDE_BOOT_TIMEOUT_MS = 30_000;
const LOCAL_FETCH_TIMEOUT_MS = 10_000;

// Preferred default-inventory filename. English is the smallest
// (~21 KB, 39 segments) so first paint comes up fastest. Falls
// back to whatever the manifest sorts first when this file isn't
// in the build.
const PREFERRED_DEFAULT_INVENTORY = "inventories/english_features.json";

async function bootPyodide() {
    mark("boot:start");

    setLoadingStatus("Loading inventory list…");
    mark("manifest:start");
    BUNDLED_INVENTORIES = await fetchJson("inventories.json");
    if (!BUNDLED_INVENTORIES.length) {
        throw new Error(
            "no inventories in inventories.json; check the build script"
        );
    }
    populateInventoryPicker();
    mark("manifest:end");

    setLoadingStatus("Loading the Python runtime…");
    mark("pyodide:start");
    const pyodide = await withTimeout(
        // packages: [] skips the automatic load of pyodide-py /
        // distutils that we don't use; ~100-300 ms init saved.
        // Our engine is pure Python and loads explicitly below.
        loadPyodide({ packages: [] }),
        PYODIDE_BOOT_TIMEOUT_MS,
        "Pyodide startup",
    );
    state.pyodide = pyodide;
    mark("pyodide:end");

    setLoadingStatus("Mounting the phonology engine…");
    mark("engine:start");
    // Bypass micropip entirely: the engine is pure Python with no
    // deps. We just fetch the .py files and write them into Pyodide's
    // FS at /home/pyodide/engine/phonology_engine/, then add the
    // parent dir to sys.path. Saves ~1 s vs micropip's dep-resolve +
    // METADATA-parse + wheel-extract path. Same effect at import.
    await mountPackage(pyodide, "engine/phonology_engine", [
        "__init__.py",
        "inventory.py",
        "feature_engine.py",
        "geometry.py",
        "segment_grouper.py",
    ], "/home/pyodide/engine");
    mark("engine:end");

    setLoadingStatus("Loading renderer modules…");
    mark("renderer:start");
    // The build copies palette.py / constants.py / analysis.py into
    // ./render/phonology_features/gui/ so the api.py imports resolve
    // to the same code the desktop runs.
    await mountRendererPackage(pyodide);
    mark("renderer:end");

    setLoadingStatus("Initializing the bridge…");
    mark("bridge:start");
    const apiSource = await fetchText("api.py");
    pyodide.FS.writeFile("/home/pyodide/api.py", apiSource);
    state.bridge = pyodide.pyimport("api");
    mark("bridge:end");

    enableBridgeGatedControls();
    setLoadingStatus("Loading default inventory…");
    mark("inventory:start");
    await loadBundledInventory(pickDefaultInventory(BUNDLED_INVENTORIES));
    mark("inventory:end");

    nodes.loadingOverlay.classList.add("hidden");
    setStatus(STATUS_TEXT[state.mode]);

    mark("boot:end");
    measure("Manifest fetch", "manifest:start", "manifest:end");
    measure("Pyodide load", "pyodide:start", "pyodide:end");
    measure("Engine mount", "engine:start", "engine:end");
    measure("Renderer mount", "renderer:start", "renderer:end");
    measure("Bridge init", "bridge:start", "bridge:end");
    measure("Default inventory", "inventory:start", "inventory:end");
    measure("Total boot", "boot:start", "boot:end");
    printBootMeasures();
}

function pickDefaultInventory(manifest) {
    // Prefer the explicit smallest-default if present; falls back to
    // the first manifest entry. Centralized so the choice is
    // discoverable and not buried in bootPyodide.
    const preferred = manifest.find(
        (m) => m.file === PREFERRED_DEFAULT_INVENTORY,
    );
    return preferred ?? manifest[0];
}

async function mountRendererPackage(pyodide) {
    // Replicate the package directory layout under /render/ in
    // Pyodide's FS, then add /render/ to sys.path. File list must
    // mirror RELAYED_SOURCES in web/scripts/build.py -- adding a
    // file there without also adding it here means the renderer
    // can build but api.py's import fails at boot.
    const base = "render/phonology_features";
    const files = [
        ["__init__.py", `${base}/__init__.py`],
        ["gui/__init__.py", `${base}/gui/__init__.py`],
        ["gui/palette.py", `${base}/gui/palette.py`],
        ["gui/constants.py", `${base}/gui/constants.py`],
        ["gui/layout.py", `${base}/gui/layout.py`],
        ["gui/vowel_layout.py", `${base}/gui/vowel_layout.py`],
        ["gui/analysis.py", `${base}/gui/analysis.py`],
    ];
    pyodide.FS.mkdirTree("/home/pyodide/render/phonology_features/gui");
    for (const [_local, urlPath] of files) {
        const text = await fetchText(urlPath);
        pyodide.FS.writeFile(`/home/pyodide/${urlPath}`, text);
    }
    pyodide.runPython(`
        import sys
        sys.path.insert(0, "/home/pyodide/render")
        sys.path.insert(0, "/home/pyodide")
    `);
}

// ---------------------------------------------------------------------
// Mount a Python package's source files into Pyodide's FS and add
// the package's parent directory to sys.path. Used in place of
// micropip.install for pure-Python packages we ship as source: we
// know exactly which files to fetch and where they go, so we can
// skip the wheel-format dance entirely.
//
// fsRelativePackagePath is the in-FS path of the package directory,
// e.g. "engine/phonology_engine" (mounted at /home/pyodide/<that>).
// sysPathDir is the directory to add to sys.path (the parent of the
// package), e.g. "/home/pyodide/engine".
// ---------------------------------------------------------------------
async function mountPackage(pyodide, fsRelativePackagePath, files, sysPathDir) {
    const fsAbsPackagePath = `/home/pyodide/${fsRelativePackagePath}`;
    pyodide.FS.mkdirTree(fsAbsPackagePath);
    const fetches = files.map(async (filename) => {
        const text = await fetchText(`${fsRelativePackagePath}/${filename}`);
        pyodide.FS.writeFile(`${fsAbsPackagePath}/${filename}`, text);
    });
    await Promise.all(fetches);
    // sys.path.insert is idempotent in practice -- adding the same
    // dir twice just leaves two equal entries that resolve the same.
    pyodide.runPython(
        `import sys\n`
        + `if ${JSON.stringify(sysPathDir)} not in sys.path:\n`
        + `    sys.path.insert(0, ${JSON.stringify(sysPathDir)})\n`
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
    } catch (e) {
        const issues = e.message ? [e.message] : ["unknown error"];
        nodes.analysisContent.innerHTML =
            "<p><b>Could not load inventory:</b></p><ul>" +
            issues.map(i => `<li>${escapeHtml(i)}</li>`).join("") +
            "</ul>";
        setStatus("Load failed.");
    }
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
    if (idx >= 0) {
        state.selected_segments.splice(idx, 1);
    } else {
        state.selected_segments.push(seg);
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
    // Visual refresh: just the two buttons on this row. No DOM
    // query, no CSS.escape, no string interpolation.
    const rec = state.feat_rows.get(feat);
    if (rec) {
        const cur = state.selected_features[feat];
        rec.plus.dataset.active = cur === "+" ? "true" : "false";
        rec.minus.dataset.active = cur === "-" ? "true" : "false";
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
        state.selected_segments = state.saved_seg_state.slice();
        state.selected_features = emptyFeatureSpec();
        for (const rec of state.feat_rows.values()) {
            rec.plus.dataset.active = "false";
            rec.minus.dataset.active = "false";
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
    }, 80);
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
    MODE_HANDLERS[state.mode](++state.analysis_token);
}

function _isStaleToken(token) {
    return token !== state.analysis_token;
}

function runSegToFeat(token) {
    const result = callBridge("analyze_segments", state.selected_segments);
    if (_isStaleToken(token)) return;
    nodes.analysisContent.innerHTML = result.analysis_html;
    _updateSegmentButtonStates(result.segment_states);
    // Update feature row display from cached node map: no DOM
    // query, single hash lookup per feature row.
    for (const [feat, rec] of state.feat_rows) {
        const info = result.feature_display[feat] || { value: "", shared: false };
        rec.row.dataset.value = info.value || "";
        rec.row.dataset.shared = info.shared ? "true" : "false";
        rec.row.dataset.contrastive = info.contrastive ? "true" : "false";
        rec.badge.textContent = info.value || "·";
    }
}

function runFeatToSeg(token) {
    const result = callBridge("analyze_features", state.selected_features);
    if (_isStaleToken(token)) return;
    nodes.analysisContent.innerHTML = result.analysis_html;
    _updateSegmentButtonStates(result.segment_states);
}

function _updateSegmentButtonStates(segmentStates) {
    // Centralized so aria-pressed stays in lockstep with data-state.
    // Selected/matched both read as "pressed" to assistive tech;
    // unmatched/suggested/default read as not-pressed.
    for (const [seg, btn] of state.seg_buttons) {
        const newState = segmentStates[seg] || "default";
        if (btn.dataset.state !== newState) {
            btn.dataset.state = newState;
            const pressed = (newState === "selected" || newState === "matched");
            btn.setAttribute("aria-pressed", pressed ? "true" : "false");
        }
    }
}

// ---------------------------------------------------------------------
// Inventory upload / download
// ---------------------------------------------------------------------
function wireUploadDownload() {
    nodes.uploadBtn.addEventListener("click", () => nodes.uploadInput.click());
    nodes.uploadInput.addEventListener("change", async (ev) => {
        const file = ev.target.files[0];
        if (!file) return;
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
    try {
        await bootPyodide();
    } catch (e) {
        console.error(e);
        setLoadingStatus(`Failed to load: ${e.message}`);
    }
}

main();
