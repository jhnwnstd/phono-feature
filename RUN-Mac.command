#!/usr/bin/env bash
# Single-step launcher for macOS. Double-click in Finder to run.
#
# .command files open in Terminal automatically; the script below sets up a
# virtualenv in app/.venv/ on first run, installs the package, and launches
# the GUI. Subsequent double-clicks reuse the same venv and start instantly.
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
        echo
        echo "Error: Python ${MIN_PY}+ required but not found on PATH."
        echo "Install Python from https://www.python.org/downloads/ and try again."
        echo
        read -r -p "Press Enter to close..."
        exit 1
    }
    echo "Setting up Phonology Segment & Feature Engine (first run)..."
    echo "Creating virtual environment with $PYTHON ..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

ENGINE_DIR="../packages/phonology-engine"
ENGINE_PYPROJECT="$ENGINE_DIR/pyproject.toml"

if [[ ! -f "$STAMP" ]] || [[ "pyproject.toml" -nt "$STAMP" ]] \
        || [[ "$ENGINE_PYPROJECT" -nt "$STAMP" ]]; then
    echo "Installing dependencies ..."
    pip install --quiet --upgrade pip
    # Engine first so the app's resolver sees a satisfied
    # phonology-engine dep instead of going to PyPI for it.
    pip install --quiet -e "$ENGINE_DIR"
    pip install --quiet -e .
    touch "$STAMP"
fi

phonology-features "$@"
