#!/usr/bin/env python3
"""Build the web app deploy artifact in ``web/dist/``.

Runnable locally (``python web/scripts/build.py``) and from the
Pages workflow. Output is what GitHub Pages publishes verbatim.

Pipeline:

1. ``copy_shared_sources``       phonology_shared/* -> dist/shared/
2. ``copy_static_assets``        web/{index.html,style.css,main.js}
                                  + web/src/phonology_web/api.py
                                  -> dist/
3. ``generate_theme_css``        palette.py -> dist/theme.css
4. ``generate_layout_css``       layout.py -> dist/layout.css
5. ``copy_inventories``          desktop/inventories/*.json -> dist/
                                  inventories/ + dist/inventories.json
6. ``write_python_bundle``       dist/shared/* + dist/api.py
                                  -> dist/python_bundle.zip
                                  (removes the loose copies)
7. ``write_bootstrap``           default inventory's render summary
                                  -> dist/bootstrap.json
8. ``hash_assets``               content-hash filenames + asset
                                  manifest + index.html rewrite
9. ``write_service_worker``      sw.js template -> dist/sw.js
10. ``write_pages_no_jekyll``    dist/.nojekyll

The full ``phonology_shared`` package (data / theory / chart /
presentation / editor) is mirrored under ``dist/shared/`` and
mounted into Pyodide's FS at runtime via zipimport. No wheel
build, no micropip install.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = REPO_ROOT / "web"
DIST = WEB_DIR / "dist"
SHARED_SRC = REPO_ROOT / "shared" / "src"
SHARED_PKG = SHARED_SRC / "phonology_shared"
DATA_DIR = SHARED_PKG / "data"
THEORY_DIR = SHARED_PKG / "theory"
CHART_DIR = SHARED_PKG / "chart"
PRESENTATION_DIR = SHARED_PKG / "presentation"
EDITOR_DIR = SHARED_PKG / "editor"
INVENTORIES = REPO_ROOT / "desktop" / "inventories"

# Make the shared source tree importable as a normal package so the
# ``spec_from_file_location`` side-loads below can transitively
# import their siblings (``editor/setup.py`` imports
# ``phonology_shared.data.limits.MAX_NAME_LENGTH`` at module load).
# CI runs this script against a bare interpreter where nothing is
# pip-installed, so we feed sys.path directly rather than relying on
# the workspace's editable install.
if str(SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(SHARED_SRC))


def clean_dist() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)


def bake_panphon_table() -> None:
    """Refresh the PanPhon-lookup JSON snapshot in shared/.

    Runs ``bake_panphon.bake_table()`` against the installed
    ``panphon`` package and writes the result to
    ``shared/.../editor/_panphon_table.generated.json``. The shared/
    mirror step below picks the file up alongside every other .py /
    .json under the package root, so the lookup provider in the
    Pyodide bundle finds it via importlib.resources at runtime.

    When ``panphon`` is not installed (typical on a fresh CI runner
    that hasn't pulled the optional dep) we print a warning, leave
    any stale snapshot in place, and continue: the LookupProvider's
    registry quietly drops the entry so the dialog falls back to
    static presets instead of crashing.
    """
    print("Baking PanPhon lookup table...")
    bake_script = WEB_DIR / "scripts" / "bake_panphon.py"
    spec = importlib.util.spec_from_file_location("bake_panphon", bake_script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load bake script at {bake_script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        table = module.bake_table()
    except ImportError as exc:
        print(
            f"  WARNING: panphon not installed ({exc}); "
            "lookup provider will be unavailable in the web bundle."
        )
        return
    out_path = SHARED_PKG / "editor" / "_panphon_table.generated.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False)
        f.write("\n")
    n_seg = len(table["segments"])
    size_kb = out_path.stat().st_size / 1024
    print(f"  baked {n_seg} segments ({size_kb:.1f} KB) -> {out_path.name}")


def bake_phoible_tables() -> None:
    """Refresh the PHOIBLE snapshots in shared/.

    Reads the vendored ``phoible.csv.gz`` under
    ``web/scripts/phoible_cache/`` and writes two JSON files:

    * ``_phoible_index.generated.json`` -> shared/.../editor/
      (small; ships inside ``python_bundle.zip``)
    * ``_phoible_data.generated.json`` -> shared/.../editor/
      (larger; ships as a SEPARATE static asset under
      ``web/dist/`` because we lazy-load it on first PHOIBLE
      click to keep the cold path cheap)

    The data file STILL gets written into the shared/ directory
    here so the desktop install picks it up via
    ``importlib.resources``; the
    :py:func:`write_python_bundle` step below opts the data file
    OUT of the zip (it walks ``_phoible_index.generated.json``
    explicitly so the larger data file is left for
    :py:func:`copy_phoible_data_asset` to handle separately).

    When the vendored cache is missing (a stripped clone, an
    intentional dev override), the bake prints a warning and
    continues: the registry quietly drops the PHOIBLE provider
    so the dialog falls back to PanPhon / static presets without
    crashing.
    """
    print("Baking PHOIBLE inventory tables...")
    bake_script = WEB_DIR / "scripts" / "bake_phoible.py"
    spec = importlib.util.spec_from_file_location("bake_phoible", bake_script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load bake script at {bake_script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        index, data, stats = module.bake_tables()
    except FileNotFoundError as exc:
        print(
            f"  WARNING: PHOIBLE cache missing ({exc}); "
            "PHOIBLE provider will be unavailable in the web bundle."
        )
        return
    out_index = SHARED_PKG / "editor" / "_phoible_index.generated.json"
    out_data = SHARED_PKG / "editor" / "_phoible_data.generated.json"
    out_index.parent.mkdir(parents=True, exist_ok=True)
    for path, payload in ((out_index, index), (out_data, data)):
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.write("\n")
    idx_kb = out_index.stat().st_size / 1024
    data_kb = out_data.stat().st_size / 1024
    print(
        f"  baked {stats['language_count']} languages / "
        f"{stats['inventory_count']} inventories "
        f"(index {idx_kb:.0f} KB, data {data_kb:.0f} KB)"
    )


def copy_shared_sources() -> None:
    """Mirror the whole ``phonology_shared`` package into
    ``dist/shared/phonology_shared/`` so the bundle can zipimport
    every submodule (``data``, ``theory``, ``chart``,
    ``presentation``, ``editor``) under the canonical dotted path.
    """
    print("Copying shared package source...")
    target_pkg = DIST / "shared" / "phonology_shared"
    if target_pkg.exists():
        shutil.rmtree(target_pkg)
    shutil.copytree(SHARED_PKG, target_pkg)
    for pycache in target_pkg.rglob("__pycache__"):
        shutil.rmtree(pycache, ignore_errors=True)
    py_files = sorted(target_pkg.rglob("*.py"))
    print(f"  {len(py_files)} .py files in shared/phonology_shared/")


def copy_static_assets() -> None:
    """Copy index.html, CSS, JS, and api.py to the dist root.

    ``api.py`` lives at ``web/src/phonology_web/api.py`` on disk so
    the bridge is a normal workspace package, but the Pyodide
    bundle still mounts it at the bundle root as ``api.py``
    (``main.js`` does ``pyodide.pyimport("api")``).
    """
    print("Copying static assets...")
    for name in ("index.html", "style.css", "main.js"):
        shutil.copy(WEB_DIR / name, DIST / name)
    shutil.copy(WEB_DIR / "src" / "phonology_web" / "api.py", DIST / "api.py")


def copy_inventories() -> None:
    """Bundle every inventory found in ``desktop/inventories/`` and
    emit a manifest. Both are read by main.js at runtime; adding a
    new JSON to ``desktop/inventories/`` makes it appear in the dropdown
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
        cwd=REPO_ROOT,
        capture_output=True,
    )
    # 0 = ignored, 1 = not ignored, anything else = git error.
    return result.returncode == 0


