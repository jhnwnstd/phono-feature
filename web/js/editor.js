// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Required Notice: Copyright 2026 John Winstead, https://github.com/jhnwnstd/phono-feature
/**
 * The inventory editor: grid render, selection model, crosshair, undo
 * and redo stack, structural edits, segment rename, cap counter and
 * the label prompt.
 *
 * The largest module and the one with the most private state. Every
 * mutable binding it declares is written only from inside this file.
 */
import { STATUS_TEXT, _formatTpl, _pluralS } from "./config.js";
import {
    STATUS_KIND,
    bridgeErrorMessage,
    callBridge,
    nodes,
    setStatus,
} from "./infra.js";
import {
    applyInventoryInfo,
    markInventoryUnlisted,
    setInventoryStatus,
} from "./inventory.js";
import {
    _editorCellSizePx,
    _pickEditorHeaderFontSize,
    closeDialog,
    openDialog,
} from "./measure.js";


/**
 * Serialize the active inventory and trigger a browser download.
 * Shared by the main toolbar's "Save as..." button and the editor's
 * "Save as..." button so both surfaces produce identical
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
        return true;
    } catch (e) {
        setStatus(`Download failed: ${e.message}`, STATUS_KIND.error);
        return false;
    }
}


// Editor state machine. Pure logic (cycle ladder, validators, remove
// prompts) lives in Python (editor/grid.py, editor/setup.py); DOM
// mutation and rapid-event handling live here. ``classifyEditorSelection``
// and ``SELECTION_SHAPE_REMOVE_TARGET`` mirror Python and are pinned by
// ``shared/tests/test_editor_mirror_parity.py``. Undo entries mirror
// ``editor.edits._BulkEdit``: {cells: [{r, c, old}, ...], new: "value"}.
// ``cells`` is indexed [feature_index][segment_index] to match the
// engine's ``get_grid_state`` and ``grid_to_inventory``.
export const editorState = {
    open: false,
    name: "",
    source: "",           // metadata.source (verbatim; normalized on save)
    features: [],
    segments: [],
    cells: [],
    dirty: false,
    selected: new Set(),  // "r,c" keys
    anchor: null,         // {r, c}, used by shift-click range extension
    focused: null,        // {r, c}, fallback target when no selection
    undoStack: [],
    redoStack: [],
    // Transaction guard for the "New" path. The editor stages cell +
    // name edits in editorState and only mutates the engine on
    // Save-as, but "New" (the setup dialog) swaps the live engine to a
    // brand-new inventory up front. ``engineReplaced`` records that an
    // UNSAVED inventory is sitting in the engine; ``committedSnapshot``
    // is the serialized inventory (+ its dropdown selection) that was
    // active before the swap, so backing out can roll the engine back
    // instead of letting the new inventory secretly persist.
    engineReplaced: false,
    committedSnapshot: null,
};

/** True when the editor holds work a discard / back-out / page unload
 *  would lose: staged grid or name edits (``dirty``) OR a created-but-
 *  unsaved inventory sitting in the engine (``engineReplaced``). Single
 *  source so the Back guard and the beforeunload guard cannot drift. */
export function editorHasUnsavedWork() {
    return editorState.dirty || editorState.engineReplaced;
}

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
// Header <th> nodes by index, cached at render for the selection
// crosshair (light the segment / feature a selected cell lines up with).
let _colHeaderNodes = [];
let _rowHeaderNodes = [];
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

