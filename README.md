# Phonology Segment and Feature Engine

Feature phonology tool. Compute natural classes, find minimal distinguishing feature bundles, and edit segment inventories.

Browser version: <https://jhnwnstd.github.io/phono-feature/>.

## Features

- Edit and create segment inventories.
- Select any set of segments to see the features they share, the features that split them, and the minimal feature bundle that uniquely characterizes the set (when one exists).
- Toggle feature values to query in the other direction: find every segment matching a `+`/`-` spec.

## Run

Requires [Python 3.11+](https://www.python.org/downloads/).

| OS | Launcher |
|---|---|
| macOS | `RUN-Mac.command` |
| Windows | `RUN-Windows.bat` |
| Linux | `RUN-Linux.sh` |

The first launch sets up the app. Later launches start immediately.

### OS notes

macOS may block unsigned command files. Right click `RUN-Mac.command`, choose **Open**, then confirm.

Windows may show a SmartScreen warning. Click **More info**, then **Run anyway**.

Linux file managers may refuse to launch shell scripts; run from a terminal instead. If you get a permission error, `chmod +x RUN-Linux.sh` first.

## Inventories

Bundled inventories live in `desktop/inventories/` and appear in the app menu.

| File                    | Description                    |
| ----------------------- | ------------------------------ |
| `hayes_features.json`   | Hayes 2009 inventory           |
| `general_features.json` | General IPA oriented inventory |
| `english_features.json` | English oriented inventory     |

You can add and build inventories through **New Inventory** in the app.

## Development

The pure-Python core lives in `shared/` (`phonology_shared.engine` for computation, `phonology_shared.render` for UI-agnostic render and view-model helpers). The desktop GUI in `desktop/` uses PyQt6 and depends on the shared core. The browser version in `web/` reuses the same core via Pyodide.

[CONTRIBUTING.md](CONTRIBUTING.md) covers the relay system, the desktop / shared / web layout, how the launchers are wired, and where the tests live. [web/README.md](web/README.md) covers the web build internals and what gets relayed from the shared sources.

The launcher creates `desktop/.venv/` and installs all three workspace packages editable. Activate it to run the tests:

```bash
./RUN-Linux.sh                                  # creates desktop/.venv
source desktop/.venv/bin/activate
pytest shared/tests                             # engine + render, no Qt
pytest desktop/tests                            # GUI + integration
pytest web/tests                                # bridge validation
```

Manual setup without the launcher (any OS):

```bash
python -m venv desktop/.venv
source desktop/.venv/bin/activate               # Windows: desktop\.venv\Scripts\activate.bat
pip install -e shared -e "desktop[dev]" -e web
```

## Repository layout

```text
.
├── README.md
├── LICENSE
├── pyproject.toml          # workspace marker
├── RUN-Mac.command
├── RUN-Windows.bat
├── RUN-Linux.sh
├── desktop/                # desktop GUI (PyQt6) + canonical inventories
│   ├── pyproject.toml
│   ├── inventories/
│   ├── src/phonology_features/
│   └── tests/
├── shared/                 # pure-Python core, consumed by both UIs
│   ├── pyproject.toml
│   ├── src/phonology_shared/
│   │   ├── engine/         # computation core (Inventory, FeatureEngine)
│   │   └── render/         # UI-agnostic render + view-model helpers
│   └── tests/
├── web/                    # browser version (static, Pyodide)
│   ├── pyproject.toml
│   ├── src/phonology_web/api.py
│   ├── index.html
│   ├── main.js
│   ├── style.css
│   ├── scripts/build.py
│   └── tests/
└── tools/                  # developer tooling + shared launcher bootstrap
    ├── install.sh
    ├── install.bat
    ├── capture_screens.py
    └── profile_app.py
```

## License

MIT. See [LICENSE](LICENSE).
