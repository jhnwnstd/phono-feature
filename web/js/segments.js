// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Required Notice: Copyright 2026 John Winstead, https://github.com/jhnwnstd/phono-feature
/**
 * Segments pane: the consonant grid, group headers, class filter
 * popover, column balancing and spillover reflow.
 *
 * Mutually dependent with ``analysis.js`` by design and that pair is
 * pinned by the layering test: a segment click runs an analysis, and
 * an analysis relayouts the grid. Both crossings are function calls
 * made after boot, never module-init reads, so the ES module cycle
 * carries no temporal-dead-zone risk.
 */
import { hasActiveSelection, runAnalysis } from "./analysis.js";
import { STATUS_TEXT } from "./config.js";
import { callBridge, nodes } from "./infra.js";
import { _rootCS, detachResizeObserver, parseCSSLength } from "./measure.js";
import { _buildSegmentButton } from "./seg_button.js";
import { VOCOID_CLASS_LABEL, VOWEL_CLASS_LABEL, state } from "./state.js";
import { _buildVowelChart } from "./vowel_chart.js";


/**
 * Render the segments pane. Vowel chart is a floated trapezoid in
 * the top-right; consonant groups stack below as flow content. If
 * the pane would overflow after layout settles, rebalance moves
 * the bottom groups into a 2-column spillover at the bottom.
 */
/** Disconnect every ResizeObserver attached to chart data
 *  elements before the chart is destroyed. Without this the
 *  observers keep firing on detached DOM through stale closures
 *  over the OLD ``chart`` payload and leak references that prevent
 *  GC.
 *
 *  New observers should register under a ``data-*-observer``
 *  property on ``dataEl`` so they're discovered by this helper
 *  automatically.
 */
function _disconnectChartObservers(grid) {
    if (!grid) return;
    for (const dataEl of grid.querySelectorAll(".vowel-chart-data")) {
        detachResizeObserver(dataEl, "_silhouetteResizeObserver");
    }
}

function renderSegmentGrid(groups, vowelChart) {
    const grid = nodes.segGrid;
    _disconnectChartObservers(grid);
    grid.innerHTML = "";
    state.seg_buttons.clear();
    // Render when there is ANYTHING vowel-ish to show: trapezoid cells,
    // or chip-strip diphthongs alone (an all-diphthong vowel system has
    // zero cells but must still list its segments; mirrors the desktop,
    // which gates set_vowels on vowel SEGMENTS, not cells).
    const hasVowelContent =
        vowelChart &&
        ((vowelChart.cells && vowelChart.cells.length) ||
            (vowelChart.diphthongs && vowelChart.diphthongs.length));
    if (hasVowelContent) {
        const vowels = document.createElement("div");
        vowels.className = "seg-vowels";
        // Sizing policy: actual width =
        // ``max(VOWEL_CHART_W_FLOOR, natural + chrome)``. Sparse
        // inventories (Spanish 5 vowels) shrink to the floor;
        // dense ones (Hayes Universal 26 vowels) grow past it.
        // Owned LOCALLY by the web renderer; desktop has its own
        // parallel ``VOWEL_CHART_W_FLOOR`` in
        // ``desktop/.../vowel_chart.py`` so the two platforms
        // can tune independently. Chrome (row-label gutter +
        // right padding) is read from the baked CSS vars so it
        // tracks ``chart_style.py`` changes without a JS edit.
        if (typeof vowelChart.natural_data_width_px === "number") {
            const chromeW =
                parseCSSLength("--vowel-chart-row-label-gutter", 72)
                + parseCSSLength("--vowel-chart-pad-r", 12);
            const naturalSlotW =
                vowelChart.natural_data_width_px + chromeW;
            vowels.style.width =
                `${Math.max(_vowelChartWFloor(), naturalSlotW)}px`;
        }
        vowels.appendChild(_buildVowelChart(vowelChart));
        grid.appendChild(vowels);
    }
    // Vocoid strip under the chart: vowel-like segments that fit no
    // class. Gated by the Vocoids filter class; usually empty.
    const vocoids = state.hidden_segment_classes.has(VOCOID_CLASS_LABEL)
        ? []
        : (state.seg_vocoids || []);
    if (vocoids.length) {
        grid.appendChild(_buildVocoidStrip(vocoids));
    }
    // Membership cardinality per glyph, read straight from the producer
    // output (``groups`` is the multiset): a glyph in more than one
    // manner class is a multi-membership consonant. The "reaches N
    // classes" cue and the placements come from this ONE source, so the
    // label can never disagree with the rows it marks.
    const multiCount = new Map();
    for (const group of groups) {
        for (const seg of group.segments) {
            multiCount.set(seg, (multiCount.get(seg) || 0) + 1);
        }
    }
    for (const group of groups) {
        grid.appendChild(_buildConsonantGroup(group, multiCount));
    }
    relayoutSegments();
}

