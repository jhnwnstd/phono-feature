// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Required Notice: Copyright 2026 John Winstead, https://github.com/jhnwnstd/phono-feature
/**
 * Inventory file upload and download, the setup dialog, and the
 * PHOIBLE picker.
 */
import { MAX_INVENTORY_BYTES, STATUS_TEXT, makeOption } from "./config.js";
import {
    editorHasUnsavedWork,
    editorState,
    refreshEditorFromCurrent,
} from "./editor.js";
import {
    STATUS_KIND,
    bridgeErrorMessage,
    callBridge,
    nodes,
    setStatus,
} from "./infra.js";
import {
    applyInventoryInfo,
    ensurePhoibleLoaded,
    loadInventoryText,
    markInventoryUnlisted,
} from "./inventory.js";
import { closeDialog, openDialog } from "./measure.js";
import { assetUrl } from "./state.js";
import { addPhoibleDropdownEntry } from "./wiring.js";


export function wireUploadDownload() {
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
        markInventoryUnlisted();
        ev.target.value = "";
    });
    // Save-as lives on the editor toolbar only; the main toolbar
    // is for selecting and viewing inventories, not exporting them.
}

/**
 * Wire the New-inventory setup dialog and return its ``open()``
 * trigger. The dialog itself owns its inputs and submit handling;
 * callers (the editor's New button) invoke ``open()`` to
 * show it.
 *
 * The preset dropdown and Tab-autofill seeds come from the same
 * inventory_setup module the desktop editor uses, so the two
 * frontends offer identical defaults. Validation is server-side
 * (Pyodide-side) through validate_setup; the dialog stays open
 * on error so the user can correct without losing input.
 */
export function wireSetupDialog() {
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
            // Suffix carries the meaning even on rendering surfaces
            // where ``<option>`` font-weight is ignored (some older
            // WebKit), so the recommended path is unambiguous
            // regardless of native ``<select>`` styling support.
            const opt = makeOption(
                PROVIDER_PREFIX + provider.name,
                `${provider.label || provider.name} (auto-fill)`
            );
            opt.style.fontWeight = "600";
            presetPicker.appendChild(opt);
        }
        for (const name of Object.keys(presets)) {
            presetPicker.appendChild(makeOption(name, name));
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
        // Editor-unsaved guard: creating a new inventory swaps the
        // engine, which discards any unsaved work in the editor.
        // Prompt once before the swap so the dialog submit cannot
        // silently erase in-progress work. Uses the same
        // editorHasUnsavedWork() predicate as closeEditor/beforeunload
        // so a created-but-unsaved inventory (engineReplaced, not yet
        // dirty) is still caught. Matches the spirit of the desktop's
        // ``_check_unsaved`` gate around :py:meth:`show_setup_dialog`.
        if (!nodes.editorView.hidden && editorHasUnsavedWork()) {
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
        // "New" runs only from inside the editor; the bridge call below
        // swaps the live engine to the new (UNSAVED) inventory. Capture
        // the committed inventory first so backing out of the editor can
        // roll the engine back rather than letting the new one persist.
        // Snapshot once per session: a second "New" keeps the original
        // rollback target.
        const editorOpen = !nodes.editorView.hidden;
        let committedSnapshot = null;
        if (editorOpen && !editorState.engineReplaced) {
            try {
                committedSnapshot = {
                    json: callBridge("serialize_current_inventory"),
                    dropdownValue: nodes.inventoryPicker.value,
                };
            } catch (_) {
                committedSnapshot = null;
            }
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
            // The new inventory is not a listed dropdown option; deselect
            // the picker so it never names it. This defends the restore +
            // save exits directly instead of relying on the editor chrome
            // covering a stale picker.
            markInventoryUnlisted();
            if (editorOpen) {
                if (committedSnapshot) {
                    editorState.committedSnapshot = committedSnapshot;
                }
                editorState.engineReplaced = true;
            }
            setStatus(
                `Created ${info.name} `
                + `(${info.segments.length} segments, `
                + `${info.features.length} features)${sourceSuffix}.`,
            );
            errorBox.textContent = "";
            close();
            // If the editor is open it must re-fetch the new
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


// One inventory-source card for the PHOIBLE picker. The radio input
// carries form state but the whole label is the click target;
// ``:has(input:checked)`` in CSS paints the accent border.
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

    // One muted secondary line carrying the description and dialect,
    // matching the desktop row so the two clients read identically.
    const subParts = [];
    if (inv.source_description) subParts.push(inv.source_description);
    if (inv.display_dialect) subParts.push(inv.display_dialect);
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


// Wire the toolbar's PHOIBLE button and its picker dialog. PHOIBLE is
// a LOAD path (parallel to the inventory picker). The 1 MB index and
// 5 MB data payload are lazy-fetched on first open via
// ``phoible_load_index`` / ``phoible_load_data`` (externalized from
// the Pyodide bundle so cold boot stays cheap).
export function wirePhoiblePicker() {
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
                _buildSourceCard(inv, defaultId, pickInventory),
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
                await ensurePhoibleLoaded();
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
    // BRIDGE_GATED_NODES path after Pyodide attaches; availability is a
    // static asset-manifest check at click time (the PHOIBLE index +
    // data are lazy dist assets, so a build that baked them has both
    // entries) rather than a bridge call that would construct the
    // provider just to answer "is PHOIBLE available?".
    button.addEventListener("click", () => {
        if (!assetUrl("phoible_index") || !assetUrl("phoible_data")) {
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
        // Editor-unsaved guard: loading a new inventory swaps the
        // engine, which discards any unsaved work in the editor.
        // Mirrors the upload + setup-dialog gate; editorHasUnsavedWork()
        // also catches a created-but-unsaved inventory, not just dirty
        // grid edits.
        if (!nodes.editorView.hidden && editorHasUnsavedWork()) {
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
