// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Required Notice: Copyright 2026 John Winstead, https://github.com/jhnwnstd/phono-feature
/**
 * Text measurement, font fitting, canvas rasterization, CSS length
 * reads, dialog open and close, and resize observers.
 *
 * Shared display primitives with no knowledge of panes. Reads a
 * Houdini-registered token at module-init time, so it imports
 * ``env.js`` for effect to pin that ordering.
 */
import "./env.js";
import { HELP_TEXT } from "./config.js";
import { nodes } from "./infra.js";
import { state } from "./state.js";


export function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;",
        '"': "&quot;", "'": "&#39;",
    })[c]);
}

// Shared 2D context for canvas-based text-width measurement. One
// per page (off-DOM, kept alive in module scope) so the seg-button
// auto-shrink path doesn't allocate a fresh canvas per glyph.
const _segMeasureCtx = document.createElement("canvas").getContext("2d");
// Font family the seg-button measure + render uses. Reads the same
// CSS variable the buttons themselves consume (Charis IPA first)
// so the canvas measure agrees with the actual rendered metrics.
const _segFontFamily = (
    getComputedStyle(document.documentElement)
        .getPropertyValue("--font-ipa")
        .trim()
    || '"Noto Sans Mono", monospace'
);
// Natural seg-button label font size, read from the relayed
// ``--font-size-control`` CSS variable so the canvas font-size
// agrees with the rendered DOM font-size by construction. The
// floor matches ``--font-size-min-px`` (the
// ``constants.FONT_SIZE_MIN_PX`` Python value baked into the CSS
// relay). Falls back to the historical literals if the variables
// are missing (defensive read pattern matching the button-width
// reads in ``applyPerGroupSegmentColumns``).
export const _rootCS = getComputedStyle(document.documentElement);

/** Read a ``--*`` CSS length off the document root. ``fallback``
 *  is returned only when the value is missing or unparseable;
 *  ``0`` (a valid CSS length) passes through. */
export function parseCSSLength(varName, fallback) {
    const v = parseFloat(_rootCS.getPropertyValue(varName));
    return Number.isFinite(v) ? v : fallback;
}

/** ``<dialog>.showModal()`` with a graceful fallback for browsers
 *  without dialog support. Captures the previously-focused
 *  element so ``closeDialog`` can restore focus to its trigger. */
export function openDialog(dialog) {
    dialog._returnFocusTo = document.activeElement;
    // Every dialog closes on a click that lands on the dialog element
    // itself (its ::backdrop, outside the content box), matching Escape
    // and the corner close button. Added once, reused across opens.
    // Dialogs opting out with ``data-persistent`` (currently just the
    // New-inventory setup dialog) require the × or Escape.
    if (!dialog._backdropHandler && !dialog.hasAttribute("data-persistent")) {
        dialog._backdropHandler = (ev) => {
            if (ev.target === dialog) closeDialog(dialog);
        };
        dialog.addEventListener("click", dialog._backdropHandler);
    }
    if (typeof dialog.showModal === "function") {
        dialog.showModal();
    } else {
        dialog.setAttribute("open", "");
        // Native <dialog> handles Escape and focus trap; the
        // fallback path needs manual Escape wiring at least.
        if (!dialog._escHandler) {
            dialog._escHandler = (ev) => {
                if (ev.key === "Escape") {
                    ev.preventDefault();
                    closeDialog(dialog);
                }
            };
            dialog.addEventListener("keydown", dialog._escHandler);
        }
    }
}

/** Symmetric counterpart for ``openDialog``. */
export function closeDialog(dialog) {
    if (typeof dialog.close === "function") {
        dialog.close();
    } else {
        dialog.removeAttribute("open");
    }
    // Restore focus to whatever triggered the dialog so keyboard
    // users do not land on document.body after close.
    const target = dialog._returnFocusTo;
    if (target && typeof target.focus === "function") {
        try { target.focus(); } catch { /* ignore */ }
    }
    dialog._returnFocusTo = null;
}