/** Build the flat vocoid strip (header + segment buttons) rendered
 *  under the vowel chart for vowel-like segments that fit no class.
 *  Reuses the ``.seg-group`` skeleton so it themes + sizes like the
 *  other groups; ``seg-vocoids`` lets CSS place it under the chart. */
function _buildVocoidStrip(segs) {
    const el = document.createElement("div");
    el.className = "seg-group seg-vocoids";
    el.dataset.group = VOCOID_CLASS_LABEL;
    const header = document.createElement("div");
    header.className = "seg-group-header";
    header.textContent = VOCOID_CLASS_LABEL;
    el.appendChild(header);
    const row = document.createElement("div");
    row.className = "seg-row";
    for (const seg of segs) row.appendChild(_buildSegmentButton(seg));
    el.appendChild(row);
    return el;
}

/** Re-render the segment grid honoring ``hidden_segment_classes``.
 *  Filters the cached consonant groups and drops the vowel chart when
 *  the "Vowels" class is hidden, then defers to ``renderSegmentGrid``
 *  so the spillover planner reflows over the visible set and reclaims
 *  the freed space. Single entry point for both a fresh load and a
 *  popover toggle. */
export function renderSegmentsWithVisibility() {
    const hidden = state.hidden_segment_classes;
    const groups = (state.seg_groups || []).filter(
        (g) => !hidden.has(g.name),
    );
    const vowelChart = hidden.has(VOWEL_CLASS_LABEL)
        ? null
        : state.seg_vowel_chart;
    renderSegmentGrid(groups, vowelChart);
    updateClassFilterButton();
}

/** Ordered class labels for the filter popover: the consonant groups
 *  in engine order, then "Vowels" if the inventory has a vowel chart.
 *  Mirrors the seg grid's own class set so every visible class gets a
 *  checkbox. */
function _segmentClassLabels() {
    const labels = (state.seg_groups || []).map((g) => g.name);
    const chart = state.seg_vowel_chart;
    if (chart && Array.isArray(chart.cells) && chart.cells.length) {
        labels.push(VOWEL_CLASS_LABEL);
    }
    if ((state.seg_vocoids || []).length) {
        labels.push(VOCOID_CLASS_LABEL);
    }
    return labels;
}

/** The segment strings in a class label: a consonant group's segments,
 *  or every vowel-chart cell's segments for "Vowels". Used to prune a
 *  hidden class out of the selection. */
function _segmentsInClass(label) {
    if (label === VOCOID_CLASS_LABEL) {
        return (state.seg_vocoids || []).slice();
    }
    if (label === VOWEL_CLASS_LABEL) {
        const out = [];
        const chart = state.seg_vowel_chart;
        if (chart && Array.isArray(chart.cells)) {
            for (const cell of chart.cells) {
                for (const s of cell.segs || []) {
                    if (s && s.seg) out.push(s.seg);
                }
            }
        }
        return out;
    }
    const g = (state.seg_groups || []).find((x) => x.name === label);
    return g ? g.segments.slice() : [];
}

/** Enable the filter button only when there is something to filter and
 *  flag it (``aria-pressed``) when any class is hidden, so the
 *  affordance reads as "active" without adding chrome to the pane. */
function updateClassFilterButton() {
    const btn = nodes.segFilterBtn;
    const labels = _segmentClassLabels();
    btn.disabled = labels.length === 0;
    btn.setAttribute(
        "aria-pressed",
        state.hidden_segment_classes.size > 0 ? "true" : "false",
    );
}

/** Build (or rebuild) the popover body from the current class list and
 *  visibility state. Rebuilt on every open so it always reflects the
 *  loaded inventory and any toggles made while it is open. */
function buildClassPopover() {
    const pop = nodes.segClassPopover;
    pop.replaceChildren();
    const heading = document.createElement("div");
    heading.className = "class-popover-heading";
    heading.textContent =
        STATUS_TEXT.class_popover_heading || "Show classes";
    pop.appendChild(heading);
    for (const label of _segmentClassLabels()) {
        const row = document.createElement("label");
        row.className = "class-popover-row";
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = !state.hidden_segment_classes.has(label);
        cb.dataset.class = label;
        const text = document.createElement("span");
        text.textContent = label;
        row.append(cb, text);
        pop.appendChild(row);
    }
}

