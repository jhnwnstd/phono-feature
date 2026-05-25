# Phonology Segment & Feature Engine

A desktop tool for distinctive-feature phonology. Browse segment inventories, compute natural classes, and find minimal distinguishing feature bundles.

**Use it in your browser:** <https://jhnwnstd.github.io/features/>. Same engine, same inventories, no install. Upload your own JSON to analyse it; download anything you build. Everything stays in your browser.

## Run it

Requires Python 3.11+. Double-click the launcher for your OS. The first run sets up a private environment in under a minute; later launches open the GUI immediately.

| OS      | Launcher          |
|---------|-------------------|
| macOS   | `RUN-Mac.command` |
| Windows | `RUN-Windows.bat` |
| Linux   | `RUN-Linux.sh`    |

If Python is missing, install it from <https://www.python.org/downloads/>.

First-launch quirks by OS:

- **macOS:** Gatekeeper blocks unsigned `.command` files. Right-click the launcher, choose **Open**, and confirm.
- **Windows:** SmartScreen flags unrecognized scripts. Click **More info**, then **Run anyway**.
- **Linux:** If the file manager won't launch `.sh` files, open a terminal here and run `./RUN-Linux.sh` (prefix with `chmod +x RUN-Linux.sh` once if you get a permission error).

## What it does

- **Inventory browser:** every segment as a +/-/0 distinctive-feature bundle.
- **Natural-class solver:** the minimal feature bundle that picks exactly a chosen segment set, when one exists.
- **Inventory builder:** author or edit inventories with +/-/0 keyboard cycling.

## Bundled inventories

Three feature sets live in `app/inventories/` and appear automatically in the GUI dropdown.

| File                       | Source                                  |
|----------------------------|-----------------------------------------|
| `hayes_features.json`      | Hayes (2009), Introductory Phonology    |
| `general_features.json`    | General-purpose IPA superset            |
| `english_features.json`    | English-focused inventory               |

Add your own through **New Inventory** in the GUI, or write a JSON file matching the schema in `app/src/phonology_features/engine/inventory.py` (see `Inventory.parse`).

## For developers

Pure-Python engine, PyQt6 GUI. Set up the dev environment manually.

```bash
cd app
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate.bat
pip install -e ".[dev]"
pytest                              # full suite, headless
pytest tests/test_engine_api.py     # engine-only, no Qt
```

Repository layout.

```
.
├── README.md
├── LICENSE
├── RUN-Mac.command / RUN-Windows.bat / RUN-Linux.sh
└── app/
    ├── pyproject.toml
    ├── inventories/
    ├── src/phonology_features/   # engine + GUI
    └── tests/
```

## License

MIT. See [LICENSE](LICENSE).
