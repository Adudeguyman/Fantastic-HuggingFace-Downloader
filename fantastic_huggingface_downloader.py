#!/usr/bin/env python3
"""
Fantastic HuggingFace Downloader - paste a link, pick a folder, get the file.

Wraps `hf download` with HF_XET_HIGH_PERFORMANCE=1. One URL field, a mode
selector (file / folder / whole repo / chosen files), a destination
browser and a live progress bar with speed and ETA.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import time
import urllib.parse
from collections import deque
from dataclasses import dataclass, field, replace
from pathlib import Path

from PySide6.QtCore import (
    QProcess,
    QProcessEnvironment,
    QSettings,
    QThread,
    QTimer,
    QUrl,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette

from theme import Theme, build_stylesheet, lucide_arrow_url, lucide_icon
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QTreeWidget,
    QTreeWidgetItem,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

def _configure_hf_environment() -> None:
    """
    Must run before the first `import huggingface_hub` anywhere in this
    process: huggingface_hub reads these into module constants at import time,
    so setting them afterwards has no effect. All hub imports in this file are
    deliberately inside functions so that this runs first.
    """
    os.environ["HF_XET_CHUNK_CACHE_SIZE_BYTES"] = "0"
    # With the chunk cache off there is nothing left to share between tools, so
    # point the xet runtime directory (logs, staging) into this folder too and
    # keep the whole install self-contained. The auth token is NOT moved: it
    # stays under HF_HOME so an existing `hf auth login` keeps working.
    os.environ.setdefault("HF_XET_CACHE", str(Path(__file__).resolve().parent / "xet-runtime"))


_configure_hf_environment()

APP_NAME = "fantastic-huggingface-downloader"
APP_VERSION = "1.0.0"
ORG_NAME = "fantastic-huggingface-downloader"
# Speed is averaged over a window rather than taken from one tick. Xet writes
# to disk and reports transfer in bursts, so a one-second delta swings between
# a few B/s and hundreds of MB/s and is useless either way.
SPEED_WINDOW = 8.0      # seconds of history used for the rate
SPEED_MIN_SPAN = 1.5    # need at least this much history before quoting a rate
QUEUE_ROOM = 120        # vertical space kept for the queue list at minimum size
DEFAULT_SIZE = (1060, 760)   # first run: wide enough for every queue column
MAX_HISTORY = 10        # recent destinations kept; favorites are unlimited
POLL_MS = 1000

MODE_FILE = "file"
MODE_FOLDER = "folder"
MODE_REPO = "repo"
MODE_SELECT = "select"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def human_bytes(n: float | None) -> str:
    if n is None:
        return "?"
    n = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} PiB"


def human_time(seconds: float | None) -> str:
    if seconds is None or seconds < 0 or seconds != seconds or seconds > 359999:
        return "--:--"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


IS_WINDOWS = os.name == "nt"
IS_MACOS = sys.platform == "darwin"


def no_window_kwargs() -> dict:
    """Stop helper subprocesses flashing a console window on Windows."""
    if IS_WINDOWS:
        flag = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return {"creationflags": flag}
    return {}


def drive_roots_windows() -> list[str]:
    """Every drive letter that currently exists, for the file dialog sidebar."""
    roots = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZAB":
        root = f"{letter}:\\"
        if os.path.exists(root):
            roots.append(root)
    return roots


def mount_points_unix() -> list[str]:
    """Real, user-visible mount points from /proc/mounts, for the file dialog sidebar."""
    interesting = []
    skip_prefixes = ("/proc", "/sys", "/dev", "/run", "/snap", "/var/lib/docker")
    skip_types = {
        "proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "cgroup", "cgroup2",
        "securityfs", "pstore", "autofs", "mqueue", "hugetlbfs", "debugfs",
        "tracefs", "configfs", "fusectl", "binfmt_misc", "squashfs", "ramfs",
        "bpf", "efivarfs", "nsfs", "overlay",
    }
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 3:
                    continue
                target, fstype = parts[1], parts[2]
                target = target.replace("\\040", " ")
                if fstype in skip_types:
                    continue
                if any(target.startswith(p) for p in skip_prefixes):
                    continue
                if target not in interesting:
                    interesting.append(target)
    except OSError:
        pass
    return interesting


def _as_path_list(value) -> list[str]:
    """QSettings hands back a bare string when a stored list had one entry."""
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value if str(v).strip()]


def list_mount_points() -> list[str]:
    """Sidebar entries for the destination browser, per platform."""
    if IS_WINDOWS:
        places = drive_roots_windows()
    elif IS_MACOS:
        places = [p for p in ("/", "/Volumes") if os.path.isdir(p)]
    else:
        places = mount_points_unix()
    home = str(Path.home())
    if home not in places:
        places.insert(0, home)
    for extra in ("Downloads", "Desktop"):
        candidate = Path.home() / extra
        if candidate.is_dir() and str(candidate) not in places:
            places.append(str(candidate))
    return places


# --------------------------------------------------------------------------
# URL parsing
# --------------------------------------------------------------------------

@dataclass
class Target:
    repo_id: str
    repo_type: str = "model"          # model | dataset | space
    revision: str | None = None       # None means the repo default branch
    path: str = ""                    # repo-relative path (file or folder), may be ""
    path_is_dir: bool = False         # True when the link was a /tree/ link
    source: str = ""                  # the raw text it was parsed from


class ParseError(ValueError):
    pass


def _split_revision(segments: list[str]) -> tuple[str, list[str]]:
    """
    Segments come after blob/resolve/tree. The revision is normally one segment,
    but PR and convert refs look like refs/pr/1 or refs/convert/parquet.
    """
    if not segments:
        raise ParseError("link is missing a revision and path")
    if segments[0] == "refs" and len(segments) >= 3:
        return "/".join(segments[:3]), segments[3:]
    return segments[0], segments[1:]


def parse_hf_url(text: str) -> Target:
    """
    Accepts:
      https://huggingface.co/owner/repo/blob/main/sub/file.safetensors
      https://huggingface.co/owner/repo/resolve/main/sub/file.safetensors
      https://huggingface.co/owner/repo/tree/main/sub
      https://huggingface.co/owner/repo
      https://huggingface.co/datasets/owner/repo/blob/main/file.parquet
      hf://datasets/owner/repo/file.parquet
      owner/repo
    """
    raw = (text or "").strip().strip('"').strip("'")
    if not raw:
        raise ParseError("nothing pasted yet")

    # hf:// URI form
    if raw.startswith("hf://"):
        rest = raw[len("hf://"):]
        seg = [s for s in rest.split("/") if s]
        repo_type = "model"
        if seg and seg[0] in ("models", "datasets", "spaces"):
            repo_type = {"models": "model", "datasets": "dataset", "spaces": "space"}[seg[0]]
            seg = seg[1:]
        if len(seg) < 2:
            raise ParseError("hf:// URI needs at least owner/repo")
        repo_id = "/".join(seg[:2])
        path = "/".join(seg[2:])
        return Target(repo_id, repo_type, None, path, False, raw)

    # bare owner/repo
    if "://" not in raw and "huggingface.co" not in raw:
        seg = [s for s in raw.split("/") if s]
        if len(seg) == 2 and all(seg):
            return Target("/".join(seg), "model", None, "", False, raw)
        raise ParseError("that does not look like a Hugging Face link")

    parsed = urllib.parse.urlsplit(raw)
    host = parsed.netloc.lower()
    if host and "huggingface.co" not in host and "hf.co" not in host:
        raise ParseError(f"unexpected host: {parsed.netloc}")

    seg = [urllib.parse.unquote(s) for s in parsed.path.split("/") if s]
    if not seg:
        raise ParseError("link has no repo in it")

    repo_type = "model"
    if seg[0] in ("datasets", "spaces"):
        repo_type = "dataset" if seg[0] == "datasets" else "space"
        seg = seg[1:]

    if not seg:
        raise ParseError("link has no repo in it")

    # canonical single-segment repos (bert-base-uncased) vs owner/repo
    if len(seg) >= 2 and seg[1] not in ("blob", "resolve", "tree", "raw"):
        repo_id = f"{seg[0]}/{seg[1]}"
        rest = seg[2:]
    else:
        repo_id = seg[0]
        rest = seg[1:]

    if not rest:
        return Target(repo_id, repo_type, None, "", False, raw)

    kind = rest[0]
    if kind not in ("blob", "resolve", "tree", "raw"):
        # things like /discussions, /commits - not downloadable targets
        return Target(repo_id, repo_type, None, "", False, raw)

    revision, tail = _split_revision(rest[1:])
    path = "/".join(tail)
    return Target(repo_id, repo_type, revision, path, kind == "tree", raw)


# --------------------------------------------------------------------------
# command construction
# --------------------------------------------------------------------------

def folder_prefix(target: Target) -> str:
    """
    The repo-relative directory a 'download its folder' request means.
    A /tree/ link already names the directory; a file link means its parent.
    """
    path = (target.path or "").rstrip("/")
    if not path:
        return ""
    if target.path_is_dir:
        return path
    return path.rpartition("/")[0]


_FORMAT_SUPPORT: dict[str, bool] = {}


def supports_format_flag(hf_bin: str) -> bool:
    """
    `hf download --format` defaults to 'auto', which picks agent-vs-human from
    the terminal. We run without a TTY, and any non-human mode calls
    disable_progress_bars(), which would leave us with no progress output at
    all. Pin it to human when the flag exists; older builds do not have it.
    """
    if hf_bin in _FORMAT_SUPPORT:
        return _FORMAT_SUPPORT[hf_bin]
    supported = False
    try:
        result = subprocess.run(
            [hf_bin, "download", "--help"],
            capture_output=True,
            text=True,
            timeout=15,
            **no_window_kwargs(),
        )
        supported = "--format" in (result.stdout + result.stderr)
    except (OSError, subprocess.SubprocessError):
        supported = False
    _FORMAT_SUPPORT[hf_bin] = supported
    return supported


def build_args(
    target: Target,
    mode: str,
    force_human: bool = False,
    selected: list[str] | None = None,
) -> list[str]:
    args = ["download", target.repo_id]

    if mode == MODE_SELECT:
        chosen = sorted(selected or [])
        if not chosen:
            raise ParseError("no files picked yet")
        # `hf download REPO_ID [FILENAMES]...` takes repo-relative paths as
        # positional arguments, so no --include juggling is needed here.
        args += chosen
    elif mode == MODE_FILE:
        if not target.path:
            raise ParseError("that link does not point at a specific file")
        args.append(target.path)
    elif mode == MODE_FOLDER:
        prefix = folder_prefix(target)
        if not prefix:
            raise ParseError(
                "that file sits at the repo root, so its folder is the whole repo"
            )
        # one --include per pattern: passing two patterns to a single --include
        # makes the second one a positional filename instead of a filter
        args += ["--include", f"{prefix}/*"]

    if target.repo_type != "model":
        args += ["--repo-type", target.repo_type]
    if target.revision:
        args += ["--revision", target.revision]
    if force_human:
        args += ["--format", "human"]
    return args


def extra_stylesheet(t: Theme) -> str:
    """
    QGroupBox and the tree header are not in the shared stylesheet, so they are
    styled here from the same tokens rather than with hand-picked colors.
    """
    check_icon = lucide_arrow_url("check", "#FFFFFF", 14, stroke=2.6)
    combo_arrow = lucide_arrow_url("chevron-down", t.text_secondary, 14, stroke=2.4)
    combo_arrow_off = lucide_arrow_url("chevron-down", t.text_disabled, 14, stroke=2.4)
    return f"""
    /* The shared sheet styles QComboBox::drop-down but never gives it an
       arrow. Once a stylesheet touches a combo Qt stops drawing the native
       one, so the dropdown looks like a plain text field and nobody realises
       there is a list behind it. */
    QComboBox::down-arrow {{
        image: url({combo_arrow});
        width: 14px;
        height: 14px;
    }}
    QComboBox::down-arrow:disabled {{ image: url({combo_arrow_off}); }}
    QComboBox::drop-down {{ width: 22px; subcontrol-position: center right; }}
    /* the shared sheet gives #Danger its error colour but no disabled state,
       so a greyed-out destructive button still looks armed */
    QPushButton#Danger:disabled {{
        color: {t.text_disabled};
        border-color: {t.border};
        background: transparent;
    }}
    QGroupBox {{
        background: {t.surface_1};
        border: 1px solid {t.border};
        border-radius: 6px;
        margin-top: 9px;
        padding: 7px 9px 6px 9px;
        font-weight: 600;
        color: {t.text_secondary};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
        color: {t.text_secondary};
    }}
    QTreeWidget {{
        background: {t.surface_1};
        border: 1px solid {t.border_strong};
        border-radius: 6px;
        color: {t.text_primary};
    }}
    /* the shared sheet leaves the label at Qt's default, which sits it hard
       against the left edge and half-disappears into the accent fill */
    QProgressBar {{
        text-align: center;
        color: {t.text_primary};
        min-height: 20px;
        font-weight: 600;
    }}
    /* Inline rename editors live INSIDE item views, and the shared sheet's
       QLineEdit padding (5px 10px) makes them taller than a row - Qt then
       squashes them and clips the text. Seen when creating a new folder in the
       file dialog. Scoped to views so ordinary inputs keep their padding. */
    QAbstractItemView QLineEdit {{
        padding: 0 3px;
        min-height: 0;
        border-radius: 3px;
        background: {t.surface_2};
        border: 1px solid {t.accent};
        color: {t.text_primary};
    }}
    QTreeWidget::item {{ padding: 3px 4px; }}
    QTreeWidget::item:selected {{
        background: {t.accent_subtle};
        color: {t.text_primary};
    }}
    QTreeWidget::item:hover {{ background: {t.surface_hover}; }}
    /* Views fall back to Qt's LIGHT palette for these two, which paints white
       bands across a dark list. Both must be set explicitly. */
    QTreeWidget {{ alternate-background-color: {t.surface_2}; }}
    QTreeWidget::indicator {{
        width: 16px; height: 16px;
        border: 1px solid {t.border_strong};
        border-radius: 4px;
        background: {t.surface_2};
    }}
    QTreeWidget::indicator:hover {{ border-color: {t.accent}; }}
    QTreeWidget::indicator:checked {{
        background: {t.accent};
        border-color: {t.accent};
        image: url({check_icon});
    }}
    QHeaderView::section {{
        background: {t.surface_2};
        color: {t.text_secondary};
        border: 0;
        border-right: 1px solid {t.border};
        border-bottom: 1px solid {t.border};
        padding: 5px 8px;
        font-weight: 600;
    }}
    """


def app_dir() -> Path:
    """The folder this script lives in - the whole install, venv included."""
    return Path(__file__).resolve().parent


def make_settings() -> "QSettings":
    """
    Keep settings.ini next to the app so nothing is squirrelled away in a
    hidden config directory. Falls back to the platform default only if this
    folder is not writable (read-only media, shared install).
    """
    target = app_dir() / "settings.ini"
    try:
        with open(target, "a", encoding="utf-8"):
            pass
        return QSettings(str(target), QSettings.Format.IniFormat)
    except OSError:
        return QSettings(ORG_NAME, APP_NAME)


def download_environment() -> dict[str, str]:
    """
    Environment overrides for the `hf download` child process.

    TQDM_POSITION is the load-bearing one. huggingface_hub builds its progress
    bars with `disable=None`, which makes tqdm auto-disable whenever stderr is
    not a terminal - and a QProcess pipe never is. Without this override the
    CLI emits no progress output at all, so there is nothing to parse.
    `TQDM_POSITION=-1` is the documented escape hatch that forces bars on
    regardless of TTY.
    """
    return {
        "HF_XET_HIGH_PERFORMANCE": "1",
        "PYTHONUNBUFFERED": "1",
        # Highest-priority progress switch in huggingface_hub. We inherit the
        # user's whole environment, so a stray export must not blank the bar.
        "HF_HUB_DISABLE_PROGRESS_BARS": "0",
        "TQDM_POSITION": "-1",
        # No chunk cache. Without this hf_xet keeps up to 10 GB of 64KB chunks
        # in ~/.cache/huggingface/xet to deduplicate future downloads. This app
        # pulls distinct files to a local dir, so that mostly buys nothing and
        # puts gigabytes outside the project folder. 0 disables it outright.
        "HF_XET_CHUNK_CACHE_SIZE_BYTES": "0",
        "HF_XET_CACHE": str(app_dir() / "xet-runtime"),
        "COLUMNS": "160",
    }


def preview_command(
    hf_bin: str, target: Target, mode: str, dest: str, selected: list[str] | None = None
) -> str:
    local_dir = resolve_local_dir(dest, strip_prefix_for(target, mode))
    args = build_args(target, mode, supports_format_flag(hf_bin), selected) + [
        "--local-dir", local_dir
    ]
    return "HF_XET_HIGH_PERFORMANCE=1 " + " ".join(shlex.quote(a) for a in [hf_bin] + args)


def lookup_key(target: Target, mode: str | None = None) -> tuple:
    """
    Identifies a metadata request, so a late reply for an edited URL is
    dropped. Deliberately excludes the mode: one fetch gives the whole repo
    listing and every mode is a filter over it, so switching modes or picking
    files never re-hits the network.
    """
    return (target.repo_id, target.repo_type, target.revision)


# Windows caps an entire command line at 32767 characters; Linux ARG_MAX is far
# higher but not infinite. Hand-picked files are queued one per command so this
# is no longer reachable that way, but it stays as a safety net for pathological
# repo ids or destination paths.
COMMAND_LENGTH_LIMIT = 30000 if os.name == "nt" else 120000


def command_length(args: list[str]) -> int:
    return sum(len(a) + 1 for a in args)


STATUS_QUEUED = "Queued"
STATUS_RUNNING = "Downloading"
STATUS_DONE = "Done"
STATUS_FAILED = "Failed"
STATUS_CANCELED = "Canceled"
FINISHED_STATUSES = (STATUS_DONE, STATUS_FAILED, STATUS_CANCELED)


@dataclass
class QueueItem:
    """
    One `hf download` invocation.

    Hand-picked files become one item each, so a big selection is a long queue
    rather than one enormous command line. Whole-repo and whole-folder stay a
    single item, because there the pattern does the work.
    """

    target: Target
    mode: str
    dest: str          # the folder the user picked for the file itself
    label: str
    size: int = 0
    files: list[tuple[str, int]] = field(default_factory=list)
    status: str = STATUS_QUEUED
    detail: str = ""

    @property
    def repo_label(self) -> str:
        rev = f"@{self.target.revision}" if self.target.revision else ""
        return f"{self.target.repo_id}{rev}"

    def local_dir(self) -> str:
        """
        What to pass as --local-dir.

        hf writes to <local-dir>/<repo-relative-path> and verifies at that same
        path, so to land a file in the folder the user picked we hand hf the
        parent of the repo's own subfolder rather than moving anything
        afterwards. Moving is what used to break the hash check.
        """
        return resolve_local_dir(self.dest, self.strip_prefix())

    def strip_prefix(self) -> str:
        return strip_prefix_for(self.target, self.mode)

    def final_dir(self) -> str:
        """Where this item's files actually end up."""
        prefix = self.strip_prefix()
        base = Path(self.local_dir())
        return str(base / prefix) if prefix else str(base)

    def args(self, force_human: bool) -> list[str]:
        return build_args(self.target, self.mode, force_human) + [
            "--local-dir", self.local_dir()
        ]