/** Position the popover directly under the filter button using fixed
 *  (viewport) coordinates from the button's rect, right-aligned to the
 *  button and clamped on screen. Fixed + body-level placement is why it
 *  escapes the seg panel's containing block and overflow clipping. */
export function positionClassPopover() {
    const pop = nodes.segClassPopover;
    const r = nodes.segFilterBtn.getBoundingClientRect();
    pop.style.top = `${Math.round(r.bottom + 4)}px`;
    // offsetWidth is valid here: the popover is already shown.
    const pw = pop.offsetWidth || 184;
    const left = Math.max(
        8,
        Math.min(Math.round(r.right - pw), window.innerWidth - pw - 8),
    );
    pop.style.left = `${left}px`;
}

/** Open or close the class-visibility popover. ``force`` true opens,
 *  false closes; omitted toggles on the current state. */
export function toggleClassPopover(force) {
    const pop = nodes.segClassPopover;
    const btn = nodes.segFilterBtn;
    const open = force === undefined ? pop.hidden : force;
    if (open) {
        buildClassPopover();
        pop.hidden = false;
        positionClassPopover();
        btn.setAttribute("aria-expanded", "true");
    } else {
        pop.hidden = true;
        btn.setAttribute("aria-expanded", "false");
    }
}

/** Toggle one class's visibility from a popover checkbox change and
 *  re-render. Keeps the popover open so the user can flip several. */
export function onClassPopoverChange(ev) {
    const cb = ev.target.closest('input[type="checkbox"]');
    if (!cb) return;
    const label = cb.dataset.class;
    let pruned = false;
    if (cb.checked) {
        state.hidden_segment_classes.delete(label);
    } else {
        state.hidden_segment_classes.add(label);
        // Drop from the selection only the segments that now have NO
        // visible, deselectable button (the ghost-selection contract
        // gap). Under the MULTISET a segment can render in several
        // classes, so hiding one class must NOT deselect a segment still
        // shown in another visible class; only a segment left with no
        // visible placement is pruned.
        const stillVisible = new Set();
        for (const other of _segmentClassLabels()) {
            if (other !== label && !state.hidden_segment_classes.has(other)) {
                for (const s of _segmentsInClass(other)) stillVisible.add(s);
            }
        }
        const orphaned = new Set(
            _segmentsInClass(label).filter((s) => !stillVisible.has(s)),
        );
        if (orphaned.size) {
            const before = state.selected_segments.length;
            state.selected_segments = state.selected_segments.filter(
                (s) => !orphaned.has(s),
            );
            pruned = state.selected_segments.length !== before;
        }
    }
    renderSegmentsWithVisibility();
    // Re-run analysis only when there is selection / query state to
    // re-apply to the rebuilt buttons, or a prune just changed the
    // selection. With nothing selected the empty-state hints are already
    // correct, so the bridge round-trip is pure overhead and is skipped.
    if (state.bridge && (pruned || hasActiveSelection())) runAnalysis();
}

// Cached signature of the last successful relayout pass. When the
// grid width, vowel-chart width, row count, and per-row segment
// counts are all unchanged, the math below would produce the same
// answer; we early-return. Catches: (a) double-firing at startup
// (renderSegmentGrid + the initial resize listener), (b) idempotent
// re-runs on pane activation when width didn't actually change.
let _lastRelayoutKey = "";

/** Single entry point for any code path that changes the segments
 *  pane width or contents: re-runs the per-group column pass and
 *  the spillover rebalance. Always defers to the next frame so
 *  layout has flushed before measuring; same-state calls early-
 *  return via ``_lastRelayoutKey`` so call-site centralisation
 *  doesn't multiply startup work. */
export function relayoutSegments() {
    const grid = nodes.segGrid;
    if (!grid) return;
    const run = () => {
        const vowelsEl = grid.querySelector(".seg-vowels");
        const rows = [...grid.querySelectorAll(".seg-row")];
        const key = [
            grid.clientWidth,
            vowelsEl ? vowelsEl.offsetWidth : 0,
            rows.length,
            rows.map(
                (r) => r.querySelectorAll(".seg-btn").length,
            ).join(","),
        ].join("|");
        if (key === _lastRelayoutKey) return;
        // Only record the key once the bridge can actually apply the
        // layout. Pre-bridge both passes no-op (they need the shared
        // planner), so caching the key then would suppress the first
        // real pass once the bridge is in.
        if (state.bridge) _lastRelayoutKey = key;
        // Thread the already-queried row list through so the
        // column-picker doesn't re-run the same querySelectorAll.
        applyPerGroupSegmentColumns(rows);
        rebalanceSegmentSpillover();
    };
    if ("requestAnimationFrame" in window) {
        window.requestAnimationFrame(run);
    } else {
        run();
    }
}

