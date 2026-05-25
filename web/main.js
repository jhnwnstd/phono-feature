// Web app bootstrap. Loads Pyodide, installs the phonology-engine
// wheel + the desktop-source renderer files, then wires UI events
// to call the Python bridge in api.py.
//
// All paths below are relative to the deployed site root, so they
// work both under `python -m http.server` locally and under GitHub
// Pages with a project subpath (the <base> tag handles the prefix).

const $ = (id) => document.getElementById(id);
const setStatus = (msg) => { $("statusbar").textContent = msg; };
const setLoadingStatus = (msg) => { $("loading-status").textContent = msg; };

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
// fetch wrappers that throw a useful Error on non-2xx instead of
// returning an HTML 404 page that .json() then parses as a mystery
// SyntaxError. Use everywhere we hit network.
// ---------------------------------------------------------------------
async function fetchOk(url) {
    const r = await fetch(url);
    if (!r.ok) {
        throw new Error(`fetch ${url}: ${r.status} ${r.statusText}`);
    }
    return r;
}
async function fetchJson(url) { return (await fetchOk(url)).json(); }
async function fetchText(url) { return (await fetchOk(url)).text(); }

// ---------------------------------------------------------------------
// withTimeout: rejects if ``promise`` doesn't settle within ``ms``.
// Use on anything that could stall indefinitely (CDN fetches,
// Pyodide cold start). Without it, a stalled load leaves users on
// the loading screen forever with no error.
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
const inventoryTextCache = new Map();
async function fetchInventoryText(file) {
    if (inventoryTextCache.has(file)) return inventoryTextCache.get(file);
    const text = await fetchText(file);
    inventoryTextCache.set(file, text);
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
    if (!state.bridge) throw new Error(`bridge not ready: ${fnName}`);
    const proxies = [];
    const pyArgs = args.map((a) => {
        if (a === null || typeof a !== "object") return a;
        const p = state.pyodide.toPy(a);
        proxies.push(p);
        return p;
    });
    let result;
    try {
        result = state.bridge[fnName](...pyArgs);
        if (result && typeof result.toJs === "function") {
            const js = result.toJs({ dict_converter: Object.fromEntries });
            result.destroy();
            return js;
        }
        return result;
    } finally {
        for (const p of proxies) p.destroy();
    }
}

