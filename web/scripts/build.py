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
5. ``copy_inventories``          app/inventories/*.json -> dist/
                                  inventories/ + dist/inventories.json
6. ``write_python_bundle``       dist/{engine,render}/* + dist/api.py
                                  -> dist/python_bundle.zip
                                  (removes the loose copies)
7. ``write_bootstrap``           default inventory's render summary
                                  -> dist/bootstrap.json
8. ``hash_assets``               content-hash filenames + asset
                                  manifest + index.html rewrite
9. ``write_service_worker``      sw.js template -> dist/sw.js
10. ``write_pages_no_jekyll``    dist/.nojekyll

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
    imports from at runtime."""
    print("Relaying renderer sources from desktop GUI...")
    target = DIST / "render" / "phonology_features" / "gui"
    target.mkdir(parents=True, exist_ok=True)
    (DIST / "render" / "phonology_features" / "__init__.py").write_text("")
    (target / "__init__.py").write_text("")
    for name in RELAYED_SOURCES:
        src = DESKTOP_GUI / name
        if not src.exists():
            raise RuntimeError(f"missing desktop source: {src}")
        shutil.copy(src, target / name)


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
    skipped: list[str] = []
    for inv in sorted(INVENTORIES.glob("*.json")):
        if _is_gitignored(inv):
            skipped.append(inv.name)
            continue
        shutil.copy(inv, out / inv.name)
        manifest.append({
            "file": f"inventories/{inv.name}",
            "label": _inventory_label(inv),
        })
    (DIST / "inventories.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
    )
    print(f"  manifest: {len(manifest)} inventories")
    if skipped:
        print(f"  skipped (gitignored): {', '.join(skipped)}")


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
    """Emit ``theme.css`` from palette.LIGHT / palette.DARK so the
    same color values drive both desktop chrome and web CSS
    variables. Edits to palette.py propagate to both on the next
    build.
    """
    print("Generating theme.css from palette.py...")
    palette = _load_palette_module()
    lines: list[str] = [
        "/* AUTO-GENERATED from app/src/phonology_features/gui/palette.py",
        " * by web/scripts/build.py. Do not edit by hand. */",
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
    """``tag_blue_text`` -> ``tag-blue-text``."""
    return palette_key.replace("_", "-").lower()


def _load_palette_module() -> ModuleType:
    """Import ``palette.py`` directly without bringing in the rest
    of the desktop GUI package (the build runs outside the package
    layout, so a normal import would fail).
    """
    palette_path = DESKTOP_GUI / "palette.py"
    spec = importlib.util.spec_from_file_location("_palette", palette_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {palette_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
        phonology_features/gui/analysis.py
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
        out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9,
    ) as zf:
        for zip_path, src in entries:
            zf.write(src, arcname=zip_path)

    shutil.rmtree(DIST / "engine", ignore_errors=True)
    shutil.rmtree(DIST / "render", ignore_errors=True)
    raw = sum(p.stat().st_size for _, p in entries if p.exists())
    print(f"  {len(entries)} files, {out.stat().st_size} bytes zip ({raw} raw)")


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
    for css in ("theme.css", "style.css"):
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
