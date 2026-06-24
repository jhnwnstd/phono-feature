#!/usr/bin/env python3
"""Verify the arithmetic editor-grid column/row sizing against the real
browser box model.

The feature grid used to size its columns by tearing the table down to
natural layout, forcing a synchronous reflow, and reading offsetWidth
for every cell. ``_alignHeaderPanesToData`` now sizes columns by cached
canvas ``measureText`` arithmetic instead. This harness boots the built
site, opens the editor on the real inventory, and proves the new sizing
is regression-free:

1. NO CLIP: every header / row-header / data cell fits its assigned
   width (``scrollWidth <= clientWidth + 1``).
2. ALIGNED: the column-header pane and the data pane resolve to the same
   total width and the same per-column widths (so headers sit over their
   data).
3. NOT NARROWER THAN NATURAL: each assigned column width is >= the width
   the browser would give that header in natural layout (the old
   behaviour), and within a few px of it (no width blow-up).

Exit 0 on pass, 1 on any violation. Standalone (own server + chromium),
mirroring web/scripts/smoke.py.
"""

from __future__ import annotations

import http.server
import socketserver
import sys
import threading
from pathlib import Path

DIST = Path(__file__).resolve().parents[1] / "dist"
PORT = 8921
BOOT_TIMEOUT_MS = 120_000

# Runs entirely in the page after the editor renders. Returns a plain
# dict the Python side asserts on.
_CHECK_JS = r"""
() => {
    const colsThs = [...document.querySelectorAll(
        '.editor-grid-pane-cols .editor-grid th')];
    const rowThs = [...document.querySelectorAll(
        '.editor-grid-pane-rows .editor-grid th')];
    const dataTds = [...document.querySelectorAll(
        '.editor-grid-pane-data .editor-grid td')];
    const colsTable = document.querySelector(
        '.editor-grid-pane-cols .editor-grid');
    const dataTable = document.querySelector(
        '.editor-grid-pane-data .editor-grid');

    const TOL = 1;  // integer sub-pixel slack for scrollWidth rounding
    const clip = (els) => els
        .filter((e) => e.scrollWidth > e.clientWidth + TOL)
        .map((e) => ({
            text: e.textContent,
            scrollWidth: e.scrollWidth,
            clientWidth: e.clientWidth,
        }));

    // Natural-width oracle: lay each header out in a standalone
    // .editor-grid cell (no fixed colgroup) and read its offsetWidth.
    // That is exactly what the old reflow-based code measured.
    const probe = document.createElement('table');
    probe.className = 'editor-grid';
    probe.style.cssText =
        'position:absolute;left:-99999px;top:-99999px;table-layout:auto';
    const pbody = document.createElement('tbody');
    probe.appendChild(pbody);
    document.body.appendChild(probe);
    const naturalOf = (text, bold) => {
        const tr = document.createElement('tr');
        const th = document.createElement(bold ? 'th' : 'td');
        th.textContent = text;
        tr.appendChild(th);
        pbody.appendChild(tr);
        const w = th.getBoundingClientRect().width;
        pbody.removeChild(tr);
        return w;
    };

    const widthChecks = colsThs.map((th) => {
        const assigned = th.getBoundingClientRect().width;
        const natural = naturalOf(th.textContent, true);
        return {
            text: th.textContent,
            assigned: Math.round(assigned * 100) / 100,
            natural: Math.round(natural * 100) / 100,
            narrower: assigned < natural - 0.5,
            blownUp: assigned > natural + 4,
        };
    });
    probe.remove();

    // Per-column alignment between the cols pane and the data pane:
    // compare the first data row's cell widths to the header widths.
    const firstDataRow = dataTable
        ? dataTable.querySelector('tr')
        : null;
    const dataRowCells = firstDataRow
        ? [...firstDataRow.querySelectorAll('td')]
        : [];
    const perColMismatch = [];
    for (let c = 0; c < colsThs.length && c < dataRowCells.length; c++) {
        const hw = colsThs[c].getBoundingClientRect().width;
        const dw = dataRowCells[c].getBoundingClientRect().width;
        if (Math.abs(hw - dw) > 1) {
            perColMismatch.push({
                col: c,
                text: colsThs[c].textContent,
                headerW: Math.round(hw * 100) / 100,
                dataW: Math.round(dw * 100) / 100,
            });
        }
    }

    const colsW = colsTable
        ? colsTable.getBoundingClientRect().width : 0;
    const dataW = dataTable
        ? dataTable.getBoundingClientRect().width : 0;

    return {
        nCols: colsThs.length,
        nRows: rowThs.length,
        nData: dataTds.length,
        headers: colsThs.map((t) => t.textContent),
        widestHeader: widthChecks
            .slice()
            .sort((a, b) => b.assigned - a.assigned)[0] || null,
        clipCols: clip(colsThs),
        clipRows: clip(rowThs),
        clipData: clip(dataTds),
        colsW: Math.round(colsW * 100) / 100,
        dataW: Math.round(dataW * 100) / 100,
        tableWidthMismatch: Math.abs(colsW - dataW) > 1,
        perColMismatch,
        narrower: widthChecks.filter((w) => w.narrower),
        blownUp: widthChecks.filter((w) => w.blownUp),
    };
}
"""


