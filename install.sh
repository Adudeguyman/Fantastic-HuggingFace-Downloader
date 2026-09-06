#!/usr/bin/env bash
#
# Fantastic HuggingFace Downloader installer.
#
# Everything is installed INSIDE this folder: the virtual environment goes in
# ./venv next to the app. Nothing is copied to a hidden location. To move the
# install, move the folder. To remove it, delete the folder.
#
# The only things that can land outside this folder are an applications-menu
# entry, a desktop shortcut and a PATH launcher, and each is asked about
# separately and defaults to no.

set -euo pipefail

APP="fantastic-huggingface-downloader"
CMD="fantastic-hf"          # short name for the optional terminal command
APPNAME="Fantastic HuggingFace Downloader"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SRC_DIR/venv"
APP_PY="$SRC_DIR/fantastic_huggingface_downloader.py"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_FILE="$DESKTOP_DIR/$APP.desktop"

say() { printf '%s\n' "$*"; }

die() {
    local msg="$*"
    printf 'ERROR: %s\n' "$msg" >&2
    if [ ! -t 1 ]; then
        if command -v zenity >/dev/null 2>&1; then
            zenity --error --title="$APPNAME installer" --width=460 --text="$msg" || true
        elif command -v kdialog >/dev/null 2>&1; then
            kdialog --error "$msg" || true
        fi
    fi
    exit 1
}

# Ask a yes/no question. Falls back to zenity/kdialog with no terminal, and
# answers "no" when it cannot ask at all - nothing optional is created silently.
ask_yn() {
    local prompt="$1" default="$2" reply
    if [ -t 0 ]; then
        local hint="[y/N]"
        if [ "$default" = "y" ]; then hint="[Y/n]"; fi
        read -rp "$prompt $hint " reply
        if [ -z "$reply" ]; then reply="$default"; fi
        case "$reply" in
            y|Y|yes|YES) return 0 ;;
            *) return 1 ;;
        esac
    elif command -v zenity >/dev/null 2>&1; then
        zenity --question --width=420 --title="$APPNAME" --text="$prompt"
    elif command -v kdialog >/dev/null 2>&1; then
        kdialog --yesno "$prompt"
    else
        [ "$default" = "y" ]
    fi
}

# ------------------------------------------------- run in a visible terminal
if [ ! -t 1 ] && [ -z "${FHD_NO_RELAUNCH:-}" ]; then
    export FHD_NO_RELAUNCH=1
    INNER="bash '$SRC_DIR/install.sh'; echo; read -rp 'Press Enter to close... '"
    if command -v x-terminal-emulator >/dev/null 2>&1; then
        exec x-terminal-emulator -e bash -c "$INNER"
    elif command -v gnome-terminal >/dev/null 2>&1; then
        exec gnome-terminal -- bash -c "$INNER"
    elif command -v konsole >/dev/null 2>&1; then
        exec konsole -e bash -c "$INNER"
    elif command -v xfce4-terminal >/dev/null 2>&1; then
        exec xfce4-terminal -e "bash -c \"$INNER\""
    elif command -v mate-terminal >/dev/null 2>&1; then
        exec mate-terminal -- bash -c "$INNER"
    elif command -v xterm >/dev/null 2>&1; then
        exec xterm -e bash -c "$INNER"
    fi
fi

# ------------------------------------------------------------------- update
# Pull first, so an update to this script is picked up before we act on it.
if [ -d "$SRC_DIR/.git" ] && command -v git >/dev/null 2>&1 && [ -z "${FHD_PULLED:-}" ]; then
    if [ -n "$(git -C "$SRC_DIR" status --porcelain 2>/dev/null)" ]; then
        say "You have local changes here, so skipping the update check."
        say "Run 'git pull' yourself when you are ready."
        say ""
    elif ask_yn "Check for updates first (git pull)?" y; then
        BEFORE="$(git -C "$SRC_DIR" rev-parse HEAD 2>/dev/null || echo none)"
        if git -C "$SRC_DIR" pull --ff-only; then
            AFTER="$(git -C "$SRC_DIR" rev-parse HEAD 2>/dev/null || echo none)"
            if [ "$BEFORE" != "$AFTER" ]; then
                say ""
                say "Updated. Restarting the installer with the new version..."
                export FHD_PULLED=1
                exec bash "$SRC_DIR/install.sh" "$@"
            fi
            say "Already up to date."
        else
            say "Could not pull (no network, or the branch has diverged)."
            say "Carrying on with the version you have."
        fi
        say ""
    fi