def items_for_request(
    target: Target,
    mode: str,
    dest: str,
    all_files: list[tuple[str, int]] | None,
    selected: list[str] | None,
) -> list[QueueItem]:
    """Turn what the user set up into one or more queue items."""
    sizes = dict(all_files or [])

    if mode == MODE_SELECT:
        items = []
        for path in sorted(selected or []):
            one = replace(target, path=path, path_is_dir=False)
            items.append(
                QueueItem(
                    target=one,
                    mode=MODE_FILE,
                    dest=dest,
                    label=path,
                    size=sizes.get(path, 0),
                    files=[(path, sizes.get(path, 0))],
                )
            )
        return items

    files = files_for_mode(all_files or [], target, mode)
    if mode == MODE_FILE:
        label = target.path
    elif mode == MODE_FOLDER:
        label = folder_prefix(target) + "/"
    else:
        label = "(whole repo)"
    return [
        QueueItem(
            target=target,
            mode=mode,
            dest=dest,
            label=label,
            size=sum(sz for _, sz in files),
            files=files,
        )
    ]


def strip_prefix_for(target: Target, mode: str) -> str:
    """The repo subfolder an item's files sit in, or '' if there is none."""
    if mode == MODE_FILE and target.path:
        return target.path.rpartition("/")[0]
    if mode == MODE_FOLDER:
        return folder_prefix(target)
    return ""


def hf_token_path() -> Path:
    """Where the hf CLI keeps its token. Same file `hf auth login` writes."""
    try:
        from huggingface_hub import constants

        return Path(constants.HF_TOKEN_PATH)
    except Exception:  # noqa: BLE001
        home = os.environ.get("HF_HOME") or str(Path.home() / ".cache" / "huggingface")
        return Path(home) / "token"


def token_env_override() -> str | None:
    """
    HF_TOKEN in the environment beats the saved file, so a token entered here
    would silently do nothing. Worth telling the user rather than leaving them
    to wonder why a gated repo still fails.
    """
    value = os.environ.get("HF_TOKEN", "").strip()
    return value or None


def read_saved_token() -> str | None:
    try:
        value = hf_token_path().read_text().strip()
        return value or None
    except OSError:
        return None


def save_token(token: str) -> None:
    """
    Write the token the way the CLI does: owner-only file in an owner-only
    directory.

    Deliberately not huggingface_hub.login(), which validates over the network
    first and writes nothing if that call fails - so it cannot save a token
    while offline, or behind a proxy that blocks the check.
    """
    path = hf_token_path()
    try:
        from huggingface_hub.utils._auth import _write_secret

        _write_secret(path, token.strip())
        return
    except Exception:  # noqa: BLE001 - fall back to doing it by hand
        pass
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w") as fh:
        fh.write(token.strip())
    try:
        path.chmod(0o600)
        path.parent.chmod(0o700)
    except (OSError, NotImplementedError):
        pass        # Windows has no POSIX modes


def clear_token() -> bool:
    try:
        hf_token_path().unlink()
        return True
    except OSError:
        return False


class TokenCheckWorker(QThread):
    """Asks the Hub who the token belongs to, without blocking the dialog."""

    done = Signal(str, str, str)     # username, error, kind ("auth"/"offline"/"other")

    def __init__(self, token: str, parent=None):
        super().__init__(None)
        self.token = token
        _LIVE_WORKERS.add(self)
        self.finished.connect(lambda: _LIVE_WORKERS.discard(self))

    def run(self) -> None:
        try:
            from huggingface_hub import HfApi

            info = HfApi().whoami(token=self.token)
            self.done.emit(str(info.get("name") or info.get("fullname") or "?"), "")
        except Exception as exc:  # noqa: BLE001
            self.done.emit("", f"{type(exc).__name__}: {exc}")


