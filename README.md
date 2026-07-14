# Phonology Segment and Feature Engine

Feature phonology tool. Compute natural classes, find minimal distinguishing feature bundles, and edit segment inventories.

Browser version: <https://jhnwnstd.github.io/phono-feature/>.

## Features

- Edit and create segment inventories.
- Select any set of segments to see the features they share, the features that split them, and the minimal feature bundle that uniquely characterizes the set (when one exists).
- Toggle feature values to query in the other direction: find every segment matching a `+`/`-` spec.

## Run

Clone or download this repository. Requires
[Python 3.11+](https://www.python.org/downloads/).

| OS | Launcher |
|---|---|
| macOS | `RUN-Mac.command` |
| Windows | `RUN-Windows.bat` |
| Linux | `RUN-Linux.sh` |

The first launch sets up the app. Later launches start immediately.

macOS may block unsigned command files: right click `RUN-Mac.command`, choose **Open**, then confirm. Windows may show a SmartScreen warning: click **More info**, then **Run anyway**. Linux file managers may refuse to launch shell scripts; run from a terminal (`chmod +x RUN-Linux.sh` first if needed).

## Inventories

Bundled inventories live in `desktop/inventories/` and appear in the inventory dropdown. The bundled set covers the Hayes 2009 universal phoneme inventory and a range of language inventories (English, German, Hindi, Japanese, Korean, Mandarin, Spanish, Arabic, Turkish, and more). Add and build your own through **New** in the inventory editor,
or load any of PHOIBLE's 3,000+ language inventories through the
**PHOIBLE** button.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the repo layout, the desktop / shared / web relay contract, where the tests live, and the lint and verification chain. [web/README.md](web/README.md) covers the web build internals.

## License

PolyForm Noncommercial 1.0.0. See [LICENSE](LICENSE). Free for
personal, academic, and other noncommercial use. For commercial
licensing, open an issue or reach the author through this
repository's profile. Bundled third-party materials keep their own
licenses: PHOIBLE 2.0 data is CC BY-SA 3.0 and the Charis SIL font
is OFL 1.1 (see `PHOIBLE_LICENSE.txt` and `CHARIS_SIL_LICENSE.txt`).
