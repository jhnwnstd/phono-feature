#!/usr/bin/env python3
"""Assemble the web app's deploy artifact in ``web/dist/``.

Reproducible, no GitHub-specific shell glue: runnable locally too via
``python web/scripts/build.py``. The output directory is what GitHub
Pages publishes verbatim.

Layout produced:

    web/dist/
    ├── index.html
    ├── style.css
    ├── main.js
    ├── api.py
    ├── engine/phonology_engine/
    │   ├── __init__.py
    │   ├── inventory.py
    │   ├── feature_engine.py
    │   ├── geometry.py
    │   └── segment_grouper.py
    ├── render/phonology_features/
    │   ├── __init__.py
    │   └── gui/
    │       ├── __init__.py
    │       ├── palette.py
    │       ├── constants.py
    │       └── analysis.py
    └── inventories/
        ├── english_features.json
        ├── general_features.json
        └── hayes_features.json

Both ``engine/`` and ``render/`` are COPIES of canonical sources
(packages/phonology-engine/ and app/src/phonology_features/gui/).
Mounted into Pyodide's FS at runtime and added to sys.path; no
wheel build, no micropip install. Faster cold boot, fewer build
dependencies (no need for the ``build`` package).
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

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"
DIST = WEB_DIR / "dist"
ENGINE_PKG = ROOT / "packages" / "phonology-engine"
DESKTOP_GUI = ROOT / "app" / "src" / "phonology_features" / "gui"
INVENTORIES = ROOT / "app" / "inventories"

# Files copied from the desktop GUI source. They have no module-level
# Qt imports (verified: detect_system_theme in palette.py wraps its
# Qt imports in try/except), so they run unchanged inside Pyodide.
RELAYED_SOURCES = [
    "palette.py",
    "constants.py",
    "analysis.py",
    "layout.py",
    "vowel_layout.py",
]




def clean_dist() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)


def copy_engine_sources() -> None:
    """Copy the engine package's source tree into the deploy.

    Previously this built a wheel and let ``micropip.install`` unpack
    it inside Pyodide. micropip is a pip-equivalent (dep resolution,
    METADATA parsing, version satisfaction, importer-cache
    invalidation) and we use none of that: the engine is one pure
    Python package with zero deps. Bypassing micropip and just
    writing the .py files to Pyodide's FS saves ~1s on cold boot.
    main.js mounts the directory below at /home/pyodide/engine and
    adds it to sys.path; the rest of the bridge code is unchanged.
    """
    print("Copying engine package source...")
    target_pkg = DIST / "engine" / "phonology_engine"
    if target_pkg.exists():
        shutil.rmtree(target_pkg)
    src_pkg = ENGINE_PKG / "src" / "phonology_engine"
    shutil.copytree(src_pkg, target_pkg)
    # Strip __pycache__ if the source tree happens to carry one.
    for pycache in target_pkg.rglob("__pycache__"):
        shutil.rmtree(pycache, ignore_errors=True)
    py_files = sorted(target_pkg.glob("*.py"))
    print(f"  {len(py_files)} .py files in engine/phonology_engine/")


def copy_static_assets() -> None:
    """Files JS/HTML refers to directly under the site root."""
    print("Copying static assets...")
    for name in ("index.html", "style.css", "main.js", "api.py"):
        shutil.copy(WEB_DIR / name, DIST / name)


def relay_renderer_sources() -> None:
    """Copy the desktop's pure-Python renderer files into the spot
    where api.py's imports expect to find them."""
    print("Relaying renderer sources from desktop GUI...")
    target = DIST / "render" / "phonology_features" / "gui"
    target.mkdir(parents=True, exist_ok=True)
    # Empty __init__.py stubs so Python sees real packages.
    (DIST / "render" / "phonology_features" / "__init__.py").write_text("")
    (target / "__init__.py").write_text("")
    for name in RELAYED_SOURCES:
        src = DESKTOP_GUI / name
        if not src.exists():
            raise RuntimeError(f"missing desktop source: {src}")
        shutil.copy(src, target / name)