def _serve() -> socketserver.TCPServer:
    handler_cls = type(
        "Handler",
        (http.server.SimpleHTTPRequestHandler,),
        {
            "__init__": lambda self, *a, **k: (
                http.server.SimpleHTTPRequestHandler.__init__(
                    self, *a, directory=str(DIST), **k
                )
            ),
            "log_message": lambda *a, **k: None,
        },
    )
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler_cls)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main() -> int:
    if not DIST.is_dir():
        print(f"FAIL: {DIST} missing; run build.py first", file=sys.stderr)
        return 1
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("FAIL: playwright not installed", file=sys.stderr)
        return 1

    httpd = _serve()
    try:
        with sync_playwright() as p:
            bt = getattr(p, "chromium", None)
            if bt is None or not Path(bt.executable_path).exists():
                print("SKIP: chromium driver not installed")
                return 0
            browser = bt.launch(headless=True)
            page = browser.new_context(
                viewport={"width": 1280, "height": 720}
            ).new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(
                f"http://127.0.0.1:{PORT}/", wait_until="domcontentloaded"
            )
            page.wait_for_function(
                "() => document.querySelectorAll('.seg-btn').length > 0",
                timeout=BOOT_TIMEOUT_MS,
            )
            page.click("#builder-btn")
            page.wait_for_function(
                "() => document.querySelectorAll("
                "'.editor-grid-pane-cols .editor-grid th').length > 0",
                timeout=BOOT_TIMEOUT_MS,
            )
            page.wait_for_timeout(150)  # let the align pass settle
            r = page.evaluate(_CHECK_JS)
            browser.close()
    finally:
        httpd.shutdown()

    if errors:
        print("FAIL: page errors:", *errors, sep="\n  ", file=sys.stderr)
        return 1

    print(
        f"editor grid: {r['nCols']} columns, {r['nRows']} rows, "
        f"{r['nData']} data cells"
    )
    wh = r["widestHeader"]
    if wh:
        print(
            f"widest header: /{wh['text']}/ assigned={wh['assigned']}px "
            f"natural={wh['natural']}px"
        )
    affricates = [h for h in r["headers"] if "͡" in h or "͜" in h]
    print(
        f"affricate/contour headers exercised: {len(affricates)} "
        f"{affricates[:8]}"
    )

    failures = []
    if r["clipCols"]:
        failures.append(f"clipped column headers: {r['clipCols']}")
    if r["clipRows"]:
        failures.append(f"clipped row headers: {r['clipRows']}")
    if r["clipData"]:
        failures.append(f"clipped data cells: {r['clipData'][:5]}")
    if r["tableWidthMismatch"]:
        failures.append(
            f"pane width mismatch: cols={r['colsW']} data={r['dataW']}"
        )
    if r["perColMismatch"]:
        failures.append(f"per-column misalignment: {r['perColMismatch'][:5]}")
    if r["narrower"]:
        failures.append(
            f"columns NARROWER than natural (clip risk): {r['narrower'][:5]}"
        )
    if r["blownUp"]:
        failures.append(f"columns >4px wider than natural: {r['blownUp'][:5]}")

    if failures:
        print("\nFAIL:", *failures, sep="\n  ", file=sys.stderr)
        return 1
    print(
        "\nPASS: no clipping, panes aligned, widths match natural "
        "layout within tolerance."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