/** Attach a ResizeObserver that fires ``callback`` once per
 *  observed mutation. Stored on ``dataEl`` under ``key`` so a
 *  later ``detachResizeObserver`` call (or
 *  ``_disconnectChartObservers``) can disconnect it cleanly.
 *  Idempotent: re-attaching the same key replaces the prior obs. */
export function attachResizeObserver(dataEl, key, callback) {
    if (typeof ResizeObserver === "undefined") return;
    detachResizeObserver(dataEl, key);
    const obs = new ResizeObserver(() => {
        if (!dataEl.isConnected) return;
        requestAnimationFrame(() => {
            if (dataEl.isConnected) callback();
        });
    });
    obs.observe(dataEl);
    dataEl[key] = obs;
}

export function detachResizeObserver(dataEl, key) {
    const prev = dataEl[key];
    if (prev) {
        prev.disconnect();
        delete dataEl[key];
    }
}

const SEG_FONT_NATURAL_PX = parseCSSLength("--font-size-control", 13);
// Seg-button shrink floor. Deliberately below the global
// ``--font-size-min-px`` (10): Charis IPA renders the widest hayes
// tie-bar affricates (``k+͡x+``, ``ɡ+͡ɣ+``) too wide to fit the 33px
// button at 10px, and a two-glyph affricate icon stays legible at 9
// (the desktop already paints every seg button at a fixed 9pt). This
// is a content-driven floor for an icon-like glyph, not body text.
const SEG_FONT_FLOOR_PX = 9;
// Inner width budget for seg-button text. ``--seg-btn-min-w`` is
// 33 px; subtract the 1.5 px border on each side and leave 1 px of
// breathing room so glyphs sit just inside the outline. Picked to
// match the empirical ``clientWidth`` of an unstyled seg-btn so
// canvas measurement and DOM layout agree on the fit boundary.
const SEG_FIT_BUDGET_PX = 30;

// Pick the largest font-size that fits ``text`` inside the seg-button
// width, or null when the natural size fits. Canvas measurement, off
// the DOM, so the picked size lands with first paint. Memoized on
// text since the IPA glyph set across inventories is small.
// Map is never evicted; cleared only when ``--font-ipa`` itself
// changes (which never happens at runtime today).
const _segFontSizeCache = new Map();

/** Largest font-size (in 0.5px steps from ``naturalPx`` down to
 *  ``floorPx``) at which ``text`` fits ``budgetPx``, measured on the
 *  shared canvas in ``fontPrefix``+``family`` (``fontPrefix`` carries a
 *  weight like ``"bold "``). Returns null when the natural size already
 *  fits, or ``floorPx`` when even that overflows (``overflow: hidden``
 *  clips the residual). ``cache`` is a per-config text->size memo. Shared
 *  by the seg-buttons and the editor's square segment-header cells. */
function _pickFittedFontSize(
    text, fontPrefix, family, naturalPx, floorPx, budgetPx, cache,
) {
    const cached = cache.get(text);
    if (cached !== undefined) return cached;
    _segMeasureCtx.font = `${fontPrefix}${naturalPx}px ${family}`;
    if (_segMeasureCtx.measureText(text).width <= budgetPx) {
        cache.set(text, null);
        return null;
    }
    for (let px = naturalPx - 0.5; px >= floorPx; px -= 0.5) {
        _segMeasureCtx.font = `${fontPrefix}${px}px ${family}`;
        if (_segMeasureCtx.measureText(text).width <= budgetPx) {
            cache.set(text, px);
            return px;
        }
    }
    cache.set(text, floorPx);
    return floorPx;
}

export function _pickSegFontSize(text) {
    return _pickFittedFontSize(
        text, "", _segFontFamily,
        SEG_FONT_NATURAL_PX, SEG_FONT_FLOOR_PX, SEG_FIT_BUDGET_PX,
        _segFontSizeCache,
    );
}

