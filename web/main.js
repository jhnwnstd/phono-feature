// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Required Notice: Copyright 2026 John Winstead, https://github.com/jhnwnstd/phono-feature
/**
 * Web app entry point.
 *
 * Boots Pyodide, mounts the phonology engine bundle, renders an
 * inlined bootstrap inventory before Pyodide finishes loading, then
 * wires UI events to bridge calls into api.py.
 *
 * The app is split across ``js/``; this file only orders the startup
 * sequence. The import graph is a DAG apart from one pinned mutual
 * pair (``segments`` and ``analysis``), enforced by
 * ``shared/tests/test_web_module_layers.py``.
 */
import "./js/env.js";
import { bootPyodide } from "./js/boot.js";
import { wireEditor, wireLabelPrompt } from "./js/editor.js";
import { initNodes, mark, setLoadingStatus } from "./js/infra.js";
import {
    applyBootstrap,
    prewarmCommonAnalyses,
    schedulePhoiblePrefetch,
} from "./js/inventory.js";
import {
    wirePhoiblePicker,
    wireSetupDialog,
    wireUploadDownload,
} from "./js/io.js";
import { _refitSegButtons } from "./js/measure.js";
import {
    wireBugButton,
    wireColorblindToggle,
    wireMatchModeToggle,
    wireStatusbarBrand,
    wireThemeToggle,
} from "./js/prefs.js";
import { _refreshButtonStrideCache } from "./js/segments.js";
import {
    registerServiceWorker,
    wireAnalysisTabs,
    wireClassFilter,
    wireClearButtons,
    wireFeatureDelegation,
    wireHelp,
    wireInventoryPicker,
    wirePanelClickMode,
    wireSegmentDelegation,
    wireSegmentSpilloverResize,
} from "./js/wiring.js";


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
    // Order matters: the setup dialog must be wired before the
    // editor, because the editor's New button receives its open()
    // trigger from the dialog's wire-up return value.
    const setupDialog = wireSetupDialog();
    wireLabelPrompt();
    wireEditor(setupDialog);
    wireAnalysisTabs();
    wireClearButtons();
    wireClassFilter();
    wireHelp();
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
