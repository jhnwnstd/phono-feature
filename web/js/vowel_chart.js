// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Required Notice: Copyright 2026 John Winstead, https://github.com/jhnwnstd/phono-feature
/**
 * Vowel chart rendering: silhouette polygons, guide paths, cell
 * placement, stacks, pairs and contrast-set capsules.
 *
 * The silhouette and projection maths mirror
 * ``phonology_shared.chart.vowel_space_geometry``; the parity tests
 * extract spans from this file and drive them against the Python
 * source, so the mirrored expressions must stay literal.
 */
import { CHART_STYLE, STATUS_TEXT } from "./config.js";
import { attachResizeObserver, showHelp } from "./measure.js";
import { _buildSegmentButton } from "./seg_button.js";



/**
 * Build the IPA vowel trapezoid: 6 height rows × 6 backness-
 * rounding columns. Row/column placement comes from Python
 * (chart.vowels.vowel_grid_pos) so it matches the desktop's
 * VowelChartWidget cell-for-cell.
 */
/** Cascade: return a silhouette dict with its corner fields
 *  recomputed for the given rendered data width in pixels. Mirrors
 *  ``silhouette_for_data_width`` in
 *  ``shared/.../chart/vowel_space_geometry/silhouette.py``.
 *
 *  The cell-extent fields (``front_anchor_at_top``,
 *  ``front_anchor_at_bottom``, ``back_anchor``,
 *  ``cell_outer_extent_px``) are the source of truth. The corners
 *  are derived: ``anchor * dw + sign * extent_px`` translated
 *  back to a [0, 1] fraction. At any data width the silhouette
 *  wraps the outer cell edge flush by construction. */
function _silhouetteForDataWidth(sil, dwPx) {
    if (!sil || dwPx <= 0) return sil;
    const extentPx = sil.cell_outer_extent_px || 0;
    if (extentPx === 0) return sil;
    const extentNorm = extentPx / dwPx;
    // Per-side extents: the outline-growth pass reserves the front
    // and back edges independently (a wide back-edge group must
    // not float the front edge away from single-button front
    // cells). 0 / absent means "mirror the back extent", which is
    // the historical symmetric payload.
    const frontExtentNorm = (sil.front_cell_outer_extent_px || 0) > 0
        ? sil.front_cell_outer_extent_px / dwPx
        : extentNorm;
    const corners = _cornersFromAnchors({
        front_anchor_at_top: sil.front_anchor_at_top ?? sil.top_left,
        front_anchor_at_bottom: sil.front_anchor_at_bottom ?? sil.bottom_left,
        back_anchor: sil.back_anchor ?? sil.top_right,
        back_anchor_at_bottom: sil.back_anchor_at_bottom,
        bottom_width: sil.bottom_width ?? 1,
        extent_norm: extentNorm,
        front_extent_norm: frontExtentNorm,
    });
    return { ...sil, ...corners };
}

// Mirror of ``silhouette._BACK_APEX_PULL``: fraction of the distance
// from the back anchor toward the apex the OUTLINE's back column
// travels at bottom_y. THE BACK EDGE STAYS VERTICAL. the dorsal
// boundary is a strong articulatory/phonological anchor, held at
// ``back_anchor`` across every row. Only the FRONT boundary tapers
// as height lowers. Python is the source of truth; keep this at 0.0
// unless changing it in silhouette.py at the same time.
const _BACK_APEX_PULL = 0.0;

// Mirror of ``silhouette._apex_back_column_at_bottom``.
// Under _BACK_APEX_PULL = 0.0 this reduces to back for every input.
function _apexBackColumnAtBottom(back, canonicalApex, bottomWidth) {
    const backPullPivot = back - _BACK_APEX_PULL * (back - canonicalApex);
    return backPullPivot + bottomWidth * (back - backPullPivot);
}

// Mirror of ``silhouette._corners_from_anchors``. Applies per-side
// pixel-extent offsets to pre-computed anchor positions. Back-column
// position at bottom_y is derived from ``back_anchor_at_bottom`` (the
// canonical apex; null for classic trapezoid) via the shared pull
// policy above, so the outline right edge and the back-column guide
// land at the same base position (differing only by extent_norm).
// Returns { top_left, top_right, bottom_left, bottom_right }.
function _cornersFromAnchors({
    front_anchor_at_top, front_anchor_at_bottom,
    back_anchor, back_anchor_at_bottom,
    bottom_width,
    extent_norm, front_extent_norm,
}) {
    const backEdgeAtBot = back_anchor_at_bottom == null
        ? back_anchor
        : _apexBackColumnAtBottom(back_anchor, back_anchor_at_bottom, bottom_width);
    return {
        top_left: front_anchor_at_top - front_extent_norm,
        top_right: back_anchor + extent_norm,
        bottom_left: front_anchor_at_bottom - front_extent_norm,
        bottom_right: backEdgeAtBot + extent_norm,
    };
}

