// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Required Notice: Copyright 2026 John Winstead, https://github.com/jhnwnstd/phono-feature
/**
 * Features pane, match mode, and the analysis pipeline that answers a
 * selection: scheduling, debounce, bridge dispatch and the result
 * tabs.
 *
 * See ``segments.js`` for the mutual dependency between the two.
 */
import { LIMITS, MODE, cloneFeatureSpec, emptyFeatureSpec } from "./config.js";
import { STATUS_KIND, callBridge, nodes, setStatus } from "./infra.js";
import { createRasterizedLabel } from "./measure.js";
import { relayoutSegments } from "./segments.js";
import { state } from "./state.js";


export function onSegmentClicked(seg) {
    activateMode(MODE.SEG_TO_FEAT);
    const idx = state.selected_segments.indexOf(seg);
    const wasSelected = idx >= 0;
    if (wasSelected) {
        state.selected_segments.splice(idx, 1);
    } else {
        state.selected_segments.push(seg);
    }
    // Optimistic flip so the click feels instant; the debounced
    // runSegToFeat reconciles the full state after. Flip EVERY
    // .seg-btn[data-seg=...] so multi-placement segments stay in sync.
    const nextState = wasSelected ? "default" : "selected";
    const nextPressed = wasSelected ? "false" : "true";
    const cssSafe = CSS.escape(seg);
    for (const btn of document.querySelectorAll(
        `.seg-btn[data-seg="${cssSafe}"]`,
    )) {
        btn.dataset.state = nextState;
        btn.setAttribute("aria-pressed", nextPressed);
    }
    scheduleAnalysis();
}

// Render the feature panel. Cards are pre-distributed across two
// columns by ``layout.distribute_feature_groups`` on the Python side;
// this just mounts each card in the column it advertises.
export function renderFeaturePanel(featureGroups) {
    const list = nodes.featList;
    list.innerHTML = "";
    state.feat_rows.clear();
    const columnCount = 2;
    const cols = Array.from({ length: columnCount }, () => {
        const c = document.createElement("div");
        c.className = "feat-col";
        return c;
    });
    let totalRows = 0;
    for (const group of featureGroups) {
        const colIndex = Math.max(
            0, Math.min(columnCount - 1, group.column ?? 0),
        );
        cols[colIndex].appendChild(_buildFeatureGroup(group));
        totalRows += (group.features || []).length;
    }
    for (const c of cols) list.appendChild(c);
    applyFeatureDensity(totalRows);
}

// Switch the feature pane to compact density when the active-feature
// count crosses FEAT_COMPACT_THRESHOLD, matching the desktop.
function applyFeatureDensity(featureCount) {
    const threshold = LIMITS.feat_compact_threshold || 22;
    const compact = featureCount >= threshold;
    if (compact) {
        nodes.featPanel.dataset.density = "compact";
    } else {
        delete nodes.featPanel.dataset.density;
    }
}

function _buildFeatureGroup(group) {
    const groupEl = document.createElement("div");
    groupEl.className = "feat-group";
    const header = document.createElement("div");
    header.className = "feat-group-header";
    header.textContent = group.name;
    groupEl.appendChild(header);
    for (const feat of group.features) {
        groupEl.appendChild(_buildFeatureRow(feat));
    }
    return groupEl;
}