// Wire the editor: toolbar buttons, cell/header click behaviors,
// keyboard dispatch, unsaved-work guards. Mirrors the desktop's
// ``InventoryEditor``. Cell interactions:
//   plain click        select single (or bulk-cycle if already selected)
//   shift-click        rectangular range from the anchor
//   ctrl/cmd-click     toggle individual cells
//   headers            select col/row (2nd click clears); corner = select all
//   Space              bulk-cycle selection to next value
//   1/2/3/0            set value directly (from shared VALUE_KEYS)
//   Esc                clear selection
export function wireEditor(setupDialog) {
    const openEditor = () => {
        if (cycleLadder === null) {
            // First open: fetch the shared editor constants in one call.
            const cfg = callBridge("get_editor_config");
            cycleLadder = cfg.cycle_ladder;
            valueKeys = cfg.value_keys;
            moveKeys = cfg.move_keys;
            maxUndoDepth = cfg.max_undo_depth;
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
        // "Unsaved" covers both staged grid edits AND a new inventory
        // created via "New" that was never saved: backing out of either
        // must not silently keep the work.
        const hasUnsaved = editorHasUnsavedWork();
        if (hasUnsaved
            && !confirm("Discard unsaved changes to the inventory?")) {
            return;
        }
        // Roll the engine back to the inventory that was committed when
        // "New" replaced it, so the unsaved inventory does not persist
        // behind the editor.
        if (editorState.engineReplaced) {
            restoreCommittedInventory();
        }
        editorState.open = false;
        editorState.dirty = false;
        editorState.engineReplaced = false;
        editorState.committedSnapshot = null;
        clearSelection();
        editorState.undoStack.length = 0;
        editorState.redoStack.length = 0;
        nodes.editorView.hidden = true;
        setMainChromeInert(false);
    };

    nodes.editorBtn.addEventListener("click", openEditor);
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

    // Source: a modal to add/edit the inventory's provenance (a
    // citation, URL, DOI, or a pasted BibTeX entry). Staged on
    // editorState like the name; normalized + written to
    // metadata.source on Save as, where classify_source displays it.
    nodes.editorSourceBtn.addEventListener("click", openSourceDialog);
    nodes.editorSourceCancel.addEventListener("click", () => {
        closeDialog(nodes.editorSourceDialog);
    });
    nodes.editorSourceDialog
        .querySelector("form")
        .addEventListener("submit", () => {
            // method="dialog": the submit closes the dialog; capture the
            // value first. Escape / Cancel never submit, so they discard.
            const next = nodes.editorSourceTextarea.value;
            if (next === editorState.source) return;
            editorState.source = next;
            markEditorDirty();
            refreshSourceButton();
            setEditorStatus(
                "Source will apply on Save as... (Back to discard).",
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
        if (!editorHasUnsavedWork()) return;
        ev.preventDefault();
        ev.returnValue = "";
    });
}

// Pull the active engine's grid state and adopt as editor state.
// Called on open and after any engine swap (New, Save-as).
export function refreshEditorFromCurrent() {
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
    editorState.source = snapshot.source || "";
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
    refreshSourceButton();
    // The web has no linked-on-disk file, so this label is purely a
    // dirty cue: blank when clean (just loaded OR just saved: no
    // "(unsaved)" contradicting the "Saved as X" status), "(modified)"
    // once edited (markEditorDirty). The Name input already names it.
    nodes.editorFileLabel.textContent = "";
    renderEditorGrid();
    repaintFocused();
    refreshEditorCapCounter();
    setEditorStatus(
        `${editorState.segments.length} segments × `
        + `${editorState.features.length} features`,
    );
}

/** Reflect whether a source is set on the toolbar button's label. */
function refreshSourceButton() {
    const has = editorState.source.trim().length > 0;
    nodes.editorSourceBtn.textContent = has ? "Edit source" : "Add source";
    nodes.editorSourceBtn.title = has
        ? "Edit the inventory's source"
        : "Add a source for the inventory (a citation, URL, DOI, "
        + "or a pasted BibTeX entry)";
}

/** Open the source modal, prefilled with the staged source. */
function openSourceDialog() {
    nodes.editorSourceTextarea.value = editorState.source;
    openDialog(nodes.editorSourceDialog);
    try { nodes.editorSourceTextarea.focus(); } catch { /* ignore */ }
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
    _colHeaderNodes = [];
    _rowHeaderNodes = [];
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
        // Shrink an oversized segment glyph to fit the square cell.
        const fit = _pickEditorHeaderFontSize(segments[c]);
        if (fit !== null) th.style.fontSize = `${fit}px`;
        colsRow.appendChild(th);
        _colHeaderNodes.push(th);
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
        _rowHeaderNodes.push(th);
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
// canvas (cached) and size columns/rows by pure arithmetic: measure
// once with the font engine, then layout is arithmetic. The per-cell
// box overhead (padding + collapsed border) and the single-line row
// height are page-constant, calibrated once from a real cell.
/** Size the two segment panes' tables and compensate for the data
 *  pane's scrollbar. Every segment column is ONE fixed square
 *  (``--editor-cell-size``, via CSS ``table-layout: fixed``), so there
 *  is no per-column measurement any more: the tables just need an
 *  explicit width (cols * cell) for fixed layout to honour the cell
 *  widths, and row heights come from the CSS cell ``height``. Called
 *  after each render. */
function _alignHeaderPanesToData() {
    const dataTable = nodes.editorGridData.querySelector("table");
    if (!dataTable) return;
    const colsTable = nodes.editorGridCols.querySelector("table");
    const n = editorState.segments.length;
    const gridW = n > 0 ? `${n * _editorCellSizePx}px` : "";
    dataTable.style.width = gridW;
    if (colsTable) colsTable.style.width = gridW;

    // Apply scrollbar-gutter compensation conditionally on the
    // data pane's ACTUAL scrollbar visibility. The previous
    // implementation stamped both borders unconditionally at
    // ``wireEditor`` time, leaving a phantom panel-coloured
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

// Selection model.

function clearSelection() {
    editorState.selected.clear();
    editorState.anchor = null;
    repaintSelection();
}

/** Select the inclusive cell rectangle [r0..r1] × [c0..c1], set the
 *  anchor/focused cells, then repaint. The shared tail of every
 *  selection helper below; loop order is irrelevant since `selected`
 *  is a Set. */
function _selectRange(r0, r1, c0, c1, anchor, focused) {
    editorState.selected.clear();
    for (let r = r0; r <= r1; r++) {
        for (let c = c0; c <= c1; c++) {
            editorState.selected.add(cellKey(r, c));
        }
    }
    editorState.anchor = anchor;
    editorState.focused = focused;
    repaintSelection();
    repaintFocused();
}

function selectSingleCell(r, c) {
    _selectRange(r, r, c, c, { r, c }, { r, c });
}

function extendSelectionTo(r, c) {
    if (editorState.anchor === null) {
        selectSingleCell(r, c);
        return;
    }
    const { r: ar, c: ac } = editorState.anchor;
    _selectRange(
        Math.min(ar, r), Math.max(ar, r),
        Math.min(ac, c), Math.max(ac, c),
        editorState.anchor, { r, c }
    );
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
    _selectRange(0, numRows - 1, c, c, { r: 0, c }, { r: 0, c });
}

function selectRow(r) {
    const numCols = editorState.segments.length;
    _selectRange(r, r, 0, numCols - 1, { r, c: 0 }, { r, c: 0 });
}

function selectAll() {
    const numRows = editorState.features.length;
    const numCols = editorState.segments.length;
    _selectRange(
        0, numRows - 1, 0, numCols - 1,
        { r: 0, c: 0 }, { r: 0, c: 0 }
    );
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
    repaintHeaderCrosshair();
    updateRemoveButtonStates();
}

// Mirror of shared ``editor.grid.classify_selection``; inlined for
// zero bridge-hop cost on rapid shift-drag. Returns a shape name
// ("empty" | "single_cell" | "single_column" | "single_row" |
// "full_grid" | "rectangle" | "irregular") plus row/col indices when
// meaningful. Pinned by shared/tests/test_editor_mirror_parity.py.
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

// Mirror of shared ``header_highlight_for_selection`` (grid.py); pinned
// by shared/tests/test_editor_mirror_parity.py. Returns
// ``{ cols: Set<number>, rows: Set<number> }``. Empty set means "no
// single axis to highlight" (selection covers the whole axis).
function headerHighlightForSelection() {
    const numRows = editorState.features.length;
    const numCols = editorState.segments.length;
    const cols = new Set();
    const rows = new Set();
    for (const key of editorState.selected) {
        const { r, c } = parseCellKey(key);
        cols.add(c);
        rows.add(r);
    }
    if (numCols > 0 && cols.size >= numCols) cols.clear();
    if (numRows > 0 && rows.size >= numRows) rows.clear();
    return { cols, rows };
}

/** Light the segment / feature headers the current selection pins
 *  down (see headerHighlightForSelection). A cheap full sweep over the
 *  cached header nodes: at most one row plus one column of them. */
function repaintHeaderCrosshair() {
    const { cols, rows } = headerHighlightForSelection();
    for (let c = 0; c < _colHeaderNodes.length; c++) {
        _colHeaderNodes[c].classList.toggle("is-axis-lit", cols.has(c));
    }
    for (let r = 0; r < _rowHeaderNodes.length; r++) {
        _rowHeaderNodes[r].classList.toggle("is-axis-lit", rows.has(r));
    }
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

// Keyboard focus indicator.

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

// Edit primitive.

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

// Structural-edit primitives.
//
// Add / remove segment, add / remove feature, and rename segment are
// all undoable, sharing the one undo stack with cell edits. Each
// records enough to reconstruct the prior state (the removed column /
// row values, the old name) so undo and redo are exact inverses.
// Mirrors the desktop editor's structural-edit records.

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

// Mouse handling.

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
    _selectRange(
        0, numRows - 1,
        Math.min(anchorCol, targetCol), Math.max(anchorCol, targetCol),
        { r: 0, c: anchorCol }, { r: 0, c: targetCol }
    );
}

function extendSelectionToRow(targetRow) {
    const numCols = editorState.segments.length;
    if (numCols === 0) return;
    const anchorRow = editorState.anchor?.r ?? targetRow;
    _selectRange(
        Math.min(anchorRow, targetRow), Math.max(anchorRow, targetRow),
        0, numCols - 1,
        { r: anchorRow, c: 0 }, { r: targetRow, c: 0 }
    );
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

// Keyboard handling.

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
        if (lower === "a") {
            // Keyboard equivalent of clicking the corner cell.
            ev.preventDefault();
            selectAll();
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

// Add / remove segments and features.

/** Right-click a column header to edit (rename) that segment inline.
 *  Mirrors the desktop editor's header double-click rename. The
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
    // ``preventScroll``: the header pane is ``overflow:hidden`` with its
    // scrollLeft/Top JS-mirrored from the data pane. A default focus
    // scrolls the input into view, nudging the pane's scroll out of sync
    // with the data pane, which drifts the rename box sideways off its
    // column. Not scrolling on focus keeps the panes aligned.
    input.focus({ preventScroll: true });
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
    _afterStructuralEdit(`Renamed segment '${oldName}' to '${proposed}'.`);
}

/** Shared tail for the editor's structural mutators (add / remove a
 *  segment or feature, commit a rename). Re-renders the grid, drops
 *  the selection, marks the inventory dirty, refreshes the cap
 *  counters, shows ``statusMsg``, and returns focus to the grid so
 *  Ctrl-Z / Ctrl-Y work immediately. The single home for this
 *  six-step tail. */
function _afterStructuralEdit(statusMsg) {
    renderEditorGrid();
    clearSelection();
    markEditorDirty();
    scheduleEditorCapRefresh();
    setEditorStatus(statusMsg);
    nodes.editorGridScroll.focus();
}

function addSegmentToState(seg) {
    const index = editorState.segments.length;
    const col = editorState.cells.map(() => ZERO_VALUE);
    _insertSegmentAt(index, seg, col);
    pushUndoEdit({ kind: "segAdd", index, seg, col });
    _afterStructuralEdit(_formatTpl(
        "added_segment_template", "Added segment '{seg}'.", { seg },
    ));
}

function addFeatureToState(feat) {
    const index = editorState.features.length;
    const row = Array.from(
        { length: editorState.segments.length }, () => ZERO_VALUE,
    );
    _insertFeatureAt(index, feat, row);
    pushUndoEdit({ kind: "featAdd", index, feat, row });
    _afterStructuralEdit(_formatTpl(
        "added_feature_template", "Added feature '{feat}'.", { feat },
    ));
}

function removeSelectedSegment() {
    const c = getSingleSelectedColumn();
    if (c === null) return;
    const seg = editorState.segments[c];
    // Confirm prompt text comes from the shared Python so the web
    // wording matches the desktop's ``ask_question`` body exactly.
    const prompt = callBridge("confirm_remove_segment_prompt", seg);
    if (!confirm(prompt)) return;
    // _removeSegmentAt captures the column values before the splice so
    // undo can restore the segment with its feature values intact.
    const col = _removeSegmentAt(c);
    pushUndoEdit({ kind: "segRemove", index: c, seg, col });
    _afterStructuralEdit(_formatTpl(
        "removed_segment_template", "Removed segment '{seg}'.", { seg },
    ));
}

function removeSelectedFeature() {
    const r = getSingleSelectedRow();
    if (r === null) return;
    const feat = editorState.features[r];
    const prompt = callBridge("confirm_remove_feature_prompt", feat);
    if (!confirm(prompt)) return;
    // _removeFeatureAt captures the row values before the splice so
    // undo can restore the feature with its per-segment values intact.
    const row = _removeFeatureAt(r);
    pushUndoEdit({ kind: "featRemove", index: r, feat, row });
    _afterStructuralEdit(_formatTpl(
        "removed_feature_template", "Removed feature '{feat}'.", { feat },
    ));
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
 * Roll the engine back to the inventory snapshotted before "New"
 * replaced it (see ``editorState.committedSnapshot``). Re-loads the
 * serialized inventory so the engine, the rendered panels, the
 * statusbar, and the dropdown all return to the committed state; the
 * unsaved new inventory is discarded.
 */
function restoreCommittedInventory() {
    const snap = editorState.committedSnapshot;
    if (!snap) return;
    try {
        const info = callBridge("load_inventory_json", snap.json, "");
        applyInventoryInfo(info);
        setInventoryStatus(info);
        // Restore whatever the dropdown showed for the committed
        // inventory (a bundled file value, a PHOIBLE entry, or "" if it
        // was itself unlisted). Programmatic ``.value`` does not fire a
        // ``change`` event, so this does not re-trigger a load.
        nodes.inventoryPicker.value = snap.dropdownValue;
    } catch (e) {
        // Best-effort: a failed restore leaves the new inventory in
        // place, no worse than before this guard existed.
        setStatus(
            bridgeErrorMessage(e, "Could not restore the previous inventory."),
            STATUS_KIND.error,
        );
    }
}

/**
 * The active inventory has just been saved to a file, so it is the
 * committed state now: drop the rollback marker (a later back-out
 * keeps it) and deselect the dropdown, since a saved inventory is not
 * one of the listed bundled / PHOIBLE options. The statusbar carries
 * its name instead.
 */
function finishInventoryTransaction() {
    editorState.engineReplaced = false;
    editorState.committedSnapshot = null;
    markInventoryUnlisted();
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
        // A "New" inventory saved with no further edits is committed by
        // the download itself; stop tracking it for rollback, but only
        // if the file actually downloaded (else keep the rollback so
        // Back still restores the previous inventory).
        if (downloadCurrentInventory() && editorState.engineReplaced) {
            finishInventoryTransaction();
        }
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
            editorState.source,
        );
    } catch (e) {
        setEditorStatus(`Save failed: ${bridgeErrorMessage(e, "error")}`);
        return;
    }
    editorState.dirty = false;
    applyInventoryInfo(info);
    // The engine swapped to the saved inventory, so refresh the main
    // statusbar's name + counts line through its single writer (the
    // load path pairs these two; save-as must too).
    setInventoryStatus(info);
    refreshEditorFromCurrent();
    // Finalize the transaction only on a real download; a failed save
    // keeps the rollback marker so Back restores the prior inventory.
    if (downloadCurrentInventory()) {
        finishInventoryTransaction();
    }
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

// Label-prompt modal.

// Pending invocation state: the title / labels / handlers vary per
// call site (+ Segment vs + Feature), but the dialog itself is
// reused. ``_labelPromptPending`` is the active invocation; the
// form-submit listener is wired once and reads from it.
let _labelPromptPending = null;

/**
 * Show the shared text-input modal. Used by + Segment and
 * + Feature to gather the new label, validate it via the bridge
 * (which routes through the same validator the desktop editor
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
    // Route through the shared dialog helper so the prompt captures
    // its trigger (+Segment / +Feature) and restores focus to it on
    // close, like every other dialog. openDialog does not focus an
    // input, so we still rAF-focus the text field afterwards.
    openDialog(nodes.labelPromptDialog);
    requestAnimationFrame(() => nodes.labelPromptInput.focus());
}

function closeLabelPrompt() {
    closeDialog(nodes.labelPromptDialog);
    _labelPromptPending = null;
}

export function wireLabelPrompt() {
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