/** Port of ``inset_silhouette_for_draw`` in silhouette.py: push the DRAWN
 *  outline OUTWARD by ``insetPx`` on every side so the chips float
 *  inside a quiet field. Draw-only; never feeds cell positions. */
function _insetSilhouetteForDraw(sil, dwPx, dhPx, insetPx) {
    if (!sil || dwPx <= 0 || dhPx <= 0 || insetPx <= 0) return sil;
    const dx = insetPx / dwPx;
    const dy = insetPx / dhPx;
    return {
        ...sil,
        top_left: sil.top_left - dx,
        bottom_left: sil.bottom_left - dx,
        top_right: sil.top_right + dx,
        bottom_right: sil.bottom_right + dx,
        top_y: sil.top_y - dy,
        bottom_y: sil.bottom_y + dy,
    };
}

/** Cascade: port of ``rounded_silhouette_polygon_points`` in
 *  ``shared/.../chart/vowel_space_geometry/silhouette.py``. Returns a CSS
 *  ``clip-path: polygon()`` points string with the four corners
 *  smoothed via quadratic Bezier. Must stay byte-identical to the
 *  Python helper; the test suite at
 *  ``shared/tests/test_rounded_silhouette.py`` pins the polygon
 *  output and any drift here would silently un-track the
 *  rendered silhouette. */
function _roundedSilhouettePolygonPoints(sil, radiusFrac, segmentsPerCorner) {
    const seg = segmentsPerCorner ?? 5;
    const corners = [
        [sil.top_left, sil.top_y],
        [sil.bottom_left, sil.bottom_y],
        [sil.bottom_right, sil.bottom_y],
        [sil.top_right, sil.top_y],
    ];
    const n = corners.length;
    const points = [];
    for (let i = 0; i < n; i++) {
        const prev = corners[(i - 1 + n) % n];
        const curr = corners[i];
        const nxt = corners[(i + 1) % n];
        let dxIn = prev[0] - curr[0];
        let dyIn = prev[1] - curr[1];
        const lenIn = Math.hypot(dxIn, dyIn) || 1.0;
        dxIn /= lenIn; dyIn /= lenIn;
        let dxOut = nxt[0] - curr[0];
        let dyOut = nxt[1] - curr[1];
        const lenOut = Math.hypot(dxOut, dyOut) || 1.0;
        dxOut /= lenOut; dyOut /= lenOut;
        const rIn = Math.min(radiusFrac, lenIn * 0.45);
        const rOut = Math.min(radiusFrac, lenOut * 0.45);
        const pInX = curr[0] + rIn * dxIn;
        const pInY = curr[1] + rIn * dyIn;
        const pOutX = curr[0] + rOut * dxOut;
        const pOutY = curr[1] + rOut * dyOut;
        for (let s = 0; s <= seg; s++) {
            const t = s / seg;
            const omt = 1.0 - t;
            const bx = omt * omt * pInX
                + 2.0 * omt * t * curr[0]
                + t * t * pOutX;
            const by = omt * omt * pInY
                + 2.0 * omt * t * curr[1]
                + t * t * pOutY;
            points.push(`${(bx * 100).toFixed(3)}% ${(by * 100).toFixed(3)}%`);
        }
    }
    return points.join(", ");
}

// Update the flush + outset silhouette polygons on ``dataEl`` and the
// outline ``<polygon>``. FLUSH wraps the cell extent (drives the
// clip-path fill and the guide-container trim); OUTSET pushes the
// drawn trapezoid outward by ``insetPx`` so chips float inside a
// quiet field. Cell positions are untouched.
function _updateSilhouettePolygons({
    dataEl, outlinePoly, shape, radiusFrac,
    silAdj, silDraw, dw, dh, insetPx,
}) {
    dataEl.style.setProperty(
        `--vowel-${shape}-rounded-points`,
        _roundedSilhouettePolygonPoints(silAdj, radiusFrac),
    );
    let outlineStr = _roundedSilhouettePolygonPoints(silDraw, radiusFrac);
    if (insetPx > 0) {
        // Remap the outset polygon from the flush box (dw x dh) into
        // the outset box (dw + 2*inset x dh + 2*inset) so the outline
        // pseudo-element's grown area lines up with the drawn stroke.
        const denomX = dw + 2 * insetPx;
        const denomY = dh + 2 * insetPx;
        outlineStr = outlineStr.split(",").map((pt) => {
            const xy = pt.trim().split(/\s+/);
            const px = (parseFloat(xy[0]) / 100 * dw + insetPx)
                / denomX * 100;
            const py = (parseFloat(xy[1]) / 100 * dh + insetPx)
                / denomY * 100;
            return `${px.toFixed(3)}% ${py.toFixed(3)}%`;
        }).join(", ");
    }
    dataEl.style.setProperty(
        `--vowel-${shape}-outline-points`, outlineStr,
    );
    outlinePoly.setAttribute("points", outlineStr.replace(/%/g, ""));
}

