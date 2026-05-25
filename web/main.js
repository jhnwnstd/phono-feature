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

async function bootPyodide() {
    setLoadingStatus("Loading inventory list…");
    BUNDLED_INVENTORIES = await (await fetch("inventories.json")).json();
    populateInventoryPicker();

    setLoadingStatus("Loading the Python runtime…");
    const pyodide = await loadPyodide();
    state.pyodide = pyodide;

    setLoadingStatus("Installing the phonology engine…");
    await pyodide.loadPackage("micropip");
    const micropip = pyodide.pyimport("micropip");
    // The build script puts the wheel at ./wheels/. Glob isn't
    // available; the filename is templated by the build script.
    const wheelUrl = new URL("wheels/phonology_engine-0.1.0-py3-none-any.whl",
        document.baseURI).toString();
    await micropip.install(wheelUrl);

    setLoadingStatus("Loading renderer modules…");
    // The build copies palette.py / constants.py / analysis.py into
    // ./render/phonology_features/gui/ so the api.py imports resolve
    // to the same code the desktop runs.
    await mountRendererPackage(pyodide);

    setLoadingStatus("Initializing the bridge…");
    const apiSource = await (await fetch("api.py")).text();
    pyodide.FS.writeFile("/home/pyodide/api.py", apiSource);
    state.bridge = pyodide.pyimport("api");

    setLoadingStatus("Loading default inventory…");
    await loadBundledInventory(BUNDLED_INVENTORIES[0]);

    $("loading-overlay").classList.add("hidden");
    setStatus("Click a segment to inspect its features.");
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
        const text = await (await fetch(urlPath)).text();
        pyodide.FS.writeFile(`/home/pyodide/${urlPath}`, text);
    }
    pyodide.runPython(`
        import sys
        sys.path.insert(0, "/home/pyodide/render")
        sys.path.insert(0, "/home/pyodide")
    `);
}

// ---------------------------------------------------------------------
// Inventory loading
// ---------------------------------------------------------------------
async function loadBundledInventory(item) {
    const text = await (await fetch(item.file)).text();
    await loadInventoryText(text, item.label);
}

async function loadInventoryText(text, sourceLabel) {
    try {
        const info = state.bridge.load_inventory_json(text, sourceLabel).toJs(
            { dict_converter: Object.fromEntries }
        );
        state.inventory_name = info.name;
        state.segments = info.segments;
        state.features = info.features;
        state.selected_segments = [];
        state.selected_features = {};
        renderSegmentGrid(info.groups);
        renderFeaturePanel(info.features);
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
// Feature panel
// ---------------------------------------------------------------------
function renderFeaturePanel(features) {
    const list = $("feat-list");
    list.innerHTML = "";
    for (const feat of features) {
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
            btn.dataset.polarity = polarity === "+" ? "+" : "-";
            btn.textContent = polarity;
            btn.addEventListener("click", () => onFeatureClicked(feat, polarity === "+" ? "+" : "-"));
            row.appendChild(btn);
        }
        list.appendChild(row);
    }
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
    const result = state.bridge.analyze_segments(
        state.pyodide.toPy(state.selected_segments)
    ).toJs({ dict_converter: Object.fromEntries });
    $("analysis-content").innerHTML = result.analysis_html;
    // Update segment button states.
    for (const btn of document.querySelectorAll(".seg-btn")) {
        const newState = result.segment_states[btn.dataset.seg] || "default";
        if (btn.dataset.state !== newState) btn.dataset.state = newState;
    }
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
    const result = state.bridge.analyze_features(
        state.pyodide.toPy(state.selected_features)
    ).toJs({ dict_converter: Object.fromEntries });
    $("analysis-content").innerHTML = result.analysis_html;
    for (const btn of document.querySelectorAll(".seg-btn")) {
        const newState = result.segment_states[btn.dataset.seg] || "default";
        if (btn.dataset.state !== newState) btn.dataset.state = newState;
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
        const text = state.bridge.serialize_current_inventory();
        const name = state.bridge.get_current_inventory_name();
        const blob = new Blob([text], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${name}.json`;
        a.click();
        URL.revokeObjectURL(url);
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
            state.bridge.set_active_theme(next);
            // Re-run analysis to refresh chip colors embedded in HTML.
            runAnalysis();
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
// Entry point
// ---------------------------------------------------------------------
async function main() {
    wireThemeToggle();
    wireInventoryPicker();
    wireUploadDownload();
    wireExpandButton();
    try {
        await bootPyodide();
    } catch (e) {
        console.error(e);
        setLoadingStatus(`Failed to load: ${e.message}`);
    }
}

main();