def copy_inventories() -> None:
    """Bundle every inventory found in ``app/inventories/`` and emit
    a manifest. Both are read by main.js at runtime; adding a new
    inventory to ``app/inventories/`` makes it appear in the web app
    on the next build with zero web/-side edits.

    Inventories that ``.gitignore`` excludes are SKIPPED. This keeps
    local-only test files (like ``blevins_features.json``) out of
    the deployed web app, so local builds match what CI ships even
    when the user has extra files on disk.
    """
    print("Copying bundled inventories...")
    out = DIST / "inventories"
    out.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, str]] = []
    skipped: list[str] = []
    for inv in sorted(INVENTORIES.glob("*.json")):
        if _is_gitignored(inv):
            skipped.append(inv.name)
            continue
        shutil.copy(inv, out / inv.name)
        manifest.append(
            {
                "file": f"inventories/{inv.name}",
                "label": _inventory_label(inv),
            }
        )
    (DIST / "inventories.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False)
    )
    print(f"  manifest: {len(manifest)} inventories")
    if skipped:
        print(f"  skipped (gitignored): {', '.join(skipped)}")


def _is_gitignored(path: Path) -> bool:
    """Return True if git would ignore ``path`` (per the repo's
    .gitignore / .git/info/exclude). Returns False if git isn't
    available or this isn't a git checkout, which is the right
    default for CI environments and tarball installs: ship
    everything, since there's no .gitignore to consult.
    """
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(path)],
        cwd=ROOT,
        capture_output=True,
    )
    # exit 0  = path IS ignored
    # exit 1  = path is NOT ignored
    # other   = git error (not a repo, git missing, etc.) -> treat as not ignored
    return result.returncode == 0