// Build the ``d`` attribute for the interior guide path.
// Horizontals run at each row's ``chart_y`` between the frontmost and
// backmost column verticals (an INNER TRAPEZOID, so no line juts past
// the outermost cell column). Verticals run between the topmost and
// bottommost row centres, threading the actual rendered pair midpoint
// via ``colX`` (which includes the per-column confinement nudge).
function _buildGuidePath({
    guideCols, guideRows, guideColumnSamples, silAdj, dw,
}) {
    const gTy = silAdj.top_y;
    const gBy = silAdj.bottom_y;
    const gSpan = gBy - gTy || 1;
    const colX = (colIdx, y) => {
        const col = guideCols[colIdx];
        if (!col) return 0;
        const samples = guideColumnSamples[colIdx];
        const nudgeNorm = samples && samples.length
            ? (samples[0].anchor.nudge_px || 0) / dw
            : 0;
        if (typeof col.guide_x_at_y0 !== "number") {
            return col.chart_x + nudgeNorm;
        }
        return col.guide_x_at_y0
            + y * (col.guide_x_at_y1 - col.guide_x_at_y0)
            + nudgeNorm;
    };
    let frontIdx = -1;
    let backIdx = -1;
    guideCols.forEach((col, i) => {
        if (frontIdx < 0 || col.chart_x < guideCols[frontIdx].chart_x) frontIdx = i;
        if (backIdx < 0 || col.chart_x > guideCols[backIdx].chart_x) backIdx = i;
    });
    const d = [];
    for (const row of guideRows) {
        const y = row.chart_y;
        const xL = frontIdx >= 0
            ? colX(frontIdx, y) * 100
            : (silAdj.top_left
                + (silAdj.bottom_left - silAdj.top_left)
                  * (y - gTy) / gSpan) * 100;
        const xR = backIdx >= 0
            ? colX(backIdx, y) * 100
            : (silAdj.top_right
                + (silAdj.bottom_right - silAdj.top_right)
                  * (y - gTy) / gSpan) * 100;
        const ys = (y * 100).toFixed(3);
        d.push(`M${xL.toFixed(3)} ${ys} L${xR.toFixed(3)} ${ys}`);
    }
    const firstRow = guideRows[0];
    const lastRow = guideRows[guideRows.length - 1];
    const yTopGuide = firstRow ? firstRow.chart_y : gTy;
    const yBotGuide = lastRow ? lastRow.chart_y : gBy;
    for (let i = 0; i < guideCols.length; i++) {
        const xTop = colX(i, yTopGuide);
        const xBot = colX(i, yBotGuide);
        d.push(
            `M${(xTop * 100).toFixed(3)} ${(yTopGuide * 100).toFixed(3)} `
            + `L${(xBot * 100).toFixed(3)} ${(yBotGuide * 100).toFixed(3)}`
        );
    }
    return d.join(" ");
}

