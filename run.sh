#!/usr/bin/env bash
# Auto-setup launcher for media_finder.py
#
# Replaces READ.md: performs the setup steps automatically (create the venv,
# check that every dependency e.g. yt-dlp is installed and install anything
# that is missing) and then runs the main script with all passed arguments.
#
# Usage:
#   ./run.sh "apostle babs adewumi"
#   ./run.sh "apostle babs adewumi" --source telegram --limit 20

set -u

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]:-$0}")")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

PYTHON="${PYTHON:-python3}"
VENV_DIR="${VENV_DIR:-venv}"
REQ_FILE="requirements.txt"

# --- Step 0: python3 must exist -------------------------------------------
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "ERROR: '$PYTHON' was not found. Install Python 3.10+ first." >&2
    exit 1
fi

# --- Step 1 (README.md): create the virtual environment if missing --------
if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "==> Creating virtual environment in '$VENV_DIR' ..."
    if ! "$PYTHON" -m venv "$VENV_DIR"; then
        echo "ERROR: could not create the virtual environment." >&2
        echo "On Debian/Ubuntu install it with: sudo apt install python3-venv" >&2
        exit 1
    fi
fi

VENV_PY="$VENV_DIR/bin/python"

# --- Step 2 (README.md): check dependencies, install what is missing ------
need_install=0
for module in yt_dlp rich telethon dotenv; do
    if ! "$VENV_PY" -c "import $module" >/dev/null 2>&1; then
        echo "==> Missing dependency: $module"
        need_install=1
    fi
done

if [ "$need_install" -eq 1 ]; then
    echo "==> Installing missing dependencies from '$REQ_FILE' ..."
    if ! "$VENV_PY" -m pip install -q -r "$REQ_FILE"; then
        echo "ERROR: failed to install dependencies." >&2
        exit 1
    fi
    echo "==> Dependencies installed."
else
    echo "==> All dependencies are already installed."
fi

# --- Step 3: run the main script with the given arguments -----------------
exec "$VENV_PY" media_finder.py "$@"