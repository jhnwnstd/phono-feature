# Phonology Segment & Feature Engine

A desktop tool for distinctive-feature phonology work. It browses segment
inventories, inspects feature matrices, computes natural classes, finds
minimal distinguishing feature bundles, and infers hierarchical feature
dependencies (geometry).

The engine is a pure-Python library. The GUI is a PyQt6 application.

## Quick start

You only need Python 3.11+ installed. Everything else (virtualenv,
dependencies, the console script) is set up the first time you launch.

| Your platform | Double-click this file |
|---------------|------------------------|
| macOS         | `RUN-Mac.command`      |
| Windows       | `RUN-Windows.bat`      |
| Linux         | `RUN-Linux.sh`         |

The first launch creates a private `app/.venv/` and installs the package
into it. Expect under a minute on a typical connection (PyQt6 alone is
about 60 MB). Every later launch reuses that environment and starts the
GUI immediately.

If you don't have Python yet, install it from
<https://www.python.org/downloads/> and try the launcher again.

### macOS first-launch note

Gatekeeper may block an unsigned `.command` file the first time. Right-click
`RUN-Mac.command`, choose **Open**, and confirm. Subsequent double-clicks
work normally.

### Windows first-launch note

SmartScreen may warn about an unrecognized script. Click **More info**,
then **Run anyway**. Subsequent launches run without prompts.

### Linux first-launch note

If your file manager doesn't offer a "Run" option for `.sh` files, open a
terminal in this folder and execute `./RUN-Linux.sh`. If you get a
permission error, run `chmod +x RUN-Linux.sh` first; some download
methods strip the executable bit.

## Features

- **Inventory browser** loads a JSON inventory and walks every segment by
  its distinctive features.
- **Natural-class solver** takes any set of segments and returns the
  minimal feature bundle that selects exactly that set, when one exists.
- **Distance and nearest neighbors** computes per-pair Hamming distance
  over contrastive features and supports k-nearest-neighbor lookup.
- **Feature geometry inference** runs permutation tests to identify which
  features statistically depend on others.
- **Inventory builder** opens a separate window for authoring or editing
  inventories with keyboard-friendly +/-/0 cycling.
- **Live theme swap** toggles light and dark mode in place without a
  restart.

## Bundled inventories

Four feature sets ship under `app/inventories/`. The GUI lists them in
its inventory dropdown automatically.

| File                       | Source                                          |
|----------------------------|-------------------------------------------------|
| `hayes_features.json`      | Hayes (2009), Introductory Phonology            |
| `blevins_features.json`    | Blevins (2004), Evolutionary Phonology          |
| `general_features.json`    | General-purpose IPA superset                    |
| `english_features.json`    | English-focused inventory                       |

Author your own through the **New Inventory** flow in the GUI, or write a
JSON file that matches the schema validated in
`app/src/phonology_features/engine/inventory_validator.py`.

## For developers

The full source lives under `app/`. If you've already launched once via
`RUN-*`, the venv is set up; otherwise do it manually:

```bash
cd app
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate.bat
pip install -e ".[dev]"             # pytest, mypy, ruff
```

Then:

```bash
pytest                              # full suite, runs headless
pytest tests/test_engine_api.py     # engine-only smoke (no PyQt)
```

Repository layout:

```
.
├── README.md
├── LICENSE
├── RUN-Mac.command            # double-click launcher (macOS)
├── RUN-Windows.bat            # double-click launcher (Windows)
├── RUN-Linux.sh               # launcher (Linux)
└── app/                       # everything below this line is private
    ├── pyproject.toml
    ├── requirements.txt
    ├── inventories/           # bundled JSON feature inventories
    ├── src/phonology_features/  # library + GUI package
    └── tests/                 # pytest suite (offscreen Qt for GUI tests)
```

## License

MIT. See [LICENSE](LICENSE).