export function _buildVowelChart(chart) {
    const groupEl = document.createElement("div");
    groupEl.className = "seg-group vowel-chart-group";

    // Outer rectangular UI space. Three rows (title, column
    // headers, body) and two columns (row labels, data area). Only
    // the data area gets the trapezoid silhouette and
    // absolutely-positioned cells; labels and the title stay in
    // the rectangular chrome.
    const chartEl = document.createElement("div");
    chartEl.className = "vowel-chart";
    chartEl.setAttribute("role", "grid");
    chartEl.setAttribute(
        "aria-label",
        STATUS_TEXT.vowel_chart_accessible_name || "IPA vowel chart",
    );

    // Title sits in row 1, column 2 only; centered over the data
    // area, NOT over the row-label gutter. Mirrors the desktop's
    // manual ``move(dx + (dw - tw) // 2, 0)`` placement; the
    // shared ``VowelChartGeometry`` documents this as the contract
    // both UIs must honour.
    const titleEl = document.createElement("div");
    titleEl.className = "vowel-chart-title";
    // ``chart.title`` comes from the shared
    // chart.vowel_space_geometry.model.VOWEL_CHART_TITLE so the desktop
    // and web charts always agree on the heading.
    titleEl.textContent = chart.title;
    titleEl.title = "How vowels are placed";
    titleEl.addEventListener("click", () => showHelp("vowels"));
    chartEl.appendChild(titleEl);

    const corner = document.createElement("div");
    corner.className = "vowel-chart-corner";
    chartEl.appendChild(corner);

    // Column headers (Front/Central/Back). Positioned absolutely
    // at x=0%, 50%, 100% so they align with the data cells at the
    // TOP row (the widest row of the trapezoid). For lower rows
    // the cells migrate inward; the headers do not move.
    const headersEl = document.createElement("div");
    headersEl.className = "vowel-chart-cols";
    chart.cols.forEach((col) => {
        const colHeader = document.createElement("div");
        colHeader.className = "vowel-chart-col-label";
        colHeader.textContent = col.label;
        // col.chart_x = backness anchor in the data area's [0,1] space.
        colHeader.style.left = (col.chart_x * 100) + "%";
        headersEl.appendChild(colHeader);
    });
    chartEl.appendChild(headersEl);

    // Row labels sit outside the silhouette's slanted left edge and
    // follow the trapezoid inward as it shrinks; the empty gutter
    // in grid col 1 reserves space for the overflowing label text.
    const labelsEl = document.createElement("div");
    labelsEl.className = "vowel-chart-row-labels";
    chartEl.appendChild(labelsEl);

    // Trapezoid data area. Cells drop at chart_x/chart_y already
    // projected through the shape; the bridge's ``silhouette`` payload
    // overrides the baked canonical corners with inventory-adapted
    // ones (e.g. no-open-vowels inventories get a wider bottom edge).
    const dataEl = document.createElement("div");
    dataEl.className = "vowel-chart-data";
    if (chart.shape) {
        dataEl.setAttribute("data-shape", chart.shape);
    }
    // Publish the geometry's natural height as a CSS custom prop;
    // the CSS rule combines it with the floor via max().
    if (typeof chart.natural_data_height_px === "number"
        && chart.natural_data_height_px > 0) {
        dataEl.style.setProperty(
            "--vowel-natural-data-h",
            chart.natural_data_height_px + "px",
        );
    }
    // Outline SVG. One <polygon> with a stroke drawn along the exact
    // shape gives a uniform-thickness edge on every side of the
    // trapezoid (the prior CSS pseudo-element pair used a 1 px inset
    // clip-path, which produces a stroke wider on slanted edges than
    // horizontal ones). Sized to the OUTSET frame (dataEl expanded by
    // ``--vowel-silhouette-inset`` on every side) so the outline sits
    // outside the cell extent.
    const outlineSvgNS = "http://www.w3.org/2000/svg";
    const outlineSvg = document.createElementNS(outlineSvgNS, "svg");
    outlineSvg.setAttribute("class", "vowel-chart-outline");
    outlineSvg.setAttribute("viewBox", "0 0 100 100");
    outlineSvg.setAttribute("preserveAspectRatio", "none");
    outlineSvg.setAttribute("aria-hidden", "true");
    const outlinePoly = document.createElementNS(outlineSvgNS, "polygon");
    outlinePoly.setAttribute("vector-effect", "non-scaling-stroke");
    outlineSvg.appendChild(outlinePoly);
    dataEl.appendChild(outlineSvg);

    const sil = chart.silhouette;
    if (sil) {
        const shape = sil.shape || chart.shape || "trapezoid";
        const radiusFrac = CHART_STYLE.silhouette_corner_radius_frac;
        let lastPolyW = -1;
        let lastPolyH = -1;
        const refreshPolygon = () => {
            // ``dataEl`` may be detached (inventory swap between rAF
            // and firing) or unmeasured yet (clientWidth 0 before
            // first layout).
            if (!dataEl.isConnected) return;
            const dw = dataEl.clientWidth || 0;
            const dh = dataEl.clientHeight || 0;
            if (dw <= 0 || dh <= 0) return;
            // Skip on size-unchanged so observer double-fire + sub-
            // pixel jitter don't rebuild identical polygons every
            // frame. Real drags always advance so this stays per-
            // frame (not debounced) for lag-free tracking.
            if (dw === lastPolyW && dh === lastPolyH) return;
            lastPolyW = dw;
            lastPolyH = dh;
            const silAdj = _silhouetteForDataWidth(sil, dw);
            const insetPx = parseFloat(
                getComputedStyle(dataEl).getPropertyValue(
                    "--vowel-silhouette-inset",
                ),
            ) || 0;
            const silDraw = _insetSilhouetteForDraw(silAdj, dw, dh, insetPx);
            _updateSilhouettePolygons({
                dataEl, outlinePoly, shape, radiusFrac,
                silAdj, silDraw, dw, dh, insetPx,
            });
            guidePath.setAttribute("d", _buildGuidePath({
                guideCols, guideRows, guideColumnSamples, silAdj, dw,
            }));
            // Anchor the diphthong footer to the trapezoid's bottom-
            // left corner instead of the data area's left edge.
            chartEl.style.setProperty(
                "--vowel-diph-indent",
                Math.max(0, silDraw.bottom_left * dw) + "px",
            );
            _refreshVowelStackClamp(dataEl);
        };
        requestAnimationFrame(refreshPolygon);
        attachResizeObserver(
            dataEl, "_silhouetteResizeObserver", refreshPolygon,
        );
    }
    // Per-row labels go INSIDE the data area so the slanted left
    // edge is the natural alignment reference (``right: 100%`` is
    // the data area's right edge; ``right: calc(100% - L%)`` puts
    // the label's right edge at fraction ``L`` from the left, i.e.
    // on the silhouette's left edge at this row). Labels overflow
    // leftward out of the data area into the empty labels gutter
    // (``.vowel-chart-row-labels`` in grid column 1), so the
    // reserved track keeps them legible.
    const silTopY = sil ? sil.top_y : 0;
    const silBotY = sil ? sil.bottom_y : 1;
    const silTopLeft = sil ? sil.top_left : 0;
    const silBotLeft = sil ? sil.bottom_left : 0;
    const silSpanY = silBotY - silTopY;
    for (const row of chart.rows) {
        const rowLabel = document.createElement("div");
        rowLabel.className = "vowel-chart-row-label";
        rowLabel.textContent = row.label;
        // ``row.silhouette_left`` is baked shared-side by
        // ``silhouette_left_at_y`` so the value accounts for the
        // rounded-corner insets at the top and bottom of the
        // silhouette polygon. The label anchors to this value
        // and lands flush against the rendered silhouette edge
        // regardless of corner rounding. Fall back to the legacy
        // linear interp only if the relay payload is missing the
        // field (older bridge / offline build).
        let leftNorm;
        if (typeof row.silhouette_left === "number") {
            leftNorm = row.silhouette_left;
        } else if (silSpanY > 0) {
            const t = Math.min(
                1, Math.max(0, (row.chart_y - silTopY) / silSpanY)
            );
            leftNorm = silTopLeft + (silBotLeft - silTopLeft) * t;
        } else {
            leftNorm = 0;
        }
        // ``row.label_y`` is the shared geometry's label anchor:
        // chart_y shifted by half a button on top / bottom tiers so
        // the label centres on the anchor button row, with
        // ``row.silhouette_left`` evaluated at that SAME y so the
        // label-to-outline gap stays constant. Label placement is
        // deliberately divorced from cell positioning; falling back
        // to chart_y covers an older bridge payload.
        const labelY = typeof row.label_y === "number"
            ? row.label_y
            : row.chart_y;
        rowLabel.style.setProperty("--row-y", String(labelY));
        rowLabel.style.setProperty("--row-left", leftNorm.toFixed(5));
        dataEl.appendChild(rowLabel);
    }
    // Interior guides: ONE SVG <path> with horizontal row subpaths
    // through each row's cell centres and vertical column subpaths at
    // each column's chart_x (the rounded/unrounded pair divider).
    // Every row's chart_y IS the cell centre (the shared pipeline
    // pre-pulls extreme rows inward), so the horizontals sit directly
    // on chart_y. The path is still rebuilt in refreshPolygon because
    // the per-column confinement nudge is px-based and needs the live
    // data-area width. Endpoints sit on the flush silhouette so no
    // line juts past the trapezoid.
    const guidesEl = document.createElement("div");
    guidesEl.className = "vowel-chart-guides";
    const svgNS = "http://www.w3.org/2000/svg";
    const guideSvg = document.createElementNS(svgNS, "svg");
    guideSvg.setAttribute("class", "vowel-guide-svg");
    guideSvg.setAttribute("viewBox", "0 0 100 100");
    guideSvg.setAttribute("preserveAspectRatio", "none");
    guideSvg.setAttribute("aria-hidden", "true");
    guideSvg.setAttribute("width", "100%");
    guideSvg.setAttribute("height", "100%");
    const guidePath = document.createElementNS(svgNS, "path");
    guidePath.setAttribute("vector-effect", "non-scaling-stroke");
    guideSvg.appendChild(guidePath);
    guidesEl.appendChild(guideSvg);
    const guideRows = chart.rows || [];
    const guideCols = chart.cols || [];
    // Per (guide-col, row) sampled pair midpoint anchor: cells' chart_x
    // already rides the trapezoid slant, and confinement pushes
    // near-slant cells inward by ``cell.nudge_px``, so
    // ``chart_x + nudge_px / dw`` is where the actual pair midpoint
    // sits. Guides sample this per row so the vertical threads the
    // real cell midpoint at every row, not just a theoretical column
    // projection (front-column diagonal was ~5 px off before).
    //
    // ``chart.cells[].col`` is the shared classifier's 9-slot index
    // (0/1 unrounded/rounded front pair, 2/3 central, 4/5 back, 6/7/8
    // the neutral-round row for each backness). ``chart.cols[]`` names
    // the three BACKNESS columns. The single source of truth for the
    // slot -> backness mapping is ``vowel_space._BACKNESS_GROUP_BY_COL``
    // in the shared package; the JS mirror keeps it inline so we don't
    // have to bake the map on the wire.
    const guideColFromCellCol = (col) => (col < 6 ? col >> 1 : col - 6);
    const rowByLogical = new Map(
        (chart.rows || []).map((r) => [r.logical_row, r.chart_y]),
    );
    const guideAnchorsByCol = guideCols.map(() => new Map());
    for (const cell of chart.cells || []) {
        if (!Array.isArray(cell.segs) || cell.segs.length === 0) continue;
        const guideCol = guideColFromCellCol(cell.col);
        if (guideCol < 0 || guideCol >= guideAnchorsByCol.length) continue;
        // Multiple cells at the same (guide_col, row) share the same
        // chart_x + nudge (pair mates + neutral-round mates round-trip
        // to the same anchor), so we keep the first sample only.
        if (!guideAnchorsByCol[guideCol].has(cell.row)) {
            guideAnchorsByCol[guideCol].set(cell.row, {
                chart_x: cell.chart_x,
                nudge_px: cell.nudge_px || 0,
            });
        }
    }
    // Row-sorted samples per column, used by ``colX`` below to build
    // the guide vertical as a polyline threading every sampled midpoint.
    const guideColumnSamples = guideAnchorsByCol.map((map) =>
        Array.from(map.entries())
            .map(([logical, anchor]) => ({
                row_y: rowByLogical.get(logical) ?? 0,
                anchor,
            }))
            .sort((a, b) => a.row_y - b.row_y),
    );
    dataEl.appendChild(guidesEl);
    const slotNormByLogical = new Map(
        (chart.rows || []).map(
            (r) => [r.logical_row, r.slot_height_norm || 0],
        ),
    );
    // Only monophthongs land in cells (the shared placer skips
    // diphthongs; they are listed as chips below the chart).
    for (const cell of chart.cells) {
        // Multiple vowels can map to the same chart cell (the
        // classic case is ə / ɜ / ɚ all landing in open-mid central
        // for the General inventory). The bridge groups them into
        // ``cell.segs`` in the shared classifier's order: base form
        // first for a contrast-bearing cell, descending placement
        // confidence for a featureless stack.
        const segs = cell.segs;
        if (!Array.isArray(segs) || segs.length === 0) continue;
        let target;
        if (segs.length === 1) {
            target = _buildVowelCellButton(segs[0]);
        } else {
            // ``display_kind`` is the shared classifier's choice for
            // how to arrange multiple entries inside one chart slot.
            // PAIR kinds (long / nasal / rhotic / phonation / tone)
            // render horizontally; CONTRAST_SET renders as a 2x2
            // grid; STACK falls back to a vertical column.
            const kind = cell.display_kind || "stack";
            switch (kind) {
                case "stack":
                    target = _buildVowelCellStack(
                        segs, slotNormByLogical.get(cell.row),
                    );
                    break;
                case "long_pair":
                case "nasal_pair":
                case "rhotic_pair":
                case "phonation_pair":
                case "tone_pair":
                case "pharyngeal_pair":
                    target = _buildVowelCellPair(segs, kind);
                    break;
                case "contrast_set":
                    target = _buildVowelCellContrastSet(
                        segs, cell.grid, cell.spans,
                    );
                    break;
                default:
                    // Unknown kind from the bridge: log + fall back so
                    // the chart still renders, but a future Python-side
                    // VowelCellDisplayKind variant addition surfaces in
                    // the console instead of silently displaying as STACK.
                    console.warn(
                        `vowel cell display_kind "${kind}" not handled `
                        + `by the web renderer; falling back to STACK. `
                        + `Update the switch in _buildVowelChart.`,
                    );
                    target = _buildVowelCellStack(
                        segs, slotNormByLogical.get(cell.row),
                    );
            }
        }
        // Position concern: backness anchor projected through the
        // chart silhouette. Display concern: fixed-pixel shift so
        // rounded/unrounded mates stay exactly tangent regardless
        // of how narrow the row becomes. ``--pair-side`` is the
        // signed multiplier; the per-mate shift is half a button
        // width plus half the within-pair gap, expressed as a CSS
        // calc against ``--seg-btn-w`` / ``--vowel-pair-gap`` so a
        // future bump to either constant flows through.
        target.style.left = (cell.chart_x * 100) + "%";
        target.style.top = (cell.chart_y * 100) + "%";
        target.style.setProperty("--pair-side", String(cell.pair_side));
        // Hard-boundary confinement offset (px); 0 for cells the
        // outline already contains. Applied inside the transform
        // calc alongside the pair shift.
        if (cell.nudge_px) {
            target.style.setProperty("--cell-nudge", `${cell.nudge_px}px`);
        }
        // Per-cell pair shift. The geometry always populates the
        // effective value (canonical for unconflicted cells,
        // elevated when a wide-cell same-anchor collision was
        // resolved), so the renderer applies it unconditionally;
        // no "0 means canonical" sentinel to re-implement here.
        target.style.setProperty(
            "--vowel-pair-shift", `${cell.pair_shift_px}px`,
        );
        // Every cell centre-anchors via the default
        // ``translate(-50%, -50%)`` on ``.vowel-chart-cell``:
        // ``chart_y`` is the visual cell centre for every row (the
        // shared ``_finalize_row_plan`` pulls the extreme rows'
        // centres inward so their edges hug the silhouette). No
        // per-row tier override.
        dataEl.appendChild(target);
    }
    chartEl.appendChild(dataEl);
    _appendVowelDiphthongChipStrip(chartEl, chart);

    groupEl.appendChild(chartEl);
    return groupEl;
}

