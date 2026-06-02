# Contributing

A short orientation for people landing in the repo for the first time.
Once you have the launcher running (see [README.md](README.md#run)),
this file explains the deliberate parts of the layout so a change in
one place doesn't silently rot another.

## The relay system: one Python source, two UIs

The desktop app (PyQt6) and the browser app (Pyodide) are two
front-ends over the same engine and the same renderer. The pattern:

1. Pure-Python modules live in `app/src/phonology_features/gui/shared/`.
   They have **no module-level Qt imports** (the few Qt classes used
   inside `palette.py` are imported lazily inside functions).
2. `web/scripts/build.py:RELAYED_SOURCES` lists each shared module by
   filename. The build script copies them into
   `web/dist/render/phonology_features/gui/shared/`.
3. The web bridge (`web/api.py`) imports from
   `phonology_features.gui.shared.<name>` at runtime inside Pyodide,
   so any change you make in `shared/` reaches both UIs on the next
   `python web/scripts/build.py`.

In addition to the source relay, two CSS files are generated at
build time from the same Python constants the desktop reads:

* `dist/theme.css` from `shared/palette.py` (LIGHT, DARK, COLORBLIND_*
  dicts).
* `dist/layout.css` from `shared/layout.py` (pane-width thresholds,
  per-row heights, analysis-pane sizing).

If you find yourself adding a number to `web/style.css` that already
exists in `shared/layout.py`, route it through the generator instead
and consume the CSS variable. Parity tests in `app/tests/` will fail
loudly if a layout literal in CSS disagrees with the Python source.

## Three-tier `gui/` layout

```
app/src/phonology_features/gui/
├── shared/         relayed to the web; no Qt at import time
├── controllers/    desktop-only orchestration objects MainWindow owns
├── builder/        Inventory Builder window and helpers
└── *.py            desktop Qt widgets (MainWindow, widgets, vowel_chart,
                    themed_widgets, style_utils, _themed_style_cache)
```

The boundary rules:

* `shared/` is the only place web-relayed code lives. Anything that
  imports `PyQt6.QtWidgets` at module scope belongs in `gui/` proper,
  not `shared/`.
* `controllers/` holds the four desktop-only orchestrators
  (`GeometryController`, `ModeController`, `ThemeController`,
  `InventoryDirController`). They are constructed and owned by
  `MainWindow` and have no module-private (`_`-prefixed) class
  prefix because they are no longer module-internal.
* `builder/` is self-contained and uses `shared/` for its grid-logic
  helpers.

When you add a new module, the first question is "would the web need
this too?" If yes, it goes in `shared/` and the build relay needs
the filename appended to `RELAYED_SOURCES`.

## Launchers and the install bootstrap

Three single-step launchers live at the repo root:

* `RUN-Linux.sh`
* `RUN-Mac.command`
* `RUN-Windows.bat`

Each launcher delegates to a shared bootstrap in `scripts/`:

* the two Unix launchers `source scripts/install.sh` and call
  `phono_install`;
* the Windows launcher `call`s `scripts\install.bat`.

Both bootstraps pick a Python 3.11+ interpreter, create `app/.venv/`
on first run, install the engine and the app in editable mode, and
stamp `app/.venv/.installed` so subsequent runs skip the install
step unless `pyproject.toml` changes.

If you change the launcher contract (Python version, install flags,
venv location), change `scripts/install.sh` and `scripts/install.bat`
together so the three launchers stay in lockstep.

## Where tests live

| Suite                              | What it covers                                |
|------------------------------------|-----------------------------------------------|
| `packages/phonology-engine/tests/` | Pure-Python engine: Inventory, FeatureEngine, geometry. No Qt. |
| `app/tests/`                       | Desktop GUI + integration. Boots PyQt6 under `QT_QPA_PLATFORM=offscreen`. |
| `app/tests/test_jsfallback_parity.py`, `test_status_text_relay.py` | Pin the web's pre-bridge JS mirrors and the build-time JSON bake against the Python source they shadow. |
| `web/scripts/smoke.py`             | Playwright end-to-end: boots the built site through Pyodide, drives the bridge, and asserts the analysis pane populates. |

## Lint and verification chain

The CI pipeline runs the lint chain from the repo root and the test
suites from each package:

```bash
app/.venv/bin/python -m isort . --profile black --check-only
app/.venv/bin/python -m black -l 79 --check .
app/.venv/bin/python -m flake8 app/ packages/ web/scripts/
app/.venv/bin/python -m mypy

app/.venv/bin/python -m pytest packages/phonology-engine -q
app/.venv/bin/python -m pytest app/tests -q

app/.venv/bin/python web/scripts/build.py
app/.venv/bin/python web/scripts/smoke.py
```

`uv.lock` is committed; `uv lock --check` should pass before any
dependency-touching change lands.

## Tooling scripts

`scripts/` holds developer tooling that isn't part of the runtime:

* `install.sh` -- shared launcher bootstrap (sourced by RUN-Linux /
  RUN-Mac).
* `install.bat` -- Windows equivalent (called by RUN-Windows.bat).
* `capture_screens.py` -- drives the offscreen Qt build through the
  scripted demo states and saves PNGs to `.github/screenshots/`.
* `profile_app.py` -- cold-start cProfile of the full session,
  walking through every bundled inventory and every mode.

`app/inventories/_schema.json` is the JSON Schema for inventory
files. The leading underscore tells both the desktop dropdown and
the web build to skip it (it's metadata, not a loadable inventory).

## More

* Web build internals and the relay contract in detail:
  [web/README.md](web/README.md).
* High-level project overview, run instructions, and repo layout:
  [README.md](README.md).
