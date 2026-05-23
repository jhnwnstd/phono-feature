# Phonology Segment & Feature Engine

A desktop tool for distinctive-feature phonology. Browse segment inventories, compute natural classes, find minimal distinguishing feature bundles, and infer hierarchical feature geometry.

## Run it

Requires Python 3.11+. Double-click the launcher for your OS. The first run sets up a private environment in under a minute. Later launches open the GUI immediately.

| OS      | File              |
|---------|-------------------|
| macOS   | `RUN-Mac.command` |
| Windows | `RUN-Windows.bat` |
| Linux   | `RUN-Linux.sh`    |

If Python is missing, install it from <https://www.python.org/downloads/> and try again.

**First-launch warnings.** macOS Gatekeeper blocks unsigned `.command` files. Right-click the launcher, choose **Open**, and confirm. Windows SmartScreen flags unrecognized scripts. Click **More info**, then **Run anyway**. On Linux, if `.sh` files won't run from the file manager, open a terminal here and run `./RUN-Linux.sh` (prefix with `chmod +x RUN-Linux.sh` if a permission error appears).

## What it does

- **Inventory browser** walks every segment by its distinctive features.
- **Natural-class solver** returns the minimal feature bundle selecting exactly a chosen set of segments, when one exists.
- **Inventory builder** authors or edits inventories with +/-/0 keyboard cycling.

## Bundled inventories

Four feature sets live in `app/inventories/` and appear automatically in the GUI dropdown.

| File                       | Source                                  |
|----------------------------|-----------------------------------------|
| `hayes_features.json`      | Hayes (2009), Introductory Phonology    |
| `blevins_features.json`    | Blevins (2004), Evolutionary Phonology  |
| `general_features.json`    | General-purpose IPA superset            |
| `english_features.json`    | English-focused inventory               |

Add your own through **New Inventory** in the GUI, or write a JSON file matching the schema in `app/src/phonology_features/engine/inventory_validator.py`.

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
    ├── requirements.txt
    ├── inventories/
    ├── src/phonology_features/   # engine + GUI
    └── tests/
```

## License

MIT. See [LICENSE](LICENSE).