/** Below the vowel space: a "Diphthongs" label followed by one
 *  chip per diphthong segment. Each chip is a normal seg-btn, so
 *  clicking it dispatches the same selection flow as any other
 *  segment (the delegated ``#seg-grid`` handler keys off data-seg).
 *  Renders nothing when the inventory has no diphthongs. */
function _appendVowelDiphthongChipStrip(chartEl, chart) {
    const diphthongs = chart.diphthongs;
    if (!Array.isArray(diphthongs) || diphthongs.length === 0) return;
    const label = document.createElement("div");
    label.className = "vowel-diphthong-label";
    label.textContent = "Diphthongs";
    chartEl.appendChild(label);
    const strip = document.createElement("div");
    strip.className = "vowel-diphthong-chips";
    strip.setAttribute("aria-label", "Diphthongs in this inventory");
    // Defensive dedup even though the geometry ordering is stable.
    const seen = new Set();
    for (const seg of diphthongs) {
        if (!seg || seen.has(seg)) continue;
        seen.add(seg);
        strip.appendChild(_buildSegmentButton(seg));
    }
    chartEl.appendChild(strip);
}

/** Build a single vowel-cell button from an IPA segment string. */
function _buildVowelCellButton(seg) {
    const btn = _buildSegmentButton(seg);
    btn.classList.add("vowel-chart-cell");
    return btn;
}

