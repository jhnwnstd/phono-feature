#!/usr/bin/env python3
"""Validate the web MULTISET rendering + fan-out against a live PHOIBLE
inventory (the desktop analog is the silent-render-loss hazard; on web
the risk is a reconcile/refit that touches only one instance of a
duplicated glyph). Loads a prenasalized inventory via the PHOIBLE picker
and asserts:

  1. a multi-membership consonant renders in >= 2 manner rows,
  2. those buttons carry the ``data-multiclass`` cue (count from the
     producer output),
  3. selecting one instance fans the state out to EVERY instance,
  4. a refit (resize) preserves both placements.

Run after build.py:  python web/scripts/check_multiset.py
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
LANGUAGE = "Xhosa"  # Nguni: prenasalized stops + clicks -> multi-membership


def _serve() -> socketserver.TCPServer:
    handler = type(
        "H",
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
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _fail(msg: str) -> int:
    print(f"  FAIL: {msg}", file=sys.stderr)
    return 1


def run(page) -> int:
    from playwright.sync_api import TimeoutError as PWTimeout

    page.on(
        "console",
        lambda m: (
            print(f"  [console.{m.type}] {m.text[:120]}")
            if m.type in ("error", "warning")
            else None
        ),
    )
    page.on(
        "response",
        lambda r: (
            print(f"  [net {r.status}] {r.url.split('/')[-1]}")
            if "phoible" in r.url.lower()
            else None
        ),
    )
    page.goto(f"http://127.0.0.1:{PORT}/", wait_until="domcontentloaded")
    page.wait_for_function(
        "() => document.querySelectorAll('.seg-btn').length > 0",
        timeout=BOOT_TIMEOUT_MS,
    )
    print("  booted")

    # --- drive the PHOIBLE picker to a prenasalized inventory ---
    page.click("#phoible-btn")
    page.wait_for_selector("#phoible-active:not([hidden])", timeout=30_000)
    # The picker lazy-fetches + ingests the externalized PHOIBLE index on
    # open; the debounced, bridge-backed search returns nothing until that
    # completes. Poll: re-fire the search each second until a real result
    # row (not the "no matches" hint) appears. Fire a PREFIX of the name,
    # not the exact full name: dispatching the exact single-match name in
    # one shot races the debounce/render and can leave the list empty.
    query = LANGUAGE[:3]
    fire = (
        "() => { const s = document.querySelector('#phoible-search');"
        f" s.focus(); s.value = {query!r};"
        " s.dispatchEvent(new Event('input', {bubbles: true})); }"
    )
    typed = False
    for _ in range(30):
        page.evaluate(fire)
        page.wait_for_timeout(1000)
        n = page.eval_on_selector("#phoible-results", "e => e.children.length")
        txt = page.eval_on_selector("#phoible-results", "e => e.textContent")
        if n and "match" not in txt.lower():
            typed = True
            break
    if not typed:
        return _fail(f"no PHOIBLE results for {query!r} after ingest")
    # pick the exact language row among the prefix matches
    page.eval_on_selector(
        "#phoible-results",
        "el => { for (const li of el.children)"
        f" if (li.textContent === {LANGUAGE!r})"
        " return li.dispatchEvent(new MouseEvent('mousedown',"
        " {bubbles: true, cancelable: true})); }",
    )
    page.wait_for_selector(
        "#phoible-radios input[type='radio']", timeout=30_000
    )
    page.eval_on_selector(
        "#phoible-radios input[type='radio']", "el => el.click()"
    )
    page.wait_for_selector("#phoible-load:not([disabled])", timeout=30_000)
    page.click("#phoible-load")
    # grid re-renders; wait until a multi-membership glyph appears
    try:
        page.wait_for_function(
            """() => {
                const seen = {};
                for (const b of document.querySelectorAll(
                        '#seg-grid .seg-btn[data-seg]')) {
                    seen[b.dataset.seg] = (seen[b.dataset.seg] || 0) + 1;
                }
                return Object.values(seen).some((n) => n >= 2);
            }""",
            timeout=30_000,
        )
    except PWTimeout:
        return _fail(f"{LANGUAGE} loaded but no multi-membership glyph")
    print(f"  loaded {LANGUAGE}")

    # --- 1 + 2: a glyph in >= 2 rows carries the data-multiclass cue ---
    info = page.evaluate("""() => {
            const bySeg = {};
            for (const b of document.querySelectorAll(
                    '#seg-grid .seg-btn[data-seg]')) {
                (bySeg[b.dataset.seg] = bySeg[b.dataset.seg] || []).push(b);
            }
            const seg = Object.keys(bySeg).find(
                (s) => bySeg[s].length >= 2);
            const btns = bySeg[seg];
            return {
                seg,
                count: btns.length,
                cues: btns.map((b) => b.dataset.multiclass || null),
            };
        }""")
    seg = info["seg"]
    print(f"  multi-membership glyph {seg!r} renders in {info['count']} rows")
    if any(c is None for c in info["cues"]):
        return _fail(f"{seg!r} missing data-multiclass cue: {info['cues']}")
    if not all(int(c) == info["count"] for c in info["cues"]):
        return _fail(
            f"{seg!r} cue {info['cues']} disagrees with row count "
            f"{info['count']} (cue must come from the producer output)"
        )
    print(f"  cue ok: data-multiclass={info['cues'][0]} on every instance")

    # --- 3: selecting one instance fans state out to every instance ---
    page.eval_on_selector(
        f"#seg-grid .seg-btn[data-seg='{seg}']", "el => el.click()"
    )
    page.wait_for_timeout(500)  # let the click flip + bridge reconcile settle
    states = page.evaluate(f"""() => [...document.querySelectorAll(
            '#seg-grid .seg-btn[data-seg=\\'{seg}\\']')]
            .map((b) => b.dataset.state)""")
    if len(set(states)) != 1 or states[0] == "default":
        return _fail(f"{seg!r} instances not synced after click: {states}")
    print(f"  fan-out ok: all instances -> {states[0]!r}")

    # --- 4: a refit (resize) preserves both placements ---
    page.set_viewport_size({"width": 900, "height": 720})
    page.wait_for_timeout(400)
    page.set_viewport_size({"width": 1280, "height": 720})
    page.wait_for_timeout(400)
    after = page.evaluate(f"""() => [...document.querySelectorAll(
            '#seg-grid .seg-btn[data-seg=\\'{seg}\\']')].length""")
    if after != info["count"]:
        return _fail(
            f"refit collapsed {seg!r} placements: {info['count']} -> {after}"
        )
    print(f"  refit ok: {seg!r} still in {after} rows")
    return 0


def main() -> int:
    if not DIST.is_dir():
        return _fail(f"{DIST} missing; run build.py first")
    httpd = _serve()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _fail("playwright not installed")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_context(
                viewport={"width": 1280, "height": 720}
            ).new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            rc = run(page)
            browser.close()
            if errors:
                print("  page errors:", errors[:5], file=sys.stderr)
                rc = rc or 1
    finally:
        httpd.shutdown()
    print("  OK" if rc == 0 else "  FAILED")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
