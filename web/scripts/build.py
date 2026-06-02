#!/usr/bin/env python3
"""Build the web app deploy artifact in ``web/dist/``.

Runnable locally (``python web/scripts/build.py``) and from the
Pages workflow. Output is what GitHub Pages publishes verbatim.

Pipeline:

1. ``copy_engine_sources``       engine package -> dist/engine/
2. ``copy_static_assets``        web/{index.html,style.css,main.js,
                                  api.py} -> dist/
3. ``relay_renderer_sources``    desktop GUI relayed sources ->
                                  dist/render/
4. ``generate_theme_css``        palette.py -> dist/theme.css
5. ``generate_layout_css``       layout.py -> dist/layout.css
6. ``copy_inventories``          app/inventories/*.json -> dist/
                                  inventories/ + dist/inventories.json
7. ``write_python_bundle``       dist/{engine,render}/* + dist/api.py
                                  -> dist/python_bundle.zip
                                  (removes the loose copies)
8. ``write_bootstrap``           default inventory's render summary
                                  -> dist/bootstrap.json
9. ``hash_assets``               content-hash filenames + asset
                                  manifest + index.html rewrite
10. ``write_service_worker``     sw.js template -> dist/sw.js
11. ``write_pages_no_jekyll``    dist/.nojekyll

Both ``engine/`` and ``render/`` are copies of canonical sources
(``packages/phonology-engine/`` and ``app/src/phonology_features/
gui/``). Mounted into Pyodide's FS at runtime via zipimport; no
wheel build, no micropip install.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"
DIST = WEB_DIR / "dist"
ENGINE_PKG = ROOT / "packages" / "phonology-engine"
DESKTOP_GUI = ROOT / "app" / "src" / "phonology_features" / "gui"
INVENTORIES = ROOT / "app" / "inventories"

# Desktop GUI files relayed verbatim into the web bundle. Each one
# is pure Python with no module-level Qt imports (palette.py wraps
# its Qt imports in a function), so they run unchanged in Pyodide.
RELAYED_SOURCES = [
    "palette.py",
    "constants.py",
    "analysis.py",
    "view_models.py",
    "mode_logic.py",
    "layout.py",
    "vowel_layout.py",
    "inventory_setup.py",
    "grid_logic.py",
]


def clean_dist() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)


def copy_engine_sources() -> None:
    """Copy the engine package's .py tree into ``dist/engine/``."""
    print("Copying engine package source...")
    target_pkg = DIST / "engine" / "phonology_engine"
    if target_pkg.exists():
        shutil.rmtree(target_pkg)
    src_pkg = ENGINE_PKG / "src" / "phonology_engine"
    shutil.copytree(src_pkg, target_pkg)
    for pycache in target_pkg.rglob("__pycache__"):
        shutil.rmtree(pycache, ignore_errors=True)
    py_files = sorted(target_pkg.glob("*.py"))
    print(f"  {len(py_files)} .py files in engine/phonology_engine/")


def copy_static_assets() -> None:
    """Copy index.html, CSS, JS, and api.py to the dist root."""
    print("Copying static assets...")
    for name in ("index.html", "style.css", "main.js", "api.py"):
        shutil.copy(WEB_DIR / name, DIST / name)


def relay_renderer_sources() -> None:
    """Copy desktop renderer files into the package path api.py
    imports from at runtime.

    The relayed modules live in ``app/.../gui/shared/`` on disk and
    are imported in the web as ``phonology_features.gui.shared.X``,
    so we mirror the ``shared/`` subdir into the dist tree.
    """
    print("Relaying renderer sources from desktop GUI...")
    target = DIST / "render" / "phonology_features" / "gui"
    shared = target / "shared"
    shared.mkdir(parents=True, exist_ok=True)
    (DIST / "render" / "phonology_features" / "__init__.py").write_text("")
    (target / "__init__.py").write_text("")
    (shared / "__init__.py").write_text("")
    src_shared = DESKTOP_GUI / "shared"
    for name in RELAYED_SOURCES:
        src = src_shared / name
        if not src.exists():
            raise RuntimeError(f"missing desktop source: {src}")
        shutil.copy(src, shared / name)