// Build a single feature row. Clicks are caught by a delegated
// listener on #feat-list (wireFeatureDelegation).
function _buildFeatureRow(feat) {
    const row = document.createElement("div");
    row.className = "feat-row";
    row.dataset.feat = feat;
    const name = document.createElement("div");
    name.className = "feat-name";
    name.setAttribute("aria-label", feat);
    // Plain DOM text (not rasterized) so ``font-variant: small-caps``
    // shapes via the system font's OpenType smcp; canvas font support
    // for small-caps is inconsistent (broken in WebKit). Features with
    // an INLP glossary entry get an <a> inside .feat-name so flex and
    // small-caps still apply; underline styling in .feat-glossary-link.
    const glossaryUrl = state.featureGlossary
        ? state.featureGlossary[feat]
        : undefined;
    if (glossaryUrl) {
        const link = document.createElement("a");
        link.className = "feat-glossary-link";
        link.href = glossaryUrl;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = feat;
        link.title = "Open the glossary entry (opens in a new tab)";
        name.appendChild(link);
    } else {
        name.textContent = feat;
    }
    row.appendChild(name);
    // Fixed-width .feat-controls slot: badge and +/- buttons swap
    // in the same slot so the name column doesn't reflow on mode.
    const controls = document.createElement("div");
    controls.className = "feat-controls";
    const badge = document.createElement("div");
    badge.className = "feat-badge";
    badge.setAttribute("aria-label", "·");
    badge.appendChild(
        createRasterizedLabel("·", '12px "Noto Sans", sans-serif')
    );
    controls.appendChild(badge);
    const polarityButtons = {};
    for (const polarity of ["+", "−"]) {
        const btn = document.createElement("button");
        btn.className = "feat-btn";
        btn.type = "button";
        const code = polarity === "+" ? "+" : "-";
        btn.dataset.polarity = code;
        btn.setAttribute("aria-label", polarity);
        btn.appendChild(
            createRasterizedLabel(polarity, '13px "Noto Sans", sans-serif')
        );
        controls.appendChild(btn);
        polarityButtons[code] = btn;
    }
    row.appendChild(controls);
    state.feat_rows.set(feat, {
        row, badge,
        plus: polarityButtons["+"],
        minus: polarityButtons["-"],
    });
    return row;
}

// Paint a feature row's +/- toggle state + data-query-value.
// ``value`` is "+", "-", or empty to clear.
function setFeatureRowQuery(rec, value) {
    rec.plus.dataset.active = value === "+" ? "true" : "false";
    rec.minus.dataset.active = value === "-" ? "true" : "false";
    if (value === "+" || value === "-") rec.row.dataset.queryValue = value;
    else delete rec.row.dataset.queryValue;
}

// Re-apply FEAT-mode query markers onto every row after a rebuild.
export function _restoreFeatureQueryMarkers() {
    for (const [feat, rec] of state.feat_rows) {
        setFeatureRowQuery(rec, state.selected_features[feat]);
    }
}

export function onFeatureClicked(feat, polarity) {
    activateMode(MODE.FEAT_TO_SEG);
    if (state.selected_features[feat] === polarity) {
        delete state.selected_features[feat];
    } else {
        state.selected_features[feat] = polarity;
    }
    const rec = state.feat_rows.get(feat);
    if (rec) setFeatureRowQuery(rec, state.selected_features[feat]);
    scheduleAnalysis();
}

