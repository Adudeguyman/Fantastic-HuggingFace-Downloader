#!/usr/bin/env bash
#
# Removes the virtual environment from this folder, plus any optional
# shortcuts the installer created outside it. Downloaded models are never
# touched. To remove the app itself, delete this folder.

set -euo pipefail

APP="fantastic-huggingface-downloader"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SRC_DIR/venv"
BIN_DIR="$HOME/.local/bin"
CMD="fantastic-hf"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

if [ ! -t 1 ] && [ -z "${FHD_NO_RELAUNCH:-}" ]; then
    export FHD_NO_RELAUNCH=1
    INNER="bash '$SRC_DIR/uninstall.sh'; echo; read -rp 'Press Enter to close... '"
    if command -v x-terminal-emulator >/dev/null 2>&1; then
        exec x-terminal-emulator -e bash -c "$INNER"
    elif command -v gnome-terminal >/dev/null 2>&1; then
        exec gnome-terminal -- bash -c "$INNER"
    elif command -v konsole >/dev/null 2>&1; then
        exec konsole -e bash -c "$INNER"
    elif command -v xterm >/dev/null 2>&1; then
        exec xterm -e bash -c "$INNER"
    fi
fi

DESKTOP_HOME=""
if command -v xdg-user-dir >/dev/null 2>&1; then
    DESKTOP_HOME="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
fi
if [ -z "$DESKTOP_HOME" ] || [ ! -d "$DESKTOP_HOME" ]; then
    DESKTOP_HOME="$HOME/Desktop"
fi

printf 'This will remove:\n'
printf '  %s\n' "$VENV" "$SRC_DIR/xet-runtime"
printf '  %s (if present)\n' "$DESKTOP_DIR/$APP.desktop" "$DESKTOP_HOME/$APP.desktop" "$BIN_DIR/$CMD"
printf '\nThe app itself and your settings.ini stay in this folder.\n'
printf 'Downloaded files are never touched.\n\n'
read -rp 'Continue? [y/N] ' reply
case "$reply" in
    y|Y|yes|YES) ;;
    *) printf 'Canceled.\n'; exit 0 ;;
esac

rm -rf "$VENV" "$SRC_DIR/xet-runtime"
rm -f "$DESKTOP_DIR/$APP.desktop" "$DESKTOP_HOME/$APP.desktop" "$BIN_DIR/$CMD" "$BIN_DIR/$APP"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi

printf '\nRemoved. Delete this folder to get rid of the rest.\n'