def copy_inventories() -> None:
    """Bundle every inventory found in ``app/inventories/`` and
    emit a manifest. Both are read by main.js at runtime; adding a
    new JSON to ``app/inventories/`` makes it appear in the dropdown
    on the next build.

    Files ``.gitignore`` excludes are skipped so local-only test
    inventories don't leak into the deploy when CI builds.
    """
    print("Copying bundled inventories...")
    out = DIST / "inventories"
    out.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, str]] = []
    skipped_private: list[str] = []
    skipped_gitignored: list[str] = []
    for inv in sorted(INVENTORIES.glob("*.json")):
        # Underscore-prefixed siblings (e.g. ``_schema.json``) are
        # metadata that lives alongside the inventories but isn't
        # itself an inventory; the desktop dropdown applies the same
        # filter in ``InventoryDirController``.
        if inv.name.startswith("_"):
            skipped_private.append(inv.name)
            continue
        if _is_gitignored(inv):
            skipped_gitignored.append(inv.name)
            continue
        shutil.copy(inv, out / inv.name)
        manifest.append(
            {
                "file": f"inventories/{inv.name}",
                "label": _inventory_label(inv),
            }
        )
    (DIST / "inventories.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
    )
    print(f"  manifest: {len(manifest)} inventories")
    if skipped_private:
        print(f"  skipped (private): {', '.join(skipped_private)}")
    if skipped_gitignored:
        print(f"  skipped (gitignored): {', '.join(skipped_gitignored)}")


def _is_gitignored(path: Path) -> bool:
    """Whether git would ignore ``path``. Returns False if git is
    unavailable or this isn't a checkout, which is the right
    default for CI / tarball installs: ship everything.
    """
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(path)],
        cwd=ROOT,
        capture_output=True,
    )
    # 0 = ignored, 1 = not ignored, anything else = git error.
    return result.returncode == 0


