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
import importlib.util
import json
import shutil
import subprocess
import sys
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
    into a single ``python_bundle.json`` for one-request mounting.

    Why: before this, main.js held a hand-maintained file list that
    had to mirror RELAYED_SOURCES and the engine *.py glob. Adding a
    file here without updating the JS side (or vice versa) produced
    an import error at runtime. The bundle has the build emit the
    list it ships, and main.js just consumes it -- one source of
    truth for "what Python code does this deploy contain".

    Side benefit: one HTTP request instead of one-per-file (engine
    is 5 files, renderer is 6, plus api.py -- 12 round trips
    collapse to 1).

    Bundle shape:
        {
          "sys_paths": [absolute dirs to push onto sys.path],
          "files": { "<rel-path>": "<source>", ... }
        }

    ``rel-path`` is the path under /home/pyodide/ where the file
    should be written. ``sys_paths`` are pushed in order, so the
    earlier ones win on ``import`` collisions (engine first, then
    render).
    """
    print("Bundling Python sources...")
    files: dict[str, str] = {}
    # Engine package + the empty __init__'s.
    for path in sorted((DIST / "engine").rglob("*.py")):
        rel = path.relative_to(DIST).as_posix()
        files[rel] = path.read_text(encoding="utf-8")
    # Renderer package (relayed from desktop) + __init__'s.
    for path in sorted((DIST / "render").rglob("*.py")):
        rel = path.relative_to(DIST).as_posix()
        files[rel] = path.read_text(encoding="utf-8")
    # Bridge module, mounted at /home/pyodide/api.py.
    files["api.py"] = (DIST / "api.py").read_text(encoding="utf-8")

    bundle = {
        "sys_paths": [
            "/home/pyodide/engine",
            "/home/pyodide/render",
            "/home/pyodide",
        ],
        "files": files,
    }
    (DIST / "python_bundle.json").write_text(
        json.dumps(bundle, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  {len(files)} files, {sum(len(v) for v in files.values())} chars")


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
    write_pages_no_jekyll()

    print(f"\nBuild complete: {DIST}")
    print("Serve locally with:")
    print(f"  cd {DIST} && python -m http.server 8000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
