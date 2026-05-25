# Phonology Segment and Feature Engine

A desktop tool for distinctive feature phonology. It supports segment inventories, natural class search, and minimal distinguishing feature bundles.

Browser version: <https://jhnwnstd.github.io/features/>

The browser version uses the same engine and inventories. It runs locally in the browser. You can upload JSON inventories and download your work.

## Features

- View and edit segment inventories.
- Search for natural classes by feature criteria.
- Find the features that distinguish a segment from a natural class.
- Find the smallest feature set that distinguishes two segments.
- Create inventories for any language.

## Run

Requires Python 3.11+.

Use the launcher for your operating system.

| OS | Launcher |
|---|---|
| macOS | `RUN-Mac.command` |
| Windows | `RUN-Windows.bat` |
| Linux | `RUN-Linux.sh` |

The first launch creates a local Python environment. Later launches open the app directly.

Install Python from <https://www.python.org/downloads/> if your system does not have it.

### OS notes

macOS may block unsigned command files. Right click `RUN-Mac.command`, choose **Open**, then confirm.

Windows may show a SmartScreen warning. Click **More info**, then **Run anyway**.

Linux file managers may not run shell scripts directly. Open a terminal in the project folder and run:

```bash
./RUN-Linux.sh
````

If needed, make the launcher executable first:

```bash
chmod +x RUN-Linux.sh
```

## Inventories

Bundled inventories live in `app/inventories/` and appear in the app menu.

| File                    | Description                    |
| ----------------------- | ------------------------------ |
| `hayes_features.json`   | Hayes 2009 inventory           |
| `general_features.json` | General IPA oriented inventory |
| `english_features.json` | English oriented inventory     |

You can add inventories through **New Inventory** in the app.

## Development

The engine is pure Python. The GUI uses PyQt6.

```bash
cd app
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
pytest tests/test_engine_api.py
```

On Windows, activate the environment with:

```bat
.venv\Scripts\activate.bat
```

## Repository layout

```text
.
├── README.md
├── LICENSE
├── RUN-Mac.command
├── RUN-Windows.bat
├── RUN-Linux.sh
└── app/
    ├── pyproject.toml
    ├── inventories/
    ├── src/phonology_features/
    └── tests/
```

## License

MIT. See [LICENSE](LICENSE).
