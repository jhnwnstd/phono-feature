# Contributing

Once you have the launcher running (see [README.md](README.md#run)),
this file explains the deliberate parts of the repo layout.

By submitting a contribution, you license it to the project owner
under terms that permit relicensing, including commercial licensing.

## The relay system: one Python source, two UIs

The desktop app (PyQt6) and the browser app (Pyodide) are two
front-ends over the same shared package. The pattern:

1. Pure-Python modules live in `shared/src/phonology_shared/`,
   split by functional role into six subpackages:
   * `data/`: inventory schema, parsing, hard caps.
   * `theory/`: phonological analysis engine + geometry.
   * `chart/`: IPA chart placement (consonants, vowels).
   * `presentation/`: palette, layout, view models, mode logic,
     HTML analysis renderer.
   * `editor/`: inventory-editor grid + setup helpers.
   * `application/`: UI-agnostic `SessionState` (selection, mode,
     active inventory).

   No subpackage has Qt or DOM imports at module scope.
2. `web/scripts/build.py:copy_shared_sources` mirrors the whole
   `phonology_shared/` tree into `web/dist/shared/phonology_shared/`,
   then `write_python_bundle` packs that tree plus
   `web/src/phonology_web/api.py` into `python_bundle.zip` which
   Pyodide mounts via zipimport.
3. The web bridge (`web/src/phonology_web/api.py`) imports from
   `phonology_shared.<subpackage>.<name>` at runtime inside
   Pyodide, so any change you make in `shared/` reaches both UIs
   on the next `python web/scripts/build.py`.

In addition to the source mirror, `theme.css` and `layout.css`
are generated at build time from the same Python constants the
desktop reads (the full file-by-file map lives in
[web/README.md](web/README.md#auto-generated-files-do-not-edit-by-hand)).

If you find yourself adding a number to `web/style.css` that
already exists in `presentation/layout.py`, route it through the
generator instead and consume the CSS variable. Parity tests in
`shared/tests/` fail loudly if a layout literal in CSS disagrees
with the Python source.

## Repo layout

```
phono-feature/
├── desktop/                 PyQt6 application + tests + inventory data.
│   ├── src/phonology_features/
│   │   ├── _logging.py      Pure Python; desktop owns this.
│   │   ├── _settings.py     QSettings; Qt-only.
│   │   └── gui/
│   │       ├── editor/     Inventory Editor window and helpers.
│   │       ├── controllers/ Desktop orchestrators (mode, theme, etc).
│   │       └── *.py         Qt widgets (MainWindow, widgets, etc).
│   ├── inventories/         Canonical JSON inventories.
│   └── tests/               Qt-dependent tests.
├── shared/                  Framework-agnostic Python both UIs use.
│   └── src/phonology_shared/
│       ├── data/            Inventory schema + hard caps.
│       ├── theory/          Analysis engine + geometry.
│       ├── chart/           IPA chart placement (consonants + vowels).
│       ├── presentation/    Palette, layout, view models, mode logic.
│       ├── editor/          Editor grid + setup.
│       └── application/     Shared SessionState.
├── web/                     Pyodide bridge + browser surface.
│   ├── src/phonology_web/api.py  JS-to-Python bridge.
│   ├── index.html, main.js, style.css, sw.js
│   ├── scripts/             build.py, smoke.py, ...
│   └── tests/               Bridge validation tests.
└── tools/                   Dev tooling (capture_screens, install.sh, ...).
```

The boundary rules:

* `shared/` is the only place web-consumed Python lives. Anything
  that imports `PyQt6.QtWidgets` at module scope belongs in
  `desktop/src/phonology_features/gui/` proper.
* `data/` is the leaf; everything else may depend on it. `theory/`,
  `chart/`, and `editor/` never import anything UI-shaped. `chart/`
  and `editor/` read display constants and helpers from
  `presentation/`; `data/inventory.py` lazy-imports the
  `presentation/` metadata resolver at one commented site to avoid
  a cycle. No other reverse edge is allowed.
* `controllers/` holds desktop-only orchestrators
  (`GeometryController`, `ModeController`, `ThemeController`,
  `InventoryDirController`, `DialogCoordinator`).

When you add a new module, the first question is "would the web
need this too?" If yes, it goes in `shared/` under the subpackage
that matches its role. The whole `phonology_shared/` tree is
mirrored into the bundle automatically; no manual filename list
to update.

## Launchers and the install bootstrap

Three single-step launchers live at the repo root:

* `RUN-Linux.sh`
* `RUN-Mac.command`
* `RUN-Windows.bat`

Each launcher delegates to a shared bootstrap in `tools/`:

* the two Unix launchers `source tools/install.sh` and call
  `phono_install`;
* the Windows launcher `call`s `tools\install.bat`.

Both bootstraps create `desktop/.venv/` on first run, install
`phonology-shared`, `phonology-features`, and `phonology-web` in
editable mode, and stamp `desktop/.venv/.installed` so subsequent
runs skip the install step. The Unix bootstrap picks a Python
3.11+ interpreter and reinstalls when the desktop or shared
`pyproject.toml` is newer than the stamp. cmd.exe has no timestamp
test, so the Windows bootstrap takes `py -3` (or `python`) as
found and reinstalls only when the stamp is missing; delete
`desktop\.venv\.installed` to force one.

If you change the launcher contract (Python version, install
flags, venv location), change `tools/install.sh` and
`tools/install.bat` together so the three launchers stay in
lockstep.

## Where tests live

| Suite                | What it covers |
|----------------------|---|
| `shared/tests/`      | Pure-Python: Inventory, FeatureEngine, geometry, chart placement, layout, mode_logic, view_models, editor grid. No Qt. |
| `desktop/tests/`     | Desktop GUI + integration. Boots PyQt6 under `QT_QPA_PLATFORM=offscreen`. |
| `web/tests/`         | Bridge boundary: every `api.py` entry rejects bad input as `ValidationError` and returns JSON-clean values; plus PHOIBLE builder round-trip and source-editing tests. |
| `shared/tests/test_editor_mirror_parity.py`, `test_relay_smoke.py` | Pin the web's pre-bridge JS mirrors and the build-time JSON bake against the Python source they shadow. |
| `web/scripts/smoke.py` | Playwright end-to-end: boots the built site through Pyodide, drives the bridge, asserts the analysis pane populates. |

## Lint and verification chain

CI runs the lint chain from the repo root and the test suites
from each package; `smoke.py` runs at deploy time in `pages.yml`,
not in `ci.yml`. The full chain, runnable locally:

```bash
desktop/.venv/bin/python -m isort . --profile black --check-only
desktop/.venv/bin/python -m black -l 79 --check .
desktop/.venv/bin/python -m flake8 .
desktop/.venv/bin/python -m mypy
desktop/.venv/bin/python tools/check_license_headers.py
node --check web/main.js && node --check web/sw.js
cd web && npx eslint main.js sw.js && cd ..

desktop/.venv/bin/python -m pytest shared/tests -q
desktop/.venv/bin/python -m pytest desktop/tests -q
desktop/.venv/bin/python -m pytest web/tests -q

desktop/.venv/bin/python web/scripts/build.py
desktop/.venv/bin/python web/scripts/smoke.py
```

`uv.lock` is committed; `uv lock --check` should pass before any
dependency-touching change lands.

The formatter checks (isort, black) are advisory in CI; flake8,
mypy, the license-header gate, `node --check`, and ESLint hard
fail. Opt in to automatic formatting with `pre-commit install`
(config at `.pre-commit-config.yaml`).

## Tooling scripts

`tools/` holds developer tooling that isn't part of the runtime:

* `install.sh`: shared launcher bootstrap (sourced by RUN-Linux
  / RUN-Mac).
* `install.bat`: Windows equivalent (called by RUN-Windows.bat).
* `capture_screens.py`: drives the offscreen Qt build through
  the scripted demo states and saves PNGs to `.github/screenshots/`.
* `profile_app.py`: cold-start cProfile of the full session,
  walking through every bundled inventory and every mode.
* `check_license_headers.py`: verifies the SPDX header in every
  distributed source file (CI hard gate); `--fix` inserts it.

`desktop/inventories/_schema.json` is the JSON Schema for
inventory files. The leading underscore tells both the desktop
dropdown and the web build to skip it (it's metadata).

Web build internals live in [web/README.md](web/README.md).
