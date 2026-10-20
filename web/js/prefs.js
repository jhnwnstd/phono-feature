// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Required Notice: Copyright 2026 John Winstead, https://github.com/jhnwnstd/phono-feature
/**
 * Persisted user preferences: theme, colourblind palette and match
 * mode, plus the storage wrappers that tolerate a blocked or cleared
 * localStorage.
 */
import {
    _restoreFeatureQueryMarkers,
    hasActiveSelection,
    runAnalysis,
} from "./analysis.js";
import { MODE, STATUS_TEXT } from "./config.js";
import { callBridge, nodes } from "./infra.js";
import { _adoptFeaturePaneState } from "./inventory.js";
import { createRasterizedLabel } from "./measure.js";
import { state } from "./state.js";


/** Theme values come from the relayed ``STATUS_TEXT.theme_values``
 *  baked from ``palette.Theme`` (Python SSOT). Hardcoded fallback
 *  only fires if the inlined JSON is missing. */
const THEME = Object.freeze(
    STATUS_TEXT.theme_values || { LIGHT: "light", DARK: "dark" },
);

/** Clamp an external value (e.g. from localStorage) to a known enum
 *  member, falling back when it is unrecognised. Validates against the
 *  relayed enum so a future Python addition (e.g. a high-contrast theme)
 *  is accepted automatically once baked. Shared by the theme /
 *  palette-mode / match-mode normalizers. */
function normalizeEnumValue(value, enumObj, fallback) {
    return new Set(Object.values(enumObj)).has(value) ? value : fallback;
}

function normalizeTheme(value) {
    return normalizeEnumValue(value, THEME, THEME.LIGHT);
}

/** Best-effort localStorage write. Persistence is a "nice to have";
 *  a quota-exceeded or storage-blocked browser (private window,
 *  iframe with storage disabled, Safari ITP eviction) must not
 *  crash the toggle. The catch logs a warning so the failure mode
 *  is observable in devtools without surfacing to the user. */
function safeStorageSet(key, value) {
    try {
        localStorage.setItem(key, value);
    } catch (e) {
        console.warn(`localStorage write failed for ${key}:`, e);
    }
}

/** Best-effort localStorage read. Some browsers (Safari Lockdown
 *  Mode, embedded contexts) throw on getItem too; treat that as
 *  "no stored value" and return null. */
function safeStorageGet(key) {
    try {
        return localStorage.getItem(key);
    } catch (e) {
        console.warn(`localStorage read failed for ${key}:`, e);
        return null;
    }
}

/**
 * Render the statusbar's "Language Doodad" brand as a rasterized
 * (non-copyable) label. Same canvas-mask trick as the segment
 * buttons: the literal text is in ``aria-label`` for screen
 * readers, but the on-screen glyphs come from a CSS mask so
 * drag-select-copy doesn't pick anything up.
 */
export function wireStatusbarBrand() {
    nodes.statusbarBrand.replaceChildren(
        createRasterizedLabel(
            "Language Doodad", 'italic 13px "Noto Sans", sans-serif'
        )
    );
}

/**
 * Open the project's GitHub Issues "new issue" page in a new
 * tab. The bug-report URL is the canonical place to file
 * reproducible problems; no in-app capture is attempted because
 * the user knows their environment best.
 */
export function wireBugButton() {
    nodes.bugBtn.addEventListener("click", () => {
        window.open(
            "https://github.com/jhnwnstd/phono-feature/issues/new",
            "_blank",
            "noopener,noreferrer"
        );
    });
}

/** Palette-mode values come from the relayed
 *  ``STATUS_TEXT.palette_mode_values`` baked from
 *  ``palette.PaletteMode`` (Python SSOT). Hardcoded fallback only
 *  fires if the inlined JSON is missing. */
const PALETTE_MODE = Object.freeze(
    STATUS_TEXT.palette_mode_values || {
        STANDARD: "standard",
        COLORBLIND: "colorblind",
    },
);

