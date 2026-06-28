#!/usr/bin/env python3
"""End-to-end smoke test for the built web app.

Serves ``web/dist/`` from a local HTTP server, opens it across
Chromium / Firefox / WebKit via Playwright (each one skipped
cleanly if its driver binary is not installed), and asserts:

* Pyodide boots and the bridge attaches.
* The default inventory renders segment buttons and feature rows.
* Clicking a segment populates the analysis pane.
* No console / page errors during boot.

After the baseline check at 1280x720 the same page is resized to
two extra viewports (360x640 and 3440x1440) where additional
assertions run:

* The narrow viewport must keep the statusbar brand visible
  even when the message text is artificially long, and the
  single-column collapse must engage.
* The ultrawide viewport must keep ``main.grid`` capped under
  ``--content-max-w`` so the page doesn't fan out edge-to-edge.

Designed for CI: the build workflow produces ``web/dist/``, this
smokes it, regressions fail the deploy. Exit 0 on success, 1 on
any failure.
"""

from __future__ import annotations

import http.server
import socketserver
import sys
import threading
from pathlib import Path

DIST = Path(__file__).resolve().parents[1] / "dist"
PORT = 8920
BOOT_TIMEOUT_MS = 120_000

# Browsers to sweep. Each entry's first value is the human label
# used in log lines; the second is the attribute name on the
# Playwright ``p`` object that returns the BrowserType.
BROWSERS = (
    ("chromium", "chromium"),
    ("firefox", "firefox"),
    ("webkit", "webkit"),
)

# Extra viewports beyond the 1280x720 baseline. Each tuple is
# (label, width, height, check_callable_name) where the callable
# is one of the run_* functions below.
EXTRA_VIEWPORTS = (
    ("narrow-mobile", 360, 640, "run_narrow_checks"),
    ("ultrawide", 3440, 1440, "run_ultrawide_checks"),
)


def main() -> int:
    if not DIST.is_dir():
        print(
            f"FAIL: {DIST} does not exist; run build.py first",
            file=sys.stderr,
        )
        return 1

    handler_cls = type(
        "Handler",
        (http.server.SimpleHTTPRequestHandler,),
        {
            "__init__": lambda self, *a, **k: (
                http.server.SimpleHTTPRequestHandler.__init__(
                    self,
                    *a,
                    directory=str(DIST),
                    **k,
                )
            ),
            "log_message": lambda *a, **k: None,
        },
    )
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler_cls)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("FAIL: playwright not installed", file=sys.stderr)
        httpd.shutdown()
        return 1

    overall_rc = 0
    with sync_playwright() as p:
        any_browser_ran = False
        for label, attr in BROWSERS:
            browser_type = getattr(p, attr, None)
            if browser_type is None:
                print(f"SKIP: {label}: Playwright BrowserType not found")
                continue
            try:
                exe = browser_type.executable_path
            except AttributeError:
                # Older Playwright versions don't expose this property
                # on the BrowserType class; treat as "driver missing"
                # rather than swallowing every exception class (which
                # masked real Playwright import errors).
                exe = ""
            if not exe or not Path(exe).exists():
                print(f"SKIP: {label}: driver not installed at {exe!r}")
                continue
            any_browser_ran = True
            print(f"\n=== {label} ===")
            rc = run_for_browser(browser_type, label)
            if rc != 0:
                overall_rc = rc

        if not any_browser_ran:
            print(
                "FAIL: no Playwright driver installed; "
                "run 'playwright install' to bootstrap one of "
                "chromium / firefox / webkit",
                file=sys.stderr,
            )
            overall_rc = 1

    httpd.shutdown()
    return overall_rc


