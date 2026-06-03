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

macOS may block unsigned command files: right click `RUN-Mac.command`, choose **Open**, then confirm. Windows may show a SmartScreen warning: click **More info**, then **Run anyway**. Linux file managers may refuse to launch shell scripts; run from a terminal (`chmod +x RUN-Linux.sh` first if needed).

## Inventories

Bundled inventories live in `desktop/inventories/` and appear in the app menu. The bundled set covers Hayes 2009, a general IPA inventory, and English. Add and build your own through **New Inventory** in the app.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the repo layout, the desktop / shared / web relay contract, where the tests live, and the lint and verification chain. [web/README.md](web/README.md) covers the web build internals.

## License

MIT. See [LICENSE](LICENSE).