// Stacked vertical container for a vowel-chart cell holding multiple
// vowels. Segs arrive in the shared classifier's stack order (leading
// entry on top). Children are plain buttons, NOT ``.vowel-chart-cell``;
// that class carries ``position: absolute`` for the (x, y) anchor, so
// applying it to children would pile them at the same point.
function _buildVowelCellStack(segs, slotNorm) {
    const cell = document.createElement("div");
    cell.className = "vowel-chart-cell vowel-chart-cell-stack";
    // Metadata for the resize-time slot-clamp pass.
    if (typeof slotNorm === "number" && slotNorm > 0) {
        cell.dataset.slotNorm = String(slotNorm);
        cell.dataset.stackDepth = String(segs.length);
    }
    const denseThreshold = CHART_STYLE.vowel_cell_dense_threshold;
    const ultraThreshold = CHART_STYLE.vowel_cell_ultra_threshold;
    if (segs.length >= ultraThreshold) {
        cell.dataset.cellDensity = "ultra";
    } else if (segs.length >= denseThreshold) {
        cell.dataset.cellDensity = "dense";
    }
    // Tooltip explains the intentional packing (shrunk buttons
    // otherwise read as broken).
    if (segs.length >= denseThreshold) {
        cell.title = `${segs.length} segments share this cell: ${segs.join(" ")}`;
    }
    for (const seg of segs) {
        cell.appendChild(_buildSegmentButton(seg));
    }
    return cell;
}