// State managed in JS (Python holds the engine + inventory).
const state = {
    mode: "seg_to_feat",          // or "feat_to_seg"
    selected_segments: [],         // ordered for analysis consistency
    selected_features: {},         // {feature: "+" | "-"}
    inventory_name: "",
    segments: [],
    features: [],
    debounce_timer: null,
    pyodide: null,
    bridge: null,                  // imported api module
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
    BUNDLED_INVENTORIES = await withTimeout(
        fetchJson("inventories.json"),
        LOCAL_FETCH_TIMEOUT_MS,
        "inventories manifest fetch",
    );
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
        loadPyodide(),
        PYODIDE_BOOT_TIMEOUT_MS,
        "Pyodide startup",
    );
    state.pyodide = pyodide;
    mark("pyodide:end");

    setLoadingStatus("Installing the phonology engine…");
    mark("wheel:start");
    await pyodide.loadPackage("micropip");
    const micropip = pyodide.pyimport("micropip");
    // The build script puts the wheel at ./wheels/. Glob isn't
    // available; the filename is templated by the build script.
    const wheelUrl = new URL("wheels/phonology_engine-0.1.0-py3-none-any.whl",
        document.baseURI).toString();
    await micropip.install(wheelUrl);
    micropip.destroy();
    mark("wheel:end");

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

    $("loading-overlay").classList.add("hidden");
    setStatus("Click a segment to inspect its features.");

    mark("boot:end");
    measure("Manifest fetch", "manifest:start", "manifest:end");
    measure("Pyodide load", "pyodide:start", "pyodide:end");
    measure("Engine wheel install", "wheel:start", "wheel:end");
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
    // Pyodide's FS, then add /render/ to sys.path.
    const base = "render/phonology_features";
    const files = [
        ["__init__.py", `${base}/__init__.py`],
        ["gui/__init__.py", `${base}/gui/__init__.py`],
        ["gui/palette.py", `${base}/gui/palette.py`],
        ["gui/constants.py", `${base}/gui/constants.py`],
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
// Bridge-gated controls. Toolbar controls that call into Python are
// disabled at page load and re-enabled once bootPyodide finishes. The
// loading overlay covers the panels visually, but keyboard focus can
// still reach the toolbar; disabling is the only reliable guard.
// ---------------------------------------------------------------------
const BRIDGE_GATED_IDS = [
    "inventory-picker",
    "upload-btn",
    "download-btn",
];
function enableBridgeGatedControls() {
    for (const id of BRIDGE_GATED_IDS) $(id).disabled = false;
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
        state.selected_features = {};
        renderSegmentGrid(info.groups);
        renderFeaturePanel(info.feature_groups);
        $("analysis-content").innerHTML = "";
        setStatus(`Loaded ${info.name} (${info.segments.length} segments, ${info.features.length} features).`);
    } catch (e) {
        const issues = e.message ? [e.message] : ["unknown error"];
        $("analysis-content").innerHTML =
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
// Segment grid
// ---------------------------------------------------------------------
function renderSegmentGrid(groups) {
    const grid = $("seg-grid");
    grid.innerHTML = "";
    for (const group of groups) {
        const groupEl = document.createElement("div");
        groupEl.className = "seg-group";
        const header = document.createElement("div");
        header.className = "seg-group-header";
        header.textContent = group.name.toUpperCase();
        groupEl.appendChild(header);
        const row = document.createElement("div");
        row.className = "seg-row";
        for (const seg of group.segments) {
            const btn = document.createElement("button");
            btn.className = "seg-btn";
            btn.type = "button";
            btn.dataset.seg = seg;
            btn.dataset.state = "default";
            // aria-pressed mirrors data-state for screen readers. Updated
            // on every state change so AT users hear the toggle.
            btn.setAttribute("aria-pressed", "false");
            btn.setAttribute("aria-label", `/${seg}/`);
            btn.textContent = seg;
            btn.addEventListener("click", () => onSegmentClicked(seg));
            row.appendChild(btn);
        }
        groupEl.appendChild(row);
        grid.appendChild(groupEl);
    }
}

function onSegmentClicked(seg) {
    activateMode("seg_to_feat");
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
// extras. Layout mirrors the desktop's feature-card panel.
// ---------------------------------------------------------------------
function renderFeaturePanel(featureGroups) {
    const list = $("feat-list");
    list.innerHTML = "";
    for (const group of featureGroups) {
        const groupEl = document.createElement("div");
        groupEl.className = "feat-group";
        const header = document.createElement("div");
        header.className = "feat-group-header";
        header.textContent = group.name.toUpperCase();
        groupEl.appendChild(header);
        for (const feat of group.features) {
            groupEl.appendChild(_buildFeatureRow(feat));
        }
        list.appendChild(groupEl);
    }
}

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
    for (const polarity of ["+", "−"]) {
        const btn = document.createElement("button");
        btn.className = "feat-btn";
        btn.type = "button";
        const code = polarity === "+" ? "+" : "-";
        btn.dataset.polarity = code;
        btn.textContent = polarity;
        btn.addEventListener("click", () => onFeatureClicked(feat, code));
        row.appendChild(btn);
    }
    return row;
}

function onFeatureClicked(feat, polarity) {
    activateMode("feat_to_seg");
    if (state.selected_features[feat] === polarity) {
        delete state.selected_features[feat];
    } else {
        state.selected_features[feat] = polarity;
    }
    // Update the feat-btn active visual on this row.
    for (const btn of document.querySelectorAll(`.feat-row[data-feat="${cssEscape(feat)}"] .feat-btn`)) {
        const active = state.selected_features[feat] === btn.dataset.polarity;
        btn.dataset.active = active ? "true" : "false";
    }
    scheduleAnalysis();
}

function cssEscape(s) {
    return (window.CSS && window.CSS.escape) ? window.CSS.escape(s) : s.replace(/"/g, '\\"');
}

// ---------------------------------------------------------------------
// Mode toggle (visual chrome only; actual mode lives in state.mode)
// ---------------------------------------------------------------------
function activateMode(mode) {
    if (state.mode === mode) return;
    state.mode = mode;
    $("seg-panel").dataset.active = (mode === "seg_to_feat") ? "true" : "false";
    $("feat-panel").dataset.active = (mode === "feat_to_seg") ? "true" : "false";
    // Clear the opposite-mode state so the analysis pane reflects
    // only the active mode's input.
    if (mode === "seg_to_feat") {
        state.selected_features = {};
        document.querySelectorAll(".feat-btn[data-active='true']").forEach(b => b.dataset.active = "false");
    } else {
        state.selected_segments = [];
        document.querySelectorAll(".seg-btn[data-state='selected']").forEach(b => b.dataset.state = "default");
    }
    setStatus(mode === "seg_to_feat"
        ? "Click a segment to inspect its features."
        : "Toggle feature values (+/−) to find matching segments.");
}

// ---------------------------------------------------------------------
// Analysis (debounced to coalesce rapid clicks)
// ---------------------------------------------------------------------
function scheduleAnalysis() {
    clearTimeout(state.debounce_timer);
    state.debounce_timer = setTimeout(runAnalysis, 80);
}

function runAnalysis() {
    if (state.mode === "seg_to_feat") {
        runSegToFeat();
    } else {
        runFeatToSeg();
    }
}

function runSegToFeat() {
    const result = callBridge("analyze_segments", state.selected_segments);
    $("analysis-content").innerHTML = result.analysis_html;
    _updateSegmentButtonStates(result.segment_states);
    // Update feature row display.
    for (const row of document.querySelectorAll(".feat-row")) {
        const info = result.feature_display[row.dataset.feat] || { value: "", shared: false };
        row.dataset.value = info.value || "";
        row.dataset.shared = info.shared ? "true" : "false";
        row.dataset.contrastive = info.contrastive ? "true" : "false";
        const badge = row.querySelector(".feat-badge");
        if (badge) badge.textContent = info.value || "·";
    }
}

function runFeatToSeg() {
    const result = callBridge("analyze_features", state.selected_features);
    $("analysis-content").innerHTML = result.analysis_html;
    _updateSegmentButtonStates(result.segment_states);
}

function _updateSegmentButtonStates(segmentStates) {
    // Centralized so aria-pressed stays in lockstep with data-state.
    // Selected/matched both read as "pressed" to assistive tech;
    // unmatched/suggested/default read as not-pressed.
    for (const btn of document.querySelectorAll(".seg-btn")) {
        const newState = segmentStates[btn.dataset.seg] || "default";
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
    $("upload-btn").addEventListener("click", () => $("upload-input").click());
    $("upload-input").addEventListener("change", async (ev) => {
        const file = ev.target.files[0];
        if (!file) return;
        const text = await file.text();
        await loadInventoryText(text, file.name);
        ev.target.value = "";
    });
    $("download-btn").addEventListener("click", () => {
        try {
            const text = callBridge("serialize_current_inventory");
            const name = callBridge("get_current_inventory_name");
            const blob = new Blob([text], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `${name}.json`;
            a.click();
            URL.revokeObjectURL(url);
        } catch (e) {
            setStatus(`Download failed: ${e.message}`);
        }
    });
}

// ---------------------------------------------------------------------
// Theme toggle (CSS variables + Python palette swap)
// ---------------------------------------------------------------------
function wireThemeToggle() {
    const stored = localStorage.getItem("theme");
    if (stored === "dark") {
        document.documentElement.dataset.theme = "dark";
        $("theme-btn").textContent = "☀";
    }
    $("theme-btn").addEventListener("click", () => {
        const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
        document.documentElement.dataset.theme = next;
        $("theme-btn").textContent = next === "dark" ? "☀" : "☾";
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
    $("inventory-picker").addEventListener("change", () => {
        const file = $("inventory-picker").value;
        const item = BUNDLED_INVENTORIES.find(i => i.file === file);
        if (item) loadBundledInventory(item);
    });
}

function populateInventoryPicker() {
    const picker = $("inventory-picker");
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
    $("expand-btn").addEventListener("click", () => {
        const pane = $("analysis-pane");
        const expanded = pane.classList.toggle("expanded");
        $("expand-btn").textContent = expanded ? "⤣" : "⤢";
    });
}

// ---------------------------------------------------------------------
// Clear buttons (one per panel, both wipe the same shared state).
// Matches the desktop's "Clear means clear" semantics: each Clear
// resets both panes and the analysis pane, and activates the panel
// whose Clear was pressed.
// ---------------------------------------------------------------------
function wireClearButtons() {
    $("seg-clear-btn").addEventListener("click", (ev) => {
        ev.stopPropagation();
        activateMode("seg_to_feat");
        clearAll();
    });
    $("feat-clear-btn").addEventListener("click", (ev) => {
        ev.stopPropagation();
        activateMode("feat_to_seg");
        clearAll();
    });
}

function clearAll() {
    state.selected_segments = [];
    state.selected_features = {};
    for (const btn of document.querySelectorAll(".seg-btn")) {
        btn.dataset.state = "default";
        btn.setAttribute("aria-pressed", "false");
    }
    for (const row of document.querySelectorAll(".feat-row")) {
        row.dataset.value = "";
        row.dataset.shared = "false";
        row.dataset.contrastive = "false";
        const badge = row.querySelector(".feat-badge");
        if (badge) badge.textContent = "·";
    }
    for (const btn of document.querySelectorAll(".feat-btn[data-active='true']")) {
        btn.dataset.active = "false";
    }
    $("analysis-content").innerHTML = "";
    setStatus(state.mode === "seg_to_feat"
        ? "Click a segment to inspect its features."
        : "Toggle feature values (+/−) to find matching segments.");
}

// ---------------------------------------------------------------------
// Clicking anywhere in a panel switches mode to that panel's mode,
// except when the click was on a button (which has its own handler).
// Equivalent to the desktop's eventFilter that listens for clicks in
// empty panel space.
// ---------------------------------------------------------------------
function wirePanelClickMode() {
    $("seg-panel").addEventListener("click", (ev) => {
        if (ev.target.closest("button")) return;
        activateMode("seg_to_feat");
    });
    $("feat-panel").addEventListener("click", (ev) => {
        if (ev.target.closest("button")) return;
        activateMode("feat_to_seg");
    });
}

// ---------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------
async function main() {
    wireThemeToggle();
    wireInventoryPicker();
    wireUploadDownload();
    wireExpandButton();
    wireClearButtons();
    wirePanelClickMode();
    try {
        await bootPyodide();
    } catch (e) {
        console.error(e);
        setLoadingStatus(`Failed to load: ${e.message}`);
    }
}

main();
