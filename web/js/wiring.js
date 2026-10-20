// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Required Notice: Copyright 2026 John Winstead, https://github.com/jhnwnstd/phono-feature
/**
 * Event wiring: inventory picker, analysis tabs, clear buttons, class
 * filter, click delegation, spillover resize, service worker and the
 * help windows.
 *
 * Top tier below the entry point. Nothing imports it except
 * ``main.js``, ``boot.js`` and ``io.js``.
 */
import {
    _applyFeatureRowStates,
    _applySegmentStates,
    _restoreFeatureQueryMarkers,
    activateAnalysisTab,
    activateMode,
    onFeatureClicked,
    onSegmentClicked,
    runAnalysis,
} from "./analysis.js";
import { MODE, _formatTpl, emptyFeatureSpec, makeOption } from "./config.js";
import {
    STATUS_KIND,
    bridgeErrorMessage,
    callBridge,
    flashStatus,
    nodes,
    setStatus,
} from "./infra.js";
import { applyInventoryInfo, loadBundledInventory } from "./inventory.js";
import { closeDialog, showHelp } from "./measure.js";
import {
    onClassPopoverChange,
    positionClassPopover,
    relayoutSegments,
    toggleClassPopover,
} from "./segments.js";
import { BUNDLED_INVENTORIES, pickDefaultInventory, state } from "./state.js";


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
        group.appendChild(makeOption(PHOIBLE_OPTION_PREFIX + id, name));
    }
    picker.appendChild(group);
}

/** Cache a picker-loaded PHOIBLE inventory in the dropdown and
 *  select its entry. Idempotent per inventory id. */
export function addPhoibleDropdownEntry(inventoryId, name) {
    phoibleDropdownEntries.set(String(inventoryId), name);
    renderPhoibleDropdownGroup();
    nodes.inventoryPicker.value = PHOIBLE_OPTION_PREFIX + inventoryId;
}

export function wireInventoryPicker() {
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

export function populateInventoryPicker() {
    const picker = nodes.inventoryPicker;
    picker.innerHTML = "";
    for (const item of BUNDLED_INVENTORIES) {
        const opt = makeOption(item.file, item.label);
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
export function wireAnalysisTabs() {
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

export function wireClearButtons() {
    // Wipe state synchronously before triggering the mode switch so
    // the user never sees a flash of prior analysis content during
    // the debounced reanalysis window.
    const wireClear = (btn, mode) =>
        btn.addEventListener("click", (ev) => {
            ev.stopPropagation();
            clearAll();
            if (state.mode !== mode) {
                activateMode(mode);
            } else if (state.bridge) {
                runAnalysis();
            }
        });
    wireClear(nodes.segClearBtn, MODE.SEG_TO_FEAT);
    wireClear(nodes.featClearBtn, MODE.FEAT_TO_SEG);
}

/** Wire the segment-class visibility popover: the header filter button
 *  toggles it, a checkbox change flips one class' visibility, and a
 *  click outside or Escape dismisses it. The popover acts purely on the
 *  cached render payload, so it needs no bridge round-trip. */
export function wireClassFilter() {
    nodes.segFilterBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        toggleClassPopover();
    });
    nodes.segClassPopover.addEventListener("change", onClassPopoverChange);
    // Outside-press dismiss in the CAPTURE phase so it always fires,
    // even though segment buttons / the grid delegation call
    // stopPropagation in the bubble phase (which would otherwise strand
    // the popover open). A press on the button or inside the popover is
    // excluded so it does not fight the toggle / checkbox handlers.
    document.addEventListener(
        "pointerdown",
        (ev) => {
            if (nodes.segClassPopover.hidden) return;
            if (nodes.segFilterBtn.contains(ev.target)) return;
            if (nodes.segClassPopover.contains(ev.target)) return;
            toggleClassPopover(false);
        },
        true,
    );
    document.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape" && !nodes.segClassPopover.hidden) {
            toggleClassPopover(false);
            nodes.segFilterBtn.focus();
        }
    });
    // Keep the popover anchored to the button if the layout shifts
    // (window resize, or a pane scroll) while it is open.
    const reanchor = () => {
        if (!nodes.segClassPopover.hidden) positionClassPopover();
    };
    window.addEventListener("resize", reanchor);
    window.addEventListener("scroll", reanchor, true);
}