def _inventory_label(path: Path) -> str:
    """Display label for the dropdown. Prefers ``metadata.name`` from
    the JSON itself; falls back to a Title-Cased filename if missing.
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
    """Emit ``theme.css`` from ``palette.LIGHT`` and ``palette.DARK``
    so the same color values drive both desktop chrome and web
    CSS variables. Hand-edited ``style.css`` references ``var(--*)``;
    edits to palette.py propagate to both targets on the next build.
    """
    print("Generating theme.css from palette.py...")
    palette = _load_palette_module()
    lines = [
        "/* AUTO-GENERATED by web/scripts/build.py from",
        " * app/src/phonology_features/gui/palette.py. Do not edit",
        " * by hand: regenerate by re-running the build script. The",
        " * canonical color values live in palette.py and drive both",
        " * the desktop chrome (via Qt stylesheets) and the web app",
        " * (via these CSS custom properties). */",
        ":root {",
    ]
    for key, value in palette.LIGHT.items():
        lines.append(f"  --{_css_var_name(key)}: {value};")
    lines.append("}")
    lines.append("")
    lines.append('html[data-theme="dark"] {')
    for key, value in palette.DARK.items():
        lines.append(f"  --{_css_var_name(key)}: {value};")
    lines.append("}")
    lines.append("")
    (DIST / "theme.css").write_text("\n".join(lines))
    print(f"  {len(palette.LIGHT)} tokens per theme")


def _css_var_name(palette_key: str) -> str:
    """Map a palette dict key (``tag_blue_text``) to a CSS variable
    name (``tag-blue-text``). Underscores to hyphens; lowercased."""
    return palette_key.replace("_", "-").lower()


def _load_palette_module():
    """Import palette.py without bringing in the rest of the
    desktop GUI package. We can't do a normal ``import`` because
    ``phonology_features.gui.palette`` needs the desktop's package
    to be on the path, and the build runs from outside it.
    """
    palette_path = DESKTOP_GUI / "palette.py"
    spec = importlib.util.spec_from_file_location("_palette", palette_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {palette_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_python_bundle() -> None:
    """Pack every Python source (engine + relayed renderer + api.py)
    into a single ``python_bundle.zip`` that gets mounted onto
    Pyodide's ``sys.path`` via zipimport.

    Why a zip (vs. the JSON map we previously shipped):
    * One binary fetch + one writeFile, instead of fetch+JSON.parse
      + N writeFiles. Less JS string churn, no per-file FS syscall
      loop on the Pyodide side.
    * Python imports lazily from the zip via zipimport, so only the
      modules api.py actually imports get decoded.
    * Compressed-on-wire even without server gzip (zip uses deflate
      per-file).

    Layout inside the zip (packages flattened to root so zipimport
    can find them with a single sys.path entry):

        phonology_engine/__init__.py
        phonology_engine/inventory.py
        ...
        phonology_features/__init__.py
        phonology_features/gui/__init__.py
        ...
        api.py
    """
    print("Bundling Python sources into zip...")
    out = DIST / "python_bundle.zip"
    entries: list[tuple[str, Path]] = []
    # Engine package: dist/engine/phonology_engine/*  ->  phonology_engine/*
    for path in sorted((DIST / "engine").rglob("*.py")):
        zip_path = path.relative_to(DIST / "engine").as_posix()
        entries.append((zip_path, path))
    # Renderer package: dist/render/phonology_features/*  ->  phonology_features/*
    for path in sorted((DIST / "render").rglob("*.py")):
        zip_path = path.relative_to(DIST / "render").as_posix()
        entries.append((zip_path, path))
    # Bridge module: dist/api.py  ->  api.py
    entries.append(("api.py", DIST / "api.py"))

    # ZIP_DEFLATED gives us ~40-50% compression on Python source
    # without needing the server to gzip. ZIP_DEFLATED is in the
    # stdlib (uses zlib).
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for zip_path, src in entries:
            zf.write(src, arcname=zip_path)

    # Don't ship the loose copies once they're in the zip; the engine/
    # and render/ trees and the loose api.py become dead weight in
    # the deploy. hash_assets() also unlinks api.py; this is the
    # rest.
    shutil.rmtree(DIST / "engine", ignore_errors=True)
    shutil.rmtree(DIST / "render", ignore_errors=True)

    raw = sum(p.stat().st_size for _, p in entries if p.exists())
    print(f"  {len(entries)} files, {out.stat().st_size} bytes zip ({raw} raw)")


def write_bootstrap() -> None:
    """Precompute the default inventory's render-ready summary so
    the web app can paint segments + features on first paint,
    before Pyodide finishes loading.

    Runs as a subprocess: this script's own process doesn't import
    the engine or renderer, and we don't want to pollute its
    import state. Falls back gracefully (build succeeds without an
    inlined bootstrap; main.js renders via the bridge instead) if
    the precompute can't run.
    """
    print("Precomputing default inventory bootstrap...")
    default_inv = INVENTORIES / "english_features.json"
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
        # Non-fatal: main.js still has the bridge-driven path as a
        # fallback. We just lose the perceived-boot win.
        print("  WARNING: bootstrap precompute failed; "
              "main.js will fall back to bridge-driven render")
        print(f"  stderr: {result.stderr.strip()[:500]}")
        return
    out = DIST / "bootstrap.json"
    out.write_text(result.stdout, encoding="utf-8")
    print(f"  bootstrap.json: {out.stat().st_size} bytes")


def _hashed_name(path: Path, hash_len: int = 10) -> str:
    """Stable content-hash filename: ``name.<hex>.ext``."""
    h = hashlib.sha256(path.read_bytes()).hexdigest()[:hash_len]
    return f"{path.stem}.{h}{path.suffix}"


def hash_assets() -> None:
    """Rename build outputs to content-hashed filenames so any change
    gets a new URL. GitHub Pages caches assets at ``max-age=600`` with
    no header override, so cache-busting has to live in the URL.

    The only unhashed file is ``index.html`` (the browser fetches it
    by URL). It carries hashed references to every other asset, plus
    an inline ``application/json`` script with the runtime asset
    map main.js needs to find the (hashed) python_bundle and
    inventories manifest.

    Order matters: hash files BEFORE the files that reference them.
    Inventories first (since inventories.json names them), then the
    inventories manifest, then python_bundle and CSS, finally main.js
    and index.html.
    """
    print("Hashing assets for cache-busting...")
    runtime_map: dict[str, str] = {}
    full_map: dict[str, str] = {}

    # 1. Individual inventory JSON files. Update the manifest's
    #    ``file`` field to point at the new hashed name before we
    #    rewrite the manifest.
    inv_manifest_path = DIST / "inventories.json"
    inv_manifest = json.loads(inv_manifest_path.read_text(encoding="utf-8"))
    for entry in inv_manifest:
        old = DIST / entry["file"]
        new_name = _hashed_name(old)
        old.rename(old.with_name(new_name))
        entry["file"] = f"inventories/{new_name}"
        full_map[Path(old).name] = new_name

    # 2. The manifest itself: rewrite with hashed inventory paths,
    #    then hash the manifest file.
    inv_manifest_path.write_text(
        json.dumps(inv_manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    new_inv_manifest = _hashed_name(inv_manifest_path)
    inv_manifest_path.rename(DIST / new_inv_manifest)
    runtime_map["inventories_manifest"] = new_inv_manifest
    full_map["inventories.json"] = new_inv_manifest

    # 3. python_bundle.zip (api.py is bundled inside; the loose
    #    api.py copy was only needed by write_python_bundle and is
    #    dead weight now).
    (DIST / "api.py").unlink(missing_ok=True)
    py_bundle = DIST / "python_bundle.zip"
    new_py_bundle = _hashed_name(py_bundle)
    py_bundle.rename(DIST / new_py_bundle)
    runtime_map["python_bundle"] = new_py_bundle
    full_map["python_bundle.zip"] = new_py_bundle

    # 4. CSS files referenced from index.html.
    for css in ("theme.css", "style.css"):
        path = DIST / css
        new_name = _hashed_name(path)
        path.rename(DIST / new_name)
        full_map[css] = new_name

    # 5. main.js (last among renamed assets so its hash captures the
    #    final shipped JS).
    main_path = DIST / "main.js"
    new_main = _hashed_name(main_path)
    main_path.rename(DIST / new_main)
    full_map["main.js"] = new_main

    # 6. Rewrite index.html.
    index_path = DIST / "index.html"
    html = index_path.read_text(encoding="utf-8")
    html = html.replace(
        '<link rel="stylesheet" href="theme.css">',
        f'<link rel="stylesheet" href="{full_map["theme.css"]}">',
    )
    html = html.replace(
        '<link rel="stylesheet" href="style.css">',
        f'<link rel="stylesheet" href="{full_map["style.css"]}">',
    )
    # Inline JSON block so main.js can read the runtime asset map
    # without an extra HTTP fetch. ``type="application/json"`` is
    # data, not script, so CSP ``script-src 'self'`` still applies
    # without needing 'unsafe-inline'.
    runtime_block = (
        '<script id="asset-manifest" type="application/json">'
        + json.dumps(runtime_map, separators=(",", ":"))
        + "</script>"
    )
    # Inline the precomputed default-inventory bootstrap so main.js
    # can paint the segments grid + features panel on first paint
    # (before Pyodide loads). Best-effort: if write_bootstrap
    # couldn't run the block is absent and main.js falls back to
    # the bridge-driven render path.
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
            f'{runtime_block}\n'
            + (f'{bootstrap_block}\n' if bootstrap_block else "")
            + f'<script type="module" src="{full_map["main.js"]}"></script>'
        ),
    )
    index_path.write_text(html, encoding="utf-8")

    # 7. Full asset manifest for diagnostics, CI, and the smoke test.
    (DIST / "asset-manifest.json").write_text(
        json.dumps({"schema": 1, "assets": full_map}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  {len(full_map)} assets hashed")


def write_service_worker() -> None:
    """Stamp the service worker template with this build's precache
    list + a build-id derived from those file contents.

    The SW lives at the deploy root with a STABLE URL (sw.js, no
    hash) because browsers identify service workers by URL. The
    CONTENT changes per build (new precache list + new BUILD_ID),
    which is what triggers the browser to detect an update.

    Precaches every locally-shipped file (index.html + everything
    that was just hashed). Pyodide CDN assets are NOT precached --
    a CDN flake during install would brick the SW. They're cached
    on first successful fetch instead.
    """
    print("Writing service worker...")
    template = (WEB_DIR / "sw.js").read_text(encoding="utf-8")

    # Precache every locally-served file under dist/, except the
    # SW itself and the Jekyll marker.
    SKIP_NAMES = {"sw.js", ".nojekyll"}
    precache = ["./", "./index.html"]
    for path in sorted(DIST.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(DIST).as_posix()
        if rel in SKIP_NAMES:
            continue
        precache.append(f"./{rel}")
    # Dedupe (./ and ./index.html may collide if hashing added more).
    precache = sorted(set(precache))

    # Build ID = hash of the precache list. Any change to the
    # shipped file set bumps the ID, which renames the cache and
    # triggers the activate handler's old-cache cleanup.
    build_id = hashlib.sha256(
        json.dumps(precache).encode()
    ).hexdigest()[:10]

    sw_text = template.replace('"__BUILD_ID__"', json.dumps(build_id))
    sw_text = sw_text.replace("__PRECACHE_LIST__", json.dumps(precache))
    (DIST / "sw.js").write_text(sw_text, encoding="utf-8")
    print(f"  build_id={build_id}, {len(precache)} files precached")


def write_pages_no_jekyll() -> None:
    """Tell GitHub Pages to serve the directory as-is. Without this,
    files starting with ``_`` are filtered out by the default Jekyll
    processing; Pyodide's runtime files use that prefix."""
    (DIST / ".nojekyll").write_text("")


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    clean_dist()
    copy_engine_sources()
    copy_static_assets()
    relay_renderer_sources()
    generate_theme_css()
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
