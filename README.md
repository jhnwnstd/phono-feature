# Phonology Segment and Feature Engine

Distinctive-feature phonology tool. Browse inventories, compute natural classes, find minimal distinguishing feature bundles.

Browser version: <https://jhnwnstd.github.io/features/>.

## Features

- Browse, edit, and create segment inventories.
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

Bundled inventories live in `app/inventories/` and appear in the app menu.

| File                    | Description                    |
| ----------------------- | ------------------------------ |
| `hayes_features.json`   | Hayes 2009 inventory           |
| `general_features.json` | General IPA oriented inventory |
| `english_features.json` | English oriented inventory     |

You can add and build inventories through **New Inventory** in the app.

## Development

The engine is pure Python in `packages/phonology-engine/`. The desktop GUI in `app/` uses PyQt6 and depends on the engine. The browser version in `web/` reuses the same engine via Pyodide.

The launcher creates `app/.venv/` and installs both packages editable. Activate it to run the tests:

```bash
./RUN-Linux.sh                                  # creates app/.venv
source app/.venv/bin/activate
pytest app/tests                                # GUI + integration
pytest packages/phonology-engine/tests          # engine, no Qt
```

Manual setup without the launcher (any OS):

```bash
python -m venv app/.venv
source app/.venv/bin/activate                   # Windows: app\.venv\Scripts\activate.bat
pip install -e packages/phonology-engine -e "app[dev]"
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
├── app/                    # desktop GUI (PyQt6)
│   ├── pyproject.toml
│   ├── inventories/
│   ├── src/phonology_features/
│   └── tests/
├── web/                    # browser version (static, Pyodide)
│   ├── api.py
│   ├── index.html
│   ├── main.js
│   ├── style.css
│   └── scripts/build.py
└── packages/
    └── phonology-engine/   # shared pure-Python engine
        ├── pyproject.toml
        ├── src/phonology_engine/
        └── tests/
```

## License

MIT. See [LICENSE](LICENSE).