// Per-button stride cached once at boot. Source of truth lives
// in the CSS variables baked from ``constants.BTN_W`` /
// ``constants.BTN_GAP`` by ``web/scripts/build.py``; reading them
// per relayout walks the cascade on every splitter drag. NaN
// values mean the read happened before the relay attached;
// callers fall back to the literal defaults in that case.
let _BTN_W_CSS = NaN;
let _BTN_GAP_CSS = NaN;

// Web's PLATFORM ADJUSTMENT to the shared canonical chart-width
// floor (``MIN_VOWEL_CHART_W_PX`` in layout.py, relayed as
// ``--min-vowel-chart-w`` via build.py). The architectural
// pattern: shared layer owns the canonical math; each renderer
// adds its own platform-specific offset to land at the rendered
// floor for THIS platform. Currently 0 (no adjustment needed);
// ``test_vowel_chart_w_floor_covers_phoible`` pins this literal
// so the tuning knob stays available for future CSS box-model /
// scrollbar-gutter reconciliation.
const WEB_VOWEL_CHART_W_ADJ = 0;

function _vowelChartWFloor() {
    return parseCSSLength("--min-vowel-chart-w", 320) + WEB_VOWEL_CHART_W_ADJ;
}

export function _refreshButtonStrideCache() {
    _BTN_W_CSS = parseFloat(_rootCS.getPropertyValue("--seg-btn-w"));
    _BTN_GAP_CSS = parseFloat(_rootCS.getPropertyValue("--seg-btn-gap"));
}

/** Pick a column count per consonant group that avoids one-button
 *  orphan rows. Mirrors the desktop's per-group ``best_segment_n_cols``
 *  pass in ``SegmentGridWidget._do_relayout``: same Python helper, two
 *  call sites. Inline ``grid-template-columns`` per ``.seg-row``
 *  switches that row from the default ``flex-wrap`` to a grid with the
 *  computed count; default CSS still applies between layout passes for
 *  the brief window before this runs.
 *
 *  ``rows`` may be passed in by ``relayoutSegments`` (which has
 *  already queried them); falls back to a fresh querySelectorAll
 *  for callers that don't have a row list handy. */