fi

# ------------------------------------------------------------ prerequisites
[ -f "$APP_PY" ] || die "fantastic_huggingface_downloader.py is not next to this installer (looked in $SRC_DIR)."
[ -f "$SRC_DIR/theme.py" ] || die "theme.py is missing from $SRC_DIR - the app imports it for its look. Clone the whole repository."
[ -w "$SRC_DIR" ] || die "This folder is not writable, so the virtual environment cannot be created here.
Move the folder somewhere you own, such as your home directory, and try again.
Folder: $SRC_DIR"

PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON="$(command -v "$candidate")"
        break
    fi
done
[ -n "$PYTHON" ] || die "No python3 found on PATH. Install Python 3.9 or newer first."

if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
    die "$PYTHON is older than 3.9. PySide6 needs 3.9+."
fi
say "Using $PYTHON ($("$PYTHON" -c 'import platform; print(platform.python_version())'))"

if ! "$PYTHON" -m venv --help >/dev/null 2>&1; then
    HINT="install your distribution's python3-venv package"
    if [ -r /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        if [ "${ID:-}" = "debian" ] || [ "${ID_LIKE:-}" = "debian" ] || [ "${ID:-}" = "ubuntu" ] || [ "${ID:-}" = "linuxmint" ]; then
            HINT="sudo apt install python3-venv"
        elif [ "${ID:-}" = "fedora" ] || [ "${ID:-}" = "rhel" ] || [ "${ID:-}" = "centos" ]; then
            HINT="sudo dnf install python3-virtualenv"
        elif [ "${ID:-}" = "arch" ] || [ "${ID_LIKE:-}" = "arch" ]; then
            HINT="venv ships with python on Arch; check your install"
        elif [ "${ID:-}" = "opensuse-tumbleweed" ] || [ "${ID_LIKE:-}" = "suse" ]; then
            HINT="sudo zypper install python3-venv"
        fi
    fi
    die "The venv module is missing. Fix it with: $HINT"
fi

# ------------------------------------------------------------------ install
say ""
say "Installing into this folder:"
say "  $SRC_DIR"
say "The virtual environment goes in ./venv - roughly 1 GB once PySide6 is in."
say ""

if [ -d "$VENV" ]; then
    say "Reusing the existing ./venv"
else
    say "Creating ./venv ..."
    "$PYTHON" -m venv "$VENV" || die "Could not create a virtual environment at $VENV."
fi

# pip would otherwise cache several hundred MB of wheels in ~/.cache/pip.
# Keep that inside the folder and bin it once the install succeeds, so
# nothing is left anywhere else.
PIP_TMP="$SRC_DIR/.pip-cache"
cleanup_pip_cache() { rm -rf "$PIP_TMP"; }
trap cleanup_pip_cache EXIT

# Only touch pip when requirements.txt has actually changed since the last
# successful install. You should never have to work out whether it did.
REQ="$SRC_DIR/requirements.txt"
[ -f "$REQ" ] || die "requirements.txt is missing from $SRC_DIR"

hash_requirements() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$REQ" | cut -d" " -f1
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$REQ" | cut -d" " -f1
    else
        cksum "$REQ" | cut -d" " -f1
    fi
}

STAMP="$VENV/.installed-requirements"
WANT="$(hash_requirements)"
HAVE=""
[ -f "$STAMP" ] && HAVE="$(cat "$STAMP" 2>/dev/null || true)"

if [ "$WANT" = "$HAVE" ] && "$VENV/bin/python" -c "import PySide6, huggingface_hub" >/dev/null 2>&1; then
    say "Dependencies are already up to date - nothing to install."
