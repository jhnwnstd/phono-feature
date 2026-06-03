# Contributing

A short orientation for people landing in the repo for the first time.
Once you have the launcher running (see [README.md](README.md#run)),
this file explains the deliberate parts of the layout so a change in
one place doesn't silently rot another.

## The relay system: one Python source, two UIs

The desktop app (PyQt6) and the browser app (Pyodide) are two
front-ends over the same engine and the same renderer. The pattern:

1. Pure-Python modules live in `shared/src/phonology_shared/`. The
   `engine/` subpackage is the framework-agnostic computation core;
   the `render/` subpackage holds UI-agnostic render and view-model
   helpers. Neither has Qt or DOM imports at module scope.
2. `web/scripts/build.py:RELAYED_SOURCES` lists each render module
   by filename. The build copies them into
   `web/dist/render/phonology_shared/render/` plus the engine into
   `web/dist/engine/phonology_shared/engine/`, then bundles both
   into `python_bundle.zip` which Pyodide mounts via zipimport.
3. The web bridge (`web/src/phonology_web/api.py`) imports from
   `phonology_shared.{engine,render}.<name>` at runtime inside
   Pyodide, so any change you make in `shared/` reaches both UIs
   on the next `python web/scripts/build.py`.

In addition to the source relay, two CSS files are generated at
build time from the same Python constants the desktop reads:

* `dist/theme.css` from `shared/.../render/palette.py` (LIGHT,
  DARK, COLORBLIND_* dicts).
* `dist/layout.css` from `shared/.../render/layout.py` (pane-width
  thresholds, per-row heights, analysis-pane sizing).

If you find yourself adding a number to `web/style.css` that
already exists in `render/layout.py`, route it through the
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
│   │       ├── builder/     Inventory Builder window and helpers.
│   │       ├── controllers/ Desktop orchestrators (mode, theme, etc).
│   │       └── *.py         Qt widgets (MainWindow, widgets, etc).
│   ├── inventories/         Canonical JSON inventories.
│   └── tests/               Qt-dependent tests.
├── shared/                  Framework-agnostic Python both UIs use.
│   └── src/phonology_shared/
│       ├── engine/          Computation core (formerly phonology_engine).
│       └── render/          UI-agnostic render + view-model helpers.
├── web/                     Pyodide bridge + browser surface.
│   ├── src/phonology_web/api.py  JS-to-Python bridge.
│   ├── index.html, main.js, style.css, sw.js
│   ├── scripts/             build.py, smoke.py
│   └── tests/               Bridge validation tests.
└── tools/                   Dev tooling (capture_screens, install.sh, ...).
```

The boundary rules:

* `shared/` is the only place web-consumed Python lives. Anything
  that imports `PyQt6.QtWidgets` at module scope belongs in
  `desktop/src/phonology_features/gui/` proper.
* The engine never imports anything UI-shaped. `render` may
  import from `engine`; the reverse is forbidden.
* `controllers/` holds desktop-only orchestrators
  (`GeometryController`, `ModeController`, `ThemeController`,
  `InventoryDirController`).

When you add a new module, the first question is "would the web
need this too?" If yes, it goes in `shared/`. Render-side
additions also need the filename appended to `RELAYED_SOURCES`
in `web/scripts/build.py`.

## Launchers and the install bootstrap

Three single-step launchers live at the repo root:

* `RUN-Linux.sh`
* `RUN-Mac.command`
* `RUN-Windows.bat`

Each launcher delegates to a shared bootstrap in `tools/`:

* the two Unix launchers `source tools/install.sh` and call
  `phono_install`;
* the Windows launcher `call`s `tools\install.bat`.

Both bootstraps pick a Python 3.11+ interpreter, create
`desktop/.venv/` on first run, install `phonology-shared`,
`phonology-features`, and `phonology-web` in editable mode, and
stamp `desktop/.venv/.installed` so subsequent runs skip the
install step unless `pyproject.toml` changes.

If you change the launcher contract (Python version, install
flags, venv location), change `tools/install.sh` and
`tools/install.bat` together so the three launchers stay in
lockstep.

## Where tests live

| Suite                | What it covers |
|----------------------|---|
| `shared/tests/`      | Pure-Python engine + render: Inventory, FeatureEngine, geometry, layout, mode_logic, view_models. No Qt. |
| `desktop/tests/`     | Desktop GUI + integration. Boots PyQt6 under `QT_QPA_PLATFORM=offscreen`. |
| `web/tests/`         | Bridge-boundary validation: every `api.py` entry rejects bad input as `ValidationError`. |
| `shared/tests/test_jsfallback_parity.py`, `test_status_text_relay.py` | Pin the web's pre-bridge JS mirrors and the build-time JSON bake against the Python source they shadow. |
| `web/scripts/smoke.py` | Playwright end-to-end: boots the built site through Pyodide, drives the bridge, asserts the analysis pane populates. |

## Lint and verification chain

The CI pipeline runs the lint chain from the repo root and the
test suites from each package:

```bash
desktop/.venv/bin/python -m isort . --profile black --check-only
desktop/.venv/bin/python -m black -l 79 --check .
desktop/.venv/bin/python -m flake8 .
desktop/.venv/bin/python -m mypy

desktop/.venv/bin/python -m pytest shared/tests -q
desktop/.venv/bin/python -m pytest desktop/tests -q
desktop/.venv/bin/python -m pytest web/tests -q

desktop/.venv/bin/python web/scripts/build.py
desktop/.venv/bin/python web/scripts/smoke.py
```

`uv.lock` is committed; `uv lock --check` should pass before any
dependency-touching change lands.

## Tooling scripts

`tools/` holds developer tooling that isn't part of the runtime:

* `install.sh` -- shared launcher bootstrap (sourced by RUN-Linux
  / RUN-Mac).
* `install.bat` -- Windows equivalent (called by RUN-Windows.bat).
* `capture_screens.py` -- drives the offscreen Qt build through
  the scripted demo states and saves PNGs to `.github/screenshots/`.
* `profile_app.py` -- cold-start cProfile of the full session,
  walking through every bundled inventory and every mode.

`desktop/inventories/_schema.json` is the JSON Schema for
inventory files. The leading underscore tells both the desktop
dropdown and the web build to skip it (it's metadata, not a
loadable inventory).

Web build internals live in [web/README.md](web/README.md).