// The editor's segment-header cells are fixed squares (--editor-cell-size);
// an oversized glyph shrinks to fit the cell's inner budget instead of
// widening its column, which is why the editor no longer measures
// per-column widths. Bold, in the editor's own mono family.
export const _editorCellSizePx = parseCSSLength("--editor-cell-size", 32);
const EDITOR_FIT_BUDGET_PX = _editorCellSizePx - 4;
const _editorFontFamily = (
    _rootCS.getPropertyValue("--mono-family").trim()
    || "ui-monospace, monospace"
);
const _editorHeaderFontSizeCache = new Map();

export function _pickEditorHeaderFontSize(text) {
    return _pickFittedFontSize(
        text, "bold ", _editorFontFamily,
        SEG_FONT_NATURAL_PX, SEG_FONT_FLOOR_PX, EDITOR_FIT_BUDGET_PX,
        _editorHeaderFontSizeCache,
    );
}

/** Re-run the per-glyph shrink for every live seg button once the IPA
 *  webfont has loaded. The first-paint shrink runs at button-build,
 *  before Charis IPA is available, so it measures the fallback
 *  monospace metrics, which are narrower than Charis. Without this
 *  pass the widest tie-bar affricates keep a size that fit the
 *  fallback but overflow once Charis swaps in. The cache is cleared
 *  first so the re-measure uses the now-loaded font. */
export function _refitSegButtons() {
    _segFontSizeCache.clear();
    for (const [seg, btns] of state.seg_buttons) {
        const fit = _pickSegFontSize(seg);
        for (const btn of btns) {
            btn.style.fontSize = fit !== null ? `${fit}px` : "";
        }
    }
}

// Rasterize ``text`` as a canvas alpha-mask (black on transparent)
// at devicePixelRatio, returned as {url, w, h}. The displaying
// element supplies colour via ``background-color: currentColor``.
function rasterizeText(text, font, maxWidth) {
    const measure = document.createElement("canvas").getContext("2d");
    // 3-px padding all around so antialias edges + accent marks
    // aren't clipped on either side. Drives both the canvas size
    // and the ``maxWidth`` fit check below.
    const AA_PAD = 6;
    let activeFont = font;
    // When the caller passes ``maxWidth`` (seg-buttons do; feature
    // labels don't), pick the largest font size at which the
    // glyph's natural rendered width fits within the box. Wide
    // segments like /k+͡x+/ go down a few points; ordinary /p/
    // /tʃ/ pass through untouched.
    if (maxWidth != null) {
        const sizeMatch = font.match(/(\d+(?:\.\d+)?)px\s+(.+)/);
        if (sizeMatch) {
            const origSize = parseFloat(sizeMatch[1]);
            const rest = sizeMatch[2];
            // Pulled from the Python-driven CSS variable so the
            // JS-side font-shrink floor and the Python predicate
            // ``font_below_min`` consult the same number. Falls back
            // to 8 if the CSS variable is absent (pre-bridge boot
            // window before layout.css attaches).
            const cssMin = getComputedStyle(
                document.documentElement,
            ).getPropertyValue("--font-size-min-px").trim();
            const MIN_SIZE = parseFloat(cssMin) || 8;
            for (let size = origSize; size >= MIN_SIZE; size -= 0.5) {
                measure.font = `${size}px ${rest}`;
                const probe = measure.measureText(text);
                const pLeft = probe.actualBoundingBoxLeft ?? 0;
                const pRight = probe.actualBoundingBoxRight
                    ?? probe.width;
                const natW = Math.max(probe.width, pLeft + pRight);
                activeFont = `${size}px ${rest}`;
                if (natW + AA_PAD <= maxWidth) break;
            }
        }
    }
    measure.font = activeFont;
    const m = measure.measureText(text);
    // Optical (ink-bounding-box) centering: wrap the painted bbox +
    // AA margin, draw so the ink centre sits dead-centre of the
    // canvas. Every glyph, descender ("p"), ascender ("t"), tie-bar
    // ("t͡ʃ"), or neither, reads centred inside its button. IPA-chart
    // cells are self-contained symbols so no shared baseline needed.
    const left = m.actualBoundingBoxLeft ?? 0;
    const right = m.actualBoundingBoxRight ?? m.width;
    const ascent = m.actualBoundingBoxAscent ?? 10;
    const descent = m.actualBoundingBoxDescent ?? 2;
    const inkW = left + right;
    const inkH = ascent + descent;
    // Canvas wraps the ink bbox with ``AA_HALF`` padding all around.
    // (``AA_PAD`` from the font-shrink section is the TOTAL extra
    // dimension; half on each side here.)
    const AA_HALF = AA_PAD / 2;
    const w = Math.max(1, Math.ceil(inkW) + AA_PAD);
    const h = Math.max(1, Math.ceil(inkH) + AA_PAD);
    const dpr = window.devicePixelRatio || 1;
    const canvas = document.createElement("canvas");
    canvas.width = Math.ceil(w * dpr);
    canvas.height = Math.ceil(h * dpr);
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.font = activeFont;
    ctx.fillStyle = "#000";
    ctx.textBaseline = "alphabetic";
    ctx.textAlign = "left";
    // Origin chosen so the painted area exactly fills
    // ``[AA_HALF, w - AA_HALF]`` horizontally and
    // ``[AA_HALF, h - AA_HALF]`` vertically. Painted area:
    //   horizontal: [xOrigin - left, xOrigin + right]
    //   vertical:   [yBaseline - ascent, yBaseline + descent]
    // Setting ``xOrigin = AA_HALF + left`` makes the left painted
    // edge exactly ``AA_HALF`` (= padding) from the canvas's left
    // edge; the right edge falls at ``AA_HALF + inkW`` = canvas
    // right edge minus ``AA_HALF``. Same on the vertical axis.
    ctx.fillText(text, AA_HALF + left, AA_HALF + ascent);
    return { dataUrl: canvas.toDataURL(), width: w, height: h };
}