// Switch top-level mode, projecting outgoing state into incoming
// (seg->feat: feat := common features; feat->seg: seg := matches).
export function activateMode(mode) {
    if (state.mode === mode) return;
    const transition = state.bridge
        ? callBridge(
            "project_mode_switch",
            state.mode,
            mode,
            state.selected_segments,
            state.selected_features,
        )
        // Pre-bridge fallback = mode_logic.project_mode_transition
        // with engine=None (target mode starts empty).
        : {
            saved_seg_state:
                state.mode === MODE.SEG_TO_FEAT
                    ? state.selected_segments.slice()
                    : [],
            saved_feat_state:
                state.mode === MODE.SEG_TO_FEAT
                    ? emptyFeatureSpec()
                    : cloneFeatureSpec(state.selected_features),
            selected_segments: [],
            selected_features: emptyFeatureSpec(),
        };

    state.saved_seg_state = transition.saved_seg_state.slice();
    state.saved_feat_state = cloneFeatureSpec(transition.saved_feat_state);

    state.mode = mode;
    const isS2F = mode === MODE.SEG_TO_FEAT;
    nodes.segPanel.dataset.active = isS2F ? "true" : "false";
    nodes.featPanel.dataset.active = isS2F ? "false" : "true";

    if (isS2F) {
        state.selected_segments = transition.selected_segments.slice();
        state.selected_features = cloneFeatureSpec(transition.selected_features);
        for (const rec of state.feat_rows.values()) {
            setFeatureRowQuery(rec, "");
        }
        // FEAT→SEG: segment-button states are also painted by the
        // subsequent runAnalysis pass below (with ``suggested``
        // decoration on extension candidates). Skip the per-button
        // write here when the bridge will repaint to avoid a
        // brief flash through the intermediate ``default``/``selected``
        // state. The seg states will be canonical after runAnalysis.
        if (!state.bridge || !state.selected_segments.length) {
            const selectedSet = new Set(state.selected_segments);
            for (const [seg, btns] of state.seg_buttons) {
                const isSelected = selectedSet.has(seg);
                const target = isSelected ? "selected" : "default";
                for (const btn of btns) {
                    if (btn.dataset.state === target) continue;
                    btn.dataset.state = target;
                    btn.setAttribute(
                        "aria-pressed", isSelected ? "true" : "false",
                    );
                }
            }
        }
    } else {
        state.selected_features = cloneFeatureSpec(transition.selected_features);
        state.selected_segments = transition.selected_segments.slice();
        // SEG->FEAT: skip the intermediate selected->default write
        // when analysis will repaint segments as matched/unmatched
        // (avoids a visible flicker). Reset only when no query follows.
        if (!state.bridge || !Object.keys(state.selected_features).length) {
            for (const btns of state.seg_buttons.values()) {
                for (const btn of btns) {
                    if (btn.dataset.state === "selected") {
                        btn.dataset.state = "default";
                        btn.setAttribute("aria-pressed", "false");
                    }
                }
            }
        }
        _restoreFeatureQueryMarkers();
    }

    // Bypass debounce on mode switch (paint the new state
    // synchronously instead of leaving segments stale for 30 ms).
    if (state.bridge) runAnalysis();
    else clearAnalysisTabs();

    // Data-active flips may resize the segments pane; re-layout so
    // column tracks match the new width. Idempotent + rAF-deferred.
    relayoutSegments();
}

const ANALYSIS_DEBOUNCE_MS = 30;

// True iff the user has any active query (segments in SEG mode,
// features in FEAT mode). Single home so boot / mode / theme toggles
// can't drift on the "is anything selected" rule.
export function hasActiveSelection() {
    return state.selected_segments.length > 0
        || Object.keys(state.selected_features).length > 0;
}

export function scheduleAnalysis() {
    if (state.debounce_timer !== null) clearTimeout(state.debounce_timer);
    state.debounce_timer = setTimeout(() => {
        state.debounce_timer = null;
        runAnalysis();
    }, ANALYSIS_DEBOUNCE_MS);
}

const MODE_HANDLERS = Object.freeze({
    [MODE.SEG_TO_FEAT]: runSegToFeat,
    [MODE.FEAT_TO_SEG]: runFeatToSeg,
});

// Run analysis for the current mode. No-op pre-bridge; the boot
// path triggers a final run once the bridge attaches.
export function runAnalysis() {
    if (!state.bridge) return;
    MODE_HANDLERS[state.mode](++state.analysis_token);
}

// Apply stateFor(seg) to every cached segment button. Total sweep
// (immune to dict-fallback ghosts).
export function _applySegmentStates(stateFor) {
    for (const [seg, btns] of state.seg_buttons) {
        const newState = stateFor(seg);
        for (const btn of btns) {
            if (btn.dataset.state !== newState) {
                btn.dataset.state = newState;
                const pressed =
                    newState === "selected" || newState === "matched";
                btn.setAttribute("aria-pressed", pressed ? "true" : "false");
            }
        }
    }
}