// Clamp vowel-stack per-button height to fit the row's slot budget
// when the chart renders shorter than the natural request. Floors at
// vowel_btn_min_h_px; below that the panel scrolls internally.
function _refreshVowelStackClamp(dataEl) {
    const dh = dataEl.clientHeight || 0;
    if (dh <= 0) return;
    const minH = CHART_STYLE.vowel_btn_min_h_px;
    const denseThreshold = CHART_STYLE.vowel_cell_dense_threshold;
    const ultraThreshold = CHART_STYLE.vowel_cell_ultra_threshold;
    const styles = getComputedStyle(dataEl);
    const readPx = (name, fallback) => {
        const v = parseFloat(styles.getPropertyValue(name));
        return Number.isFinite(v) ? v : fallback;
    };
    const segBtnH = readPx("--seg-btn-h", 26);
    const denseH = readPx("--vowel-cell-dense-h", segBtnH - 4);
    const ultraH = readPx("--vowel-cell-ultra-h", segBtnH - 8);
    const gap = readPx("--vowel-cell-stack-gap", 1);
    const stacks = dataEl.querySelectorAll(
        ".vowel-chart-cell-stack[data-slot-norm]",
    );
    for (const cell of stacks) {
        const slotNorm = parseFloat(cell.dataset.slotNorm);
        const depth = parseInt(cell.dataset.stackDepth, 10);
        if (!(slotNorm > 0) || !(depth > 0)) continue;
        const tierH = depth >= ultraThreshold
            ? ultraH
            : depth >= denseThreshold ? denseH : segBtnH;
        const budget = (slotNorm * dh - (depth - 1) * gap) / depth;
        const h = Math.max(minH, Math.min(tierH, Math.floor(budget)));
        if (h < tierH) {
            cell.dataset.clamped = "";
            cell.style.setProperty("--cell-btn-h", h + "px");
        } else {
            delete cell.dataset.clamped;
            cell.style.removeProperty("--cell-btn-h");
        }
    }
}