def _inventory_label(path: Path) -> str:
    """Display label for the dropdown. Reads ``metadata.name`` (or
    top-level ``name``) from the JSON, then delegates to the shared
    helper so desktop runtime and web build agree byte-for-byte.
    """
    metadata_name: str | None = None
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        meta = raw.get("metadata", {})
        candidate = meta.get("name") or raw.get("name")
        if isinstance(candidate, str):
            metadata_name = candidate
    except (json.JSONDecodeError, OSError):
        pass
    label = _load_inventory_setup_module().inventory_display_label(
        fname=path.name, metadata_name=metadata_name
    )
    return str(label)


def generate_theme_css() -> None:
    """Emit ``theme.css`` from palette.LIGHT / palette.DARK / COLORBLIND_*
    so the same color values drive both desktop chrome and web CSS
    variables. Edits to palette.py propagate to both on the next build.

    Two perpendicular axes drive variant selection:
      * ``html[data-theme="dark"]``: dark theme overrides.
      * ``html[data-cb="on"]``:      colorblind-friendly palette.
    The colorblind-dark variant is keyed on both attributes so the
    most-specific selector wins regardless of attribute order.
    """
    print("Generating theme.css from palette.py...")
    palette = _load_palette_module()

    def block(selector: str, table: dict[str, str]) -> list[str]:
        out = [f"{selector} {{"]
        for key, value in table.items():
            out.append(f"  --{_css_var_name(key)}: {value};")
        # Bake the class-state verdict mapping as additional CSS
        # variables so style.css doesn't have to repeat the
        # verdict-to-palette-role decision. The helper is the
        # single source of truth for the mapping; the resolved
        # hex values come from this palette table.
        for state in ("natural", "not_natural"):
            keys = palette.class_state_palette_keys(state)
            assert keys is not None  # non-neutral states always map
            fg_key, bg_key = keys
            out.append(
                f"  --class-state-{state.replace('_', '-')}-fg:"
                f" {table[fg_key]};"
            )
            out.append(
                f"  --class-state-{state.replace('_', '-')}-bg:"
                f" {table[bg_key]};"
            )
        out.append("}")
        return out

    lines: list[str] = [
        "/* AUTO-GENERATED from shared/src/phonology_shared/presentation/palette.py",
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
    palette_path = PRESENTATION_DIR / "palette.py"
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
    layout_path = PRESENTATION_DIR / "layout.py"
    spec = importlib.util.spec_from_file_location("_layout", layout_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {layout_path}")
    module = importlib.util.module_from_spec(spec)
    # ``@dataclass`` introspects via ``sys.modules[cls.__module__]``;
    # register the module before exec so ``RegionConstraint`` can
    # validate its annotated fields at class creation.
    sys.modules["_layout"] = module
    spec.loader.exec_module(module)
    return module


def _load_constants_module() -> ModuleType:
    """Side-load ``constants.py`` so ``generate_layout_css`` can read
    the FONT_SIZE_* ladder without requiring the engine package to be
    installed (this script runs against a bare interpreter in CI).
    """
    constants_path = PRESENTATION_DIR / "constants.py"
    spec = importlib.util.spec_from_file_location(
        "_constants",
        constants_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {constants_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_constants"] = module
    spec.loader.exec_module(module)
    return module


def _load_inventory_setup_module() -> ModuleType:
    """Side-load ``inventory_setup.py`` so the HTML-bake step can
    substitute shared dialog strings (``SETUP_DIALOG_TITLE``,
    ``SETUP_NAME_PLACEHOLDER``) into ``index.html``.
    """
    path = EDITOR_DIR / "setup.py"
    spec = importlib.util.spec_from_file_location("_inv_setup", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_inv_setup"] = module
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
    limits_path = DATA_DIR / "limits.py"
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

    mode_logic_path = PRESENTATION_DIR / "mode_logic.py"
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
        # Other user-visible strings the JS would otherwise
        # hardcode. Each one is the exact value the desktop renders
        # via its own ``mode_logic`` call; baking here makes the
        # Python helper the single source.
        payload["clipboard_copy_template"] = (
            module.CLIPBOARD_COPY_MESSAGE_TEMPLATE
        )
        payload["validation_report_heading"] = module.VALIDATION_REPORT_HEADING
        payload["load_failed_template"] = module.LOAD_FAILED_TEMPLATE
        payload["inventory_loaded_template"] = module.INVENTORY_LOADED_TEMPLATE
        payload["theme_to_dark"] = module.theme_toggle_tooltip(is_dark=False)
        payload["theme_to_light"] = module.theme_toggle_tooltip(is_dark=True)
        payload["theme_glyph_dark"] = module.theme_toggle_glyph(is_dark=True)
        payload["theme_glyph_light"] = module.theme_toggle_glyph(is_dark=False)
        payload["palette_to_colorblind"] = module.palette_toggle_tooltip(
            is_colorblind=False
        )
        payload["palette_to_standard"] = module.palette_toggle_tooltip(
            is_colorblind=True
        )
        # Builder status templates. JS substitutes {seg}/{feat}/{n}/
        # {plural} locally because those values originate in JS state.
        payload["undo_nothing_message"] = module.UNDO_NOTHING_MESSAGE
        payload["redo_nothing_message"] = module.REDO_NOTHING_MESSAGE
        payload["undid_template"] = module.UNDID_TEMPLATE
        payload["redid_template"] = module.REDID_TEMPLATE
        payload["added_segment_template"] = module.ADDED_SEGMENT_TEMPLATE
        payload["removed_segment_template"] = module.REMOVED_SEGMENT_TEMPLATE
        payload["added_feature_template"] = module.ADDED_FEATURE_TEMPLATE
        payload["removed_feature_template"] = module.REMOVED_FEATURE_TEMPLATE
        # Builder cell-value glyphs. U+2212 (display) vs U+002D
        # (serialized). The JS used to declare these as literals;
        # baking from phonology_shared.editor.grid makes the Python
        # constants the single source.
        from phonology_shared.editor.grid import (
            MINUS_DISPLAY,
            MINUS_SERIALIZED,
        )

        payload["minus_display"] = MINUS_DISPLAY
        payload["minus_serialized"] = MINUS_SERIALIZED
        # Vowel-chart diphthong-toggle label + empty-state hints.
        # Same SSOT pattern: the desktop reads the constant by
        # import, the web reads via this status-text bake.
        from phonology_shared.presentation.constants import (
            DEFAULT_INVENTORY_STEM,
            DIPHTHONG_TOGGLE_LABEL,
            EMPTY_NATURAL_CLASS_HINT,
            EMPTY_PHOIBLE_SEARCH_HINT,
            EMPTY_SHARED_FEATURES_HINT,
        )

        payload["diphthong_toggle_label"] = DIPHTHONG_TOGGLE_LABEL
        payload["empty_natural_class_hint"] = EMPTY_NATURAL_CLASS_HINT
        payload["empty_shared_features_hint"] = EMPTY_SHARED_FEATURES_HINT
        payload["empty_phoible_search_hint"] = EMPTY_PHOIBLE_SEARCH_HINT
        # Bundled-inventory stem the web app boots into. Single
        # source so the build-time bootstrap (below) and the
        # runtime default-pick in main.js can never drift to
        # different files.
        payload["default_inventory_stem"] = DEFAULT_INVENTORY_STEM
        return payload
    finally:
        sys.modules.pop(module_name, None)


def _vowel_corner_lines(shape: str) -> list[str]:
    """Emit ``--vowel-<shape>-<corner>`` variables for every corner
    of the silhouette so the CSS clip-path can reference them
    directly. The back edge (top-right / bottom-right) is emitted as
    a ``calc()`` that mixes the back-anchor percentage with the
    pixel-offset captured in
    :py:attr:`VowelChartSilhouette.back_right_pixel_offset` -- the
    same formula the desktop and web renderers apply at runtime, so
    the canonical bake stays aligned with the interactive renders.
    """
    sil = _vowel_silhouette(shape)
    back_offset = sil["back_right_pixel_offset"]
    back_right_calc = f"calc({sil['top_right'] * 100:.3f}% + {back_offset}px)"
    return [
        f"  --vowel-{shape}-top-left: {sil['top_left'] * 100:.3f}%;",
        f"  --vowel-{shape}-top-right: {back_right_calc};",
        f"  --vowel-{shape}-bottom-left: {sil['bottom_left'] * 100:.3f}%;",
        f"  --vowel-{shape}-bottom-right: {back_right_calc};",
        f"  --vowel-{shape}-top-y: {sil['top_y'] * 100:.3f}%;",
        f"  --vowel-{shape}-bottom-y: {sil['bottom_y'] * 100:.3f}%;",
    ]


def _vowel_silhouette(shape: str) -> dict[str, float | int]:
    """Canonical silhouette field values for the given shape. Reads
    :py:func:`vowel_layout.vowel_silhouette` so the bake's numbers
    match what ``build_vowel_chart_geometry`` produces for an
    inventory-free chart."""
    from phonology_shared.chart.vowels import (
        VowelChartShape,
        vowel_silhouette,
    )

    sil = vowel_silhouette(VowelChartShape(shape))
    return {
        "top_left": sil.top_left,
        "top_right": sil.top_right,
        "bottom_left": sil.bottom_left,
        "bottom_right": sil.bottom_right,
        "top_y": sil.top_y,
        "bottom_y": sil.bottom_y,
        "back_right_pixel_offset": sil.back_right_pixel_offset,
    }


def generate_layout_css() -> None:
    """Emit ``layout.css`` from the constants in
    ``phonology_shared.presentation.layout`` so the same numbers drive both
    the desktop's Qt splitter / chart sizing and the web's CSS grid.
    Edits to the shared constants propagate to both on the next build.
    Mirrors the ``generate_theme_css`` pattern.
    """
    print("Generating layout.css from layout.py...")
    mod = _load_layout_module()
    lines: list[str] = [
        "/* AUTO-GENERATED from shared/src/phonology_shared/presentation/layout.py",
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
        # Silhouette corners for both shapes, in the data area's
        # normalised ``[0, 1]`` coordinate space. Derived in
        # ``vowel_layout.vowel_trapezoid_corners`` so the silhouette
        # outline exactly hugs the back-anchored cell positions:
        # the right edge is vertical at the back-pair's outer edge
        # and the left edge slants from front-close-left to
        # front-open-left.
        *_vowel_corner_lines("trapezoid"),
        *_vowel_corner_lines("triangle"),
        f"  --collapse-w: {mod.COLLAPSE_W}px;",
        # Per-button dimensions sourced from
        # ``constants.BTN_W`` / ``constants.BTN_GAP`` (single source
        # of truth). main.js reads ``--seg-btn-w`` and
        # ``--seg-btn-gap`` instead of literal 33 / 4 fallbacks so
        # the same per-button stride drives the desktop QGridLayout,
        # the web's container queries, and ``applyPerGroupSegmentColumns``.
        f"  --seg-btn-w: {mod.BTN_W}px;",
        f"  --seg-btn-gap: {mod.BTN_GAP}px;",
        # Per-row / per-card heights: single source of truth for
        # consonant-grid and feature-card height math in the web.
        f"  --seg-btn-h: {mod.SEG_BTN_H}px;",
        f"  --seg-btn-row-h: {mod.SEG_BTN_ROW_H}px;",
        f"  --seg-group-header-h: {mod.SEG_GROUP_HEADER_H}px;",
        f"  --feat-row-h: {mod.FEAT_ROW_H}px;",
        f"  --feat-card-chrome-h: {mod.FEAT_CARD_CHROME_H}px;",
        # Feature-row button + badge sizing. Mirrors the desktop's
        # ``_DENSITY_NORMAL`` so a single Python edit updates both
        # renderers. Without the relay these were hand-defined in
        # ``style.css`` and silently drifted whenever the desktop
        # tweaked density.
        f"  --feat-btn-w: {mod.FEAT_BTN_W}px;",
        f"  --feat-btn-h: {mod.FEAT_BTN_H}px;",
        f"  --feat-badge-w: {mod.FEAT_BADGE_W}px;",
        # Spacing ladder, radius tokens, and top-bar control heights.
        # Mirrors the desktop's literals so a one-Python-edit policy
        # tweak flows through ``layout.css`` to both UIs.
        f"  --space-xs: {mod.SPACING_PX['xs']}px;",
        f"  --space-sm: {mod.SPACING_PX['sm']}px;",
        f"  --space-md: {mod.SPACING_PX['md']}px;",
        f"  --space-lg: {mod.SPACING_PX['lg']}px;",
        f"  --space-xl: {mod.SPACING_PX['xl']}px;",
        f"  --radius-sm: {mod.RADIUS_PX['sm']}px;",
        f"  --radius-md: {mod.RADIUS_PX['md']}px;",
        f"  --radius-lg: {mod.RADIUS_PX['lg']}px;",
        f"  --control-h-md: {mod.TOOLBAR_BTN_H}px;",
        f"  --control-h-xs: {mod.PANEL_CLEAR_BTN_H}px;",
        f"  --panel-chrome-v: {mod.PANEL_CHROME_V}px;",
        f"  --min-top-pane-h: {mod.MIN_TOP_PANE_H}px;",
        # Analysis-pane sizing. Both UIs consume this via the CSS
        # variable so the desktop's Qt math
        # (``analysis_content_floor_h``, ``HARD_MIN_ANALYSIS_H``)
        # and the web's ``.analysis`` floor lock can never drift.
        f"  --min-analysis-h: {mod.MIN_ANALYSIS_H}px;",
        # Hard cap on overall content width (ultrawide). Above this
        # pixel ceiling ``main.grid`` stops growing and centres via
        # ``margin-inline: auto``; below it the grid fills the
        # available width normally.
        f"  --content-max-w: {mod.CONTENT_MAX_W_ABS}px;",
    ]
    # Web font-size ladder, relayed from ``constants.py``. Web CSS
    # rules read these so a future ladder revision is one Python
    # constant edit, not a sweep of every ``font-size:`` declaration.
    constants_mod = _load_constants_module()
    lines.extend(
        [
            "  /* Font-size ladder (from constants.py). */",
            f"  --font-size-icon: {constants_mod.FONT_SIZE_ICON_PX}px;",
            f"  --font-size-heading: {constants_mod.FONT_SIZE_HEADING_PX}px;",
            f"  --font-size-base: {constants_mod.FONT_SIZE_BASE_PX}px;",
            f"  --font-size-control: {constants_mod.FONT_SIZE_CONTROL_PX}px;",
            f"  --font-size-meta: {constants_mod.FONT_SIZE_META_PX}px;",
            f"  --font-size-label: {constants_mod.FONT_SIZE_LABEL_PX}px;",
            f"  --font-size-micro: {constants_mod.FONT_SIZE_MICRO_PX}px;",
            # ``rasterizeText`` reads this floor so the JS-side font-shrink
            # loop's lower bound stays in lockstep with the Python one.
            f"  --font-size-min-px: {constants_mod.FONT_SIZE_MIN_PX}px;",
        ]
    )
    # Per-region size contract emitted as ``--<key>-min-w/max-w/
    # min-h/max-h`` plus ``--<key>-overflow`` for the documented
    # strategy. Web style.css rules consume these via ``var(--seg-btn-
    # min-w)`` etc. so the relay is symmetric with the Qt-side
    # ``setMinimumSize`` calls in Phase C.
    lines.append("  /* Region constraints (from layout.py). */")
    for key, region in mod.REGION_CONSTRAINTS.items():
        css_key = key.replace("_", "-")
        lines.append(f"  --{css_key}-min-w: {region.min_w}px;")
        if region.max_w is not None:
            lines.append(f"  --{css_key}-max-w: {region.max_w}px;")
        lines.append(f"  --{css_key}-min-h: {region.min_h}px;")
        if region.max_h is not None:
            lines.append(f"  --{css_key}-max-h: {region.max_h}px;")
        lines.append(f"  --{css_key}-overflow: {region.overflow};")
    lines.extend(["}", ""])
    # Container-query thresholds derived from the same Python
    # constants. The seg-pane uses ``VOWEL_STACK_W`` to decide
    # whether the vowel chart floats beside the consonant grid or
    # drops below it; baking the rule here means changing
    # ``VOWEL_STACK_W`` in Python automatically rewrites the CSS
    # threshold on the next build (no hand-edits to ``style.css``).
    lines.extend(
        [
            "/* Container-query thresholds derived from layout.py. */",
            f"@container (max-width: {mod.VOWEL_STACK_W}px) {{",
            "  .seg-vowels {",
            "    float: none;",
            "    margin: var(--space-md) 0 0 0;",
            "    max-width: 100%;",
            "    min-width: 0;",
            "  }",
            "}",
            "",
        ]
    )
    (DIST / "layout.css").write_text("\n".join(lines))
    print(f"  {len(lines) - 4} layout tokens")


def write_python_bundle() -> None:
    """Pack the shared package + api.py into ``python_bundle.zip``
    and mount via zipimport at runtime.

    One binary fetch + one ``writeFile`` instead of fetch +
    JSON.parse + N writeFiles. Compressed on the wire via
    ZIP_DEFLATED even without server gzip. The loose ``dist/shared``
    tree is removed after bundling so only the zip ships.

    Zip layout (single namespace, one sys.path entry suffices)::

        phonology_shared/__init__.py
        phonology_shared/data/__init__.py
        phonology_shared/data/inventory.py
        phonology_shared/theory/feature_engine.py
        phonology_shared/chart/consonants.py
        phonology_shared/chart/vowels.py
        phonology_shared/presentation/palette.py
        ...
        phonology_shared/editor/grid.py
        phonology_shared/editor/setup.py
        api.py
    """
    print("Bundling Python sources into zip...")
    out = DIST / "python_bundle.zip"
    shared_root = DIST / "shared"
    entries: list[tuple[str, Path]] = []
    for path in sorted(shared_root.rglob("*.py")):
        entries.append((path.relative_to(shared_root).as_posix(), path))
    # Non-Python data files that ship inside the package and load via
    # importlib.resources at runtime (PanPhon lookup snapshot, PHOIBLE
    # index). The PHOIBLE *data* file is intentionally excluded: it is
    # 5 MB raw and ships as a separate static asset under ``dist/`` so
    # the cold Pyodide boot path stays cheap (the dialog fetches and
    # injects the JSON on first PHOIBLE click via the bridge).
    for path in sorted(shared_root.rglob("*.generated.json")):
        if path.name == "_phoible_data.generated.json":
            continue
        entries.append((path.relative_to(shared_root).as_posix(), path))
    entries.append(("api.py", DIST / "api.py"))

    with zipfile.ZipFile(
        out,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as zf:
        for zip_path, src in entries:
            zf.write(src, arcname=zip_path)

    shutil.rmtree(shared_root, ignore_errors=True)
    raw = sum(p.stat().st_size for _, p in entries if p.exists())
    print(
        f"  {len(entries)} files, {out.stat().st_size} bytes zip ({raw} raw)"
    )


def copy_phoible_data_asset() -> None:
    """Copy the PHOIBLE data JSON + the attribution file to dist/.

    The data JSON is lazy-loaded by main.js on first PHOIBLE click,
    not included in the Pyodide bundle, so it ships as a plain
    static asset alongside the inventories. The :py:func:`hash_assets`
    step below applies the same content-hash + asset-manifest
    treatment it does for every other static file so the browser
    cache key updates whenever PHOIBLE is re-baked.

    PHOIBLE_LICENSE.txt is the GPL-3.0 + CC BY-SA 3.0 attribution
    document the user can link from the dialog's citation chip;
    ships unhashed at a stable URL so the link in the HTML doesn't
    rot per build.
    """
    src = SHARED_PKG / "editor" / "_phoible_data.generated.json"
    if not src.exists():
        # No bake produced (cache missing); the PHOIBLE provider is
        # already excluded from the registry so the dialog won't
        # try to fetch this asset.
        return
    dst = DIST / "phoible_data.json"
    shutil.copy(src, dst)
    kb = dst.stat().st_size / 1024
    print(f"Copying PHOIBLE data asset...\n  {kb:.0f} KB -> {dst.name}")

    license_src = WEB_DIR / "scripts" / "phoible_cache" / "PHOIBLE_LICENSE.txt"
    if license_src.exists():
        shutil.copy(license_src, DIST / "PHOIBLE_LICENSE.txt")
        print("  PHOIBLE_LICENSE.txt -> dist/")


def copy_ipa_font_asset() -> None:
    """Copy the subset Charis SIL Compact woff2 + its OFL license.

    The font lives at ``web/assets/charis-ipa.woff2`` (committed,
    refreshed by running ``web/scripts/subset_ipa_font.py`` against
    the source TTF). Shipping a vendored subset means the build
    pipeline does not need fonttools at deploy time and the
    ``@font-face`` URL in ``style.css`` resolves against a known
    asset.

    The license file ships at a stable URL so the citation link in
    ``style.css`` (and the about section) does not rot per build.
    """
    font_src = WEB_DIR / "assets" / "charis-ipa.woff2"
    if not font_src.exists():
        print(
            "  WARNING: Charis IPA woff2 not found at "
            f"{font_src}; run web/scripts/subset_ipa_font.py first."
        )
        return
    dst = DIST / "charis-ipa.woff2"
    shutil.copy(font_src, dst)
    kb = dst.stat().st_size / 1024
    print(f"Copying IPA font asset...\n  {kb:.0f} KB -> {dst.name}")

    license_src = WEB_DIR / "assets" / "CHARIS_SIL_LICENSE.txt"
    if license_src.exists():
        shutil.copy(license_src, DIST / "CHARIS_SIL_LICENSE.txt")
        print("  CHARIS_SIL_LICENSE.txt -> dist/")


def write_bootstrap() -> None:
    """Precompute the default inventory's render summary so the web
    app can paint its initial UI before Pyodide finishes loading.

    Runs in a subprocess to isolate the import side effects. Best-
    effort: a failed precompute logs a warning and the build
    continues; main.js falls back to the bridge-driven render path.
    """
    print("Precomputing default inventory bootstrap...")
    # Single source of truth for the default-inventory stem;
    # main.js reads the same value via the inlined status-text
    # payload (see ``_build_status_text_payload``).
    from phonology_shared.presentation.constants import (
        DEFAULT_INVENTORY_STEM,
    )

    default_inv = INVENTORIES / f"{DEFAULT_INVENTORY_STEM}.json"
    if not default_inv.exists():
        print(f"  skipped: no default inventory at {default_inv}")
        return
    label = _inventory_label(default_inv)
    code = (
        "import sys, json\n"
        f"sys.path.insert(0, {str(SHARED_SRC)!r})\n"
        f"sys.path.insert(0, {str(WEB_DIR / 'src')!r})\n"
        "from phonology_web import api\n"
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

    # 3a. PHOIBLE data asset. Lazy-loaded by main.js on first
    #     PHOIBLE click; the hashed name lands in ``runtime_map``
    #     so ``main.js`` can ``fetch(asset_map.phoible_data)``
    #     without hard-coding the cache-busting suffix.
    phoible_data = DIST / "phoible_data.json"
    if phoible_data.exists():
        new_phoible = _hashed_name(phoible_data)
        phoible_data.rename(DIST / new_phoible)
        runtime_map["phoible_data"] = new_phoible
        full_map["phoible_data.json"] = new_phoible

    # 3b. IPA font. Hashed BEFORE the CSS step so we can rewrite
    #     style.css's ``url("charis-ipa.woff2")`` reference to the
    #     hashed name before the CSS itself gets hashed.
    ipa_font = DIST / "charis-ipa.woff2"
    new_font_name: str | None = None
    if ipa_font.exists():
        new_font_name = _hashed_name(ipa_font)
        ipa_font.rename(DIST / new_font_name)
        full_map["charis-ipa.woff2"] = new_font_name

    # 4. CSS files referenced from index.html. style.css gets a
    #    one-time rewrite to replace the font URL with its hashed
    #    name; without this the browser fetches a stale or missing
    #    asset on the cold path.
    if new_font_name:
        style_path = DIST / "style.css"
        style_text = style_path.read_text(encoding="utf-8")
        style_text = style_text.replace(
            'url("charis-ipa.woff2")',
            f'url("{new_font_name}")',
        )
        style_path.write_text(style_text, encoding="utf-8")
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
    status_text_payload = _build_status_text_payload()
    status_block = (
        '<script id="status-text" type="application/json">'
        + json.dumps(
            status_text_payload,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "</script>"
    )
    # Bake the no-engine status string into the <span id="statusbar">
    # default so the pre-JS HTML carries the SAME literal the JS
    # ``statusTextForMode(...)`` returns. ``mode_status_text`` is the
    # single source of truth; the source ``index.html`` ships a
    # matching placeholder so the page reads sensibly even if served
    # raw, but this substitution is what guarantees parity after a
    # future change to the shared string. The presence check asserts
    # the placeholder block exists at all -- if a future ``index.html``
    # edit drops the block, the bake fails loudly instead of producing
    # silently empty status text.
    statusbar_marker = '<span id="statusbar" class="statusbar-message">'
    if statusbar_marker not in html:
        raise RuntimeError(
            "index.html is missing the statusbar marker"
            f" {statusbar_marker!r}; build.py needs it to bake the"
            " shared no-engine text. Either restore the marker or"
            " update the substitution pattern."
        )
    # Replace whatever placeholder text the source carries with the
    # canonical shared string. Uses a regex to span from the marker
    # to the closing </span>.
    html = re.sub(
        re.escape(statusbar_marker) + r"[^<]*</span>",
        statusbar_marker + status_text_payload["no_engine"] + "</span>",
        html,
        count=1,
    )

    # Bake the setup-dialog title + name placeholder from
    # ``shared/inventory_setup.py`` so the desktop dialog and the
    # web modal cannot drift on these strings.
    inv_setup = _load_inventory_setup_module()

    def _bake(label: str, pattern: str, replacement: str) -> None:
        nonlocal html
        new_html, n = re.subn(pattern, replacement, html, count=1)
        if n != 1:
            raise RuntimeError(
                f"index.html bake for {label!r} matched {n} sites"
                " (expected 1); the source HTML structure has drifted"
                " from the regex in build.py. Update build.py to match."
            )
        html = new_html

    _bake(
        "setup-dialog-title",
        r'(<div class="dialog-title" id="setup-dialog-title">)[^<]*(</div>)',
        r"\1" + inv_setup.SETUP_DIALOG_TITLE + r"\2",
    )
    _bake(
        "setup-name-placeholder",
        r'(id="setup-name-input"[^>]*?placeholder=")[^"]*(")',
        r"\1" + inv_setup.SETUP_NAME_PLACEHOLDER + r"\2",
    )
    # Theme + colorblind toggles. Both UIs render identical wording
    # via ``mode_logic.theme_toggle_tooltip`` /
    # ``palette_toggle_tooltip``. The HTML carries the initial
    # (light, standard) labels; ``wireThemeToggle`` /
    # ``wireColorblindToggle`` swap them on toggle by reading
    # the same baked STATUS_TEXT keys.
    _bake(
        "cb-btn-aria-label",
        r'(id="cb-btn"[^>]*?aria-label=")[^"]*(")',
        r"\1" + status_text_payload["palette_to_colorblind"] + r"\2",
    )
    _bake(
        "cb-btn-title",
        r'(id="cb-btn"[^>]*?title=")[^"]*(")',
        r"\1" + status_text_payload["palette_to_colorblind"] + r"\2",
    )
    _bake(
        "theme-btn-aria-label",
        r'(id="theme-btn"[^>]*?aria-label=")[^"]*(")',
        r"\1" + status_text_payload["theme_to_dark"] + r"\2",
    )
    _bake(
        "theme-btn-title",
        r'(id="theme-btn"[^>]*?title=")[^"]*(")',
        r"\1" + status_text_payload["theme_to_dark"] + r"\2",
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
    # PHOIBLE data file (~5 MB) is lazy-loaded on demand; precaching
    # it would force every visitor to download it during the SW
    # install even if they never click the PHOIBLE picker. The file
    # gets cached on first fetch via the cache-first rule in sw.js
    # so subsequent visits hit the local copy. ``startswith`` so a
    # future content-hash on the same logical asset still matches.
    LAZY_PREFIXES = ("phoible_data.",)
    precache = ["./", "./index.html"]
    for path in sorted(DIST.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(DIST).as_posix()
        if rel in SKIP_NAMES:
            continue
        if any(rel.startswith(p) for p in LAZY_PREFIXES):
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
    # Bake both snapshots BEFORE the shared mirror step so the
    # generated JSON travels into ``dist/shared/`` alongside the
    # rest of the package. PHOIBLE's data file is excluded from
    # the zip bundle (see write_python_bundle) and copied to dist/
    # separately by copy_phoible_data_asset for lazy-load.
    bake_panphon_table()
    bake_phoible_tables()
    copy_shared_sources()
    copy_static_assets()
    generate_theme_css()
    generate_layout_css()
    copy_inventories()
    write_python_bundle()
    copy_phoible_data_asset()
    copy_ipa_font_asset()
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
