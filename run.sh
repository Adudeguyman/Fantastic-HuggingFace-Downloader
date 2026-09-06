#!/usr/bin/env bash
#
# Starts Fantastic HuggingFace Downloader from the venv in this folder.
# Run install.sh once first. There is no second copy anywhere else, so what
# you edit here is what runs.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SRC_DIR/venv"
APP_PY="$SRC_DIR/fantastic_huggingface_downloader.py"

complain() {
    local msg="$1"
    printf '%s\n' "$msg" >&2
    if [ ! -t 1 ]; then
        if command -v zenity >/dev/null 2>&1; then
            zenity --error --title="Fantastic HuggingFace Downloader" --width=460 --text="$msg" || true
        elif command -v kdialog >/dev/null 2>&1; then
            kdialog --error "$msg" || true
        fi
    fi
    exit 1
}

[ -f "$APP_PY" ] || complain "fantastic_huggingface_downloader.py is missing from $SRC_DIR"
[ -f "$SRC_DIR/theme.py" ] || complain "theme.py is missing from $SRC_DIR - the app imports it for its look."

if [ -x "$VENV/bin/python" ]; then
    exec "$VENV/bin/python" "$APP_PY" "$@"
fi

# No venv here, but maybe a system Python already has what we need.
if command -v python3 >/dev/null 2>&1 && python3 -c 'import PySide6, huggingface_hub' >/dev/null 2>&1; then
    exec python3 "$APP_PY" "$@"
fi

complain "Not set up yet - there is no ./venv in this folder.

Double-click install.sh here first (choose \"Run in Terminal\").
It only needs doing once, and everything stays in this folder:
$SRC_DIR"