def _inventory_label(path: Path) -> str:
    """Display label for the dropdown. Prefers ``metadata.name``
    from the JSON; falls back to a title-cased filename.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        meta = raw.get("metadata", {})
        name = meta.get("name") or raw.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    except (json.JSONDecodeError, OSError):
        pass
    stem = path.stem.removesuffix("_features").replace("_", " ")
    return stem.title()


def generate_theme_css() -> None:
    """Emit ``theme.css`` from palette.LIGHT / palette.DARK / COLORBLIND_*
    so the same color values drive both desktop chrome and web CSS
    variables. Edits to palette.py propagate to both on the next build.

    Two perpendicular axes drive variant selection:
      * ``html[data-theme="dark"]`` — dark theme overrides.
      * ``html[data-cb="on"]``      — colorblind-friendly palette.
    The colorblind-dark variant is keyed on both attributes so the
    most-specific selector wins regardless of attribute order.
    """
    print("Generating theme.css from palette.py...")
    palette = _load_palette_module()

    def block(selector: str, table: dict[str, str]) -> list[str]:
        out = [f"{selector} {{"]
        for key, value in table.items():
            out.append(f"  --{_css_var_name(key)}: {value};")
        out.append("}")
        return out

    lines: list[str] = [
        "/* AUTO-GENERATED from app/src/phonology_features/gui/shared/palette.py",
        " * by web/scripts/build.py. Do not edit by hand. */",
    ]
    lines.extend(block(":root", palette.LIGHT))
    lines.append("")
    lines.extend(block('html[data-theme="dark"]', palette.DARK))
    lines.append("")
    lines.extend(block('html[data-cb="on"]', palette.COLORBLIND_LIGHT))
    lines.append("")
    lines.extend(
        block(
            'html[data-cb="on"][data-theme="dark"]',
            palette.COLORBLIND_DARK,
        )
    )
    lines.append("")
    (DIST / "theme.css").write_text("\n".join(lines))
    print(
        f"  {len(palette.LIGHT)} standard tokens, "
        f"{len(palette.COLORBLIND_LIGHT)} colorblind tokens per theme"
    )


def _css_var_name(palette_key: str) -> str:
    """``tag_blue_text`` -> ``tag-blue-text``."""
    return palette_key.replace("_", "-").lower()


def _load_palette_module() -> ModuleType:
    """Import ``palette.py`` directly without bringing in the rest
    of the desktop GUI package (the build runs outside the package
    layout, so a normal import would fail).
    """
    palette_path = DESKTOP_GUI / "shared" / "palette.py"
    spec = importlib.util.spec_from_file_location("_palette", palette_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {palette_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_layout_module() -> ModuleType:
    """Same trick as ``_load_palette_module`` for ``layout.py``. Used
    by ``generate_layout_css`` to bake the adaptive-layout constants
    into a CSS custom-property file the stylesheet then references.
    """
    layout_path = DESKTOP_GUI / "shared" / "layout.py"
    spec = importlib.util.spec_from_file_location("_layout", layout_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {layout_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_limits_payload() -> dict[str, int]:
    """Bake the engine's hard caps into a flat dict the web JS
    consumes pre-bridge.

    The web upload pre-check at ``main.js`` needs the same
    ``MAX_INVENTORY_FILE_BYTES`` the engine enforces post-bridge
    (otherwise a 20 MB file would pass the JS gate then fail in
    Pyodide with a confusing generic error). Same drift-prevention
    pattern as the status-text bake: emit once from Python, read
    once in JS, no hand-maintained literal.

    Loads ``limits.py`` directly from the engine source tree (same
    pattern as ``_load_palette_module``/``_load_layout_module``) so
    the build script doesn't depend on the engine being installed
    as a package. CI runs ``python web/scripts/build.py`` against a
    bare interpreter; only the standard library is available.
    """
    limits_path = ENGINE_PKG / "src" / "phonology_engine" / "limits.py"
    spec = importlib.util.spec_from_file_location("_limits", limits_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {limits_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {
        "max_features": module.MAX_FEATURES,
        "max_segments": module.MAX_SEGMENTS,
        "max_name_length": module.MAX_NAME_LENGTH,
        "max_inventory_file_bytes": module.MAX_INVENTORY_FILE_BYTES,
    }


def _build_status_text_payload() -> dict[str, str]:
    """Bake the status-bar messages for every :py:class:`Mode` from
    ``mode_logic.mode_status_text`` into a flat dict.

    The web app's pre-bridge fallback (and the post-bridge cache)
    both consume this payload, so the Python helper is the single
    source of truth and the JS literal ``STATUS_TEXT`` it replaces
    can no longer drift.

    Registers the module in ``sys.modules`` before iterating
    ``Mode`` because :py:class:`enum.StrEnum`'s iteration helpers
    look up the defining module by name and would otherwise hit
    ``AttributeError`` on the temporary spec-loaded module.
    """
    import sys

    mode_logic_path = DESKTOP_GUI / "shared" / "mode_logic.py"
    module_name = "_build_mode_logic"
    spec = importlib.util.spec_from_file_location(module_name, mode_logic_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {mode_logic_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        payload: dict[str, str] = {
            str(member): module.mode_status_text(member, has_engine=True)
            for member in module.Mode
        }
        # ``no_engine`` is the message shown before any inventory
        # loads; the bridge isn't even attached yet so the web
        # definitely needs it baked at build time. Keyed separately
        # so JS reads it without ambiguity with the per-mode keys.
        payload["no_engine"] = module.mode_status_text(
            module.Mode.SEG_TO_FEAT, has_engine=False
        )
        return payload
    finally:
        sys.modules.pop(module_name, None)


def generate_layout_css() -> None:
    """Emit ``layout.css`` from the constants in
    ``phonology_features.gui.shared.layout`` so the same numbers drive both
    the desktop's Qt splitter / chart sizing and the web's CSS grid.
    Edits to the shared constants propagate to both on the next build.
    Mirrors the ``generate_theme_css`` pattern.
    """
    print("Generating layout.css from layout.py...")
    mod = _load_layout_module()
    lines: list[str] = [
        "/* AUTO-GENERATED from app/src/phonology_features/gui/shared/layout.py",
        " * by web/scripts/build.py. Do not edit by hand. */",
        ":root {",
        # Pane-width thresholds.
        f"  --seg-min-w: {mod.SEG_MIN_W}px;",
        f"  --feat-min-w: {mod.FEAT_MIN_W}px;",
        f"  --min-feat-card-w: {mod.MIN_FEAT_CARD_W}px;",
        f"  --vowel-natural-w: {mod.VOWEL_NATURAL_W}px;",
        f"  --vowel-stack-w: {mod.VOWEL_STACK_W}px;",
        f"  --vowel-pair-gap: {mod.VOWEL_PAIR_GAP_PX}px;",
        f"  --vowel-pair-separator: {mod.VOWEL_PAIR_SEPARATOR_PX}px;",
        f"  --collapse-w: {mod.COLLAPSE_W}px;",
        # Per-row / per-card heights — single source of truth for
        # consonant-grid and feature-card height math in the web.
        f"  --seg-btn-h: {mod.SEG_BTN_H}px;",
        f"  --seg-btn-row-h: {mod.SEG_BTN_ROW_H}px;",
        f"  --seg-group-header-h: {mod.SEG_GROUP_HEADER_H}px;",
        f"  --feat-row-h: {mod.FEAT_ROW_H}px;",
        f"  --feat-card-chrome-h: {mod.FEAT_CARD_CHROME_H}px;",
        f"  --panel-chrome-v: {mod.PANEL_CHROME_V}px;",
        f"  --min-top-pane-h: {mod.MIN_TOP_PANE_H}px;",
        # Analysis-pane sizing. Both UIs consume these via CSS vars
        # so the desktop's Qt math (``layout.analysis_expand_target``,
        # ``HARD_MIN_ANALYSIS_H``) and the web's ``.analysis`` /
        # ``.analysis.expanded`` rules can never drift.
        f"  --min-analysis-h: {mod.MIN_ANALYSIS_H}px;",
        f"  --analysis-expand-ratio: {mod.ANALYSIS_EXPAND_RATIO};",
        # Hard cap on overall content width (ultrawide). Above this
        # pixel ceiling ``main.grid`` stops growing and centres via
        # ``margin-inline: auto``; below it the grid fills the
        # available width normally.
        f"  --content-max-w: {mod.CONTENT_MAX_W_ABS}px;",
        "}",
        "",
    ]
    (DIST / "layout.css").write_text("\n".join(lines))
    print(f"  {len(lines) - 4} layout tokens")


def write_python_bundle() -> None:
    """Pack engine + relayed renderer + api.py into
    ``python_bundle.zip`` and mount via zipimport at runtime.

    One binary fetch + one ``writeFile`` instead of fetch +
    JSON.parse + N writeFiles. Compressed on the wire via
    ZIP_DEFLATED even without server gzip. Loose copies of the
    sources are removed after bundling.

    Zip layout (packages flattened to root so one sys.path entry
    suffices)::

        phonology_engine/__init__.py
        phonology_engine/inventory.py
        ...
        phonology_features/gui/shared/analysis.py
        ...
        api.py
    """
    print("Bundling Python sources into zip...")
    out = DIST / "python_bundle.zip"
    entries: list[tuple[str, Path]] = []
    for path in sorted((DIST / "engine").rglob("*.py")):
        entries.append((path.relative_to(DIST / "engine").as_posix(), path))
    for path in sorted((DIST / "render").rglob("*.py")):
        entries.append((path.relative_to(DIST / "render").as_posix(), path))
    entries.append(("api.py", DIST / "api.py"))

    with zipfile.ZipFile(
        out,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as zf:
        for zip_path, src in entries:
            zf.write(src, arcname=zip_path)

    shutil.rmtree(DIST / "engine", ignore_errors=True)
    shutil.rmtree(DIST / "render", ignore_errors=True)
    raw = sum(p.stat().st_size for _, p in entries if p.exists())
    print(
        f"  {len(entries)} files, {out.stat().st_size} bytes zip ({raw} raw)"
    )


def write_bootstrap() -> None:
    """Precompute the default inventory's render summary so the web
    app can paint its initial UI before Pyodide finishes loading.

    Runs in a subprocess to isolate the import side effects. Best-
    effort: a failed precompute logs a warning and the build
    continues; main.js falls back to the bridge-driven render path.
    """
    print("Precomputing default inventory bootstrap...")
    default_inv = INVENTORIES / "general_features.json"
    if not default_inv.exists():
        print(f"  skipped: no default inventory at {default_inv}")
        return
    label = _inventory_label(default_inv)
    code = (
        "import sys, json\n"
        f"sys.path.insert(0, {str(ENGINE_PKG / 'src')!r})\n"
        f"sys.path.insert(0, {str(ROOT / 'app' / 'src')!r})\n"
        f"sys.path.insert(0, {str(WEB_DIR)!r})\n"
        "import api\n"
        f"text = open({str(default_inv)!r}, encoding='utf-8-sig').read()\n"
        f"summary = api.load_inventory_json(text, {label!r})\n"
        "sys.stdout.write(json.dumps(summary, ensure_ascii=False))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            "  WARNING: bootstrap precompute failed; "
            "main.js will fall back to bridge-driven render",
        )
        print(f"  stderr: {result.stderr.strip()[:500]}")
        return
    out = DIST / "bootstrap.json"
    out.write_text(result.stdout, encoding="utf-8")
    print(f"  bootstrap.json: {out.stat().st_size} bytes")


def _hashed_name(path: Path, hash_len: int = 10) -> str:
    """``name.ext`` -> ``name.<hex>.ext``."""
    h = hashlib.sha256(path.read_bytes()).hexdigest()[:hash_len]
    return f"{path.stem}.{h}{path.suffix}"


def hash_assets() -> None:
    """Rename build outputs to content-hashed filenames and rewrite
    references so any change gets a fresh URL.

    GitHub Pages caches assets at ``max-age=600`` with no header
    override, so cache-busting has to live in the URL itself. The
    only unhashed file is ``index.html`` (the browser fetches it
    by URL); it carries hashed references to everything else plus
    an inline ``application/json`` block (``id="asset-manifest"``)
    that maps logical names to hashed URLs for main.js to read.

    Order: hash files before the files that reference them
    (inventories before the inventory manifest, etc.).
    """
    print("Hashing assets for cache-busting...")
    runtime_map: dict[str, str] = {}
    full_map: dict[str, str] = {}

    # 1. Individual inventory JSON files. Rewrite the manifest's
    #    ``file`` field to the hashed names before hashing it.
    inv_manifest_path = DIST / "inventories.json"
    inv_manifest = json.loads(inv_manifest_path.read_text(encoding="utf-8"))
    for entry in inv_manifest:
        old = DIST / entry["file"]
        new_name = _hashed_name(old)
        old.rename(old.with_name(new_name))
        entry["file"] = f"inventories/{new_name}"
        full_map[Path(old).name] = new_name

    # 2. The inventory manifest.
    inv_manifest_path.write_text(
        json.dumps(inv_manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    new_inv_manifest = _hashed_name(inv_manifest_path)
    inv_manifest_path.rename(DIST / new_inv_manifest)
    runtime_map["inventories_manifest"] = new_inv_manifest
    full_map["inventories.json"] = new_inv_manifest

    # 3. python_bundle.zip (the loose api.py is inside it already).
    (DIST / "api.py").unlink(missing_ok=True)
    py_bundle = DIST / "python_bundle.zip"
    new_py_bundle = _hashed_name(py_bundle)
    py_bundle.rename(DIST / new_py_bundle)
    runtime_map["python_bundle"] = new_py_bundle
    full_map["python_bundle.zip"] = new_py_bundle

    # 4. CSS files referenced from index.html.
    for css in ("theme.css", "layout.css", "style.css"):
        path = DIST / css
        new_name = _hashed_name(path)
        path.rename(DIST / new_name)
        full_map[css] = new_name

    # 5. main.js (last so its hash captures the final shipped JS).
    main_path = DIST / "main.js"
    new_main = _hashed_name(main_path)
    main_path.rename(DIST / new_main)
    full_map["main.js"] = new_main

    # 6. Rewrite index.html with hashed references and inline
    #    asset-manifest + bootstrap blocks.
    index_path = DIST / "index.html"
    html = index_path.read_text(encoding="utf-8")
    html = html.replace(
        '<link rel="stylesheet" href="theme.css">',
        f'<link rel="stylesheet" href="{full_map["theme.css"]}">',
    )
    html = html.replace(
        '<link rel="stylesheet" href="layout.css">',
        f'<link rel="stylesheet" href="{full_map["layout.css"]}">',
    )
    html = html.replace(
        '<link rel="stylesheet" href="style.css">',
        f'<link rel="stylesheet" href="{full_map["style.css"]}">',
    )
    # ``type="application/json"`` is non-executable data, so CSP
    # ``script-src 'self'`` applies without 'unsafe-inline'.
    runtime_block = (
        '<script id="asset-manifest" type="application/json">'
        + json.dumps(runtime_map, separators=(",", ":"))
        + "</script>"
    )
    # Bake the mode status-bar messages from ``mode_logic.py``
    # straight into the HTML so the JS pre-bridge fallback reads
    # the canonical Python output instead of carrying a literal
    # that can drift.
    status_block = (
        '<script id="status-text" type="application/json">'
        + json.dumps(
            _build_status_text_payload(),
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "</script>"
    )
    # Same inline-JSON pattern as the status block. JS reads
    # ``LIMITS.max_inventory_file_bytes`` for the upload pre-check
    # so the cap matches the engine's post-check at every build.
    limits_block = (
        '<script id="limits" type="application/json">'
        + json.dumps(_build_limits_payload(), separators=(",", ":"))
        + "</script>"
    )
    bootstrap_block = ""
    bootstrap_path = DIST / "bootstrap.json"
    if bootstrap_path.exists():
        compact = json.dumps(
            json.loads(bootstrap_path.read_text(encoding="utf-8")),
            separators=(",", ":"),
            ensure_ascii=False,
        )
        bootstrap_block = (
            '<script id="bootstrap" type="application/json">'
            + compact
            + "</script>"
        )
        new_bootstrap = _hashed_name(bootstrap_path)
        bootstrap_path.rename(DIST / new_bootstrap)
        full_map["bootstrap.json"] = new_bootstrap
    html = html.replace(
        '<script type="module" src="main.js"></script>',
        (
            f"{runtime_block}\n"
            + f"{status_block}\n"
            + f"{limits_block}\n"
            + (f"{bootstrap_block}\n" if bootstrap_block else "")
            + f'<script type="module" src="{full_map["main.js"]}"></script>'
        ),
    )
    index_path.write_text(html, encoding="utf-8")

    # 7. Standalone asset manifest for diagnostics + CI checks.
    (DIST / "asset-manifest.json").write_text(
        json.dumps(
            {"schema": 1, "assets": full_map},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"  {len(full_map)} assets hashed")


def write_service_worker() -> None:
    """Stamp the service worker template with this build's
    precache list and a build-id derived from those file contents.

    The SW lives at a stable URL (``sw.js``, unhashed) because
    browsers identify service workers by URL. Its content changes
    per build, triggering update detection. CDN-hosted Pyodide
    assets are NOT precached: a transient CDN failure during
    install would brick the SW. They're cached on first fetch.
    """
    print("Writing service worker...")
    template = (WEB_DIR / "sw.js").read_text(encoding="utf-8")

    SKIP_NAMES = {"sw.js", ".nojekyll"}
    precache = ["./", "./index.html"]
    for path in sorted(DIST.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(DIST).as_posix()
        if rel in SKIP_NAMES:
            continue
        precache.append(f"./{rel}")
    precache = sorted(set(precache))

    # Hash the precache list: any change to the shipped file set
    # bumps the build id, which renames the cache and triggers the
    # SW's activate-time old-cache cleanup.
    build_id = hashlib.sha256(
        json.dumps(precache).encode(),
    ).hexdigest()[:10]

    sw_text = template.replace('"__BUILD_ID__"', json.dumps(build_id))
    sw_text = sw_text.replace("__PRECACHE_LIST__", json.dumps(precache))
    (DIST / "sw.js").write_text(sw_text, encoding="utf-8")
    print(f"  build_id={build_id}, {len(precache)} files precached")


def write_pages_no_jekyll() -> None:
    """Disable GitHub Pages' default Jekyll processing.

    Without this, files starting with ``_`` are filtered out;
    Pyodide's runtime files use that prefix.
    """
    (DIST / ".nojekyll").write_text("")


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    clean_dist()
    copy_engine_sources()
    copy_static_assets()
    relay_renderer_sources()
    generate_theme_css()
    generate_layout_css()
    copy_inventories()
    write_python_bundle()
    write_bootstrap()
    hash_assets()
    write_service_worker()
    write_pages_no_jekyll()

    print(f"\nBuild complete: {DIST}")
    print("Serve locally with:")
    print(f"  cd {DIST} && python -m http.server 8000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