// Horizontal container for a vowel-chart cell whose two entries
// share a vowel-space position and differ on one in-cell-contrast
// feature (long / nasal / rhotic / breathy / creaky / tone). ``kind``
// is the shared ``VowelCellDisplayKind`` string, exposed as
// ``data-pair-kind`` for CSS. Children are plain seg-btns; see
// ``_buildVowelCellStack`` for why.
function _buildVowelCellPair(segs, kind) {
    const cell = document.createElement("div");
    // vowel-capsule = one segmented capsule (single outer frame,
    // shared fill, faint 1px divider) with independently-selectable
    // mates. Per-cell borders flattened by CSS.
    cell.className = "vowel-chart-cell vowel-chart-cell-pair vowel-capsule";
    if (kind) cell.dataset.pairKind = kind;
    _applyHorizontalDensity(cell, segs.length);
    for (const seg of segs) {
        cell.appendChild(_buildSegmentButton(seg));
    }
    return cell;
}

// Horizontal density tier: wide pills (5+ = dense, 6+ = ultra) drop
// their per-button width to keep the vowel space compact for click
// languages. Mirrors the vertical density tier for STACK cells and
// matches ``chart_style.effective_button_width_px`` so the geometry
// solver reserves what the buttons actually draw.
function _applyHorizontalDensity(cell, count) {
    const dense = CHART_STYLE.vowel_h_dense_threshold;
    const ultra = CHART_STYLE.vowel_h_ultra_threshold;
    if (typeof ultra === "number" && count >= ultra) {
        cell.dataset.cellDensity = "ultra";
    } else if (typeof dense === "number" && count >= dense) {
        cell.dataset.cellDensity = "dense";
    }
}

// Gridded capsule for a vowel-chart cell with 2+ entries differing on
// >1 in-cell-contrast feature. Two shapes come through:
//
// SINGLE-ROW (every entry at ``row=0`` with ``rowSpan=1``) renders as a
// flex-row PAIR capsule so it inherits the ``:first-child`` /
// ``:last-child`` corner rounding and per-cell state outlines. Anything
// else renders as a CSS grid with the divider helpers, and the
// classifier's ``spans`` array carries each cell's ``(colSpan, rowSpan)``
// so left/right cardinals stretch across empty corner slots (no dead
// clickable area).
function _buildVowelCellContrastSet(segs, grid, spans) {
    const coords = Array.isArray(grid) ? grid : [];
    const spanCoords = Array.isArray(spans) ? spans : [];
    const spanOf = (i) => {
        const sp = spanCoords[i];
        if (Array.isArray(sp) && sp.length >= 2) return [sp[0], sp[1]];
        return [1, 1];
    };
    const singleRow = coords.length > 0 && coords.every((pos, i) => {
        if (!Array.isArray(pos) || pos.length < 2) return false;
        const [, rowSpan] = spanOf(i);
        return pos[1] === 0 && rowSpan === 1;
    });
    const cell = document.createElement("div");
    cell.dataset.cellSize = String(segs.length);
    if (singleRow) {
        // The classifier lists entries base-first; sort by grid col so
        // ``[v1][BASE][v2]`` reads left-to-right in the flex row.
        cell.className =
            "vowel-chart-cell vowel-chart-cell-contrast-set vowel-capsule";
        const ordered = segs
            .map((seg, i) => ({ seg, col: coords[i][0] }))
            .sort((a, b) => a.col - b.col);
        for (const { seg } of ordered) cell.appendChild(_buildSegmentButton(seg));
        return cell;
    }
    cell.className =
        "vowel-chart-cell vowel-chart-cell-contrast-set "
        + "vowel-capsule vowel-capsule-grid";
    let maxCol = 0;
    let maxRow = 0;
    for (let i = 0; i < coords.length; i++) {
        const pos = coords[i];
        if (Array.isArray(pos) && pos.length >= 2) {
            const [colSpan, rowSpan] = spanOf(i);
            maxCol = Math.max(maxCol, pos[0] + colSpan);
            maxRow = Math.max(maxRow, pos[1] + rowSpan);
        }
    }
    // Explicit row/col sizing: ``1fr`` collapses to min-content on the
    // position-absolute cell container, which would starve spanned cells
    // and reintroduce the dead space the spans were meant to eliminate.
    cell.style.gridTemplateColumns =
        `repeat(${maxCol}, var(--seg-btn-min-w))`;
    cell.style.gridTemplateRows = `repeat(${maxRow}, var(--seg-btn-h))`;
    segs.forEach((seg, i) => {
        const btn = _buildSegmentButton(seg);
        const pos = coords[i];
        if (Array.isArray(pos) && pos.length >= 2) {
            const col = pos[0];
            const row = pos[1];
            const [colSpan, rowSpan] = spanOf(i);
            btn.style.gridColumn = `${col + 1} / span ${colSpan}`;
            btn.style.gridRow = `${row + 1} / span ${rowSpan}`;
            if (col > 0) btn.classList.add("vowel-capsule-div-l");
            if (row > 0) btn.classList.add("vowel-capsule-div-t");
        }
        cell.appendChild(btn);
    });
    return cell;
}