function normalizePaletteMode(value) {
    return normalizeEnumValue(value, PALETTE_MODE, PALETTE_MODE.STANDARD);
}

/** Push the user's restored theme + palette-mode (set by
 *  wireThemeToggle / wireColorblindToggle before the bridge
 *  attached) into Python. Without this, the analysis HTML renders
 *  with the default ``(light, standard)`` palette baked in, even
 *  though the CSS-vars layer is showing dark / colorblind. The
 *  desktop equivalent is the same constructor-time
 *  ``set_theme(saved_theme) + set_palette_mode(saved_mode)`` pair
 *  in :py:meth:`MainWindow.__init__`. */
export function _syncBridgePaletteToStoredState() {
    const theme = normalizeTheme(safeStorageGet("theme"));
    const mode = normalizePaletteMode(safeStorageGet("palette_mode"));
    try {
        callBridge("set_active_theme", theme);
        callBridge("set_active_palette_mode", mode);
    } catch (e) {
        console.warn("palette sync to bridge failed:", e);
    }
}

/** Matching-mode toggle (strict vs. underspecified matching, the
 *  internal WILDCARD mode). Mirrors the colorblind toggle's
 *  structure: persistent localStorage choice, aria-pressed on the
 *  button, and a bridge sync so the Python side recomputes
 *  natural-class results under the chosen semantics.
 *
 *  Wildcard mode treats a segment's ``0`` or absent value as
 *  compatible with either polarity of a requested feature, so a
 *  ``+Voice`` query returns +Voice AND 0Voice segments. The
 *  feature pane also surfaces features that are uniformly ``0``
 *  (otherwise unselectable) because those features ARE queryable
 *  under wildcard: every segment matches.
 */
const MATCH_MODE = Object.freeze(
    STATUS_TEXT.match_mode_values || {
        STRICT: "strict",
        WILDCARD: "wildcard",
    },
);

function normalizeMatchMode(value) {
    return normalizeEnumValue(value, MATCH_MODE, MATCH_MODE.STRICT);
}

/** Push the user's restored matching mode (set by
 *  wireMatchModeToggle before the bridge attached) into Python.
 *  Without this, all natural-class results stay on strict even
 *  when the toolbar shows the wildcard toggle pressed. */
export function _syncBridgeMatchModeToStoredState() {
    const mode = normalizeMatchMode(safeStorageGet("match_mode"));
    try {
        callBridge("set_match_mode", mode);
    } catch (e) {
        console.warn("match-mode sync to bridge failed:", e);
    }
}

/** Set a toolbar toggle's accessible + hover label from one string so
 *  the SR announcement (aria-label) and the hover tooltip (title)
 *  cannot drift apart. Shared by the match-mode / colorblind / theme
 *  toggles. */
function setButtonLabel(btn, text) {
    btn.title = text;
    btn.setAttribute("aria-label", text);
}