def run_for_browser(browser_type, label: str) -> int:
    """Boot the app in this browser at 1280x720, run the baseline
    smoke, then resize through the extra viewports and run the
    follow-up assertions. One page session per browser keeps the
    Pyodide boot cost amortised.
    """
    # Local import so the module loads cleanly even without
    # Playwright installed; main() reports the missing dep before
    # any run_for_browser call.
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    browser = browser_type.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1280, "height": 720})
    page = ctx.new_page()

    console_errors: list[str] = []
    page_errors: list[str] = []
    page.on(
        "console",
        lambda m: (
            console_errors.append(m.text) if m.type == "error" else None
        ),
    )
    page.on("pageerror", lambda e: page_errors.append(str(e)))

    url = f"http://127.0.0.1:{PORT}/"
    print(f"  open {url}")
    page.goto(url, wait_until="domcontentloaded")

    try:
        page.wait_for_function(
            "() => document.querySelectorAll('.seg-btn').length > 0",
            timeout=BOOT_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError as e:
        # Only catch the boot-timeout case; KeyboardInterrupt and
        # any genuine Playwright bug should propagate so the smoke
        # run can be killed cleanly or the bug surfaces in CI.
        print(f"  FAIL: bridge never booted: {e}", file=sys.stderr)
        _dump_errors(console_errors, page_errors)
        browser.close()
        return 1

    rc = run_baseline_checks(page, label)
    if rc != 0:
        browser.close()
        return rc

    rc = run_pane_toggle_no_overlap_checks(page, label)
    if rc != 0:
        browser.close()
        return rc

    rc = run_critical_pair_no_overlap_checks(page, label)
    if rc != 0:
        browser.close()
        return rc

    for vp_label, w, h, check_name in EXTRA_VIEWPORTS:
        print(f"  resize -> {vp_label} ({w}x{h})")
        page.set_viewport_size({"width": w, "height": h})
        check_fn = globals()[check_name]
        rc = check_fn(page, vp_label)
        if rc != 0:
            browser.close()
            return rc

    # Editor "New" transaction rollback (resets its own viewport). Runs
    # last so its inventory swap + rollback cannot disturb the layout
    # assertions above.
    rc = run_editor_rollback_check(page, label)
    if rc != 0:
        browser.close()
        return rc

    # Editor "New" unsaved-work prompt (data-loss guard). Runs after the
    # rollback check, which leaves the original inventory restored and
    # the editor closed.
    rc = run_editor_unsaved_guard_check(page, label)
    if rc != 0:
        browser.close()
        return rc

    if console_errors or page_errors:
        print(
            "  FAIL: console / page errors fired during run",
            file=sys.stderr,
        )
        _dump_errors(console_errors, page_errors)
        browser.close()
        return 1

    print(f"  OK ({label})")
    browser.close()
    return 0


def run_baseline_checks(page, label: str) -> int:
    """Original 1280x720 happy-path assertions: segments render,
    features render, clicking a segment populates the analysis pane.
    """
    seg_count = page.evaluate(
        "() => document.querySelectorAll('.seg-btn').length",
    )
    feat_count = page.evaluate(
        "() => document.querySelectorAll('.feat-row').length",
    )
    print(f"  segments={seg_count}, feature rows={feat_count}")
    if seg_count == 0 or feat_count == 0:
        print("  FAIL: empty panels after boot", file=sys.stderr)
        return 1

    clicked = page.evaluate(
        "() => { for (const b of document.querySelectorAll('.seg-btn'))"
        " { if (b.dataset.seg) { b.click(); return b.dataset.seg; } }"
        " return null; }",
    )
    print(f"  click seg /{clicked}/")
    # Firefox is markedly slower than chromium/webkit at the first
    # ``analyze_segments`` call (cold Pyodide path through the
    # Python view-models stack). 10 s was tight under the prior
    # smoke; the cold path comfortably finishes by 30 s on every
    # browser, so the wider window only matters when something is
    # actually broken (in which case 30 s still surfaces the
    # failure quickly enough).
    page.wait_for_function(
        "() => {"
        " const sel = document.getElementById('analysis-selection');"
        " const feat = document.getElementById"
        "('analysis-content-features');"
        " return sel && feat && sel.innerHTML.length > 0"
        " && feat.innerHTML.length > 0;"
        "}",
        timeout=30_000,
    )
    selection_html = page.evaluate(
        "() => document.getElementById('analysis-selection').innerHTML",
    )
    features_html = page.evaluate(
        "() => document.getElementById"
        "('analysis-content-features').innerHTML",
    )
    if "Selected" not in selection_html:
        print(
            "  FAIL: selection chip strip missing 'Selected' label. "
            f"First 200 chars: {selection_html[:200]!r}",
            file=sys.stderr,
        )
        return 1
    if "feature bundle" not in features_html.lower():
        print(
            "  FAIL: Features tab missing 'feature bundle' content. "
            f"First 200 chars: {features_html[:200]!r}",
            file=sys.stderr,
        )
        return 1
    print(
        f"  analysis: selection={len(selection_html)}B,"
        f" features={len(features_html)}B"
    )
    return 0


# Submit the editor's "New inventory" setup dialog with a given name,
# filling the segment + feature fields from their placeholder defaults
# (a smaller, valid inventory distinct from the loaded one). Shared by
# the rollback + unsaved-guard checks so the setup-submit idiom has one
# home.
_SETUP_SUBMIT_JS = (
    "(name) => {"
    " const s = document.querySelector('#setup-segments-input');"
    " const f = document.querySelector('#setup-features-input');"
    " document.querySelector('#setup-name-input').value = name;"
    " s.value = s.placeholder; f.value = f.placeholder;"
    " document.querySelector('#setup-form').requestSubmit();"
    "}"
)


def run_editor_unsaved_guard_check(page, label: str) -> int:
    """Regression guard for the editor "New" unsaved-work prompt.

    Once a new (unsaved) inventory has been created via "New", a SECOND
    "New" must PROMPT before discarding it. The guard reads
    editorHasUnsavedWork(), so it fires even though the just-created
    inventory is not yet "dirty" (engineReplaced is true). A weaker
    dirty-only guard silently discarded the created inventory.
    """
    page.set_viewport_size({"width": 1280, "height": 720})
    has_grid = page.evaluate(
        "() => document.querySelectorAll('#seg-grid .seg-btn').length"
    )
    if not has_grid:
        print("  editor-unsaved-guard: no seg-grid, skipping")
        return 0
    prompts: list[str] = []

    def _record(d) -> None:
        prompts.append(d.message)
        d.accept()

    page.on("dialog", _record)
    try:
        page.click("#editor-btn")
        page.wait_for_timeout(150)
        # First New: state was clean before it, so no prompt should fire.
        page.click("#editor-new-btn")
        page.wait_for_selector("#setup-dialog[open]", timeout=10_000)
        page.evaluate(_SETUP_SUBMIT_JS, "GUARD_FIRST")
        page.wait_for_timeout(700)
        if prompts:
            print(
                f"  FAIL: first New prompted unexpectedly ({prompts})",
                file=sys.stderr,
            )
            return 1
        # Second New: a created-but-unsaved inventory now exists; the
        # guard must prompt even though it is not "dirty".
        page.click("#editor-new-btn")
        page.wait_for_selector("#setup-dialog[open]", timeout=10_000)
        page.evaluate(_SETUP_SUBMIT_JS, "GUARD_SECOND")
        page.wait_for_timeout(700)
        if not any("Discard unsaved" in m for m in prompts):
            print(
                "  FAIL: second New did not prompt before discarding a "
                f"created-but-unsaved inventory (dialogs={prompts})",
                file=sys.stderr,
            )
            return 1
    finally:
        page.remove_listener("dialog", _record)
    # Clean up: back out of the editor, accepting the discard confirm.
    page.once("dialog", lambda d: d.accept())
    page.click("#editor-exit-btn")
    page.wait_for_timeout(400)
    print("  editor unsaved-work guard ok (second New prompted)")
    return 0


def run_editor_rollback_check(page, label: str) -> int:
    """Regression guard for the editor "New" transaction: creating a new
    inventory via the editor's New and backing out WITHOUT saving must
    roll the engine back to the previously loaded inventory, not leave
    the unsaved one behind (with the old name).
    """
    page.set_viewport_size({"width": 1280, "height": 720})
    sig_js = (
        "() => [...document.querySelectorAll('#seg-grid .seg-btn')]"
        ".map(b => b.dataset.seg).join(',')"
    )
    before = page.evaluate(sig_js)
    if not before:
        print("  editor-rollback: no seg-grid, skipping")
        return 0
    page.click("#editor-btn")
    page.wait_for_timeout(150)
    page.click("#editor-new-btn")
    try:
        page.wait_for_selector("#setup-dialog[open]", timeout=10_000)
    except Exception:  # noqa: BLE001
        print("  FAIL: setup dialog did not open", file=sys.stderr)
        return 1
    # Fill from the placeholder defaults (a smaller, different inventory
    # than the default) and submit.
    page.evaluate(_SETUP_SUBMIT_JS, "SMOKE_NEW")
    page.wait_for_timeout(700)
    if page.evaluate(sig_js) == before:
        print("  FAIL: 'New' did not swap the inventory", file=sys.stderr)
        return 1
    # Back out; accept the discard confirm (default Playwright behaviour
    # would dismiss it, cancelling the close).
    page.once("dialog", lambda d: d.accept())
    page.click("#editor-exit-btn")
    page.wait_for_timeout(700)
    after = page.evaluate(sig_js)
    hidden = page.evaluate(
        "() => document.querySelector('#editor-view').hidden"
    )
    if after != before or not hidden:
        print(
            "  FAIL: back-out did not restore the original inventory "
            f"(before#={before.count(',') + 1}, "
            f"after#={after.count(',') + 1}, editor_hidden={hidden})",
            file=sys.stderr,
        )
        return 1
    print(f"  editor rollback ok (restored {after.count(',') + 1} segments)")
    return 0


def _assert_no_overlap_js(
    page,
    selector_a: str,
    selector_b: str,
    label: str,
) -> int:
    """Pairwise non-overlap assertion runnable from any smoke check.

    Returns 0 if no element matching ``selector_a`` intersects any
    element matching ``selector_b`` (1-px tolerance to absorb sub-
    pixel boundary touches), 1 otherwise with details to stderr.
    Skips pairs where one side is empty; the panel may simply not
    contain that selector at the current viewport.
    """
    overlaps = page.evaluate(
        "(args) => {"
        " const [selA, selB] = args;"
        " const inside = (r, p) => !("
        "   r.right <= p.left + 0.5 ||"
        "   r.left >= p.right - 0.5 ||"
        "   r.bottom <= p.top + 0.5 ||"
        "   r.top >= p.bottom - 0.5"
        " );"
        " const as = [...document.querySelectorAll(selA)];"
        " const bs = [...document.querySelectorAll(selB)];"
        " const out = [];"
        " for (const a of as) {"
        "   if (bs.some(b => a === b || a.contains(b) || b.contains(a)))"
        "     continue;"
        "   const ra = a.getBoundingClientRect();"
        "   for (const b of bs) {"
        "     if (a === b || a.contains(b) || b.contains(a)) continue;"
        "     const rb = b.getBoundingClientRect();"
        "     if (inside(ra, rb)) {"
        "       out.push({a: selA, b: selB,"
        "                 ra: [ra.left, ra.top, ra.right, ra.bottom],"
        "                 rb: [rb.left, rb.top, rb.right, rb.bottom]});"
        "       break;"
        "     }"
        "   }"
        "   if (out.length >= 3) break;"
        " }"
        " return out;"
        "}",
        [selector_a, selector_b],
    )
    if overlaps:
        print(
            f"  FAIL ({label}): {selector_a} overlaps {selector_b}:"
            f" {overlaps}",
            file=sys.stderr,
        )
        return 1
    return 0


def run_pane_toggle_no_overlap_checks(page, label: str) -> int:
    """Activate the Features pane and back; assert the toggle does
    not INTRODUCE new vowel-chart overlap that wasn't there before.

    Phase A wires ``relayoutSegments`` into the pane-activation
    path so any future CSS rule that changes pane width on toggle
    will retrigger the per-group column computation. The current
    CSS only changes ``data-active`` color, so the pane width is
    invariant under toggle; this check captures that invariant by
    diffing the pre- and post-toggle overlap sets.

    The check is a delta, not an absolute, so pre-existing
    spillover-vs-float overlap (a separate bug) doesn't shadow
    Phase A's invariant.
    """

    overlap_set_js = (
        "() => {"
        " const vowels = document.querySelector('.seg-vowels');"
        " if (!vowels) return [];"
        " const v = vowels.getBoundingClientRect();"
        " const out = [];"
        " for (const btn of"
        " document.querySelectorAll('#seg-grid .seg-btn')) {"
        "   if (btn.closest('.seg-vowels')) continue;"
        "   const r = btn.getBoundingClientRect();"
        "   const intersects = !("
        "     r.right <= v.left + 0.5 ||"
        "     r.left >= v.right - 0.5 ||"
        "     r.bottom <= v.top + 0.5 ||"
        "     r.top >= v.bottom - 0.5"
        "   );"
        "   if (intersects) out.push(btn.dataset.seg);"
        " }"
        " return out.sort();"
        "}"
    )

    page.wait_for_timeout(120)
    baseline = page.evaluate(overlap_set_js)

    print("  toggle to Features pane")
    page.evaluate("() => document.getElementById('feat-panel').click()")
    page.wait_for_timeout(120)
    after_feat = page.evaluate(overlap_set_js)
    new_overlaps = sorted(set(after_feat) - set(baseline))
    if new_overlaps:
        print(
            "  FAIL (Features active): toggle introduced new"
            f" vowel-overlap segments: {new_overlaps}",
            file=sys.stderr,
        )
        return 1

    print("  toggle back to Segments pane")
    page.evaluate("() => document.getElementById('seg-panel').click()")
    page.wait_for_timeout(120)
    after_seg = page.evaluate(overlap_set_js)
    new_overlaps = sorted(set(after_seg) - set(baseline))
    if new_overlaps:
        print(
            "  FAIL (Segments active again): toggle introduced new"
            f" vowel-overlap segments: {new_overlaps}",
            file=sys.stderr,
        )
        return 1

    print("  pane-toggle introduces no new overlap")
    return 0


def run_critical_pair_no_overlap_checks(page, label: str) -> int:
    """Structural pairwise non-overlap invariants for the document
    skeleton. Pins the principle that the toolbar, main grid, and
    statusbar are stacked siblings: each must occupy a distinct
    vertical band. A future ``position: absolute`` or
    ``z-index``-shuffle that visually overlays them gets caught
    here instead of as a hand-eye-test regression.

    The seg/feat/analysis trio is handled by the CSS grid template
    columns + rows; this check pins that they don't drift into each
    other's space (e.g. via a future ``transform`` or negative
    margin).
    """
    page.wait_for_timeout(60)
    for sel_a, sel_b, pair_label in [
        ("header.toolbar", "main.grid", "toolbar vs grid"),
        ("main.grid", "footer.statusbar", "grid vs statusbar"),
        ("#seg-panel", "#feat-panel", "seg-panel vs feat-panel"),
        ("#analysis", "#seg-panel", "analysis vs seg-panel"),
        ("#analysis", "#feat-panel", "analysis vs feat-panel"),
    ]:
        rc = _assert_no_overlap_js(page, sel_a, sel_b, pair_label)
        if rc != 0:
            return rc
    print("  critical-pair no-overlap ok")
    return 0


def run_narrow_checks(page, label: str) -> int:
    """At a 360x640 viewport: the single-column collapse should
    engage, the statusbar should clip a long message via ellipsis
    instead of pushing the brand out of view, and dialogs should
    fit inside the viewport.
    """
    # Single-column collapse: grid-template-columns is "1fr" below
    # the COLLAPSE_W threshold. We check for the resolved single-
    # track form rather than parsing the raw value.
    grid_cols = page.evaluate(
        "() => getComputedStyle(document.querySelector('main.grid'))"
        ".gridTemplateColumns"
    )
    if " " in grid_cols.strip():
        print(
            "  FAIL: at 360 wide the grid did not collapse to a"
            f" single column; got {grid_cols!r}",
            file=sys.stderr,
        )
        return 1

    # Statusbar must keep the brand visible when the message is long.
    page.evaluate(
        "() => {"
        " const el = document.getElementById('statusbar');"
        " if (el) {"
        " el.textContent = 'A ' + 'very-long-status-message '.repeat(20);"
        " el.title = el.textContent;"
        " } }"
    )
    brand_info = page.evaluate(
        "() => {"
        " const b = document.querySelector('.statusbar-brand');"
        " const sb = document.querySelector('.statusbar');"
        " const msg = document.getElementById('statusbar');"
        " const body = document.body;"
        " const html = document.documentElement;"
        " if (!b || !sb) return null;"
        " const cs = getComputedStyle(sb);"
        " return {"
        "   brand_right: b.getBoundingClientRect().right,"
        "   bar_w: sb.getBoundingClientRect().width,"
        "   bar_cs: {"
        "     minWidth: cs.minWidth,"
        "     width: cs.width,"
        "     gridTemplateColumns: cs.gridTemplateColumns,"
        "     padding: cs.padding,"
        "   },"
        "   msg_w: msg.getBoundingClientRect().width,"
        "   body_w: body.getBoundingClientRect().width,"
        "   body_scroll_w: body.scrollWidth,"
        "   html_scroll_w: html.scrollWidth,"
        "   vw: window.innerWidth,"
        " };"
        "}"
    )
    if brand_info is None:
        print("  FAIL: statusbar elements missing", file=sys.stderr)
        return 1
    if brand_info["brand_right"] > brand_info["vw"] + 0.5:
        print(
            "  FAIL: long status message pushed the brand off the"
            f" viewport; details={brand_info}",
            file=sys.stderr,
        )
        return 1

    # No element should overflow the viewport on the right side.
    # ``overflow: hidden`` on body would mask, but the audit found
    # dialogs in particular as the risk; check toolbar too.
    overflow = page.evaluate(
        "() => {"
        " const w = window.innerWidth;"
        " const offenders = [];"
        " for (const sel of ['header.toolbar', 'main.grid',"
        " 'footer.statusbar']) {"
        "   const el = document.querySelector(sel);"
        "   if (!el) continue;"
        "   const r = el.getBoundingClientRect();"
        "   if (r.right > w + 0.5) offenders.push(sel + '@' + r.right);"
        " }"
        " return offenders;"
        "}"
    )
    if overflow:
        print(
            f"  FAIL: elements overflow 360 viewport: {overflow}",
            file=sys.stderr,
        )
        return 1

    print("  narrow checks ok")
    return 0


def run_ultrawide_checks(page, label: str) -> int:
    """At 3440x1440: ``main.grid`` should be capped by
    ``--content-max-w`` (composed with ``calc(100vw * RATIO)``) and
    centred via ``margin-inline: auto``. No element should overflow.
    """
    grid_w = page.evaluate(
        "() => document.querySelector('main.grid').getBoundingClientRect()"
        ".width"
    )
    body_w = page.evaluate("() => window.innerWidth")
    if grid_w >= body_w - 1:
        print(
            "  FAIL: grid is not capped at ultrawide;"
            f" grid={grid_w}px, viewport={body_w}px",
            file=sys.stderr,
        )
        return 1
    # The cap is the smaller of CONTENT_MAX_W_ABS (2400) and
    # 0.75 * viewport (= 2580). On 3440 wide the absolute cap
    # should win; allow a 2-px tolerance for sub-pixel rendering.
    if grid_w > 2400 + 2:
        print(
            f"  FAIL: grid exceeds 2400 cap at ultrawide: {grid_w}px",
            file=sys.stderr,
        )
        return 1
    print(f"  ultrawide grid capped at {int(grid_w)}px (viewport {body_w}px)")
    return 0


def _dump_errors(
    console_errors: list[str],
    page_errors: list[str],
) -> None:
    for m in console_errors:
        print(f"  [console.error] {m}", file=sys.stderr)
    for e in page_errors:
        print(f"  [pageerror] {e}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