// ``segmentStates`` is sparse: it lists only the segments whose state
// differs from ``defaultState`` (the payload's default_segment_state),
// so a segment absent from the map takes that baseline.
function _applySegmentStateMap(segmentStates, defaultState) {
    const fallback = defaultState ?? "default";
    _applySegmentStates((seg) => segmentStates?.[seg] ?? fallback);
}

export function _applyFeatureRowStates(featureRows) {
    for (const [feat, rec] of state.feat_rows) {
        const rowState = featureRows?.[feat];
        const value = rowState?.value ?? "";
        const shared = rowState?.shared === true;
        const contrastive = rowState?.contrastive === true;
        rec.row.dataset.value = value;
        rec.row.dataset.shared = shared ? "true" : "false";
        rec.row.dataset.contrastive = contrastive ? "true" : "false";
        const badgeText = rowState?.badge ?? "·";
        _setRasterizedBadge(rec.badge, badgeText);
    }
}

/** Swap a feat-row badge's rasterized label in place. No-op when
 *  the badge already carries ``text``; analysis passes that land
 *  on the same row state (the common case after the engine
 *  short-circuits identical selections) skip the DOM swap entirely. */
function _setRasterizedBadge(badgeEl, text) {
    if (badgeEl.dataset.label === text) return;
    badgeEl.dataset.label = text;
    badgeEl.setAttribute("aria-label", text);
    badgeEl.replaceChildren(
        createRasterizedLabel(text, '12px "Noto Sans", sans-serif')
    );
}

// The two analysis directions run the same flow: call the bridge,
// surface a failure, drop the result if a newer request superseded
// this ``token``, then repaint tabs + segment states. They differ
// only in the bridge fn + argument and whether feature-row states
// are repainted (seg->feat owns the feature rows; feat->seg does
// not touch them).
function _runAnalysis(token, bridgeFn, arg, applyFeatureRows, ...extra) {
    let result;
    try {
        result = callBridge(bridgeFn, arg, ...extra);
    } catch (e) {
        _surfaceBridgeFailure(bridgeFn, e);
        return;
    }
    if (token !== state.analysis_token) return;
    setAnalysisTabs(result.analysis_tabs);
    _applySegmentStateMap(
        result.segment_states, result.default_segment_state,
    );
    if (applyFeatureRows) _applyFeatureRowStates(result.feature_rows);
}

/** How many minimal specs fit the analysis pane's fixed height before a
 *  column wraps. Measured from the live content area so the shared
 *  column-major spec table fills the pane's height (then spills into
 *  more columns, then scrolls). Falls back to the shared floor before
 *  the pane is laid out. Mirrors the desktop's
 *  ``_analysis_spec_rows_per_col``. */
const ANALYSIS_MIN_SPEC_ROWS = 4;
export function analysisSpecRowsPerCol() {
    const el = nodes.analysisContentClass;
    // Class tab may be display:none (another tab active); fall back to
    // the always-sized content frame so the height is still readable.
    const h = el.clientHeight
        || (el.parentElement ? el.parentElement.clientHeight : 0);
    if (!h) return ANALYSIS_MIN_SPEC_ROWS;
    const cs = getComputedStyle(el);
    const pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
    const line = parseFloat(cs.lineHeight) || 18;
    // A spec row is one text line + the table's per-row border-spacing.
    // Reserve the "Minimal specifications (N):" heading, which is a
    // paragraph (~two lines with its bottom margin), and round DOWN so a
    // full column never overflows into a vertical scrollbar.
    const avail = h - pad - (line * 2 + 8);
    return Math.max(ANALYSIS_MIN_SPEC_ROWS, Math.floor(avail / (line + 2)));
}

function runSegToFeat(token) {
    _runAnalysis(
        token, "analyze_segments", state.selected_segments, true,
        analysisSpecRowsPerCol(),
    );
}

function runFeatToSeg(token) {
    _runAnalysis(token, "analyze_features", state.selected_features, false);
}

