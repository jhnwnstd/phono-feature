#!/usr/bin/env python3
"""End-to-end smoke test for the built web app.

Serves ``web/dist/`` over a local HTTP server, opens it in headless
Chromium via Playwright, and asserts the live behavior:

* Pyodide boots and loads the engine wheel.
* The default inventory renders segment buttons.
* Clicking a segment populates the analysis pane with HTML that
  contains the expected feature chips.
* No fatal console errors fired during the boot.

Designed for CI: the build workflow produces ``web/dist/``, this
script smokes it, and a regression in Pyodide compatibility or the
JS bridge fails the deploy instead of shipping a broken page.

Exit code 0 on success, 1 on any failure. Console errors are
printed to stderr.
"""
from __future__ import annotations

import http.server
import socketserver
import sys
import threading
from pathlib import Path

DIST = Path(__file__).resolve().parents[1] / "dist"
PORT = 8920
BOOT_TIMEOUT_MS = 120_000  # cold-load Pyodide + engine + bundle


def main() -> int:
    if not DIST.is_dir():
        print(f"FAIL: {DIST} does not exist; run build.py first", file=sys.stderr)
        return 1

    handler_cls = type(
        "Handler",
        (http.server.SimpleHTTPRequestHandler,),
        {
            "__init__": lambda self, *a, **k: http.server.SimpleHTTPRequestHandler.__init__(
                self, *a, directory=str(DIST), **k
            ),
            "log_message": lambda *a, **k: None,
        },
    )
    # allow_reuse_address so a previous smoke run that didn't shut
    # down cleanly (e.g. killed mid-test) doesn't block the next run
    # with EADDRINUSE.
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler_cls)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("FAIL: playwright not installed", file=sys.stderr)
        return 1

    rc = 1
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 720})
        page = ctx.new_page()

        console_errors: list[str] = []
        page_errors: list[str] = []
        page.on(
            "console",
            lambda m: console_errors.append(m.text) if m.type == "error" else None,
        )
        page.on("pageerror", lambda e: page_errors.append(str(e)))

        url = f"http://127.0.0.1:{PORT}/"
        print(f"Opening {url} ...")
        page.goto(url, wait_until="domcontentloaded")

        print("Waiting for the bridge to finish booting...")
        try:
            page.wait_for_function(
                "() => document.querySelectorAll('.seg-btn').length > 0",
                timeout=BOOT_TIMEOUT_MS,
            )
        except Exception as e:
            print(f"FAIL: bridge never booted: {e}", file=sys.stderr)
            print(
                "Last loading status: "
                + str(
                    page.evaluate(
                        "() => document.getElementById('loading-status')?.textContent"
                    )
                ),
                file=sys.stderr,
            )
            _dump_errors(console_errors, page_errors)
            browser.close()
            return 1

        seg_count = page.evaluate(
            "() => document.querySelectorAll('.seg-btn').length"
        )
        feat_count = page.evaluate(
            "() => document.querySelectorAll('.feat-row').length"
        )
        print(f"  segments rendered: {seg_count}")
        print(f"  feature rows:      {feat_count}")
        if seg_count == 0 or feat_count == 0:
            print("FAIL: empty panels after boot", file=sys.stderr)
            browser.close()
            return 1

        print("Clicking a segment to drive the analysis pipeline...")
        clicked = page.evaluate(
            "() => { for (const b of document.querySelectorAll('.seg-btn')) "
            "{ if (b.dataset.seg) { b.click(); return b.dataset.seg; } } "
            "return null; }"
        )
        print(f"  clicked: /{clicked}/")
        page.wait_for_function(
            "() => document.getElementById('analysis-content').innerHTML.length > 0",
            timeout=10_000,
        )
        analysis_html = page.evaluate(
            "() => document.getElementById('analysis-content').innerHTML"
        )
        if "feature bundle" not in analysis_html and "Selected" not in analysis_html:
            print(
                "FAIL: analysis pane filled but doesn't look like an analysis "
                f"result. Length={len(analysis_html)}, first 200 chars: "
                f"{analysis_html[:200]!r}",
                file=sys.stderr,
            )
            browser.close()
            return 1
        print(f"  analysis pane: {len(analysis_html)} bytes of HTML")

        if console_errors or page_errors:
            print("FAIL: console / page errors fired during boot", file=sys.stderr)
            _dump_errors(console_errors, page_errors)
            browser.close()
            return 1

        print("OK: bridge boots, panels render, analysis populates, no errors.")
        rc = 0
        browser.close()

    httpd.shutdown()
    return rc


def _dump_errors(console_errors: list[str], page_errors: list[str]) -> None:
    for m in console_errors:
        print(f"  [console.error] {m}", file=sys.stderr)
    for e in page_errors:
        print(f"  [pageerror] {e}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
