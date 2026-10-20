// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Required Notice: Copyright 2026 John Winstead, https://github.com/jhnwnstd/phono-feature
/**
 * The segment button factory.
 *
 * Its own module because both panes build segment buttons: the
 * consonant grid in ``segments.js`` and the vowel cells in
 * ``vowel_chart.js``. Keeping it a leaf below both is what stops those
 * two from importing each other.
 */
import { STATUS_TEXT } from "./config.js";
import { _pickSegFontSize } from "./measure.js";
import { state } from "./state.js";


// Build a single segment button. Native DOM text (crisper than a
// canvas rasterizer) via the ``--font-ipa`` family chain. Clicks are
// caught by a delegated listener on #seg-grid (wireSegmentDelegation).
export function _buildSegmentButton(seg, extraAttrs) {
    const btn = document.createElement("button");
    btn.className = "seg-btn";
    btn.type = "button";
    btn.dataset.seg = seg;
    btn.dataset.state = "default";
    btn.setAttribute("aria-pressed", "false");
    btn.setAttribute(
        "aria-label",
        (STATUS_TEXT.seg_accessible_label_template || "/{seg}/").replace(
            "{seg}",
            seg,
        ),
    );
    btn.textContent = seg;
    // Wide glyphs (tie-bar affricates, PHOIBLE diphthong contours,
    // combining-mark stacks) get an inline font-size to fit.
    const fit = _pickSegFontSize(seg);
    if (fit !== null) {
        btn.style.fontSize = fit + "px";
    }
    if (extraAttrs) {
        for (const [k, v] of Object.entries(extraAttrs)) {
            if (k.startsWith("data-")) btn.setAttribute(k, v);
        }
    }
    // Track ALL instances of each seg (a consonant can appear in
    // several manner classes) so state updates fan out to all.
    const instances = state.seg_buttons.get(seg);
    if (instances) {
        instances.push(btn);
    } else {
        state.seg_buttons.set(seg, [btn]);
    }
    return btn;
}
