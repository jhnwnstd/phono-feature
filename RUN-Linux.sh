#!/usr/bin/env bash
# Single-step launcher for Linux.
#
# First run: creates a local virtualenv in desktop/.venv/ and installs
# the package in editable mode. Subsequent runs reuse the same venv and
# re-install only when desktop/pyproject.toml has changed. The
# bootstrap logic lives in tools/install.sh so both desktop launchers
# share it.
#
# Pass-through args go to the app, e.g.:
#     ./RUN-Linux.sh desktop/inventories/hayes_features.json
#     ./RUN-Linux.sh -platform xcb
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=tools/install.sh
source "$SCRIPT_DIR/tools/install.sh"
phono_install "Linux"

exec "$PHONO_BIN" "$@"