/** Surface a bridge-call failure to the user instead of letting it
 *  halt the JS event loop with no feedback. The bridge raises
 *  ``ValidationError`` for bad inputs (validated at api.py); for
 *  any other exception the catch path here still keeps the UI
 *  responsive. The console line carries the full error for
 *  developer triage; the statusbar shows the friendlier summary.
 */
function _surfaceBridgeFailure(callName, err) {
    const msg = err && err.message ? err.message : String(err);
    console.error(`bridge ${callName} failed:`, err);
    setStatus(`Analysis failed: ${msg.split("\n")[0]}`, STATUS_KIND.error);
}

// Push the shared view-model's per-tab payload into the analysis pane.
// Mirrors the desktop's ``AnalysisPanel.set_sections``. Payload:
// selection/class/features/contrasts HTML, contrasts_enabled flag,
// class_state ("natural" | "not_natural" | "neutral") that colors the
// Class tab.
export function setAnalysisTabs(tabs) {
    if (!tabs) {
        clearAnalysisTabs();
        return;
    }
    // Skip ``innerHTML =`` writes when the payload is identical to
    // the prior pass; ``innerHTML =`` discards + reparses even on
    // identical strings, which is the common case when an
    // FT→ST transition lands on the same selection.
    const classHtml = tabs["class"] || "";
    const featuresHtml = tabs.features || "";
    const contrastsHtml = tabs.contrasts || "";
    if (state.lastAnalysisHtml === undefined) state.lastAnalysisHtml = {};
    const last = state.lastAnalysisHtml;
    if (last.cls !== classHtml) {
        nodes.analysisContentClass.innerHTML = classHtml;
        last.cls = classHtml;
    }
    if (last.features !== featuresHtml) {
        nodes.analysisContentFeatures.innerHTML = featuresHtml;
        last.features = featuresHtml;
    }
    if (last.contrasts !== contrastsHtml) {
        nodes.analysisContentContrasts.innerHTML = contrastsHtml;
        last.contrasts = contrastsHtml;
    }
    const contrastsEnabled = tabs.contrasts_enabled !== false;
    nodes.analysisTabContrasts.disabled = !contrastsEnabled;
    nodes.analysisTabContrasts.setAttribute(
        "aria-disabled", contrastsEnabled ? "false" : "true",
    );
    // If the user has the Contrasts tab open but the new payload
    // disables it, snap back to Class so they land on real content.
    if (
        !contrastsEnabled
        && nodes.analysisTabContrasts.getAttribute("aria-selected") === "true"
    ) {
        activateAnalysisTab("class");
    }
    nodes.analysisTabClass.dataset.classState = tabs.class_state || "neutral";
}

// Canonical full-reset sink for the analysis pane. Any new display
// cue added later must reset here too.
export function clearAnalysisTabs() {
    nodes.analysisContentClass.innerHTML = "";
    nodes.analysisContentFeatures.innerHTML = "";
    nodes.analysisContentContrasts.innerHTML = "";
    nodes.analysisTabContrasts.disabled = false;
    nodes.analysisTabContrasts.removeAttribute("aria-disabled");
    nodes.analysisTabClass.dataset.classState = "neutral";
    state.lastAnalysisHtml = {};
    activateAnalysisTab("class");
}

/** Switch the visible tab. Updates aria-selected on the tab buttons
 *  and the ``hidden`` attribute on the tab panels. */
export function activateAnalysisTab(name) {
    const buttons = [
        ["class", nodes.analysisTabClass, nodes.analysisContentClass],
        ["features", nodes.analysisTabFeatures, nodes.analysisContentFeatures],
        [
            "contrasts",
            nodes.analysisTabContrasts,
            nodes.analysisContentContrasts,
        ],
    ];
    for (const [tabName, btn, panel] of buttons) {
        const active = tabName === name;
        btn.setAttribute("aria-selected", active ? "true" : "false");
        panel.hidden = !active;
    }
}
