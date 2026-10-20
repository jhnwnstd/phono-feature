// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Required Notice: Copyright 2026 John Winstead, https://github.com/jhnwnstd/phono-feature
/**
 * Pyodide boot: script load, bundle mount and validation, the
 * bridge-gated control gate, and the first-paint handoff.
 */
import { hasActiveSelection, scheduleAnalysis } from "./analysis.js";
import {
    callBridge,
    fetchBytes,
    fetchInventoryText,
    fetchJson,
    mark,
    measure,
    nodes,
    printBootMeasures,
    printResourceSummary,
    setLoadingStatus,
    setStatus,
    withTimeout,
} from "./infra.js";
import {
    loadBundledInventory,
    renderEmptyAnalysisHints,
    setInventoryStatus,
    setStatusSource,
} from "./inventory.js";
import {
    _syncBridgeMatchModeToStoredState,
    _syncBridgePaletteToStoredState,
} from "./prefs.js";
import { relayoutSegments } from "./segments.js";
import {
    BUNDLED_INVENTORIES,
    assetUrl,
    pickDefaultInventory,
    setBundledInventories,
    state,
} from "./state.js";
import { populateInventoryPicker } from "./wiring.js";


const PYODIDE_BOOT_TIMEOUT_MS = 30_000;

const PYODIDE_BOOTSTRAP_URL =
    "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js";
// Kept in sync with the integrity= on the pyodide.js preload in
// index.html: the preload and this injected script must carry the SAME
// SRI or the browser cannot reuse the preloaded response and refetches.
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

/** Boot Pyodide + the engine bundle. `prerendered` indicates that
 *  applyBootstrap already painted the default inventory's DOM; in
 *  that case the loading overlay drops earlier (right after WASM
 *  compile), and the inventory load skips a redundant re-render. */
export async function bootPyodide({ prerendered = false } = {}) {
    mark("boot:start");
    markBridgeGatedControlsLoading();

    setLoadingStatus("Loading inventory list…");
    mark("manifest:start");
    setBundledInventories(
        await fetchJson(assetUrl("inventories_manifest")),
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
    // Sync stored theme + palette + match-mode into Python before any
    // analysis runs so the analysis HTML doesn't render with the
    // default palette while CSS is in dark/colorblind.
    _syncBridgePaletteToStoredState();
    _syncBridgeMatchModeToStoredState();

    enableBridgeGatedControls();
    // First planner-backed layout pass. Pre-bridge passes no-op, and
    // the prerendered path never re-renders the grid on its own.
    relayoutSegments();
    setLoadingStatus("Loading default inventory…");
    mark("inventory:start");
    const defaultItem = pickDefaultInventory(BUNDLED_INVENTORIES);
    if (prerendered) {
        // Panels already painted from bootstrap.json; only sync the
        // engine and status-bar facts. Status-only bridge skips the
        // full-summary deep-conversion this branch would discard.
        const text = await fetchInventoryText(defaultItem.file);
        const info = callBridge(
            "load_inventory_json_status_only", text, defaultItem.label,
        );
        setInventoryStatus(info);
        setStatusSource(info.source);
        if (hasActiveSelection()) scheduleAnalysis();
        else renderEmptyAnalysisHints();
    } else {
        await loadBundledInventory(defaultItem);
    }
    mark("inventory:end");

    // Idempotent hide (prerendered path already hid it early).
    nodes.loadingOverlay.classList.add("hidden");

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
    "editorBtn",
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