def resolve_local_dir(dest: str, strip_prefix: str) -> str:
    """
    Turn the folder the user picked into the --local-dir hf should get.

    hf always writes to <local-dir>/<repo-relative-path>. If the chosen folder
    already ends with the repo's own subfolder - picking
    .../ComfyUI/models/diffusion_models for a file at
    diffusion_models/model.safetensors - those trailing segments are dropped so
    the file lands exactly where it was pointed, with no move afterwards and
    the etag/sha256 check left intact.

    If the folder does not line up, it is used literally and the repo structure
    appears underneath it. There is no way to do better without moving the file,
    and moving is precisely what costs the verification.
    """
    dest_path = Path(dest)
    wanted = tuple(part for part in strip_prefix.split("/") if part)
    if not wanted:
        return str(dest_path)
    parts = dest_path.parts
    if len(parts) > len(wanted) and parts[-len(wanted):] == wanted:
        remaining = parts[: -len(wanted)]
        # Never strip down to the filesystem root or a bare drive: hf would put
        # its .cache/huggingface sidecar there, which is somewhere nobody
        # pointed at and may not even be writable.
        if len(remaining) > 1:
            parent = Path(*remaining)
            if _same_filesystem(dest_path, parent):
                return str(parent)
    return str(dest_path)


def _same_filesystem(child: Path, parent: Path) -> bool:
    """
    True unless the chosen folder is itself a mount point.

    Model directories are often a separate disk mounted or symlinked into the
    tree. Stripping a level there would stage the download - and measure free
    space - on the parent drive rather than the one the user pointed at and
    made room on. When either path does not exist yet we cannot tell, so we
    allow the strip; the folders are created under the resolved directory
    anyway.
    """
    try:
        return child.stat().st_dev == parent.stat().st_dev
    except OSError:
        return True


def files_for_mode(
    all_files: list[tuple[str, int]],
    target: Target,
    mode: str,
    selected: list[str] | None = None,
) -> list[tuple[str, int]]:
    """Narrow the full repo listing down to what this download will produce."""
    if mode == MODE_FILE:
        return [f for f in all_files if f[0] == target.path]
    if mode == MODE_FOLDER:
        prefix = folder_prefix(target)
        if not prefix:
            return []
        return [f for f in all_files if f[0].startswith(prefix + "/")]
    if mode == MODE_SELECT:
        chosen = set(selected or [])
        return [f for f in all_files if f[0] in chosen]
    return list(all_files)


# --------------------------------------------------------------------------
# repo metadata (size + file list) in the background
# --------------------------------------------------------------------------

_LIVE_WORKERS: set = set()


def wait_for_workers(msec: int = 5000) -> None:
    """Never let a QThread object be destroyed while it is still running."""
    for worker in list(_LIVE_WORKERS):
        try:
            worker.wait(msec)
        except RuntimeError:
            pass
    _LIVE_WORKERS.clear()


class RepoInfoWorker(QThread):
    # files | None, error string, the key this result belongs to
    done = Signal(object, str, tuple)

    def __init__(self, target: Target, mode: str, parent=None):
        # deliberately unparented: the window must not own, and so destroy,
        # a thread that may still be mid-request
        super().__init__(None)
        self.target = target
        self.mode = mode
        self.key = lookup_key(target, mode)
        _LIVE_WORKERS.add(self)
        self.finished.connect(lambda: _LIVE_WORKERS.discard(self))

    def run(self) -> None:
        try:
            from huggingface_hub import HfApi

            api = HfApi()
            info = api.repo_info(
                self.target.repo_id,
                repo_type=self.target.repo_type,
                revision=self.target.revision,
                files_metadata=True,
                timeout=15,
            )
            files = []
            for sib in info.siblings or []:
                files.append((sib.rfilename, getattr(sib, "size", None) or 0))
            # the whole listing goes back; callers filter it per mode
            self.done.emit(sorted(files), "", self.key)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, never fatal
            self.done.emit(None, f"{type(exc).__name__}: {exc}", self.key)


# --------------------------------------------------------------------------
# dependency check + graphical install
# --------------------------------------------------------------------------

def find_hf_binary() -> str | None:
    """Prefer the hf next to our own interpreter, then whatever is on PATH."""
    here = Path(sys.executable).parent
    names = ("hf.exe", "hf.cmd", "hf.bat") if IS_WINDOWS else ("hf",)
    for folder in (here, here / "Scripts", here / "bin"):
        for name in names:
            candidate = folder / name
            if candidate.is_file() and (IS_WINDOWS or os.access(candidate, os.X_OK)):
                return str(candidate)
    return shutil.which("hf")


def hub_importable() -> bool:
    try:
        import huggingface_hub  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def xet_importable() -> bool:
    """
    Presence check only - deliberately does NOT import hf_xet. Importing it
    starts its logger and creates a xet directory on disk before the user has
    even asked for a download. find_spec answers the question without running
    any of its code.
    """
    try:
        import importlib.util

        return importlib.util.find_spec("hf_xet") is not None
    except Exception:  # noqa: BLE001
        return False


