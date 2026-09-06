#!/usr/bin/env bash
# Auto-setup launcher for the NK Media Finder.
#
# Sets up the virtual environment and dependencies, then launches
# the interactive media downloader (YouTube / Telegram / by-link).
#
# Usage:
#   ./auto.sh
#   ./auto.sh "apostle babs adewumi"
#   ./auto.sh "apostle babs adewumi" --source youtube --limit 20

set -u

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]:-$0}")")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

PYTHON="${PYTHON:-python3}"
VENV_DIR="${VENV_DIR:-venv}"
REQ_FILE="requirements.txt"
VENV_PY="$VENV_DIR/bin/python"

print_header() {
    echo "=========================================="
    echo "       NK Media Finder - Setup"
    echo "=========================================="
    echo
}

print_header

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "ERROR: '$PYTHON' was not found. Install Python 3.10+ first." >&2
    exit 1
fi

echo "[1/4] Creating virtual environment..."
if [ ! -x "$VENV_PY" ]; then
    if ! "$PYTHON" -m venv "$VENV_DIR"; then
        echo "ERROR: could not create the virtual environment." >&2
        echo "On Debian/Ubuntu install it with: sudo apt install python3-venv" >&2
        exit 1
    fi
    echo "Virtual environment created."
else
    echo "Virtual environment already exists. Skipping..."
fi

echo
echo "[2/4] Checking dependencies..."
need_install=0
for module in yt_dlp rich telethon dotenv; do
    if ! "$VENV_PY" -c "import $module" >/dev/null 2>&1; then
        echo "  -> Missing dependency: $module"
        need_install=1
    fi
done

if [ "$need_install" -eq 1 ]; then
    echo "  Installing missing dependencies from '$REQ_FILE' ..."
    if ! "$VENV_PY" -m pip install -q -r "$REQ_FILE"; then
        echo "ERROR: failed to install dependencies." >&2
        exit 1
    fi
    echo "  Dependencies installed."
else
    echo "  All dependencies are already installed."
fi

echo
echo "[3/4] Checking FFmpeg..."
if command -v ffmpeg >/dev/null 2>&1; then
    echo "  FFmpeg: available"
else
    echo "  Warning: FFmpeg not found. Video/mp3 merging will be limited."
    echo "  Install it with:  sudo apt install ffmpeg"
fi

echo
echo "[4/4] Starting NK Media Finder"
echo "=========================================="
echo
exec "$VENV_PY" media_finder.py "$@"