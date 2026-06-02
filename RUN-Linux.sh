#!/usr/bin/env bash
# Single-step launcher for Linux.
#
# First run: creates a local virtualenv in app/.venv/ and installs the
# package in editable mode. Subsequent runs reuse the same venv and
# re-install only when app/pyproject.toml has changed. The bootstrap
# logic lives in scripts/install.sh so both desktop launchers share it.
#
# Pass-through args go to the app, e.g.:
#     ./RUN-Linux.sh app/inventories/hayes_features.json
#     ./RUN-Linux.sh -platform xcb
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=scripts/install.sh
source "$SCRIPT_DIR/scripts/install.sh"
phono_install "Linux"

exec phonology-features "$@"