export function wireMatchModeToggle() {
    // Tooltip strings come from the relayed STATUS_TEXT so a
    // wording change lands in one Python constant
    // (constants.MATCH_MODE_TOOLTIP_*) and propagates to both the
    // desktop's setToolTip and the web's title attribute. Defaults
    // keep the toggle usable in offline / pre-relay builds.
    const labelFor = (mode) => mode === MATCH_MODE.WILDCARD
        ? (STATUS_TEXT.match_mode_tooltip_wildcard_active
            || "Underspecified matching is on: 0 or absent values can still match +/− queries. Click for strict matching.")
        : (STATUS_TEXT.match_mode_tooltip_strict_active
            || "Allow segments with 0 or absent feature values to match queries.");
    const applyLabel = (mode) =>
        setButtonLabel(nodes.matchModeBtn, labelFor(mode));
    const stored = normalizeMatchMode(safeStorageGet("match_mode"));
    if (stored === MATCH_MODE.WILDCARD) {
        document.documentElement.dataset.matchMode = "wildcard";
        nodes.matchModeBtn.setAttribute("aria-pressed", "true");
    }
    applyLabel(stored);
    nodes.matchModeBtn.addEventListener("click", () => {
        const cur = document.documentElement.dataset.matchMode === "wildcard"
            ? MATCH_MODE.WILDCARD
            : MATCH_MODE.STRICT;
        const next = cur === MATCH_MODE.WILDCARD
            ? MATCH_MODE.STRICT
            : MATCH_MODE.WILDCARD;
        if (next === MATCH_MODE.WILDCARD) {
            document.documentElement.dataset.matchMode = "wildcard";
        } else {
            delete document.documentElement.dataset.matchMode;
        }
        nodes.matchModeBtn.setAttribute(
            "aria-pressed", next === MATCH_MODE.WILDCARD ? "true" : "false"
        );
        applyLabel(next);
        safeStorageSet("match_mode", next);
        if (!state.bridge) return;
        // Bridge call order:
        //   1. set_match_mode flips the active mode and invalidates
        //      the analyze_* lru_caches.
        //   2. inventory_summary_for_mode rebuilds the feature-pane
        //      payload under the new mode so all-0 features appear
        //      (wildcard) / disappear (strict).
        //   3. runAnalysis re-renders the current selection under
        //      the new mode.
        callBridge("set_match_mode", next);
        // Capture BEFORE the feature-pane rebuild so a selection made
        // under the old mode still drives the re-analysis below.
        const hadSelection = hasActiveSelection();
        try {
            const info = callBridge("inventory_summary_for_mode", next);
            if (info) {
                // Rebuild ONLY the feature pane (the active-feature set
                // changes: all-0 features appear in wildcard / disappear
                // in strict). Do NOT call applyInventoryInfo here: that
                // is the full inventory-SWAP routine, which clears the
                // segment + feature selection, blanks the analysis, and
                // wipes the PHOIBLE Source link. The
                // desktop's _toggle_match_mode likewise keeps the
                // selection and only repopulates the feature rows.
                _adoptFeaturePaneState(info);
                // Re-apply the FEAT-mode query markers from the
                // preserved selection onto the rebuilt rows (mirrors
                // activateMode's restore loop).
                if (state.mode === MODE.FEAT_TO_SEG) {
                    _restoreFeatureQueryMarkers();
                }
            }
        } catch (e) {
            console.warn("match-mode inventory refresh failed:", e);
        }
        if (hadSelection) runAnalysis();
    });
}


/**
 * Bind the colorblind-palette toggle. The active mode lives on
 * ``html[data-cb]`` so theme.css can override the standard
 * variables under that selector; ``aria-pressed`` doubles as the
 * styling hook for the button's accented "on" state. The Python
 * renderer is told via ``set_palette_mode`` so analysis-chip HTML
 * regenerates with matching colors.
 */
export function wireColorblindToggle() {
    // aria-label and title share one source so SRs (which prefer
    // aria-label) and hover tooltips can never drift apart.
    const labelFor = (mode) => mode === PALETTE_MODE.COLORBLIND
        ? (STATUS_TEXT.palette_to_standard || "Switch to standard palette")
        : (STATUS_TEXT.palette_to_colorblind
            || "Switch to colorblind-friendly palette");
    const applyLabel = (mode) =>
        setButtonLabel(nodes.cbBtn, labelFor(mode));
    const stored = normalizePaletteMode(safeStorageGet("palette_mode"));
    if (stored === PALETTE_MODE.COLORBLIND) {
        document.documentElement.dataset.cb = "on";
        nodes.cbBtn.setAttribute("aria-pressed", "true");
        applyLabel(PALETTE_MODE.COLORBLIND);
    } else {
        applyLabel(PALETTE_MODE.STANDARD);
    }
    nodes.cbBtn.addEventListener("click", () => {
        const cur = document.documentElement.dataset.cb === "on"
            ? PALETTE_MODE.COLORBLIND
            : PALETTE_MODE.STANDARD;
        const next = cur === PALETTE_MODE.COLORBLIND
            ? PALETTE_MODE.STANDARD
            : PALETTE_MODE.COLORBLIND;
        swapPaletteInstantly(() => {
            if (next === PALETTE_MODE.COLORBLIND) {
                document.documentElement.dataset.cb = "on";
            } else {
                delete document.documentElement.dataset.cb;
            }
        });
        nodes.cbBtn.setAttribute(
            "aria-pressed", next === PALETTE_MODE.COLORBLIND ? "true" : "false"
        );
        applyLabel(next);
        safeStorageSet("palette_mode", next);
        if (state.bridge) {
            callBridge("set_active_palette_mode", next);
            // Always repaint, even with no selection: the empty-state
            // hint HTML carries the palette color baked in, so the pane
            // must re-render to pick up the new palette. runAnalysis
            // dispatches by mode and re-runs analyze_* on the (possibly
            // empty) selection. Mirrors the desktop, which refreshes
            // analysis unconditionally on a palette change.
            runAnalysis();
        }
    });
}