function applyPerGroupSegmentColumns(rows) {
    const grid = nodes.segGrid;
    if (!grid) return;
    if (!rows) rows = [...grid.querySelectorAll(".seg-row")];
    if (rows.length === 0) return;
    // Pre-bridge the rows keep the default flex-wrap layout (see the
    // note above); the orphan-avoiding column count needs the shared
    // Python helper, so defer the whole pass until the bridge is in.
    if (!state.bridge) return;
    const sample = rows[0].querySelector(".seg-btn");
    if (!sample) return;
    const btnW = sample.offsetWidth || _BTN_W_CSS || 33;
    const gapPx = Number.isFinite(_BTN_GAP_CSS) ? _BTN_GAP_CSS : 4;
    // Consonant rows wrap around the vowel chart ONLY when the chart
    // floats. In stacked mode (container-query below VOWEL_STACK_W)
    // the chart is a full-width block above the consonants and takes
    // no horizontal space away from them; subtracting its width would
    // collapse maxCols to 1 and stack every button vertically even
    // though the pane is wide.
    const vowelsEl = grid.querySelector(".seg-vowels");
    const vowelsFloating =
        vowelsEl && window.getComputedStyle(vowelsEl).cssFloat !== "none";
    const vowelsW = vowelsFloating ? vowelsEl.offsetWidth + 16 : 0;
    const consonantW = Math.max(btnW, grid.clientWidth - vowelsW);
    const maxCols = Math.max(
        1,
        Math.floor((consonantW + gapPx) / (btnW + gapPx)),
    );
    const sizes = rows.map(
        (r) => r.querySelectorAll(".seg-btn").length,
    );
    const groupCols = callBridge(
        "best_segment_n_cols_for_groups", sizes, maxCols,
    );
    for (let i = 0; i < rows.length; i++) {
        rows[i].style.display = "grid";
        // Fixed tracks (not minmax-to-max-content): all seg-buttons
        // are the same width by design; wide glyphs shrink via the
        // rasterizer rather than letting their column expand and
        // breaking the matrix alignment.
        rows[i].style.gridTemplateColumns =
            `repeat(${groupCols[i]}, ${btnW}px)`;
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
    // Clear any prior column assignment so re-measure starts fresh.
    spillover.style.removeProperty("--seg-spillover-cols");

    const available = grid.clientHeight;
    const consonants = [...grid.querySelectorAll(
        ":scope > .seg-group:not(.vowel-chart-group)",
    )];
    if (consonants.length === 0) return;

    // Bridge path: ``plan_segment_layout`` returns the FULL plan
    // (main_count + n_spillover_cols + per-group column assignment).
    // Pre-migration the web ran a legacy 2-col partitioner that placed
    // the same inventory differently from the desktop; the shared
    // planner is the only source now. Pre-bridge there is no plan, so
    // the consonant rows keep the CSS default layout until it is in.
    if (state.bridge) {
        const groupNames = consonants.map((el) => el.dataset.group || "");
        const heights = consonants.map((el) => el.offsetHeight);
        const widths = consonants.map((el) => el.offsetWidth);
        // Only pass chartRect when the chart is a floated obstacle
        // beside the consonants; in stacked mode the chart is a full-
        // width block ABOVE the consonants (not an obstacle) and the
        // planner would otherwise use max(main_bottom, chart_bottom)
        // instead of summing them, silently underestimating total
        // height and skipping spillover that would fit. Desktop
        // passes chart_rect=None in this case (segment_grid.py:291).
        const chartEl = grid.querySelector(".vowel-chart-group");
        const vowelsEl = grid.querySelector(".seg-vowels");
        const vowelsFloating =
            vowelsEl && window.getComputedStyle(vowelsEl).cssFloat !== "none";
        let chartRect = null;
        if (chartEl && vowelsFloating) {
            const gridBox = grid.getBoundingClientRect();
            const cBox = chartEl.getBoundingClientRect();
            chartRect = [
                Math.round(cBox.left - gridBox.left),
                Math.round(cBox.top - gridBox.top),
                Math.round(cBox.width),
                Math.round(cBox.height),
            ];
        }
        // ``min_col_w`` matches what the desktop passes: the floor
        // on a spillover column's width so a narrow pane still
        // accepts at least one column. Use the canonical segment
        // button stride.
        const segBtnW = Math.round(parseCSSLength("--seg-btn-w", 33));
        const plan = callBridge(
            "plan_segment_layout",
            groupNames,
            heights,
            widths,
            grid.clientWidth,
            available,
            chartRect,
            segBtnW,
        );
        if (!plan || plan.spillover_groups.length === 0) return;
        // Surface the column count to CSS so the spillover region
        // sizes its grid to ``repeat(N, 1fr)`` with the shared
        // ``--seg-btn-gap`` between columns.
        spillover.style.setProperty(
            "--seg-spillover-cols",
            String(plan.n_spillover_cols),
        );
        grid.appendChild(spillover);
        // Walk spillover_groups in source order so the user reads
        // column-major top-to-bottom. The bridge already sorted by
        // LPT; the column_assignment array tells us where each
        // group lands.
        const spilloverIndex = new Map();
        consonants.forEach((el, idx) => {
            spilloverIndex.set(el.dataset.group || `__idx_${idx}`, el);
        });
        for (
            let i = 0;
            i < plan.spillover_groups.length;
            i++
        ) {
            const name = plan.spillover_groups[i];
            const col = plan.spillover_column_assignment[i];
            const el = spilloverIndex.get(name);
            if (!el) continue;
            // Assign the destination column via CSS grid-column;
            // groups stack within each column in source order.
            el.style.gridColumn = String(col + 1);
            spillover.appendChild(el);
        }
        return;
    }
}

function _buildConsonantGroup(group, multiCount) {
    const groupEl = document.createElement("div");
    groupEl.className = "seg-group";
    // dataset.group lets rebalanceSegmentSpillover match against
    // the bridge's spillover_groups list.
    groupEl.dataset.group = group.name;
    const header = document.createElement("div");
    header.className = "seg-group-header";
    header.textContent = group.name;
    groupEl.appendChild(header);
    const row = document.createElement("div");
    row.className = "seg-row";
    for (const seg of group.segments) {
        // data-multiclass = one segment reaching several classes.
        const n = multiCount && multiCount.get(seg);
        const extra = n > 1 ? { "data-multiclass": String(n) } : undefined;
        row.appendChild(_buildSegmentButton(seg, extra));
    }
    groupEl.appendChild(row);
    return groupEl;
}
