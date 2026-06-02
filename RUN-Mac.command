#!/usr/bin/env bash
# Single-step launcher for macOS. Double-click in Finder to run.
#
# .command files open in Terminal automatically; the script below sets
# up a virtualenv in app/.venv/ on first run, installs the package,
# and launches the GUI. Subsequent double-clicks reuse the same venv
# and start instantly. The bootstrap logic lives in scripts/install.sh
# so both desktop launchers share it.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=scripts/install.sh
source "$SCRIPT_DIR/scripts/install.sh"
phono_install "macOS"

exec phonology-features "$@"
