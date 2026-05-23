#!/usr/bin/env bash
# Single-step launcher for Linux.
#
# First run: creates a local virtualenv in app/.venv/ and installs the
# package in editable mode. Subsequent runs reuse the same venv and
# re-install only when app/pyproject.toml has changed.
#
# Pass-through args go to the app, e.g.:
#     ./RUN-Linux.sh app/inventories/hayes_features.json
#     ./RUN-Linux.sh -platform xcb
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/app"

VENV_DIR=".venv"
STAMP="$VENV_DIR/.installed"
MIN_PY="3.11"

pick_python() {
    for candidate in python3.13 python3.12 python3.11 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (${MIN_PY/./, }) else 1)" 2>/dev/null; then
                echo "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

if [[ ! -d "$VENV_DIR" ]]; then
    PYTHON="$(pick_python)" || {
        echo "Error: Python ${MIN_PY}+ required but not found on PATH." >&2
        echo "Install a recent Python (${MIN_PY}+) and try again." >&2
        read -r -p "Press Enter to close..."
        exit 1
    }
    echo "Setting up Phonology Segment & Feature Engine (first run)..."
    echo "Creating virtual environment with $PYTHON ..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

if [[ ! -f "$STAMP" ]] || [[ "pyproject.toml" -nt "$STAMP" ]]; then
    echo "Installing dependencies ..."
    pip install --quiet --upgrade pip
    pip install --quiet -e .
    touch "$STAMP"
fi

exec phonology-features "$@"
