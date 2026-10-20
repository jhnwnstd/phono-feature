// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Required Notice: Copyright 2026 John Winstead, https://github.com/jhnwnstd/phono-feature
/**
 * Environment setup that must run before any module body reads a
 * scaled CSS token or paints a hover state.
 *
 * Two self-contained side effects, no exports. Imported for effect by
 * ``main.js`` (first import, so it evaluates ahead of the whole graph)
 * and by ``measure.js``, which reads a Houdini token at module-init
 * time and so states the dependency itself rather than relying on the
 * entry's import order.
 */

// Track the last input modality on ``document.body[data-input]`` so
// hover styles only paint when the user is actively using a mouse /
// trackpad. On hybrid devices (Chromebook, Surface, iPad + trackpad)
// ``@media (hover: hover)`` alone is not enough: it matches whenever
// a hover-capable pointer exists, so a touchscreen tap still fires
// :hover in CSS and the highlight visually sticks until the user
// nudges the mouse. This attribute lets style.css gate hover
// selectors on ``body[data-input="mouse"]``, so a tap flips the
// mode to ``"touch"`` and clears the paint immediately.
(function trackInputModality() {
    if (typeof document === "undefined" || !document.body) {
        // Body isn't parsed yet at this script's evaluation time on
        // some browsers; defer to DOMContentLoaded to attach.
        document.addEventListener("DOMContentLoaded", trackInputModality, {
            once: true,
        });
        return;
    }
    const set = (mode) => {
        if (document.body.dataset.input !== mode) {
            document.body.dataset.input = mode;
        }
    };
    set("mouse");
    const onDown = (ev) => set(ev.pointerType === "mouse" ? "mouse" : "touch");
    const onMove = (ev) => {
        if (ev.pointerType === "mouse") set("mouse");
    };
    document.addEventListener("pointerdown", onDown, { passive: true });
    document.addEventListener("pointermove", onMove, { passive: true });
})();

// Register scaled content tokens (emitted as ``calc(N * var(--unit))``
// by build.py) as ``<length>`` via Houdini so ``getPropertyValue``
// returns resolved px instead of the calc expression, letting
// ``parseCSSLength`` / ``parseFloat`` succeed. Only tokens JS actually
// reads. Try/catch = graceful fallback on browsers without the API.
(function registerScaledLengthTokens() {
    if (typeof CSS === "undefined" || !CSS.registerProperty) return;
    const tokens = [
        ["--seg-btn-w", "33px"],
        ["--seg-btn-gap", "4px"],
        ["--seg-btn-h", "26px"],
        ["--vowel-cell-dense-h", "22px"],
        ["--vowel-cell-ultra-h", "18px"],
        ["--vowel-cell-dense-w", "27px"],
        ["--vowel-cell-ultra-w", "22px"],
        ["--vowel-cell-stack-gap", "1px"],
        ["--font-size-base", "14px"],
        ["--font-size-control", "13px"],
        ["--editor-cell-size", "32px"],
        ["--vowel-chart-row-label-gutter", "72px"],
        ["--vowel-chart-pad-r", "12px"],
    ];
    for (const [name, initialValue] of tokens) {
        try {
            CSS.registerProperty({
                name, syntax: "<length>", inherits: true, initialValue,
            });
        } catch (_) { /* already registered or invalid; skip */ }
    }
})();