function clearAll() {
    // Clear is "make the selection empty", not a distinct UI state.
    // The analysis pane is intentionally not wiped here: the caller
    // follows up with ``activateMode`` (on a mode change) or
    // ``runAnalysis`` (same mode), and the empty-selection payload
    // from the view-model produces the default placeholder text,
    // same shape as app launch.
    state.selected_segments = [];
    state.selected_features = emptyFeatureSpec();
    state.saved_seg_state = [];
    state.saved_feat_state = emptyFeatureSpec();
    // Reset every button/row to its baseline via the same appliers the
    // analysis path uses; selected_features was already emptied above,
    // so _restoreFeatureQueryMarkers clears every row's +/- markers.
    _applySegmentStates(() => "default");
    _applyFeatureRowStates();
    _restoreFeatureQueryMarkers();
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
export function wirePanelClickMode() {
    const wireMode = (panel, mode) =>
        panel.addEventListener("mousedown", (ev) => {
            if (ev.target.closest("button")) return;
            if (ev.button === 2) ev.preventDefault();
            activateMode(mode);
        });
    wireMode(nodes.segPanel, MODE.SEG_TO_FEAT);
    wireMode(nodes.featPanel, MODE.FEAT_TO_SEG);
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
export function wireSegmentDelegation() {
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
    // Flash (not setStatus) so the copy confirmation auto-reverts to
    // the inventory summary instead of permanently replacing it.
    const onOk = () =>
        flashStatus(
            _formatTpl(
                "clipboard_copy_template",
                "Copied /{seg}/ to clipboard",
                { seg }
            ),
            STATUS_KIND.success
        );
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

export function wireFeatureDelegation() {
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
 *  handles the rAF defer + same-state early-return.
 *
 *  Also attach a ResizeObserver to the seg-panel so container-only
 *  width changes (devtools toggle, sibling pane weight shift,
 *  scrollbar appearance during Pyodide load, font-load reflow) that
 *  cross the VOWEL_STACK_W container-query threshold WITHOUT firing
 *  a window resize still re-run the layout. Without the observer,
 *  the CSS branch flips but the JS-computed grid tracks stay stale
 *  until the next window resize.
 */
export function wireSegmentSpilloverResize() {
    let timer = 0;
    const fire = () => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => {
            timer = 0;
            relayoutSegments();
        }, SPILLOVER_RESIZE_DEBOUNCE_MS);
    };
    window.addEventListener("resize", fire);
    if (typeof ResizeObserver !== "undefined" && nodes.segPanel) {
        new ResizeObserver(fire).observe(nodes.segPanel);
    }
}

/**
 * Register the service worker after first load completes so the
 * registration request doesn't compete with critical-path fetches.
 * If main.js parsed slowly enough that window.load already fired,
 * register immediately instead of waiting for an event that won't
 * come.
 */
export function registerServiceWorker() {
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

/** Wire the SEGMENTS and FEATURES pane titles to open their help
 *  windows (the Vowels chart title is wired at chart-build time in
 *  _buildVowelChart) plus the window's Close button. */
export function wireHelp() {
    nodes.segTitle.title = "How to read the segment displays";
    nodes.segTitle.addEventListener("click", () => showHelp("segments"));
    nodes.featTitle.title = "How to read and query features";
    nodes.featTitle.addEventListener("click", () => showHelp("features"));
    nodes.helpDialogClose.addEventListener("click", () =>
        closeDialog(nodes.helpDialog));
    nodes.sourceDialogClose.addEventListener("click", () =>
        closeDialog(nodes.sourceDialog));
}