/**
 * Create a non-copyable, theme-reactive label element for the
 * given text. Returns a ``<span class="rasterized-text">`` whose
 * mask-image encodes the glyph shape; the actual paint colour
 * comes from ``currentColor`` so the parent's theme cascade
 * handles dark/light swaps without re-rendering the canvas.
 *
 * The text never appears in the DOM, so drag-select-and-copy
 * yields nothing. Screen readers fall back to the host element's
 * ``aria-label`` (this span carries ``aria-hidden="true"``).
 */
// Memo cache for ``rasterizeText`` output, keyed on
// ``${text}|${font}|${maxWidth}``. The badge + chip glyphs that go
// through ``createRasterizedLabel`` are a tiny bounded set (``·``,
// ``+``, ``-``, mode-name letters); every analysis pass would
// otherwise allocate a fresh canvas, run measureText/fillText/
// toDataURL on the same input, and discard the result. Map never
// evicts (the bounded set is <50 entries in practice).
const _rasterCache = new Map();

export function createRasterizedLabel(text, font, maxWidth) {
    const key = text + "|" + font + "|" + (maxWidth != null ? maxWidth : "");
    let cached = _rasterCache.get(key);
    if (cached === undefined) {
        cached = rasterizeText(text, font, maxWidth);
        _rasterCache.set(key, cached);
    }
    const { dataUrl, width, height } = cached;
    const span = document.createElement("span");
    span.className = "rasterized-text";
    span.setAttribute("aria-hidden", "true");
    span.style.width = width + "px";
    span.style.height = height + "px";
    span.style.setProperty("--mask-url", `url("${dataUrl}")`);
    return span;
}

/** Populate + open the shared help window for a topic ("segments" or
 *  "vowels"). Copy comes from the baked HELP_TEXT so the window matches
 *  the desktop verbatim. */
export function showHelp(topic) {
    const entry = HELP_TEXT[topic];
    if (!entry) return;
    nodes.helpDialogTitle.textContent = entry.title || "";
    nodes.helpDialogBody.innerHTML = entry.html || "";
    openDialog(nodes.helpDialog);
}