/** Apply a root-level palette change (dark-mode or colour-blind toggle)
 *  with colour transitions momentarily suppressed, so the new palette
 *  snaps in atomically. Without this, per-element colour transitions (the
 *  ``.feat-btn`` polarity fade, the PHOIBLE source-card fade) animate the
 *  CSS-variable change over their own 80-100 ms, visibly lagging the
 *  instant rest of the UI. The root carries ``[data-swapping]`` (mapped to
 *  ``transition: none`` in style.css) only across a forced style flush,
 *  then drops it so later hover/active fades keep working. */
function swapPaletteInstantly(mutate) {
    const root = document.documentElement;
    root.dataset.swapping = "";
    mutate();
    // Commit the recolour while transitions are still off; re-enabling
    // them afterwards cannot animate values already at their target.
    void root.offsetWidth;
    delete root.dataset.swapping;
}

export function wireThemeToggle() {
    // aria-label, title, AND glyph share one source (shared
    // mode_logic.theme_toggle_{tooltip,glyph}) so the SR
    // announcement, hover tooltip, and visual icon can never drift
    // from each other or from the desktop button.
    const labelFor = (theme) => theme === THEME.DARK
        ? (STATUS_TEXT.theme_to_light || "Switch to light mode")
        : (STATUS_TEXT.theme_to_dark || "Switch to dark mode");
    const glyphFor = (theme) => theme === THEME.DARK
        ? (STATUS_TEXT.theme_glyph_dark || "☀")
        : (STATUS_TEXT.theme_glyph_light || "☾");
    const applyLabel = (theme) =>
        setButtonLabel(nodes.themeBtn, labelFor(theme));
    const stored = normalizeTheme(safeStorageGet("theme"));
    if (stored === THEME.DARK) {
        document.documentElement.dataset.theme = THEME.DARK;
        nodes.themeBtn.textContent = glyphFor(THEME.DARK);
        applyLabel(THEME.DARK);
    } else {
        applyLabel(THEME.LIGHT);
    }
    nodes.themeBtn.addEventListener("click", () => {
        const cur = normalizeTheme(document.documentElement.dataset.theme);
        const next = cur === THEME.DARK ? THEME.LIGHT : THEME.DARK;
        swapPaletteInstantly(() => {
            document.documentElement.dataset.theme = next;
        });
        nodes.themeBtn.textContent = glyphFor(next);
        applyLabel(next);
        safeStorageSet("theme", next);
        if (state.bridge) {
            callBridge("set_active_theme", next);
            // Always repaint, even with no selection: the empty-state
            // hint HTML carries the theme color baked in, so the pane
            // must re-render to pick up the new theme. runAnalysis
            // dispatches by mode and re-runs analyze_* on the (possibly
            // empty) selection. Mirrors the desktop, which refreshes
            // analysis unconditionally on a theme change.
            runAnalysis();
        }
    });
}