class InstallDialog(QDialog):
    """Runs pip install in a subprocess and shows the output. No terminal needed."""

    def __init__(self, packages: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Installing dependencies")
        self.resize(720, 420)
        self.packages = packages
        self.proc: QProcess | None = None
        self.ok = False

        layout = QVBoxLayout(self)
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", *packages]
        layout.addWidget(QLabel(" ".join(shlex.quote(c) for c in cmd)))

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFont("monospace"))
        layout.addWidget(self.output, 1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.buttons.rejected.connect(self.reject)
        self.buttons.setEnabled(False)
        layout.addWidget(self.buttons)

        QTimer.singleShot(0, lambda: self._start(cmd))

    def _start(self, cmd: list[str]) -> None:
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(
            lambda err: self.output.appendPlainText(f"\n[process error] {err}")
        )
        self.proc.start(cmd[0], cmd[1:])

    def _read(self) -> None:
        data = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        self.output.moveCursor(self.output.textCursor().MoveOperation.End)
        self.output.insertPlainText(data)
        self.output.ensureCursorVisible()

    def _finished(self, code: int, _status) -> None:
        self.ok = code == 0
        self.output.appendPlainText(
            "\nDone." if self.ok else f"\npip exited with status {code}."
        )
        self.buttons.setEnabled(True)


def ensure_dependencies(parent=None) -> str | None:
    """Return a usable hf binary path, installing huggingface_hub first if needed."""
    hf_bin = find_hf_binary()
    if hf_bin and hub_importable():
        if not xet_importable():
            QMessageBox.information(
                parent,
                "Xet acceleration missing",
                "huggingface_hub is installed but hf_xet is not, so "
                "HF_XET_HIGH_PERFORMANCE will have no effect and downloads will "
                "use the slower HTTP path.\n\n"
                "Install it later with:  pip install 'huggingface_hub[hf_xet]'",
            )
        return hf_bin

    missing = []
    if not hub_importable():
        missing.append("the huggingface_hub Python package")
    if not hf_bin:
        missing.append("the 'hf' command")

    answer = QMessageBox.question(
        parent,
        "Install Hugging Face Hub?",
        "This app needs the Hugging Face Hub CLI and could not find "
        + " or ".join(missing)
        + ".\n\nInstall huggingface_hub[hf_xet] into:\n"
        + f"{sys.prefix}\n\nProceed?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return None

    dialog = InstallDialog(["huggingface_hub[hf_xet]"], parent)
    dialog.exec()

    hf_bin = find_hf_binary()
    if not (dialog.ok and hf_bin and hub_importable()):
        QMessageBox.critical(
            parent,
            "Install failed",
            "huggingface_hub still is not usable. Nothing can be downloaded "
            "until it is.",
        )
        return None
    return hf_bin


# --------------------------------------------------------------------------
# progress parsing
# --------------------------------------------------------------------------

import re  # noqa: E402  (kept next to the regexes that use it)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
# the hf CLI advertises an optional agent skill on stderr; pure noise here,
# since the whole point of this app is that you never touch the CLI
_CLI_NAG_RE = re.compile(r"hf skills (add|update)")


def clean_output(text: str) -> str:
    """Drop terminal color codes so the log pane shows text, not escape soup."""
    return _ANSI_RE.sub("", text)


def is_cli_nag(line: str) -> bool:
    return bool(_CLI_NAG_RE.search(line))


_TQDM_PCT = re.compile(r"(\d{1,3})%\|")
_FETCHING = re.compile(r"Fetching\s+(\d+)\s+files?:\s+(\d{1,3})%\|")

# Sizes as tqdm prints them. Plain tqdm: "1.20G/2.67G". huggingface_hub's Xet
# bars: "890MB / 2.67GB". The trailing B is optional and "/s" must not be
# mistaken for a total, so the total needs a leading digit.
_SIZE = r"(\d+(?:\.\d+)?)\s*([KMGT]?i?)B?"
_DONE_TOTAL = re.compile(r"\|\s*" + _SIZE + r"\s*/\s*" + _SIZE + r"(?![/\w])")
_DONE_ONLY = re.compile(r"\|\s*" + _SIZE + r"\s*(?:,|$)")
# Rate appears either inside the classic "[00:31<00:38, 38.7MB/s]" bracket or,
# for Xet bars, as a ", 41.2MB/s" postfix. Same regex catches both.
_RATE = re.compile(r"(\d+(?:\.\d+)?)\s*([KMGT]?i?)B/s")
_TQDM_TAIL = re.compile(r"\[(?P<elapsed>[\d:]+)<(?P<eta>[\d:?]+),\s*(?P<rate>[^\]]+)\]")

_UNIT = {"": 1, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12,
         "Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4}


def _to_bytes(num: str, unit: str) -> float:
    return float(num) * _UNIT.get(unit, 1)


@dataclass
class ProgressState:
    percent: int | None = None
    overall_percent: int | None = None
    rate_text: str = ""
    rate_bps: float = 0.0
    # Xet runs two counters: bytes flushed to disk (reconstruction) and bytes
    # pulled off the network (transfer). On a large file the first can sit at
    # zero for minutes while the second climbs, so both are kept.
    done_bytes: float | None = None
    transfer_bytes: float | None = None
    total_bytes: float | None = None
    last_lines: list[str] = field(default_factory=list)


def parse_progress_line(line: str, state: ProgressState) -> bool:
    """
    Update state from one progress line. Returns True if anything matched.

    Handles three shapes seen in the wild:
      plain tqdm          "name:  45%|####  | 1.20G/2.67G [00:31<00:38, 38.7MB/s]"
      Xet reconstruction  "name: reconstructing file:  33%|###   |  890MB / 2.67GB, 38.7MB/s"
      Xet transfer        "name: downloading bytes: ###   | 1.78GB, 41.2MB/s"     (no %)
      snapshot aggregate  "Fetching 15 files:  20%|##    | 3/15 [00:04<00:20]"
    """
    changed = False

    m = _FETCHING.search(line)
    if m:
        state.overall_percent = int(m.group(2))
        changed = True
    else:
        m = _TQDM_PCT.search(line)
        if m:
            state.percent = int(m.group(1))
            changed = True

    m = _DONE_TOTAL.search(line)
    if m:
        value = _to_bytes(m.group(1), m.group(2))
        # never let a bar go backwards; several bars interleave on stderr
        state.done_bytes = value if state.done_bytes is None else max(state.done_bytes, value)
        state.total_bytes = _to_bytes(m.group(3), m.group(4))
        if state.percent is None and state.total_bytes:
            state.percent = int(min(100, state.done_bytes * 100 / state.total_bytes))
        changed = True
    else:
        m = _DONE_ONLY.search(line)
        if m:
            value = _to_bytes(m.group(1), m.group(2))
            state.transfer_bytes = (
                value if state.transfer_bytes is None else max(state.transfer_bytes, value)
            )
            changed = True

    m = _RATE.search(line)
    if m:
        state.rate_bps = _to_bytes(m.group(1), m.group(2))
        state.rate_text = f"{m.group(1)}{m.group(2)}B/s"
        changed = True
    else:
        tail = _TQDM_TAIL.search(line)
        if tail:
            state.rate_text = tail.group("rate").strip()
            changed = True

    return changed


def speed_from_samples(
    samples: "deque[tuple[float, float]]", min_span: float = SPEED_MIN_SPAN
) -> float:
    """
    Average rate across the sample window, in bytes per second.

    Deliberately the derivative of the SAME byte figure shown in the readout,
    so bytes, percentage, speed and ETA can never disagree with each other.
    Taking the ends of a window rather than the last delta is what stops the
    burstiness of Xet's writes turning into wild numbers.
    """
    if len(samples) < 2:
        return 0.0
    start_time, start_bytes = samples[0]
    end_time, end_bytes = samples[-1]
    span = end_time - start_time
    if span < min_span:
        return 0.0
    return max(0.0, (end_bytes - start_bytes) / span)


def best_done_bytes(state: ProgressState, measured: float | None) -> float | None:
    """
    Furthest-along byte count from every source we have.

    Reconstruction lags transfer on big files, and the file on disk lags both
    while Xet buffers, so taking the maximum is what keeps the readout moving
    instead of pinned at zero.
    """
    candidates = [c for c in (measured, state.done_bytes, state.transfer_bytes) if c]
    return max(candidates) if candidates else None


def looks_like_progress(line: str) -> bool:
    """A line we failed to parse but which is clearly a progress bar."""
    return ("B/s" in line) or ("%|" in line) or ("|" in line and "B" in line)


# --------------------------------------------------------------------------
# main window
# --------------------------------------------------------------------------

class SettingsDialog(QDialog):
    """Somewhere to put a Hugging Face token without opening a terminal."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(560)
        self.setSizeGripEnabled(True)
        self.worker: TokenCheckWorker | None = None
        # Qt renders links in its own dark blue, which is unreadable on this
        # background, and QSS cannot style an anchor.
        accent = getattr(parent, "accent", None) or Theme("#2f6fed").accent

        layout = QVBoxLayout(self)

        heading = QLabel("Hugging Face token")
        heading.setObjectName("FieldHead")
        layout.addWidget(heading)

        # Two short lines rather than one wrapped one. A wrapped QLabel reports
        # a single line from sizeHint, so the dialog gets sized for one line and
        # clips the rest; a label that never wraps reports its true width and
        # the dialog sizes itself around it.
        for text in (
            "Only needed for private or gated repos.",
            "Create one with read access at "
            '<a href="https://huggingface.co/settings/tokens">'
            "huggingface.co/settings/tokens</a>",
        ):
            line = QLabel(text)
            line.setWordWrap(False)
            line.setOpenExternalLinks(True)
            palette = line.palette()
            palette.setColor(QPalette.ColorRole.Link, QColor(accent))
            line.setPalette(palette)
            layout.addWidget(line)

        row = QHBoxLayout()
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("hf_...")
        self.token_edit.textChanged.connect(self._update_state)
        self.show_btn = QPushButton("Show")
        self.show_btn.setCheckable(True)
        self.show_btn.setFixedWidth(70)
        self.show_btn.toggled.connect(self._toggle_echo)
        row.addWidget(self.token_edit, 1)
        row.addWidget(self.show_btn)
        layout.addLayout(row)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        # error text is unpredictable in length, so reserve a few lines rather
        # than letting a long message get cut off
        self.status.setMinimumHeight(self.status.fontMetrics().height() * 3)
        layout.addWidget(self.status)

        row = QHBoxLayout()
        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("Primary")
        self.save_btn.clicked.connect(self._save)
        self.check_btn = QPushButton("Check")
        self.check_btn.clicked.connect(self._check)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setObjectName("Danger")
        self.remove_btn.clicked.connect(self._remove)
        row.addWidget(self.save_btn)
        row.addWidget(self.check_btn)
        row.addWidget(self.remove_btn)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)

        self.where = QLabel(f"Stored in {hf_token_path()}")
        self.where.setObjectName("Hint")
        self.where.setWordWrap(True)
        layout.addWidget(self.where)

        existing = read_saved_token()
        if existing:
            self.token_edit.setText(existing)
        self._update_state()

        # Let the dialog size itself around its content. 560 is a floor, not a
        # width: at larger system font sizes the token URL needs more than that
        # and would otherwise be cut off.
        self.adjustSize()
        self.setMinimumWidth(max(560, self.sizeHint().width()))

    def _toggle_echo(self, shown: bool) -> None:
        self.token_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
        )
        self.show_btn.setText("Hide" if shown else "Show")

    def _update_state(self) -> None:
        typed = self.token_edit.text().strip()
        saved = read_saved_token()
        self.save_btn.setEnabled(bool(typed) and typed != saved)
        self.check_btn.setEnabled(bool(typed))
        self.remove_btn.setEnabled(saved is not None)

        override = token_env_override()
        if override:
            # a warning, not a hint: the token they just typed will be ignored
            self.status.setStyleSheet(f"color: {Theme.warning}; font-weight: 500;")
            self.status.setText(
                "HF_TOKEN is set in your environment and takes priority over "
                "anything saved here. Unset it, or the environment token is the "
                "one that will be used."
            )
        elif saved:
            self.status.setStyleSheet(f"color: {Theme.success};")
            self.status.setText("A token is saved. Gated repos you have access to will work.")
        else:
            self.status.setStyleSheet(f"color: {Theme.text_secondary};")
            self.status.setText("No token saved. Public repos work without one.")

    def _save(self) -> None:
        try:
            save_token(self.token_edit.text())
        except OSError as exc:
            self.status.setStyleSheet(f"color: {Theme.error};")
            self.status.setText(f"Could not save: {exc}")
            return
        self._update_state()
        if not token_env_override():
            self.status.setStyleSheet(f"color: {Theme.success};")
            self.status.setText("Saved.")

    def _remove(self) -> None:
        clear_token()
        self.token_edit.clear()
        self._update_state()

    def _check(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        self.check_btn.setEnabled(False)
        self.status.setStyleSheet(f"color: {Theme.text_secondary};")
        self.status.setText("Asking the Hub who this token belongs to...")
        self.worker = TokenCheckWorker(self.token_edit.text().strip())
        self.worker.done.connect(self._checked)
        self.worker.start()

    def _checked(self, username: str, error: str) -> None:
        if error:
            self.status.setStyleSheet(f"color: {Theme.error};")
            self.status.setText(f"That token did not work: {error}")
        else:
            self.status.setStyleSheet(f"color: {Theme.success};")
            self.status.setText(f"Valid - signed in as {username}.")
        self.check_btn.setEnabled(bool(self.token_edit.text().strip()))

    def closeEvent(self, event) -> None:
        if self.worker is not None:
            self.worker.wait(3000)
        event.accept()


class FilePickerDialog(QDialog):
    """Tick the files you want out of a repo listing."""

    def __init__(
        self,
        files: list[tuple[str, int]],
        preselected: set[str],
        parent=None,
        scope: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle("Choose files to download")
        self.resize(760, 560)
        self.all_files = files
        self.scope = scope.rstrip("/")
        self.checked: set[str] = set(preselected)
        self.scope_cb: QCheckBox | None = None      # built below; needed by _scoped_files
        self.files = self._scoped_files()

        layout = QVBoxLayout(self)

        if self.scope:
            row = QHBoxLayout()
            self.scope_cb = QCheckBox(f"Show every file in the repo, not just {self.scope}/")
            self.scope_cb.toggled.connect(self._toggle_scope)
            row.addWidget(self.scope_cb)
            row.addStretch(1)
            layout.addLayout(row)
        else:
            self.scope_cb = None

        row = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(
            "Filter, e.g. safetensors  or  diffusion_models/  (space-separated terms all must match)"
        )
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.filter_edit.setClearButtonEnabled(True)
        row.addWidget(self.filter_edit, 1)
        layout.addLayout(row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["File", "Size"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(False)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(1, 90)
        self.tree.itemChanged.connect(self._item_changed)
        layout.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.select_btn = QPushButton("Select All")
        self.select_btn.clicked.connect(lambda: self._set_shown(Qt.CheckState.Checked))
        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.clicked.connect(lambda: self._set_shown(Qt.CheckState.Unchecked))
        self.invert_btn = QPushButton("Invert Selection")
        self.invert_btn.clicked.connect(self._invert_shown)
        for button in (self.select_btn, self.clear_btn, self.invert_btn):
            row.addWidget(button)
        row.addStretch(1)
        self.summary = QLabel("")
        row.addWidget(self.summary)
        layout.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)

        # populated last: it repaints the summary, which must exist by then
        self._relabel_bulk_buttons(False)
        self._populate()
        self._update_summary()
        self.filter_edit.setFocus()

    def _scoped_files(self) -> list[tuple[str, int]]:
        """
        Only the folder the pasted link pointed at, unless the user widens it.

        Listing an entire repo when someone linked to one subfolder buries what
        they asked for among everything else.
        """
        if not self.scope or (self.scope_cb is not None and self.scope_cb.isChecked()):
            return list(self.all_files)
        prefix = self.scope + "/"
        scoped = [f for f in self.all_files if f[0].startswith(prefix)]
        return scoped or list(self.all_files)

    def _populate(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        for path, size in self.files:
            item = QTreeWidgetItem([path, human_bytes(size) if size else ""])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                0,
                Qt.CheckState.Checked if path in self.checked else Qt.CheckState.Unchecked,
            )
            item.setData(0, Qt.ItemDataRole.UserRole, size)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tree.addTopLevelItem(item)
        self.tree.blockSignals(False)
        self._apply_filter(self.filter_edit.text() if hasattr(self, "filter_edit") else "")

    def _item_changed(self, item, _column) -> None:
        path = item.text(0)
        if item.checkState(0) == Qt.CheckState.Checked:
            self.checked.add(path)
        else:
            self.checked.discard(path)
        self._update_summary()

    def _toggle_scope(self, _on: bool) -> None:
        # widening must not lose what is already ticked, so selections live in
        # self.checked rather than in the rows
        self.files = self._scoped_files()
        self._populate()
        self._update_summary()

    def _visible_items(self):
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if not item.isHidden():
                yield item

    def _apply_filter(self, text: str) -> None:
        terms = [t.lower() for t in text.split() if t]
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            haystack = item.text(0).lower()
            item.setHidden(any(t not in haystack for t in terms))
        self._relabel_bulk_buttons(bool(terms))
        self._update_summary()

    def _relabel_bulk_buttons(self, filtering: bool) -> None:
        """
        These act on the rows currently listed, which is what makes
        filter-then-add work. Saying "All" while a filter hides half the repo
        would be a lie, so the labels follow the filter.
        """
        if filtering:
            self.select_btn.setText("Select Shown")
            self.clear_btn.setText("Clear Shown")
            self.invert_btn.setText("Invert Shown")
            tip = "Applies to the rows matching your filter, not the whole list"
        else:
            self.select_btn.setText("Select All")
            self.clear_btn.setText("Clear All")
            self.invert_btn.setText("Invert Selection")
            tip = "Applies to every file listed"
        for button in (self.select_btn, self.clear_btn, self.invert_btn):
            button.setToolTip(tip)

    def _set_shown(self, state) -> None:
        # signals are blocked for speed, so the backing set must be kept in
        # step by hand - it, not the rows, is what selected_paths() reads
        checked = state == Qt.CheckState.Checked
        self.tree.blockSignals(True)
        for item in self._visible_items():
            item.setCheckState(0, state)
            if checked:
                self.checked.add(item.text(0))
            else:
                self.checked.discard(item.text(0))
        self.tree.blockSignals(False)
        self._update_summary()

    def _invert_shown(self) -> None:
        self.tree.blockSignals(True)
        for item in self._visible_items():
            path = item.text(0)
            now_checked = item.checkState(0) != Qt.CheckState.Checked
            item.setCheckState(
                0, Qt.CheckState.Checked if now_checked else Qt.CheckState.Unchecked
            )
            if now_checked:
                self.checked.add(path)
            else:
                self.checked.discard(path)
        self.tree.blockSignals(False)
        self._update_summary()

    def selected_paths(self) -> list[str]:
        listed = {f[0] for f in self.files}
        return sorted(p for p in self.checked if p in listed)

    def _update_summary(self) -> None:
        sizes = dict(self.files)
        picked = self.selected_paths()
        chosen = len(picked)
        total = sum(sizes.get(p, 0) for p in picked)
        shown = sum(1 for _ in self._visible_items())
        text = f"{chosen} of {len(self.files)} selected"
        if total:
            text += f"  ({human_bytes(total)})"
        if shown != len(self.files):
            text += f"   -   {shown} shown"
        self.summary.setText(text)
        self.ok_button.setEnabled(chosen > 0)


class MainWindow(QWidget):
    def __init__(self, hf_bin: str):
        super().__init__()
        self.hf_bin = hf_bin
        self.settings = make_settings()
        self.accent = Theme(self.settings.value("accent", "#2f6fed")).accent

        self.target: Target | None = None
        self.all_files: list[tuple[str, int]] | None = None   # whole repo listing
        self.selected_paths: list[str] = []                   # picked in the dialog
        self.files: list[tuple[str, int]] | None = None       # what this run produces
        self.total_bytes: int | None = None
        self.info_key: tuple | None = None

        self.lookup_debounce = QTimer(self)
        self.lookup_debounce.setSingleShot(True)
        self.lookup_debounce.setInterval(450)
        self.lookup_debounce.timeout.connect(self._do_info_lookup)

        self._picking = False
        self._prev_mode = MODE_FILE

        self.favorites: list[str] = []
        self.recents: list[str] = []
        self._header_labels: set[str] = set()
        self._last_dest = str(Path.home())

        self.queue: list[QueueItem] = []
        self.current_item: QueueItem | None = None
        self.paused = False

        self.proc: QProcess | None = None
        self.stderr_buf = ""
        self.stdout_buf = ""
        self.state = ProgressState()
        self.started_at = 0.0
        self.samples: deque[tuple[float, float]] = deque()
        self.speed_bps = 0.0
        self.bar_percent = 0
        self.canceled = False

        self.poll = QTimer(self)
        self.poll.setInterval(POLL_MS)
        self.poll.timeout.connect(self._tick)

        self._build_ui()
        self._restore()
        self._refresh_queue()

        # Reserve room for the list on the WINDOW rather than flooring the list
        # itself. Qt then clamps resizing at a height where the queue is usable,
        # and if a window manager forces something smaller anyway the list
        # shrinks away instead of the buttons overlapping it.
        self.setMinimumHeight(self.minimumSizeHint().height() + QUEUE_ROOM)

    # -- ui ---------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle(f"Fantastic HuggingFace Downloader {APP_VERSION}")
        outer = QVBoxLayout(self)

        # URL
        url_box = QGroupBox("Hugging Face link")
        url_layout = QVBoxLayout(url_box)
        row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(
            "https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/diffusion_models/model.safetensors"
        )
        self.url_edit.textChanged.connect(self._on_url_changed)
        paste_btn = QPushButton("  Paste")
        paste_btn.setIcon(lucide_icon("copy", Theme.text_secondary, 16))
        paste_btn.clicked.connect(self._paste)
        row.addWidget(self.url_edit, 1)
        row.addWidget(paste_btn)
        url_layout.addLayout(row)

        self.parsed_label = QLabel("Paste a link to begin.")
        self.parsed_label.setWordWrap(True)
        self.parsed_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        url_layout.addWidget(self.parsed_label)
        outer.addWidget(url_box)

        # What to grab
        mode_box = QGroupBox("What to download")
        mode_layout = QVBoxLayout(mode_box)
        row = QHBoxLayout()
        self.rb_file = QRadioButton("This file")
        self.rb_folder = QRadioButton("Its folder")
        self.rb_repo = QRadioButton("Whole repo")
        self.rb_select = QRadioButton("Choose files")
        self.rb_file.setChecked(True)
        self.mode_group = QButtonGroup(self)
        # id -> mode, so a toggle handler never has to re-scan the buttons
        self.mode_by_id = {0: MODE_FILE, 1: MODE_FOLDER, 2: MODE_REPO, 3: MODE_SELECT}
        for i, rb in enumerate((self.rb_file, self.rb_folder, self.rb_repo, self.rb_select)):
            self.mode_group.addButton(rb, i)
            row.addWidget(rb)
        self.pick_btn = QPushButton("  Choose files...")
        self.pick_btn.setIcon(lucide_icon("square-plus", Theme.text_secondary, 16))
        self.pick_btn.clicked.connect(self._pick_files)
        row.addWidget(self.pick_btn)
        row.addStretch(1)
        self.mode_group.idToggled.connect(
            lambda i, on: on and self._mode_changed(self.mode_by_id.get(i))
        )
        mode_layout.addLayout(row)

        outer.addWidget(mode_box)

        # Destination
        dest_box = QGroupBox("Destination")
        dest_layout = QVBoxLayout(dest_box)
        row = QHBoxLayout()
        self.dest_combo = QComboBox()
        self.dest_combo.setEditable(True)
        self.dest_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.dest_combo.currentTextChanged.connect(self._dest_text_changed)
        self.fav_btn = QPushButton("\u2606")
        self.fav_btn.setFixedWidth(38)
        self.fav_btn.setStyleSheet("font-size: 16px;")
        self.fav_btn.clicked.connect(self._toggle_favorite)
        browse = QPushButton("  Browse...")
        browse.setIcon(lucide_icon("folder-open", Theme.text_secondary, 16))
        browse.clicked.connect(self._browse)
        row.addWidget(self.dest_combo, 1)
        row.addWidget(self.fav_btn)
        row.addWidget(browse)
        dest_layout.addLayout(row)
        self.space_label = QLabel("")
        self.space_label.setObjectName("CountStatus")
        self.resolved_label = QLabel("")
        self.resolved_label.setWordWrap(True)
        self.resolved_label.setObjectName("CountStatus")
        dest_layout.addWidget(self.space_label)
        dest_layout.addWidget(self.resolved_label)
        outer.addWidget(dest_box)

        # Command preview
        self.cmd_label = QLabel("")
        self.cmd_label.setWordWrap(True)
        self.cmd_label.setFont(QFont("monospace"))
        self.cmd_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.cmd_label.setStyleSheet(f"color: {Theme.text_secondary};")
        outer.addWidget(self.cmd_label)

        # Add to the queue
        row = QHBoxLayout()
        self.go_btn = QPushButton("  Add to queue")
        self.go_btn.setObjectName("Primary")     # one per view
        self.go_btn.setIcon(lucide_icon("plus", "#FFFFFF", 16))
        self.go_btn.setDefault(True)
        self.go_btn.clicked.connect(self._add_to_queue)
        self.settings_btn = QPushButton("  Settings")
        self.settings_btn.setIcon(lucide_icon("settings", Theme.text_secondary, 16))
        self.settings_btn.setToolTip("Add a Hugging Face token for private or gated repos")
        self.settings_btn.clicked.connect(self._open_settings)
        self.open_btn = QPushButton("  Open folder")
        self.open_btn.setIcon(lucide_icon("folder-open", Theme.text_secondary, 16))
        self.open_btn.clicked.connect(self._open_dest)
        row.addWidget(self.go_btn)
        row.addStretch(1)
        row.addWidget(self.settings_btn)
        row.addWidget(self.open_btn)
        outer.addLayout(row)

        # Queue
        queue_box = QGroupBox("Queue")
        queue_layout = QVBoxLayout(queue_box)
        self.queue_tree = QTreeWidget()
        self.queue_tree.setHeaderLabels(["Status", "File", "Repo", "Size", "Destination"])
        self.queue_tree.setRootIsDecorated(False)
        self.queue_tree.setUniformRowHeights(True)
        self.queue_tree.setAlternatingRowColors(True)
        self.queue_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        # No floor: the list is the one thing that should give way when the
        # window is short. With a floor, a window manager that clamps to screen
        # height squeezes the layout past what its children allow and Qt lets
        # them overflow - which is how the buttons ended up painted over rows.
        self.queue_tree.setMinimumHeight(0)
        self.queue_tree.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored
        )
        qheader = self.queue_tree.header()
        qheader.setStretchLastSection(True)
        for col, width in ((0, 105), (1, 265), (2, 180), (3, 80)):
            qheader.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self.queue_tree.setColumnWidth(col, width)
        self.queue_tree.itemSelectionChanged.connect(self._refresh_queue_buttons)
        queue_layout.addWidget(self.queue_tree, 1)

        row = QHBoxLayout()
        self.start_btn = QPushButton("  Start")
        self.start_btn.setIcon(lucide_icon("play", Theme.text_secondary, 16))
        self.start_btn.setToolTip("Begin the next queued item now")
        self.start_btn.clicked.connect(self._start_queue)
        self.pause_btn = QPushButton("  Pause")
        self.pause_btn.setIcon(lucide_icon("pause", Theme.text_secondary, 16))
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.cancel_btn = QPushButton("  Cancel")
        self.cancel_btn.setObjectName("Danger")
        self.cancel_btn.setToolTip("Stop the download that is running and move to the next item")
        self.cancel_btn.setIcon(lucide_icon("x", Theme.error, 16))
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        self.remove_btn = QPushButton("  Remove")
        self.remove_btn.setIcon(lucide_icon("trash-2", Theme.text_secondary, 16))
        self.remove_btn.setToolTip("Take the selected items out of the queue")
        self.remove_btn.clicked.connect(self._remove_selected)
        self.dest_btn = QPushButton("  Destination")
        self.dest_btn.setIcon(lucide_icon("folder-open", Theme.text_secondary, 16))
        self.dest_btn.setToolTip("Send the selected queued items to a different folder")
        self.dest_btn.clicked.connect(self._set_item_destination)
        self.up_btn = QPushButton()
        self.up_btn.setIcon(lucide_icon("chevron-up", Theme.text_secondary, 16))
        self.up_btn.setToolTip("Move the selected items earlier in the queue")
        self.up_btn.clicked.connect(lambda: self._move_selected(-1))
        self.down_btn = QPushButton()
        self.down_btn.setIcon(lucide_icon("chevron-down", Theme.text_secondary, 16))
        self.down_btn.setToolTip("Move the selected items later in the queue")
        self.down_btn.clicked.connect(lambda: self._move_selected(1))
        self.clear_btn = QPushButton("  Clear done")
        self.clear_btn.setIcon(lucide_icon("check", Theme.text_secondary, 16))
        self.clear_btn.setToolTip("Remove finished, failed and canceled items from the list")
        self.clear_btn.clicked.connect(self._clear_finished)
        # Two rows: what the queue is doing, then what to do with the selection.
        # One row of nine controls needed 900px and forced a horizontal scrollbar.
        for b in (self.start_btn, self.pause_btn, self.cancel_btn):
            row.addWidget(b)
        row.addStretch(1)
        self.autostart_cb = QCheckBox("Auto-start")
        self.autostart_cb.setToolTip(
            "When on, anything you add begins downloading straight away.\n"
            "When off, items wait in the queue until you press Start."
        )
        self.autostart_cb.toggled.connect(self._autostart_toggled)
        row.addWidget(self.autostart_cb)
        queue_layout.addLayout(row)

        row = QHBoxLayout()
        for b in (self.remove_btn, self.dest_btn, self.up_btn, self.down_btn):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.clear_btn)
        queue_layout.addLayout(row)
        outer.addWidget(queue_box, 1)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        outer.addWidget(self.bar)

        self.status_label = QLabel("Idle.")
        outer.addWidget(self.status_label)
        self.queue_label = QLabel("Queue is empty.")
        self.queue_label.setObjectName("CountStatus")
        outer.addWidget(self.queue_label)

        # Log
        self.log_btn = QPushButton("Show log")
        self.log_btn.setCheckable(True)
        self.log_btn.toggled.connect(self._toggle_log)
        outer.addWidget(self.log_btn, 0, Qt.AlignmentFlag.AlignLeft)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("monospace"))
        self.log.setMaximumBlockCount(4000)
        self.log.setMinimumHeight(0)
        self.log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.log.hide()
        outer.addWidget(self.log, 1)

    def _toggle_log(self, on: bool) -> None:
        self.log.setVisible(on)
        self.log_btn.setText("Hide log" if on else "Show log")

    # -- settings ---------------------------------------------------------

    def _restore(self) -> None:
        geo = self.settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        else:
            # First run. Qt's own guess is far too narrow - it sized to the
            # widest single row and squeezed the queue's five columns into
            # about 500px. Open wide enough to read all of them, but never
            # larger than the screen.
            width, height = DEFAULT_SIZE
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                available = screen.availableGeometry()
                width = min(width, available.width() - 60)
                height = min(height, available.height() - 60)
            self.resize(max(width, self.minimumWidth()),
                        max(height, self.minimumHeight()))
        self.favorites = _as_path_list(self.settings.value("dest_favorites", []))
        self.recents = _as_path_list(self.settings.value("dest_history", []))[:MAX_HISTORY]
        self.autostart_cb.setChecked(self.settings.value("autostart", True, type=bool))
        last = self.settings.value("dest", str(Path.home() / "Downloads"))
        self._rebuild_dest_combo(last)
        self._refresh()

    def _rebuild_dest_combo(self, keep: str | None = None) -> None:
        """
        Repaint the dropdown: favorites first, then recents, with headers.

        Item text stays the bare path - the combo is editable, so decorating it
        would put stars and dashes into currentText() and from there into the
        actual download command.
        """
        text = keep if keep is not None else self.dest_combo.currentText()
        self.dest_combo.blockSignals(True)
        self.dest_combo.clear()

        self._header_labels = set()

        def add_header(label: str) -> None:
            self._header_labels.add(label)
            self.dest_combo.addItem(label)
            index = self.dest_combo.count() - 1
            # Qt.UserRole - 1 is the documented way to make a combo row
            # unselectable while leaving it visible
            self.dest_combo.setItemData(index, 0, Qt.ItemDataRole.UserRole - 1)

        if self.favorites:
            add_header("\u2500\u2500 Favorites \u2500\u2500")
            for path in self.favorites:
                self.dest_combo.addItem(path)
        recents = [r for r in self.recents if r not in self.favorites]
        if recents:
            if self.favorites:
                self.dest_combo.insertSeparator(self.dest_combo.count())
            add_header("\u2500\u2500 Recent \u2500\u2500")
            for path in recents:
                self.dest_combo.addItem(path)

        self.dest_combo.setCurrentText(text)
        self.dest_combo.blockSignals(False)
        self._refresh_fav_button()

    def _dest_text_changed(self, text: str) -> None:
        """
        Headers are visible but unselectable rows. A user cannot click one, but
        nothing else stops the text reaching --local-dir, so bounce it back to
        the last real folder rather than trusting the widget.
        """
        if text in getattr(self, "_header_labels", ()):  # noqa: SIM118
            self.dest_combo.blockSignals(True)
            self.dest_combo.setCurrentText(self._last_dest)
            self.dest_combo.blockSignals(False)
            self._refresh()
            return
        if text.strip():
            self._last_dest = text
        self._refresh()

    def _refresh_fav_button(self) -> None:
        path = self.dest_combo.currentText().strip()
        starred = path in self.favorites
        self.fav_btn.setText("\u2605" if starred else "\u2606")
        self.fav_btn.setEnabled(bool(path))
        self.fav_btn.setToolTip(
            "Remove this folder from favorites" if starred
            else "Keep this folder at the top of the list"
        )

    def _toggle_favorite(self) -> None:
        path = self.dest_combo.currentText().strip()
        if not path:
            return
        if path in self.favorites:
            self.favorites.remove(path)
            self._log(f"[destinations] un-favorited {path}")
        else:
            self.favorites.insert(0, path)
            self._log(f"[destinations] favorited {path}")
        self.settings.setValue("dest_favorites", self.favorites)
        self._rebuild_dest_combo(path)

    def _remember_dest(self, path: str) -> None:
        # favorites are pinned, so they never age out of the recent list
        if path not in self.favorites:
            if path in self.recents:
                self.recents.remove(path)
            self.recents.insert(0, path)
            self.recents = self.recents[:MAX_HISTORY]
            self.settings.setValue("dest_history", self.recents)
        self.settings.setValue("dest", path)
        self._rebuild_dest_combo(path)

    def closeEvent(self, event) -> None:
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("dest", self.dest_combo.currentText().strip())
        if self.current_item is not None:
            pending = sum(1 for i in self.queue if i.status == STATUS_QUEUED)
            extra = f" and {pending} still queued" if pending else ""
            answer = QMessageBox.question(
                self,
                "Download running",
                f"'{self.current_item.label}' is still downloading{extra}. "
                "Cancel and quit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._cancel()
        self.lookup_debounce.stop()
        wait_for_workers()
        event.accept()

    # -- parsing / preview ------------------------------------------------

    def _paste(self) -> None:
        text = QGuiApplication.clipboard().text().strip()
        if text:
            self.url_edit.setText(text)

    def _on_url_changed(self) -> None:
        self.all_files = None
        self.selected_paths = []
        self.files = None
        self.total_bytes = None
        self.info_key = None
        try:
            self.target = parse_hf_url(self.url_edit.text())
        except ParseError as exc:
            self.target = None
            self.parsed_label.setText(
                f"<span style='color:{Theme.error};'>{exc}</span>"
            )
            self._refresh()
            return

        t = self.target
        rev = t.revision or "(default branch)"
        detail = f"<b>{t.repo_id}</b> &middot; {t.repo_type} &middot; {rev}"
        if t.path:
            detail += f"<br>path: <code>{t.path}</code>"
        else:
            detail += "<br>no file path in this link - whole repo only"
        self.parsed_label.setText(detail)

        # pick a sensible default mode from the link shape
        if not t.path:
            self.rb_repo.setChecked(True)
        elif t.path_is_dir:
            self.rb_folder.setChecked(True)
        else:
            self.rb_file.setChecked(True)
        self._refresh()

    def _mode(self) -> str:
        if self.rb_folder.isChecked():
            return MODE_FOLDER
        if self.rb_repo.isChecked():
            return MODE_REPO
        if self.rb_select.isChecked():
            return MODE_SELECT
        return MODE_FILE

    def _mode_changed(self, mode: str | None = None) -> None:
        mode = mode or self._mode()

        # "Choose files" is the one mode that needs input before it means
        # anything, so selecting it is what opens the picker. Gating the radio
        # on an existing selection made it impossible to ever reach.
        if mode == MODE_SELECT and not self.selected_paths and not self._picking:
            self._picking = True
            try:
                got_files = self._pick_files()
            finally:
                self._picking = False
            if not got_files:
                self._revert_mode()
                return

        self._refresh()
        if mode != MODE_SELECT or self.selected_paths:
            self._prev_mode = mode

    def _revert_mode(self) -> None:
        """Back out of Choose files when the picker was dismissed empty."""
        target = self._prev_mode if self._prev_mode != MODE_SELECT else MODE_REPO
        button = {
            MODE_FILE: self.rb_file,
            MODE_FOLDER: self.rb_folder,
            MODE_REPO: self.rb_repo,
        }.get(target, self.rb_repo)
        if not button.isEnabled():
            button = self.rb_repo
        button.setChecked(True)

    def _pick_files(self) -> bool:
        """Open the picker. Returns True if the user came back with a selection."""
        if not self.target:
            return False
        if not self.all_files:
            QMessageBox.information(
                self,
                "Still fetching the file list",
                "The list of files in this repo has not arrived yet.\n\n"
                "Give it a moment and try again. If it never arrives, the log "
                "pane will say why.",
            )
            return False
        # Everything ticked by default: the workflow is unchecking what you do
        # not want, not building a selection from nothing. Reopening the picker
        # keeps whatever you had chosen last time.
        scope = strip_prefix_for(self.target, self._mode()) or folder_prefix(self.target)
        if not scope and self.target.path:
            scope = self.target.path.rpartition("/")[0]
        in_scope = [
            f[0] for f in self.all_files
            if not scope or f[0].startswith(scope.rstrip("/") + "/")
        ] or [f[0] for f in self.all_files]
        preselected = set(self.selected_paths) or set(in_scope)
        dialog = FilePickerDialog(self.all_files, preselected, self, scope=scope)
        if dialog.exec():
            self.selected_paths = dialog.selected_paths()
            if self.selected_paths:
                self.rb_select.setChecked(True)
            self._refresh()
            return bool(self.selected_paths)
        self._refresh()
        return False

    def _refresh(self) -> None:
        t = self.target
        has_path = bool(t and t.path)
        self.rb_file.setEnabled(bool(t) and has_path and not (t and t.path_is_dir))
        self.rb_folder.setEnabled(bool(t) and bool(folder_prefix(t)) if t else False)
        self.rb_repo.setEnabled(bool(t))
        if self.rb_file.isChecked() and not self.rb_file.isEnabled():
            (self.rb_folder if self.rb_folder.isEnabled() else self.rb_repo).setChecked(True)

        self._refresh_fav_button()
        have_listing = bool(self.all_files)
        # Both stay available as soon as there is a repo. If the listing has
        # not arrived, clicking says so rather than presenting a dead control.
        self.pick_btn.setEnabled(bool(t))
        self.rb_select.setEnabled(bool(t))
        if self.selected_paths:
            picked = len(self.selected_paths)
            self.rb_select.setText(f"Choose files ({picked})")
        else:
            self.rb_select.setText("Choose files")

        self._recompute_files()
        dest = self.dest_combo.currentText().strip()
        self._update_space(dest)
        self._update_resolved(dest)

        # Adding while something downloads is the point of the queue, so this
        # is never gated on whether a download is in flight.
        self.go_btn.setEnabled(bool(t) and bool(dest))
        running = self.current_item is not None

        if not t or not dest:
            self.cmd_label.setText("")
            return
        try:
            self.cmd_label.setText(
                preview_command(self.hf_bin, t, self._mode(), dest, self.selected_paths)
            )
        except ParseError as exc:
            self.cmd_label.setText(f"({exc})")
            self.go_btn.setEnabled(False)
            return

        if not running:
            self._start_info_lookup()

    def _update_resolved(self, dest: str) -> None:
        """
        Say where files will actually land whenever that is not the folder in
        the box. hf writes to <local-dir>/<repo-path>, so a destination that
        does not end with the repo's own subfolder gets that structure
        underneath it - better to show it than let it surprise someone.
        """
        self.resolved_label.clear()
        if not (self.target and dest):
            self.resolved_label.hide()
            return
        items = items_for_request(
            self.target, self._mode(), dest, self.all_files, self.selected_paths
        )
        if not items:
            self.resolved_label.hide()
            return
        landing = {i.final_dir() for i in items}
        if landing == {str(Path(dest))}:
            self.resolved_label.hide()
            return
        shown = sorted(landing)[:2]
        text = "Files land in: " + ", ".join(shown)
        if len(landing) > len(shown):
            text += f" (+{len(landing) - len(shown)} more)"
        self.resolved_label.setText(text)
        self.resolved_label.show()

    def _update_space(self, dest: str) -> None:
        probe = Path(dest) if dest else None
        while probe and not probe.exists() and probe != probe.parent:
            probe = probe.parent
        if not probe or not probe.exists():
            self.space_label.setText("")
            return
        try:
            usage = shutil.disk_usage(probe)
        except OSError:
            self.space_label.setText("")
            return
        text = f"{human_bytes(usage.free)} free on {probe}"
        if self.total_bytes:
            text += f"   |   download size {human_bytes(self.total_bytes)}"
            if self.total_bytes > usage.free:
                text = f"<span style='color:{Theme.error};'>{text} - not enough room</span>"
        self.space_label.setText(text)

    def _recompute_files(self) -> None:
        """Derive this run's file set from the cached listing. No network."""
        if self.all_files is None or not self.target:
            self.files = None
            self.total_bytes = None
        else:
            self.files = files_for_mode(
                self.all_files, self.target, self._mode(), self.selected_paths
            )
            self.total_bytes = sum(size for _, size in self.files) or None
        self._update_space(self.dest_combo.currentText().strip())

    def _start_info_lookup(self) -> None:
        # typing in the URL box fires this on every keystroke; settle first
        self.lookup_debounce.start()

    def _do_info_lookup(self) -> None:
        if not self.target:
            return
        key = lookup_key(self.target, self._mode())
        if key == self.info_key:
            return  # already have it, or already asking for it
        self.info_key = key
        worker = RepoInfoWorker(self.target, self._mode())
        worker.done.connect(self._info_ready)
        worker.start()

    def _info_ready(self, files, error: str, key: tuple) -> None:
        if key != self.info_key:
            return  # the URL or mode moved on while this was in flight
        if error:
            self._log(f"[metadata] {error}")
            self.all_files = None
            self.files = None
            self.total_bytes = None
        else:
            self.all_files = files
            if not files:
                self._log("[metadata] the Hub reports no files in this repo")
        self._recompute_files()

    # -- destination ------------------------------------------------------

    def _browse(self) -> None:
        dialog = QFileDialog(self, "Choose a destination folder")
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        # Qt's own dialog, so every mounted drive is reachable from the sidebar
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        places = self.favorites + [p for p in list_mount_points() if p not in self.favorites]
        dialog.setSidebarUrls([QUrl.fromLocalFile(p) for p in places])
        current = self.dest_combo.currentText().strip()
        if current and Path(current).is_dir():
            dialog.setDirectory(current)
        if dialog.exec():
            chosen = dialog.selectedFiles()
            if chosen:
                self._remember_dest(chosen[0])
                self._refresh()

    def _open_settings(self) -> None:
        SettingsDialog(self).exec()

    def _open_dest(self) -> None:
        dest = self.dest_combo.currentText().strip()
        if not dest or not Path(dest).is_dir():
            return
        try:
            if IS_WINDOWS:
                os.startfile(dest)  # noqa: S606 - the documented Windows way
            elif IS_MACOS:
                subprocess.Popen(["open", dest])
            else:
                subprocess.Popen(["xdg-open", dest])
        except (OSError, AttributeError) as exc:
            self._log(f"[open folder] {exc}")

    # -- download ---------------------------------------------------------

    def _expected_paths(self, dest: Path) -> list[Path]:
        """Final resting paths of the files we expect this download to produce."""
        if not self.files:
            return []
        return [dest / rel for rel, _size in self.files]

    def _measure(self, dest: Path) -> int:
        """
        Bytes on disk for this download: finished files plus whatever is still
        landing.

        In-progress files live in .cache/huggingface/download as
        <short_hash>.<etag>.incomplete - names built from hub internals that we
        must not try to reconstruct, so glob for them instead. This holds for
        the Xet path too, which writes to the same incomplete file.
        """
        total = 0
        for final in self._expected_paths(dest):
            try:
                total += final.stat().st_size
            except OSError:
                pass

        download_dir = dest / ".cache" / "huggingface" / "download"
        try:
            for partial in download_dir.rglob("*.incomplete"):
                try:
                    total += partial.stat().st_size
                except OSError:
                    pass
        except OSError:
            pass
        return total

    # -- queue ------------------------------------------------------------

    def _add_to_queue(self) -> None:
        if not self.target:
            return
        dest = self.dest_combo.currentText().strip()
        if not dest:
            return
        dest_path = self._prepare_dest(dest)
        if dest_path is None:
            return

        items = items_for_request(
            self.target,
            self._mode(),
            str(dest_path),
            self.all_files,
            self.selected_paths,
        )
        if not items:
            QMessageBox.warning(
                self,
                "Nothing to add",
                "That selection does not match any files in the repo.",
            )
            return

        # validate each item builds a runnable command before queueing any
        for item in items:
            try:
                item.args(supports_format_flag(self.hf_bin))
            except ParseError as exc:
                QMessageBox.warning(self, "Cannot queue that", str(exc))
                return

        # bytes land under --local-dir, which may not be the folder picked
        self._warn_if_short_on_space(Path(items[0].local_dir()), sum(i.size for i in items))
        self._remember_dest(str(dest_path))
        self.queue.extend(items)
        self._log(f"[queue] added {len(items)} item(s) from {items[0].repo_label}")
        self._refresh_queue()
        if self.autostart_cb.isChecked():
            self._pump_queue()
        self._refresh()

    def _start_queue(self) -> None:
        """Manual go: clears a pause and starts the next queued item."""
        if self.paused:
            self.paused = False
            self._log("[queue] resumed")
        self._pump_queue()
        self._refresh_queue()

    def _autostart_toggled(self, on: bool) -> None:
        self.settings.setValue("autostart", bool(on))
        if on:
            self._pump_queue()
        self._refresh_queue()

    def _prepare_dest(self, dest: str) -> Path | None:
        dest_path = Path(dest).expanduser()
        try:
            dest_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "Cannot use that folder", str(exc))
            return None
        if not os.access(dest_path, os.W_OK):
            QMessageBox.critical(self, "Cannot use that folder", f"{dest_path} is not writable.")
            return None
        return dest_path

    def _warn_if_short_on_space(self, dest_path: Path, needed: int) -> None:
        if not needed:
            return
        try:
            free = shutil.disk_usage(dest_path).free
        except OSError:
            return
        queued = sum(i.size for i in self.queue if i.status == STATUS_QUEUED)
        if needed + queued > free:
            QMessageBox.warning(
                self,
                "Short on free space",
                f"The queue would need about {human_bytes(needed + queued)} but only "
                f"{human_bytes(free)} is free on that drive.\n\n"
                "The items are queued anyway - remove some, or point them at "
                "another drive with 'Set destination...'.",
            )

    def _selected_items(self) -> list["QueueItem"]:
        out = []
        for widget_item in self.queue_tree.selectedItems():
            index = self.queue_tree.indexOfTopLevelItem(widget_item)
            if 0 <= index < len(self.queue):
                out.append(self.queue[index])
        return out

    def _remove_selected(self) -> None:
        for item in self._selected_items():
            if item is self.current_item:
                self._log("[queue] not removing the item that is downloading; cancel it first")
                continue
            self.queue.remove(item)
        self._refresh_queue()

    def _move_selected(self, delta: int) -> None:
        rows = sorted(
            self.queue_tree.indexOfTopLevelItem(w) for w in self.queue_tree.selectedItems()
        )
        if delta > 0:
            rows.reverse()
        moved = []
        for row in rows:
            target_row = row + delta
            if not (0 <= target_row < len(self.queue)):
                continue
            if self.queue[row] is self.current_item or self.queue[target_row] is self.current_item:
                continue
            self.queue[row], self.queue[target_row] = self.queue[target_row], self.queue[row]
            moved.append(target_row)
        self._refresh_queue()
        for row in moved:
            self.queue_tree.topLevelItem(row).setSelected(True)

    def _set_item_destination(self) -> None:
        items = [i for i in self._selected_items() if i.status == STATUS_QUEUED]
        if not items:
            return
        dialog = QFileDialog(self, "Destination for the selected queue items")
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        places = self.favorites + [p for p in list_mount_points() if p not in self.favorites]
        dialog.setSidebarUrls([QUrl.fromLocalFile(p) for p in places])
        dialog.setDirectory(items[0].dest)
        if not dialog.exec():
            return
        chosen = dialog.selectedFiles()
        if not chosen:
            return
        dest_path = self._prepare_dest(chosen[0])
        if dest_path is None:
            return
        for item in items:
            item.dest = str(dest_path)
        self._log(f"[queue] {len(items)} item(s) now going to {dest_path}")
        self._refresh_queue()

    def _clear_finished(self) -> None:
        self.queue = [i for i in self.queue if i.status not in FINISHED_STATUSES]
        self._refresh_queue()

    def _toggle_pause(self) -> None:
        self.paused = not self.paused
        if self.paused:
            self._log("[queue] paused; the current download continues")
        else:
            self._log("[queue] resumed")
            self._pump_queue()
        self._refresh_queue()

    def _refresh_queue(self) -> None:
        self.queue_tree.blockSignals(True)
        self.queue_tree.clear()
        for item in self.queue:
            widget_item = QTreeWidgetItem([
                item.detail or item.status,
                item.label,
                item.repo_label,
                human_bytes(item.size) if item.size else "",
                item.final_dir(),
            ])
            widget_item.setTextAlignment(3, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            color = {
                STATUS_DONE: Theme.success,
                STATUS_FAILED: Theme.error,
                STATUS_CANCELED: Theme.warning,
                STATUS_RUNNING: self.accent,
            }.get(item.status, Theme.text_secondary)
            widget_item.setForeground(0, QColor(color))
            widget_item.setForeground(4, QColor(Theme.text_secondary))
            self.queue_tree.addTopLevelItem(widget_item)
        self.queue_tree.blockSignals(False)

        pending = sum(1 for i in self.queue if i.status == STATUS_QUEUED)
        remaining = sum(i.size for i in self.queue if i.status == STATUS_QUEUED)
        done = sum(1 for i in self.queue if i.status == STATUS_DONE)
        parts = []
        if self.current_item:
            parts.append("1 downloading")
        if pending:
            parts.append(f"{pending} queued" + (f" ({human_bytes(remaining)})" if remaining else ""))
        if done:
            parts.append(f"{done} done")
        failed = sum(1 for i in self.queue if i.status == STATUS_FAILED)
        if failed:
            parts.append(f"{failed} failed")
        self.queue_label.setText("   |   ".join(parts) if parts else "Queue is empty.")

        self.pause_btn.setText("  Resume" if self.paused else "  Pause")
        self.pause_btn.setIcon(
            lucide_icon("play" if self.paused else "pause", Theme.text_secondary, 16)
        )
        self._refresh_queue_buttons()

    def _refresh_queue_buttons(self) -> None:
        chosen = self._selected_items()
        removable = any(i is not self.current_item for i in chosen)
        self.remove_btn.setEnabled(removable)
        self.dest_btn.setEnabled(any(i.status == STATUS_QUEUED for i in chosen))
        self.up_btn.setEnabled(bool(chosen))
        self.down_btn.setEnabled(bool(chosen))
        self.clear_btn.setEnabled(any(i.status in FINISHED_STATUSES for i in self.queue))
        waiting = any(i.status == STATUS_QUEUED for i in self.queue)
        self.start_btn.setEnabled(waiting and self.current_item is None)
        self.pause_btn.setEnabled(bool(self.queue) or self.paused)
        self.cancel_btn.setEnabled(self.current_item is not None)

    def _pump_queue(self) -> None:
        """Start the next queued item if nothing is running."""
        if self.current_item is not None or self.paused:
            return
        for item in self.queue:
            if item.status == STATUS_QUEUED:
                self._run_item(item)
                return
        self.status_label.setText("Queue finished." if self.queue else "Idle.")
        self.bar.setValue(0)

    def _run_item(self, item: "QueueItem") -> None:
        dest_path = Path(item.local_dir())
        try:
            args = item.args(supports_format_flag(self.hf_bin))
        except ParseError as exc:
            item.status = STATUS_FAILED
            item.detail = str(exc)
            self._refresh_queue()
            self._pump_queue()
            return

        env = QProcessEnvironment.systemEnvironment()
        for key, value in download_environment().items():
            env.insert(key, value)

        self.proc = QProcess(self)
        self.proc.setProcessEnvironment(env)
        if IS_WINDOWS:
            # hf.exe is a console program; without this it flashes a black
            # window on every download.
            try:
                CREATE_NO_WINDOW = 0x08000000

                def _hide_console(a):
                    a.flags |= CREATE_NO_WINDOW
                    return a

                self.proc.setCreateProcessArgumentsModifier(_hide_console)
            except (AttributeError, TypeError):
                pass
        self.proc.readyReadStandardError.connect(self._read_stderr)
        self.proc.readyReadStandardOutput.connect(self._read_stdout)
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(self._proc_error)

        self.current_item = item
        item.status = STATUS_RUNNING
        item.detail = ""
        self.files = item.files
        self.total_bytes = item.size or None
        self.canceled = False
        self.state = ProgressState()
        self.stderr_buf = ""
        self.stdout_buf = ""
        self.speed_bps = 0.0
        self.bar_percent = 0
        self.started_at = time.monotonic()
        self.samples = deque()

        self.bar.setValue(0)
        self.status_label.setText(f"Starting {item.label}...")
        self._log(f"[app] version {APP_VERSION}")
        self._log(f"[queue] {item.repo_label} -> {item.label}")
        self._log("$ " + " ".join(shlex.quote(a) for a in [self.hf_bin] + args))

        self.proc.start(self.hf_bin, args)
        self.poll.start()
        self._refresh_queue()

    def _cancel(self) -> None:
        if not self.proc or self.proc.state() == QProcess.ProcessState.NotRunning:
            return
        self.canceled = True
        self.status_label.setText("Canceling...")
        self.proc.terminate()
        QTimer.singleShot(4000, self._kill_if_alive)

    def _kill_if_alive(self) -> None:
        if self.proc and self.proc.state() != QProcess.ProcessState.NotRunning:
            self.proc.kill()

    def _proc_error(self, err) -> None:
        self._log(f"[process error] {err}")

    # -- output handling --------------------------------------------------

    def _read_stderr(self) -> None:
        data = clean_output(bytes(self.proc.readAllStandardError()).decode("utf-8", "replace"))
        self.stderr_buf += data
        # tqdm redraws with \r, so treat both terminators as line ends
        chunks = re.split(r"[\r\n]", self.stderr_buf)
        self.stderr_buf = chunks.pop() if chunks else ""
        for line in chunks:
            line = line.strip()
            if not line:
                continue
            if parse_progress_line(line, self.state):
                continue
            if is_cli_nag(line):
                continue
            if looks_like_progress(line):
                # progress text the parser did not understand - surface it
                # loudly so the format can be added rather than guessed at
                self._log(f"[unparsed progress] {line}")
                continue
            self._log(line)

    def _read_stdout(self) -> None:
        data = clean_output(bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace"))
        self.stdout_buf += data
        chunks = self.stdout_buf.split("\n")
        self.stdout_buf = chunks.pop()
        for line in chunks:
            if line.strip() and not is_cli_nag(line):
                self._log(line.rstrip())

    def _tick(self) -> None:
        dest = Path(
            self.current_item.local_dir() if self.current_item
            else (self.dest_combo.currentText().strip() or ".")
        )
        now = time.monotonic()

        # Always measure: the .incomplete glob needs no file list. Only the
        # finished-file part depends on metadata, and that is a bonus.
        measured = self._measure(dest)

        total = self.total_bytes or self.state.total_bytes
        done = best_done_bytes(self.state, measured)

        # One series drives everything. Speed used to be the disk delta while
        # the byte count came from the network counter, so the bar could leap
        # while the rate read a few hundred KiB/s - they were measuring
        # different things.
        if done is not None:
            self.samples.append((now, float(done)))
            while len(self.samples) > 2 and now - self.samples[0][0] > SPEED_WINDOW:
                self.samples.popleft()
        speed = speed_from_samples(self.samples)
        if speed <= 0:
            # too early to have a window; the CLI's own figure will do
            speed = self.state.rate_bps
        self.speed_bps = speed

        # Derive the percentage from the same byte figure shown in the text,
        # rather than trusting the printed one. Xet's reconstruction bar prints
        # 0% for as long as it is buffering, which would peg the bar at zero
        # while the byte readout climbs.
        percent = None
        if total and done:
            percent = int(min(100, done * 100 / total))

        printed = self.state.overall_percent
        if printed is None:
            printed = self.state.percent
        if printed is not None:
            percent = printed if percent is None else max(percent, printed)

        if percent is not None:
            # never let the bar retreat: several bars interleave on stderr and
            # the transfer count can briefly outrun a stale reconstruction line
            self.bar_percent = max(self.bar_percent, max(0, min(100, percent)))
            self.bar.setValue(self.bar_percent)

        bits = []
        if done is not None and total:
            bits.append(f"{human_bytes(done)} / {human_bytes(total)}")
        elif done:
            bits.append(human_bytes(done))

        if speed > 0:
            bits.append(f"{human_bytes(speed)}/s")
        elif self.state.rate_text:
            bits.append(self.state.rate_text)

        if total and done is not None and speed > 0:
            remaining = max(0.0, total - done)
            bits.append(f"ETA {human_time(remaining / speed)}")

        bits.append(f"elapsed {human_time(now - self.started_at)}")
        self.status_label.setText("   |   ".join(bits))

    def _finished(self, code: int, _status) -> None:
        self.poll.stop()
        for buf, sink in ((self.stderr_buf, self._log), (self.stdout_buf, self._log)):
            if buf.strip():
                sink(buf.strip())
        self.stderr_buf = self.stdout_buf = ""

        item = self.current_item
        self.current_item = None

        if item is None:
            self._refresh_queue()
            return

        if self.canceled:
            item.status = STATUS_CANCELED
            item.detail = "Canceled"
            self.status_label.setText("Canceled. Partial data is kept; requeue to resume.")
            self._refresh_queue()
            self._pump_queue()
            self._refresh()
            return

        if code != 0:
            item.status = STATUS_FAILED
            item.detail = f"Failed (exit {code})"
            self.bar.setValue(0)
            self.status_label.setText(f"{item.label} failed (exit {code}). See the log.")
            self.log_btn.setChecked(True)
            self._log(f"[queue] FAILED {item.label} (exit {code})")
            # one bad item must not stall everything behind it
            self._refresh_queue()
            self._pump_queue()
            self._refresh()
            return

        self.bar.setValue(100)
        item.status = STATUS_DONE
        item.detail = "Done"
        removed = self._clean_sidecar(item)
        self.status_label.setText(
            f"Finished {item.label}." + (f" Cleared {removed} sidecar file(s)." if removed else "")
        )
        self._refresh_queue()
        self._pump_queue()
        self._refresh()


    # -- sidecar cleanup ---------------------------------------------------

    def _sidecar_paths(self, local_dir: Path, rel: str) -> list[Path]:
        """
        The .metadata and .lock this download left behind for one file.

        Derived with huggingface_hub's own helper where possible - the naming
        inside that folder is an implementation detail that has already caught
        me out once - with a manual fallback if the private module moves.
        """
        try:
            from huggingface_hub._local_folder import get_local_download_paths

            paths = get_local_download_paths(local_dir=local_dir, filename=rel)
            return [Path(paths.metadata_path), Path(paths.lock_path)]
        except Exception:  # noqa: BLE001 - never let cleanup break a download
            # NB: append, never with_suffix - the repo filename already has a
            # suffix, so with_suffix(".lock") on "model.safetensors" yields
            # "model.lock" and silently misses the real file.
            base = local_dir / ".cache" / "huggingface" / "download" / rel
            return [
                base.with_name(base.name + ".metadata"),
                base.with_name(base.name + ".lock"),
            ]

    def _clean_sidecar(self, item: "QueueItem") -> int:
        """
        Drop the .metadata for the files this item just finished.

        With the metadata gone, a future run of the same download cannot skip on
        the stored etag; it falls through to hashing the file on disk and
        comparing it to the Hub's sha256, repairing it on a mismatch. That is a
        better guarantee than the tag, at the cost of reading the file.

        *.incomplete files are never touched: they belong to cancelled or failed
        downloads that are still resumable, and they live in the same folder.
        """
        local_dir = Path(item.local_dir())
        removed = 0
        for rel, _size in item.files:
            for path in self._sidecar_paths(local_dir, rel):
                if path.suffix == ".incomplete":
                    continue        # belt and braces; should never match
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        self._prune_sidecar_dir(local_dir)
        if removed:
            self._log(f"[cleanup] removed {removed} sidecar file(s) under {local_dir}")
        return removed

    def _prune_sidecar_dir(self, local_dir: Path) -> None:
        """Remove the .cache/huggingface tree once nothing useful is left in it."""
        hf_dir = local_dir / ".cache" / "huggingface"
        download = hf_dir / "download"
        if not hf_dir.is_dir():
            return
        try:
            # anything still pending keeps the whole folder
            if any(download.rglob("*.incomplete")) or any(download.rglob("*.metadata")):
                return
        except OSError:
            return
        try:
            for stale in download.rglob("*.lock"):
                stale.unlink(missing_ok=True)
            for directory in sorted(
                (d for d in download.rglob("*") if d.is_dir()),
                key=lambda d: len(d.parts), reverse=True,
            ):
                directory.rmdir()
            download.rmdir()
            for name in ("CACHEDIR.TAG", ".gitignore", ".gitignore.lock"):
                (hf_dir / name).unlink(missing_ok=True)
            hf_dir.rmdir()
            (local_dir / ".cache").rmdir()
        except OSError:
            pass        # something else lives there; leaving it is harmless

    # -- log --------------------------------------------------------------

    def _log(self, text: str) -> None:
        self.log.appendPlainText(text)


# --------------------------------------------------------------------------

def fallback_error(message: str) -> None:
    """Last resort when Qt itself will not come up."""
    if IS_WINDOWS:
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "Fantastic HuggingFace Downloader", 0x10)
            return
        except Exception:  # noqa: BLE001
            pass
    for tool in ("zenity", "kdialog"):
        exe = shutil.which(tool)
        if not exe:
            continue
        try:
            if tool == "zenity":
                subprocess.run([exe, "--error", "--text", message], check=False)
            else:
                subprocess.run([exe, "--error", message], check=False)
            return
        except OSError:
            continue
    print(message, file=sys.stderr)


def main() -> int:
    try:
        app = QApplication(sys.argv)
    except Exception as exc:  # noqa: BLE001
        fallback_error(f"Fantastic HuggingFace Downloader could not start Qt: {exc}")
        return 1

    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)

    # The accent is the only user-editable token: set "accent" in settings.ini
    # and the whole ramp follows from it.
    accent = make_settings().value("accent", "#2f6fed") or "#2f6fed"
    app.setStyleSheet(build_stylesheet(accent=accent) + extra_stylesheet(Theme(accent)))

    hf_bin = ensure_dependencies()
    if not hf_bin:
        return 1

    window = MainWindow(hf_bin)
    window.show()

    if len(sys.argv) > 1:
        window.url_edit.setText(sys.argv[1])

    code = app.exec()
    wait_for_workers()
    return code


if __name__ == "__main__":
    sys.exit(main())