else
    say "Installing dependencies (a few hundred MB the first time, please wait)..."
    "$VENV/bin/python" -m pip install --cache-dir "$PIP_TMP" --upgrade pip >/dev/null \
        || die "Could not upgrade pip inside ./venv."
    "$VENV/bin/python" -m pip install --cache-dir "$PIP_TMP" --upgrade -r "$REQ" \
        || die "Dependency installation failed. Scroll up for pip's output."
    printf '%s\n' "$WANT" > "$STAMP"
    say "Dependencies installed."
fi
cleanup_pip_cache

chmod +x "$SRC_DIR/run.sh" 2>/dev/null || true

say ""
say "Installed. Everything lives in $SRC_DIR"
say "  start it:   ./run.sh in this folder"
if [ -d "$SRC_DIR/.git" ]; then
    say "  update it:  run install.sh again. It pulls the latest version and only"
    say "              reinstalls dependencies if they actually changed."
else
    say "  update it:  download a newer copy over this folder, then run install.sh"
    say "              again. It only reinstalls dependencies if they changed."
    say "              (clone the git repo instead and it will self-update)"
fi
say "  remove it:  delete this folder (or run uninstall.sh)"
say ""

# ---------------------------------------------- optional, outside the folder
if ask_yn "Show it in your applications menu, so you can launch it like any other app?" n; then
    mkdir -p "$DESKTOP_DIR"
    cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=$APPNAME
GenericName=Hugging Face Downloader
Comment=Paste a Hugging Face link and download the file
Exec=$SRC_DIR/run.sh %u
Path=$SRC_DIR
Icon=folder-download
Terminal=false
Categories=Network;FileTransfer;Utility;
Keywords=huggingface;model;download;safetensors;
StartupNotify=true
EOF
    chmod 0644 "$DESKTOP_FILE"
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
    fi
    say "Created $DESKTOP_FILE"
    say "(it points back here, so moving this folder will break it)"

    DESKTOP_HOME=""
    if command -v xdg-user-dir >/dev/null 2>&1; then
        DESKTOP_HOME="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
    fi
    if [ -z "$DESKTOP_HOME" ] || [ ! -d "$DESKTOP_HOME" ]; then
        DESKTOP_HOME="$HOME/Desktop"
    fi
    if [ -d "$DESKTOP_HOME" ] && ask_yn "Also put an icon on your desktop?" n; then
        cp -f "$DESKTOP_FILE" "$DESKTOP_HOME/$APP.desktop"
        chmod 0755 "$DESKTOP_HOME/$APP.desktop"
        if command -v gio >/dev/null 2>&1; then
            gio set "$DESKTOP_HOME/$APP.desktop" metadata::trusted true >/dev/null 2>&1 || true
        fi
        say "Created $DESKTOP_HOME/$APP.desktop"
    fi
fi

say ""
say "Only if you use a terminal: a '$CMD' command lets you start the app by"
say "typing $CMD from any folder, instead of opening this one. If you plan"
say "to launch it from the menu or run.sh, you do not need this."
if ask_yn "Add the '$CMD' terminal command?" n; then
    mkdir -p "$BIN_DIR"
    cat > "$BIN_DIR/$CMD" <<EOF
#!/usr/bin/env bash
exec "$SRC_DIR/run.sh" "\$@"
EOF
    chmod 0755 "$BIN_DIR/$CMD"
    say "Created $BIN_DIR/$CMD"
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *) say "Note: $BIN_DIR is not on your PATH yet, so '$CMD' will not resolve until it is." ;;
    esac
fi

if ask_yn "Start it now?" n; then
    # The app must outlive this installer AND the terminal it runs in. A plain
    # background job stays in the terminal's session, so closing that terminal
    # sends it SIGHUP and the app dies looking like a silent crash. setsid puts
    # it in its own session with no controlling terminal; nohup is the fallback
    # where setsid is missing. stdin is closed so a backgrounded process can
    # never be stopped by SIGTTIN.
    if command -v setsid >/dev/null 2>&1; then
        setsid "$SRC_DIR/run.sh" </dev/null >/dev/null 2>&1 &
    else
        nohup "$SRC_DIR/run.sh" </dev/null >/dev/null 2>&1 &
    fi
    disown 2>/dev/null || true
    sleep 1
    say "Started. You can close this window."
fi
