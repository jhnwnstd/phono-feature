#!/usr/bin/env bash
# Shared install bootstrap for the desktop launchers (sourced, not
# executed). Defines phono_install, which creates desktop/.venv on
# first call and refreshes the editable install when either
# pyproject.toml is newer than the marker stamp. Sets PHONO_BIN to
# the absolute path of the venv's phonology-features console script
# so launchers ``exec`` it directly and avoid any shim/PATH lookup
# (pyenv-virtualenv, conda, asdf etc. would otherwise intercept
# the bare command name even with the venv on PATH).
#
# Usage from a launcher:
#     source "$REPO_ROOT/tools/install.sh"
#     phono_install "macOS"     # or "Linux"
#     exec "$PHONO_BIN" "$@"

# Minimum Python version. Bump together with desktop/pyproject.toml's
# requires-python; the pick_python check guards both.
PHONO_MIN_PY="3.11"

phono_pick_python() {
    local candidate
    for candidate in python3.13 python3.12 python3.11 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (${PHONO_MIN_PY/./, }) else 1)" 2>/dev/null; then
                echo "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

# $1: human-readable platform name used in the install-Python hint
#     when no suitable interpreter is found.
phono_install() {
    local platform_name="${1:-this platform}"
    local repo_root
    repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    cd "$repo_root/desktop"

    local venv_dir=".venv"
    local stamp="$venv_dir/.installed"
    local shared_dir="../shared"
    local shared_pyproject="$shared_dir/pyproject.toml"

    if [[ ! -d "$venv_dir" ]]; then
        local python
        python="$(phono_pick_python)" || {
            echo "Error: Python ${PHONO_MIN_PY}+ required but not found on PATH." >&2
            echo "Install a recent Python (${PHONO_MIN_PY}+) for ${platform_name} and try again." >&2
            read -r -p "Press Enter to close..."
            exit 1
        }
        echo "Setting up Phonology Segment & Feature Engine (first run)..."
        echo "Creating virtual environment with $python ..."
        "$python" -m venv "$venv_dir"
    fi

    # shellcheck source=/dev/null
    source "$venv_dir/bin/activate"

    if [[ ! -f "$stamp" ]] \
            || [[ "pyproject.toml" -nt "$stamp" ]] \
            || [[ "$shared_pyproject" -nt "$stamp" ]]; then
        echo "Installing dependencies ..."
        pip install --quiet --upgrade pip
        # Shared first so the app's resolver sees a satisfied
        # phonology-shared dep instead of going to PyPI for it.
        pip install --quiet -e "$shared_dir"
        pip install --quiet -e .
        # Web bridge is a workspace member so lint/mypy/pytest can
        # see it from the same venv; runtime only needs api.py via
        # the Pyodide bundle.
        pip install --quiet -e "../web"
        touch "$stamp"
    fi

    # Absolute path to the console script so the launcher's exec
    # bypasses pyenv-virtualenv / conda / asdf shims that would
    # otherwise intercept the bare ``phonology-features`` name.
    PHONO_BIN="$repo_root/desktop/$venv_dir/bin/phonology-features"
    export PHONO_BIN
}
