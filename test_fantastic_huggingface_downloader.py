import os
import pathlib
import sys
from base64 import b64decode as _b64decode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fantastic_huggingface_downloader as H

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"{label}\n   got:  {got!r}\n   want: {want!r}")


# ---- URL parsing ---------------------------------------------------------
t = H.parse_hf_url(
    "https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/"
    "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors"
)
check("blob repo", t.repo_id, "Comfy-Org/MiniMax-H3")
check("blob type", t.repo_type, "model")
check("blob rev", t.revision, "main")
check("blob path", t.path,
      "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors")
check("blob isdir", t.path_is_dir, False)

t = H.parse_hf_url("https://huggingface.co/owner/repo/resolve/main/a.bin?download=true")
check("resolve path", t.path, "a.bin")

t = H.parse_hf_url("https://huggingface.co/owner/repo/tree/main/subdir/deeper")
check("tree path", t.path, "subdir/deeper")
check("tree isdir", t.path_is_dir, True)

t = H.parse_hf_url("https://huggingface.co/datasets/HuggingFaceFW/fineweb/blob/main/x.parquet")
check("dataset type", t.repo_type, "dataset")
check("dataset repo", t.repo_id, "HuggingFaceFW/fineweb")

t = H.parse_hf_url("https://huggingface.co/owner/repo")
check("bare repo path", t.path, "")
check("bare repo rev", t.revision, None)

t = H.parse_hf_url("https://huggingface.co/bert-base-uncased")
check("canonical repo", t.repo_id, "bert-base-uncased")

t = H.parse_hf_url("https://huggingface.co/owner/repo/blob/refs%2Fpr%2F5/model.safetensors")
check("pr revision", t.revision, "refs/pr/5")
check("pr path", t.path, "model.safetensors")

t = H.parse_hf_url("hf://datasets/owner/ds/data/train.parquet")
check("hf uri type", t.repo_type, "dataset")
check("hf uri path", t.path, "data/train.parquet")

t = H.parse_hf_url("  owner/repo  ")
check("bare id", t.repo_id, "owner/repo")

for bad in ["", "not a url", "https://example.com/a/b"]:
    try:
        H.parse_hf_url(bad)
        fails.append(f"expected ParseError for {bad!r}")
    except H.ParseError:
        pass

# ---- command building ----------------------------------------------------
t = H.parse_hf_url(
    "https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/"
    "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors"
)
check("file args", H.build_args(t, H.MODE_FILE), [
    "download", "Comfy-Org/MiniMax-H3",
    "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    "--revision", "main",
])
check("folder args", H.build_args(t, H.MODE_FOLDER), [
    "download", "Comfy-Org/MiniMax-H3",
    "--include", "diffusion_models/*",
    "--revision", "main",
])
# a file at the repo root has no parent folder to fetch
root = H.parse_hf_url("https://huggingface.co/o/r/blob/main/config.json")
check("root folder prefix", H.folder_prefix(root), "")
try:
    H.build_args(root, H.MODE_FOLDER)
    fails.append("expected ParseError for folder mode on a root-level file")
except H.ParseError:
    pass

tree = H.parse_hf_url("https://huggingface.co/o/r/tree/main/sub/deep")
check("tree folder prefix", H.folder_prefix(tree), "sub/deep")

check("repo args", H.build_args(t, H.MODE_REPO), [
    "download", "Comfy-Org/MiniMax-H3", "--revision", "main",
])

d = H.parse_hf_url("https://huggingface.co/datasets/o/r/blob/main/f.parquet")
check("dataset args", H.build_args(d, H.MODE_FILE), [
    "download", "o/r", "f.parquet", "--repo-type", "dataset", "--revision", "main",
])

# ---- ANSI stripping and CLI-nag filtering --------------------------------
raw = ("\x1b[90mHint: The `hf-cli` skill is not installed. "
       "Run `hf skills add -g --claude` to teach your AI agents how to use "
       "the `hf` CLI.\x1b[0m")
cleaned = H.clean_output(raw)
assert "\x1b" not in cleaned and "[90m" not in cleaned, "escape codes survived"
assert cleaned.startswith("Hint: The `hf-cli` skill"), cleaned
assert H.is_cli_nag(cleaned), "the skill advert should be filtered from the log"
assert H.is_cli_nag(H.clean_output("\x1b[90mHint: ... hf skills update hf-cli ...\x1b[0m"))

# a genuine message must NOT be swallowed by the filter
for keep in ["Fetching 3 files", "401 Client Error: Unauthorized",
             "/home/me/ComfyUI/models/diffusion_models/model.safetensors"]:
    assert not H.is_cli_nag(keep), f"wrongly filtered: {keep}"

# progress must still parse after color codes are stripped
st_c = H.ProgressState()
assert H.parse_progress_line(
    H.clean_output("\x1b[0mmodel.safetensors:  50%|#####     | 1.0G/2.0G "
                   "[00:10<00:10, 100MB/s]\x1b[0m"), st_c)
check("pct after strip", st_c.percent, 50)

# ---- output mode pinning -------------------------------------------------
check("format flag appended", H.build_args(t, H.MODE_FILE, True)[-2:], ["--format", "human"])
check("format flag omitted", "--format" in H.build_args(t, H.MODE_FILE, False), False)

check(
    "preview",
    H.preview_command("hf-does-not-exist", t, H.MODE_FILE, "/mnt/target/path"),
    "HF_XET_HIGH_PERFORMANCE=1 hf-does-not-exist download Comfy-Org/MiniMax-H3 "
    "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors "
    "--revision main --local-dir /mnt/target/path",
)
# a missing binary must degrade to "no --format", never crash
check("probe on missing binary", H.supports_format_flag("hf-does-not-exist"), False)

# spaces in the destination must survive as a single shell token
assert "'/mnt/my drive'" in H.preview_command("hf-does-not-exist", t, H.MODE_FILE, "/mnt/my drive")

# ---- progress parsing: the three real shapes ------------------------------
# Xet reconstruction bar (has %, "890MB / 2.67GB", rate as a postfix, no bracket)
sx = H.ProgressState()
assert H.parse_progress_line(
    "minimax_h3_fl2va_pruned_int8_convrot.saf(…): reconstructing file:  33%|███       |  890MB / 2.67GB, 38.7MB/s", sx)
check("xet pct", sx.percent, 33)
check("xet done", sx.done_bytes, 890e6)
check("xet total", sx.total_bytes, 2.67e9)
check("xet rate", sx.rate_bps, 38.7e6)
check("xet rate text", sx.rate_text, "38.7MB/s")

# Xet transfer bar (NO percentage, done bytes only, rate postfix)
st2 = H.ProgressState()
assert H.parse_progress_line(
    "minimax_h3_fl2va_pruned_int8_convrot.saf(…): downloading bytes: ████████▎ | 2.23GB, 41.2MB/s", st2)
check("transfer pct stays None", st2.percent, None)
check("transfer done", st2.transfer_bytes, 2.23e9)
check("transfer leaves recon unset", st2.done_bytes, None)
check("transfer rate", st2.rate_bps, 41.2e6)

# transfer bar is kept SEPARATELY, never merged into the reconstruction count
assert H.parse_progress_line("x: downloading bytes: ██| 9.99GB, 41.2MB/s", sx)
check("recon count untouched by transfer", sx.done_bytes, 890e6)
check("transfer tracked on its own", sx.transfer_bytes, 9.99e9)

# Regression: a big file buffers, so reconstruction stays at 0.00B for a long
# while and the transfer bar is the only live number. Reporting 0 here was the
# "stuck on 0B / 19GB" bug.
big = H.ProgressState()
H.parse_progress_line("f: reconstructing file:   0%|   |  0.00B / 19.0GB", big)
check("recon pinned at zero", big.done_bytes, 0.0)
H.parse_progress_line("f: downloading bytes: █  |  4.10GB, 45.8MB/s", big)
assert abs(big.transfer_bytes - 4.10e9) < 1, big.transfer_bytes
assert abs(H.best_done_bytes(big, None) - 4.10e9) < 1
assert abs(H.best_done_bytes(big, 0) - 4.10e9) < 1
# once reconstruction overtakes, it wins
H.parse_progress_line("f: reconstructing file:  30%|###|  5.70GB / 19.0GB", big)
assert abs(H.best_done_bytes(big, None) - 5.70e9) < 1
# nothing may ever go backwards
H.parse_progress_line("f: downloading bytes: █  |  0.50GB, 40MB/s", big)
assert abs(H.best_done_bytes(big, None) - 5.70e9) < 1, "went backwards"
# disk wins when it is furthest along
check("disk can win", H.best_done_bytes(big, 9.0e9), 9.0e9)
check("no sources at all", H.best_done_bytes(H.ProgressState(), None), None)

# a bar with no total carries only a byte count, so it feeds the transfer
# counter rather than the disk-flushed one
st3 = H.ProgressState()
H.parse_progress_line("name: reconstructing file: |  445MB", st3)
check("no-total goes to transfer", st3.transfer_bytes, 445e6)
check("no-total leaves recon unset", st3.done_bytes, None)
check("no-total pct", st3.percent, None)
check("no-total still reported", H.best_done_bytes(st3, None), 445e6)

# percent derived from bytes when the % field is absent
st4 = H.ProgressState()
assert H.parse_progress_line("name: |  1.00GB / 4.00GB, 10MB/s", st4)
check("derived pct", st4.percent, 25)

# The full Xet stderr stream, captured byte for byte from huggingface_hub's
# own XetDownloadProgressReporter (carriage returns, ANSI cursor moves and
# all) and embedded here so the parser is checked against real output rather
# than lines invented to match it. Regenerate by rendering that class and
# base64-ing its stderr.
_XET_STREAM_B64 = (
    "Cg1taW5pbWF4X2gzX2ZsMnZhX3BydW5lZF9pbnQ4X2NvbnZyb3Quc2FmZXRlbnNvcnM6ICAgMCV8"
    "ICAgICAgICAgIHwgIDAuMDBCIC8gMi42N0dCICAgICAgICAgICAgG1tBDURvd25sb2FkaW5nIGJ5"
    "dGVzOiAgICAgICAgICAgfCAgMC4wMEIgICAgICAgICAgICAKDW1pbmltYXhfaDNfZmwydmFfcHJ1"
    "bmVkX2ludDhfY29udnJvdC5zYWZldGVuc29yczogIDE3JXzilojilosgICAgICAgIHwgIDQ0NU1C"
    "IC8gMi42N0dCICAgICAgICAgICAgG1tBDURvd25sb2FkaW5nIGJ5dGVzOiDilojilojilojilo4g"
    "ICAgICB8ICA4OTBNQiwgNDEuMk1CL3MgIAoNbWluaW1heF9oM19mbDJ2YV9wcnVuZWRfaW50OF9j"
    "b252cm90LnNhZmV0ZW5zb3JzOiAgMzMlfOKWiOKWiOKWiOKWjiAgICAgIHwgIDg5ME1CIC8gMi42"
    "N0dCLCAzOC43TUIvcyAgG1tBCg1taW5pbWF4X2gzX2ZsMnZhX3BydW5lZF9pbnQ4X2NvbnZyb3Qu"
    "c2FmZXRlbnNvcnM6ICA1MCV84paI4paI4paI4paI4paIICAgICB8IDEuMzNHQiAvIDIuNjdHQiwg"
    "MzguN01CL3MgIBtbQQ1Eb3dubG9hZGluZyBieXRlczog4paI4paI4paI4paI4paI4paI4paLICAg"
    "fCAxLjc4R0IsIDQxLjJNQi9zICAKDW1pbmltYXhfaDNfZmwydmFfcHJ1bmVkX2ludDhfY29udnJv"
    "dC5zYWZldGVuc29yczogIDY3JXzilojilojilojilojilojilojilosgICB8IDEuNzhHQiAvIDIu"
    "NjdHQiwgMzguN01CL3MgIBtbQQ1Eb3dubG9hZGluZyBieXRlczog4paI4paI4paI4paI4paI4paI"
    "4paI4paI4paOIHwgMi4yM0dCLCA0MS4yTUIvcyAgCg1taW5pbWF4X2gzX2ZsMnZhX3BydW5lZF9p"
    "bnQ4X2NvbnZyb3Quc2FmZXRlbnNvcnM6ICA4MyV84paI4paI4paI4paI4paI4paI4paI4paI4paO"
    "IHwgMi4yM0dCIC8gMi42N0dCLCAzOC43TUIvcyAgG1tBDURvd25sb2FkaW5nIGJ5dGVzOiDiloji"
    "lojilojilojilojilojilojilojilojiloh8IDIuNjdHQiwgNDEuMk1CL3MgIA1Eb3dubG9hZGlu"
    "ZyBieXRlczog4paI4paI4paI4paI4paI4paI4paI4paI4paI4paIfCAyLjY3R0IsIDQxLjJNQi9z"
    "ICAKDW1pbmltYXhfaDNfZmwydmFfcHJ1bmVkX2ludDhfY29udnJvdC5zYWZldGVuc29yczogIDgz"
    "JXzilojilojilojilojilojilojilojilojilo4gfCAyLjIzR0IgLyAyLjY3R0IsIDM4LjdNQi9z"
    "ICAK"
)
raw = _b64decode(_XET_STREAM_B64).decode("utf-8", "replace")
import re as _re
lines = [l.strip() for l in _re.split(r"[\r\n]", H.clean_output(raw)) if l.strip()]
sfull = H.ProgressState(); unparsed = []
for l in lines:
    if not H.parse_progress_line(l, sfull):
        unparsed.append(l)
check("every real xet line parsed", unparsed, [])
check("final pct from stream", sfull.percent, 83)
assert sfull.rate_bps > 0, "rate never extracted from the real stream"

# ---- progress parsing (legacy plain tqdm) ---------------------------------
st = H.ProgressState()
line = ("minimax_h3.safetensors:  45%|####5     | 1.20G/2.67G "
        "[00:31<00:38, 38.7MB/s]")
assert H.parse_progress_line(line, st)
check("pct", st.percent, 45)
check("rate", st.rate_text, "38.7MB/s")

st2 = H.ProgressState()
assert H.parse_progress_line("Fetching 15 files:  20%|##        | 3/15 [00:04<00:20]", st2)
check("overall pct", st2.overall_percent, 20)

check("noise ignored", H.parse_progress_line("Downloading to /tmp/x", H.ProgressState()), False)
check("noise not flagged", H.looks_like_progress("Downloading to /tmp/x"), False)
check("bar-ish flagged", H.looks_like_progress("weird: ### | 5.0GB"), True)

# the plain-tqdm rate inside the bracket still yields a numeric speed
st5 = H.ProgressState()
H.parse_progress_line("f:  10%|#  | 1.0G/10G [00:10<01:30, 100MB/s]", st5)
check("bracket rate numeric", st5.rate_bps, 100e6)
check("bracket done/total", (st5.done_bytes, st5.total_bytes), (1.0e9, 10e9))

from PySide6.QtWidgets import QApplication  # noqa: E402
import tempfile, pathlib  # noqa: E402

app = QApplication.instance() or QApplication([])
win = H.MainWindow("hf")

with tempfile.TemporaryDirectory() as tmp:
    dest = pathlib.Path(tmp)
    # Byte measurement must find the in-progress file even though its name is
    # <short_hash>.<etag>.incomplete, built from hub internals we cannot and
    # must not reconstruct. Globbing is the only safe way to spot it.
    dl = dest / ".cache" / "huggingface" / "download"
    dl.mkdir(parents=True, exist_ok=True)
    (dl / "a1b2c3d4.9f8e7d6c5b4a39281706.incomplete").write_bytes(b"q" * 42)
    win.files = [("diffusion_models/model.safetensors", 100)]
    check("measures an etag-named partial", win._measure(dest), 42)

    # nested partials (folder or whole-repo downloads) count too
    nested = dl / "diffusion_models"
    nested.mkdir(parents=True, exist_ok=True)
    (nested / "ffffeeee.0011223344556677.incomplete").write_bytes(b"w" * 8)
    check("measures nested partials", win._measure(dest), 50)

    # once the file is finished, the completed bytes are counted instead
    (dest / "diffusion_models").mkdir(exist_ok=True)
    (dest / "diffusion_models" / "model.safetensors").write_bytes(b"z" * 100)
    check("counts finished files", win._measure(dest), 150)

    # a destination with nothing downloaded yet reads as zero, not as an error
    win.files = [("nothing/here.bin", 10)]
    empty = dest / "empty-dest"
    empty.mkdir()
    check("empty destination", win._measure(empty), 0)

# ---- picker dialog behaviour ---------------------------------------------
from PySide6.QtCore import Qt as _Qt  # noqa: E402

# self-contained: this block must not depend on where else in the file a
# fixture happens to be defined
picker_listing = [
    ("README.md", 4_000),
    ("config.json", 1_200),
    ("diffusion_models/big.safetensors", 19_000_000_000),
    ("diffusion_models/small.safetensors", 9_500_000_000),
    ("text_encoders/t5xxl.safetensors", 4_800_000_000),
]
dlg = H.FilePickerDialog(picker_listing, {"config.json"}, None)
check("preselection honoured", dlg.selected_paths(), ["config.json"])

# Opening fresh ticks everything: the workflow is unchecking what you do not
# want. Deriving the preselection from the current mode gave an EMPTY picker
# whenever it was opened by selecting the "Choose files" radio, because the
# mode was already select and matched nothing.
dlg_all = H.FilePickerDialog(picker_listing, {f[0] for f in picker_listing}, None)
check("everything ticked by default", len(dlg_all.selected_paths()), len(picker_listing))
dlg_all.deleteLater()
check("OK enabled with a selection", dlg.ok_button.isEnabled(), True)

# The bulk buttons act on the rows currently listed, which is what makes
# filter-then-add work - so they must not claim "All" while a filter is hiding
# half the repo.
check("labels say All with no filter",
      [_b.text() for _b in (dlg.select_btn, dlg.clear_btn, dlg.invert_btn)],
      ["Select All", "Clear All", "Invert Selection"])
dlg.filter_edit.setText("safetensors")
check("labels say Shown while filtering",
      [_b.text() for _b in (dlg.select_btn, dlg.clear_btn, dlg.invert_btn)],
      ["Select Shown", "Clear Shown", "Invert Shown"])
dlg.filter_edit.setText("")
check("labels revert when the filter clears", dlg.select_btn.text(), "Select All")

dlg.filter_edit.setText("safetensors diffusion")   # all terms must match
check("filter is AND, not OR",
      [i.text(0) for i in dlg._visible_items()],
      ["diffusion_models/big.safetensors", "diffusion_models/small.safetensors"])

dlg._set_shown(_Qt.CheckState.Checked)
check("select-shown only touches visible rows",
      sorted(dlg.selected_paths()),
      ["config.json", "diffusion_models/big.safetensors", "diffusion_models/small.safetensors"])

dlg._set_shown(_Qt.CheckState.Unchecked)
check("clear-shown leaves hidden picks alone", dlg.selected_paths(), ["config.json"])

dlg.filter_edit.setText("")
dlg._set_shown(_Qt.CheckState.Unchecked)
check("OK disabled with nothing picked", dlg.ok_button.isEnabled(), False)
dlg.deleteLater()

# ---- the picker is scoped to the folder the link pointed at ---------------
# Linking to one subfolder and being shown every file in the repo buries what
# was asked for. The listing narrows, with one click to widen it again.
_scoped_listing = [
    ("README.md", 1), ("config.json", 1),
    ("diffusion_models/a.safetensors", 2), ("diffusion_models/b.safetensors", 3),
    ("text_encoders/t5.safetensors", 4), ("vae/v.safetensors", 5),
]
# the app preselects only what is in scope, so mirror that here
_in_scope = {f[0] for f in _scoped_listing if f[0].startswith("diffusion_models/")}
_sc = H.FilePickerDialog(_scoped_listing, _in_scope, None, scope="diffusion_models")
check("only the linked folder is listed",
      [f[0] for f in _sc.files],
      ["diffusion_models/a.safetensors", "diffusion_models/b.safetensors"])
check("selection is scoped too", _sc.selected_paths(),
      ["diffusion_models/a.safetensors", "diffusion_models/b.safetensors"])
assert _sc.scope_cb is not None, "there must be a way to widen the listing"

# widening shows everything without losing what was already ticked
_sc.scope_cb.setChecked(True)
check("widening lists the whole repo", len(_sc.files), len(_scoped_listing))
check("earlier ticks survive widening", _sc.selected_paths(),
      ["diffusion_models/a.safetensors", "diffusion_models/b.safetensors"])
# and files revealed by widening start unticked - you widened to add something
# specific, not to grab the whole repo
assert "README.md" not in _sc.selected_paths()

# ticking something outside the original folder works after widening
for _i in range(_sc.tree.topLevelItemCount()):
    _row2 = _sc.tree.topLevelItem(_i)
    if _row2.text(0) == "vae/v.safetensors":
        _row2.setCheckState(0, _Qt.CheckState.Checked)
assert "vae/v.safetensors" in _sc.selected_paths()
_sc.deleteLater()

# a bare repo link has nothing to scope to, so no widen box appears
_un = H.FilePickerDialog(_scoped_listing, set(), None, scope="")
check("unscoped lists everything", len(_un.files), len(_scoped_listing))
check("no widen box when unscoped", _un.scope_cb, None)
_un.deleteLater()

# a scope that matches nothing must not produce an empty picker
_empty = H.FilePickerDialog(_scoped_listing, set(), None, scope="nonexistent")
check("a scope matching nothing falls back to the full list",
      len(_empty.files), len(_scoped_listing))
_empty.deleteLater()

# ---- window smoke --------------------------------------------------------
win.url_edit.setText(
    "https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/diffusion_models/m.safetensors"
)
assert win.rb_file.isChecked(), "a blob link should preselect file mode"
win.url_edit.setText("https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/diffusion_models")
assert win.rb_folder.isChecked(), "a tree link should preselect folder mode"
win.url_edit.setText("https://huggingface.co/Comfy-Org/MiniMax-H3")
assert win.rb_repo.isChecked(), "a bare repo link should preselect repo mode"
assert not win.rb_file.isEnabled(), "file mode needs a path"
assert not win.rb_folder.isEnabled(), "folder mode needs a path"

win.url_edit.setText("https://huggingface.co/o/r/blob/main/config.json")
assert not win.rb_folder.isEnabled(), "root-level file has no folder to fetch"
assert win.rb_file.isChecked()

# ---- picking individual files out of a repo -------------------------------
listing = [
    ("README.md", 4_000),
    ("config.json", 1_200),
    ("diffusion_models/big.safetensors", 19_000_000_000),
    ("diffusion_models/small.safetensors", 9_500_000_000),
    ("text_encoders/t5xxl.safetensors", 4_800_000_000),
]
repo = H.parse_hf_url("https://huggingface.co/Comfy-Org/MiniMax-H3")
blob = H.parse_hf_url("https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/diffusion_models/big.safetensors")

# one fetch serves every mode: the key must not vary with mode or path
check("key ignores mode", H.lookup_key(repo, H.MODE_REPO), H.lookup_key(repo, H.MODE_SELECT))
# The key ignores path and mode, but NOT revision: a bare repo link means
# "default branch" (revision None) which is not provably the same ref as an
# explicit /blob/main/, since a repo's default branch need not be main.
check("key ignores path within one revision",
      H.lookup_key(blob, H.MODE_FILE), H.lookup_key(blob, H.MODE_REPO))
assert H.lookup_key(repo) != H.lookup_key(blob), "None revision must not be assumed to be main"

check("repo mode = everything", len(H.files_for_mode(listing, repo, H.MODE_REPO)), 5)
check("file mode = just that one",
      H.files_for_mode(listing, blob, H.MODE_FILE), [("diffusion_models/big.safetensors", 19_000_000_000)])
check("folder mode = the folder",
      [f[0] for f in H.files_for_mode(listing, blob, H.MODE_FOLDER)],
      ["diffusion_models/big.safetensors", "diffusion_models/small.safetensors"])
picked = ["config.json", "text_encoders/t5xxl.safetensors"]
check("select mode = the picks",
      [f[0] for f in H.files_for_mode(listing, repo, H.MODE_SELECT, picked)], picked)
check("select ignores unknown paths",
      H.files_for_mode(listing, repo, H.MODE_SELECT, ["nope.bin"]), [])
check("folder mode on a root file is empty",
      H.files_for_mode(listing, H.parse_hf_url("https://huggingface.co/o/r/blob/main/a.bin"), H.MODE_FOLDER), [])

# selected files become positional arguments, sorted and deduplicated by set use
args = H.build_args(repo, H.MODE_SELECT, False, ["b.safetensors", "a.safetensors"])
check("select args sorted", args, ["download", "Comfy-Org/MiniMax-H3", "a.safetensors", "b.safetensors"])
try:
    H.build_args(repo, H.MODE_SELECT, False, [])
    fails.append("empty selection should raise")
except H.ParseError:
    pass

# command-length guard: a huge selection must be caught, not handed to exec
many = [f"folder_{i:03d}/model_shard_{i:05d}_of_09999.safetensors" for i in range(4000)]
assert H.command_length(H.build_args(repo, H.MODE_SELECT, False, many)) > H.COMMAND_LENGTH_LIMIT
assert H.command_length(H.build_args(repo, H.MODE_SELECT, False, many[:20])) < H.COMMAND_LENGTH_LIMIT

# ---- destination resolution -----------------------------------------------
# hf writes AND verifies at <local-dir>/<repo-path>, so landing a file in the
# folder the user picked means handing hf the parent of the repo's subfolder.
# Moving the file afterwards is what used to destroy the hash check.
check("subfolder stripped so the file lands where it was pointed",
      H.resolve_local_dir("/ai/ComfyUI/models/diffusion_models", "diffusion_models"),
      "/ai/ComfyUI/models")
check("nested prefix stripped whole",
      H.resolve_local_dir("/ai/models/split_files/diffusion_models", "split_files/diffusion_models"),
      "/ai/models")
check("no match means the destination is used literally",
      H.resolve_local_dir("/mnt/scratch", "diffusion_models"), "/mnt/scratch")
check("partial match must NOT strip",
      H.resolve_local_dir("/ai/models/diffusion_models", "split_files/diffusion_models"),
      "/ai/models/diffusion_models")
check("no prefix at all", H.resolve_local_dir("/ai/models", ""), "/ai/models")
# Model folders are often a separate disk mounted into the tree. Stripping a
# level there would stage the download - and measure free space - on the parent
# drive rather than the one the user pointed at and made room on.
import os as _os2
if _os2.path.exists("/dev/shm") and _os2.stat("/dev/shm").st_dev != _os2.stat("/dev").st_dev:
    check("does not strip across a mount point",
          H.resolve_local_dir("/dev/shm", "shm"), "/dev/shm")
_same = _tf.mkdtemp() if False else None
import tempfile as _tf6
_r6 = pathlib.Path(_tf6.mkdtemp())
(_r6 / "models" / "diffusion_models").mkdir(parents=True)
check("still strips within one filesystem",
      H.resolve_local_dir(str(_r6 / "models" / "diffusion_models"), "diffusion_models"),
      str(_r6 / "models"))
check("undecidable paths still strip",
      H.resolve_local_dir("/nonexistent/models/diffusion_models", "diffusion_models"),
      "/nonexistent/models")

# a repo folder must never be stripped past the root
check("cannot strip everything", H.resolve_local_dir("/diffusion_models", "diffusion_models"),
      "/diffusion_models")

_dest = "/ai/ComfyUI/models/diffusion_models"
_blob2 = H.parse_hf_url("https://huggingface.co/C/M/blob/main/diffusion_models/big.safetensors")
_it = H.items_for_request(_blob2, H.MODE_FILE, _dest, [("diffusion_models/big.safetensors", 5)], [])[0]
check("item passes the stripped dir to hf", _it.local_dir(), "/ai/ComfyUI/models")
check("but the file lands in the chosen folder", _it.final_dir(), _dest)
assert _it.args(False)[-2:] == ["--local-dir", "/ai/ComfyUI/models"]

# a whole repo has no single prefix, so its structure appears under the pick
_ri = H.items_for_request(H.parse_hf_url("https://huggingface.co/C/M"), H.MODE_REPO,
                          _dest, listing, [])[0]
check("whole repo is not stripped", _ri.local_dir(), _dest)

# The preview must show the command that actually runs. It previously appended
# the raw destination while execution used the stripped one, so the two
# disagreed on --local-dir.
_prev = H.preview_command("hf-does-not-exist", _blob2, H.MODE_FILE, _dest)
check("preview and execution agree on --local-dir",
      _prev.split("--local-dir")[-1].strip(), _it.args(False)[-1])

# ---- queue construction ---------------------------------------------------
qrepo = H.parse_hf_url("https://huggingface.co/Comfy-Org/MiniMax-H3")
qblob = H.parse_hf_url("https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/diffusion_models/big.safetensors")

# Picked files become one item each: that is what removes the command-length
# ceiling, since no single command ever lists more than one path.
qitems = H.items_for_request(qrepo, H.MODE_SELECT, "/d", listing,
                             ["config.json", "diffusion_models/big.safetensors"])
check("one item per picked file", len(qitems), 2)
check("items sorted by path", [i.label for i in qitems],
      ["config.json", "diffusion_models/big.safetensors"])
check("sizes carried over", [i.size for i in qitems], [1_200, 19_000_000_000])
for qi in qitems:
    check(f"{qi.label} runs as a single-file download", qi.mode, H.MODE_FILE)
    assert qi.label in qi.args(False), "the file must be a positional argument"
    assert "--include" not in qi.args(False)

# ...while whole-repo and whole-folder stay ONE item, because the pattern does
# the work and expanding them would be pointless
check("whole repo is one item", len(H.items_for_request(qrepo, H.MODE_REPO, "/d", listing, [])), 1)
check("folder is one item", len(H.items_for_request(qblob, H.MODE_FOLDER, "/d", listing, [])), 1)
check("repo item label", H.items_for_request(qrepo, H.MODE_REPO, "/d", listing, [])[0].label, "(whole repo)")
check("folder item label",
      H.items_for_request(qblob, H.MODE_FOLDER, "/d", listing, [])[0].label, "diffusion_models/")
check("repo item totals the repo",
      H.items_for_request(qrepo, H.MODE_REPO, "/d", listing, [])[0].size,
      sum(sz for _, sz in listing))

# a selection of thousands is now fine: each command carries one path
huge = [f"folder_{i:03d}/shard_{i:05d}.safetensors" for i in range(4000)]
huge_items = H.items_for_request(qrepo, H.MODE_SELECT, "/d", [(h, 1) for h in huge], huge)
check("4000 files queue cleanly", len(huge_items), 4000)
assert max(H.command_length(i.args(False)) for i in huge_items) < H.COMMAND_LENGTH_LIMIT, \
    "per-item commands must stay well under the OS limit"

mixed = H.items_for_request(qrepo, H.MODE_SELECT, "/first", listing, ["config.json"])
check("destination stored on the item", mixed[0].dest, "/first")
assert mixed[0].args(False)[-2:] == ["--local-dir", "/first"]
mixed[0].dest = "/second"
assert mixed[0].args(False)[-2:] == ["--local-dir", "/second"], "changing dest must change the command"

# an item from another repo keeps its own repo id and revision
other_repo = H.parse_hf_url("https://huggingface.co/Other-Org/Second/blob/v2/vae/v.safetensors")
oi = H.items_for_request(other_repo, H.MODE_FILE, "/d", [("vae/v.safetensors", 5)], [])[0]
check("cross-repo item keeps its repo", oi.repo_label, "Other-Org/Second@v2")
assert "Other-Org/Second" in oi.args(False)

check("nothing picked yields no items",
      H.items_for_request(qrepo, H.MODE_SELECT, "/d", listing, []), [])

# ---- auto-start and the manual Start button -------------------------------
import tempfile as _tf5  # noqa: E402
_as = H.MainWindow("hf-does-not-exist")
_as.lookup_debounce.stop()
_as.dest_combo.setCurrentText(_tf5.mkdtemp())
_as.url_edit.setText("https://huggingface.co/C/M/blob/main/a.bin")
_as.all_files = [("a.bin", 10)]
_as._refresh()

# with auto-start off, adding must NOT begin downloading
_as.autostart_cb.setChecked(False)
_as._add_to_queue()
check("item queued", len(_as.queue), 1)
check("auto-start off leaves it waiting", _as.queue[0].status, H.STATUS_QUEUED)
check("nothing running", _as.current_item, None)
check("Start is offered", _as.start_btn.isEnabled(), True)

# the preference survives a restart
check("auto-start persisted", _as.settings.value("autostart", True, type=bool), False)

# Start also clears a pause
_as.paused = True
_as._start_queue()
check("Start clears the pause", _as.paused, False)
_as.queue.clear()
_as.current_item = None
_as._refresh_queue()
check("Start disabled with an empty queue", _as.start_btn.isEnabled(), False)
_as.close()

# ---- inline rename editors ------------------------------------------------
# Creating a new folder in the file dialog opens a QLineEdit INSIDE the view.
# The shared stylesheet pads every QLineEdit by 5px 10px, which makes that
# editor taller than a row; Qt squashes it and the name gets clipped.
from PySide6.QtWidgets import QTreeWidget as _QTW, QTreeWidgetItem as _QTWI  # noqa: E402
from PySide6.QtWidgets import QLineEdit as _QLE  # noqa: E402
from PySide6.QtCore import Qt as _Qt2  # noqa: E402
from theme import build_stylesheet as _bss, Theme as _Th  # noqa: E402

_old_sheet = app.styleSheet()
app.setStyleSheet(_bss(accent="#2f6fed") + H.extra_stylesheet(_Th("#2f6fed")))
_t = _QTW()
_t.setHeaderLabels(["Name"])
_row = _QTWI(["New Folder3"])
_row.setFlags(_row.flags() | _Qt2.ItemFlag.ItemIsEditable)
_t.addTopLevelItem(_row)
_t.resize(400, 120)
_t.show()
app.processEvents()
_row_h = _t.visualItemRect(_row).height()
_t.editItem(_row, 0)
app.processEvents()
_ed = _t.findChild(_QLE)
assert _ed is not None, "no inline editor appeared"
assert _ed.sizeHint().height() <= _row_h, (
    f"inline editor wants {_ed.sizeHint().height()}px in a {_row_h}px row - text will clip")
assert _ed.height() >= _ed.fontMetrics().height(), "editor too short to show its own text"

# ordinary inputs must keep their normal padding
_plain = _QLE()
_plain.show()
app.processEvents()
assert _plain.sizeHint().height() > _ed.sizeHint().height(), (
    "the view-scoped rule leaked onto ordinary inputs")
_t.close()
_plain.close()
app.setStyleSheet(_old_sheet)

# ---- default window size --------------------------------------------------
# Qt's own guess opened at about 570px, which squeezed the queue's five columns
# into ~500px of viewport and truncated the destination path entirely.
check("default is wide enough for the queue", H.DEFAULT_SIZE[0] >= 1000, True)

_sz = H.MainWindow("hf-does-not-exist")
_sz.lookup_debounce.stop()
_sz.url_edit.setText("https://huggingface.co/Vortex5/Shadow-Siren-24B")
for _i in range(4):
    _qi = H.QueueItem(target=_sz.target, mode=H.MODE_FILE,
                      dest="/mnt/moar/eLLM/models/diffusion_models",
                      label=f"model-{_i:05d}-of-00011.safetensors", size=4_400_000_000)
    _qi.status = H.STATUS_DONE
    _qi.detail = "Done"
    _sz.queue.append(_qi)
_sz._refresh_queue()
_sz.resize(*H.DEFAULT_SIZE)      # this offscreen screen is small, so size directly
_sz.show()
app.processEvents()
_hdr = _sz.queue_tree.header()
_truncated = [
    _sz.queue_tree.headerItem().text(_c)
    for _c in range(_hdr.count())
    if _sz.queue_tree.columnWidth(_c) < _sz.queue_tree.sizeHintForColumn(_c)
]
check("no column is truncated at the default width", _truncated, [])
_cols = sum(_sz.queue_tree.columnWidth(_c) for _c in range(_hdr.count()))
assert _cols <= _sz.queue_tree.viewport().width(), (
    f"columns total {_cols}px but only {_sz.queue_tree.viewport().width()}px of viewport")
_sz.close()

# ---- layout ---------------------------------------------------------------
from PySide6.QtWidgets import QSizePolicy as _QSP  # noqa: E402
_ly = H.MainWindow("hf-does-not-exist")
_ly.lookup_debounce.stop()
_ly.url_edit.setText("https://huggingface.co/C/M")
for _i in range(6):
    _qi = H.QueueItem(target=_ly.target, mode=H.MODE_FILE, dest="/d",
                      label=f"f{_i}.safetensors", size=10)
    _qi.status = H.STATUS_DONE
    _ly.queue.append(_qi)
_ly._refresh_queue()
_ly.show()
app.processEvents()

# The list must be able to give way, or a window manager that clamps to screen
# height squeezes the layout past what its children allow and Qt lets them
# overflow - which is how the buttons ended up painted over the rows.
check("list has no hard floor", _ly.queue_tree.minimumHeight(), 0)
check("list yields vertically",
      _ly.queue_tree.sizePolicy().verticalPolicy(), _QSP.Policy.Ignored)

# ...but the WINDOW reserves room, so at its own minimum the queue is usable
_ly.resize(880, 50)
app.processEvents()
assert _ly.queue_tree.height() >= 80, f"list only {_ly.queue_tree.height()}px at minimum"

def _overlaps(win):
    bottom = win.queue_tree.mapTo(win, win.queue_tree.rect().bottomLeft()).y()
    top = win.pause_btn.mapTo(win, win.pause_btn.rect().topLeft()).y()
    return top < bottom

assert not _overlaps(_ly), "queue buttons overlap the list at the minimum size"

# and nothing overlaps even if the minimum is ignored outright
for _h in (600, 500, 420):
    _ly.setMinimumHeight(0)
    _ly.resize(880, _h)
    app.processEvents()
    assert not _overlaps(_ly), f"queue buttons overlap the list at {_h}px"

# the queue controls must fit without forcing a horizontal scrollbar
check("queue fits an 880px window", _ly.findChild(type(_ly.queue_tree)).parent()
      .minimumSizeHint().width() <= 880, True)
_ly.close()

# ---- sidecar cleanup ------------------------------------------------------
# Deleting the .metadata is what forces hf to fall through to hashing the local
# file against the Hub sha256 on a re-run, instead of trusting the stored etag.
# The .incomplete files sharing that folder belong to cancelled downloads and
# must survive, or Cancel stops being resumable.
import tempfile as _tf4  # noqa: E402

_cl = H.MainWindow("hf-does-not-exist")
_cl.lookup_debounce.stop()
with _tf4.TemporaryDirectory() as _tmp:
    _d = pathlib.Path(_tmp)
    _dl = _d / ".cache" / "huggingface" / "download"
    (_dl / "diffusion_models").mkdir(parents=True)
    (_dl / "diffusion_models" / "done.safetensors.metadata").write_text("meta")
    (_dl / "diffusion_models" / "done.safetensors.lock").write_text("")
    (_dl / "text_encoders").mkdir(parents=True)
    _partial = _dl / "text_encoders" / "abc123.etag999.incomplete"
    _partial.write_bytes(b"y" * 5000)
    (_d / ".cache" / "huggingface" / "CACHEDIR.TAG").write_text("tag")
    (_d / ".cache" / "huggingface" / ".gitignore").write_text("*")

    _item = H.QueueItem(
        target=H.parse_hf_url("https://huggingface.co/C/M/blob/main/diffusion_models/done.safetensors"),
        mode=H.MODE_FILE, dest=str(_d), label="diffusion_models/done.safetensors",
        files=[("diffusion_models/done.safetensors", 10)])
    _removed = _cl._clean_sidecar(_item)
    check("metadata and lock removed", _removed, 2)
    assert not (_dl / "diffusion_models" / "done.safetensors.metadata").exists()
    assert _partial.is_file(), "a resumable partial was deleted"
    assert (_d / ".cache").is_dir(), "folder must stay while a partial lives in it"

    # once the partial is gone too, the whole sidecar tree goes
    _partial.unlink()
    _cl._prune_sidecar_dir(_d)
    assert not (_d / ".cache").exists(), "empty sidecar tree should be removed"

# cleanup must never raise, whatever it is pointed at
_cl._clean_sidecar(H.QueueItem(
    target=H.parse_hf_url("https://huggingface.co/C/M/blob/main/a.bin"),
    mode=H.MODE_FILE, dest="/nonexistent/path/xyz", label="a.bin", files=[("a.bin", 1)]))
_cl.close()

# ---- metadata lookup lifecycle ------------------------------------------
a = H.parse_hf_url("https://huggingface.co/o/r/blob/main/a.bin")
b = H.parse_hf_url("https://huggingface.co/o/r/blob/main/b.bin")
other = H.parse_hf_url("https://huggingface.co/other/repo/blob/main/a.bin")
# Two files in the SAME repo share a key on purpose: one listing serves every
# file, folder, whole-repo and hand-picked selection, so switching between
# them never refetches.
check("same repo shares one fetch", H.lookup_key(a, H.MODE_FILE), H.lookup_key(b, H.MODE_REPO))
assert H.lookup_key(a) != H.lookup_key(other), "different repos must not share a key"
rev = H.parse_hf_url("https://huggingface.co/o/r/blob/v2/a.bin")
assert H.lookup_key(a) != H.lookup_key(rev), "a different revision is a different listing"

# a reply for a repo we have moved on from must not be applied
win.target = a
win.info_key = H.lookup_key(a)
win.all_files = None
win._info_ready([("stale.bin", 999)], "", H.lookup_key(other))
check("stale reply dropped", win.all_files, None)
win.rb_repo.setChecked(True)
win._info_ready([("a.bin", 128)], "", H.lookup_key(a))
check("current reply applied", win.total_bytes, 128)

# the lookup is debounced, so typing does not spawn a thread per keystroke
win.info_key = None
win._start_info_lookup()
win._start_info_lookup()
assert win.lookup_debounce.isActive(), "debounce timer should be armed"
win.lookup_debounce.stop()
check("no threads spawned by debounce alone", len(H._LIVE_WORKERS), 0)

# ---- speed measurement ----------------------------------------------------
# Speed used to be an EMA of the DISK delta while the byte readout came from the
# network counter. Xet flushes to disk in lumps, so the two disagreed wildly:
# the bar leapt hundreds of MB while the rate showed a few hundred KiB/s.
from collections import deque as _deque  # noqa: E402

check("no samples yet", H.speed_from_samples(_deque()), 0.0)
check("one sample is not a rate", H.speed_from_samples(_deque([(0.0, 100.0)])), 0.0)
# too little history is reported as "unknown" rather than as a wild guess
check("window too short to quote",
      H.speed_from_samples(_deque([(0.0, 0.0), (0.3, 3_000_000.0)])), 0.0)

_MiB = 1024 * 1024
_steady = _deque([(float(t), float(t * 4 * _MiB)) for t in range(9)])
assert abs(H.speed_from_samples(_steady) - 4 * _MiB) < 1, "steady 4 MiB/s misread"

# the real shape: network smooth, disk arriving in 12 MiB lumps every 3s. The
# reported rate must track the truth, not the lumps.
_bursty, _flushed = _deque(), 0
for _t in range(1, 13):
    _xfer = _t * 4 * _MiB
    if _xfer - _flushed >= 12 * _MiB:
        _flushed = _xfer
    _bursty.append((float(_t), float(max(_flushed, _xfer))))
    while len(_bursty) > 2 and _t - _bursty[0][0] > H.SPEED_WINDOW:
        _bursty.popleft()
_rate = H.speed_from_samples(_bursty)
assert 3.5 * _MiB <= _rate <= 4.5 * _MiB, f"bursty writes misread as {_rate/_MiB:.1f} MiB/s"

# The sharpest case: bytes that ONLY arrive in lumps, which is what the disk
# series looks like on its own. A last-delta rate reads 0 between flushes and
# 12 MiB/s on one, both wrong; the window has to smooth it to the truth.
_lumpy, _flushed2 = _deque(), 0
for _t in range(1, 13):
    _arrived = _t * 4 * _MiB
    if _arrived - _flushed2 >= 12 * _MiB:
        _flushed2 = _arrived
    _lumpy.append((float(_t), float(_flushed2)))
    while len(_lumpy) > 2 and _t - _lumpy[0][0] > H.SPEED_WINDOW:
        _lumpy.popleft()
_lumpy_rate = H.speed_from_samples(_lumpy)
assert 3.0 * _MiB <= _lumpy_rate <= 5.0 * _MiB, (
    f"lumpy arrivals misread as {_lumpy_rate / _MiB:.1f} MiB/s; a last-delta rate "
    "would report 0 between flushes and 12 MiB/s on one")

# a stalled transfer reads as zero, not as a stale number
_stalled = _deque([(float(t), 5_000_000.0) for t in range(9)])
check("a stall reads as zero", H.speed_from_samples(_stalled), 0.0)

# and the series can never go backwards into a negative rate
_weird = _deque([(0.0, 900.0), (5.0, 100.0)])
assert H.speed_from_samples(_weird) >= 0.0

# ---- bar percentage: bytes beat the printed percentage --------------------
# Xet prints 0% while it buffers. Trusting that pegged the bar at zero even
# though the byte counts were climbing, so the percentage is derived from the
# same bytes shown in the text and the printed one is only a floor.
import tempfile as _tf, pathlib as _pl
_w = H.MainWindow("hf-does-not-exist")
_w.lookup_debounce.stop()
_w.dest_combo.setCurrentText(_tf.mkdtemp())
_w.files = None
_w.total_bytes = 19_000_000_000
_w.started_at = 0.0
_w.bar_percent = 0
_w.state = H.ProgressState()
_w.state.percent = 0                       # what the reconstruction bar prints
_w.state.transfer_bytes = 4_750_000_000    # a quarter of the way, off the network
_w._tick()
check("bar uses bytes, not the printed 0%", _w.bar.value(), 25)

# a printed percentage ahead of the bytes still wins (acts as a floor)
_w.state.percent = 60
_w._tick()
check("printed percentage is a floor", _w.bar.value(), 60)

# and the bar must never retreat when a stale line arrives
_w.state.percent = 0
_w.state.transfer_bytes = 1
_w._tick()
check("bar never goes backwards", _w.bar.value(), 60)
_w.close()

# ---- reaching "Choose files" ----------------------------------------------
from PySide6.QtWidgets import QDialog as _QDialog  # noqa: E402
from unittest.mock import patch as _patch          # noqa: E402
import tempfile as _tf3                            # noqa: E402

_c = H.MainWindow("hf-does-not-exist")
_c.lookup_debounce.stop()
_c.dest_combo.setCurrentText(_tf3.mkdtemp())
_c.url_edit.setText("https://huggingface.co/C/M/blob/main/diffusion_models/a.safetensors")
_c.all_files = None

# The radio used to be gated on already having a selection, which made it
# impossible to ever reach: you needed picked files to enable the control that
# picks files. Both it and the button stay live whenever there is a repo.
check("picker button live before the listing lands", _c.pick_btn.isEnabled(), True)
check("Choose files live before the listing lands", _c.rb_select.isEnabled(), True)

# clicking it while the listing is still in flight explains itself, and does
# not strand the user in a mode that cannot download anything
_seen = {}
with _patch.object(H.QMessageBox, "information", lambda *a, **k: _seen.update(hit=True)):
    _c.rb_select.setChecked(True)
check("explains that the listing is not ready", _seen.get("hit"), True)
assert _c._mode() != H.MODE_SELECT, "must not sit in Choose files with no listing"

_c.all_files = [("diffusion_models/a.safetensors", 8), ("diffusion_models/b.safetensors", 9)]
_c._refresh()

# choosing the radio opens the picker; accepting a selection lands in select mode
def _accept_all(self):
    for _i in range(self.tree.topLevelItemCount()):
        self.tree.topLevelItem(_i).setCheckState(0, _Qt.CheckState.Checked)
    return _QDialog.DialogCode.Accepted

from PySide6.QtCore import Qt as _Qt  # noqa: E402
_c.selected_paths = []
_c.rb_file.setChecked(True)
with _patch.object(H.FilePickerDialog, "exec", _accept_all):
    _c.rb_select.setChecked(True)
check("selecting the radio opened the picker", _c._mode(), H.MODE_SELECT)
check("selection captured", len(_c.selected_paths), 2)

check("radio shows the count", _c.rb_select.text(), "Choose files (2)")

# opening the picker with no prior selection must tick every file, whether it
# was reached by the radio or the button
_probe = {}
def _capture(self):
    _probe["ticked"] = sorted(self.selected_paths())
    return _QDialog.DialogCode.Rejected
_c.selected_paths = []
_c.rb_repo.setChecked(True)
with _patch.object(H.FilePickerDialog, "exec", _capture):
    _c._pick_files()
check("fresh open ticks everything", _probe["ticked"],
      sorted(f[0] for f in _c.all_files))
_c.selected_paths = []
with _patch.object(H.FilePickerDialog, "exec", _capture):
    _c.rb_select.setChecked(True)
check("same via the radio", len(_probe["ticked"]), len(_c.all_files))

# but reopening keeps what you chose last time rather than re-ticking all
_c.selected_paths = ["diffusion_models/a.safetensors"]
with _patch.object(H.FilePickerDialog, "exec", _capture):
    _c._pick_files()
check("reopen keeps prior choice", _probe["ticked"], ["diffusion_models/a.safetensors"])

# cancelling the picker returns to whichever mode you came from
for _rb, _want in [(_c.rb_file, H.MODE_FILE), (_c.rb_folder, H.MODE_FOLDER), (_c.rb_repo, H.MODE_REPO)]:
    _c.selected_paths = []
    _rb.setChecked(True)
    with _patch.object(H.FilePickerDialog, "exec", lambda self: _QDialog.DialogCode.Rejected):
        _c.rb_select.setChecked(True)
    check(f"cancel returns to {_want}", _c._mode(), _want)
    check(f"no phantom selection after cancelling from {_want}", _c.selected_paths, [])
_c.close()

# ---- destination favorites and recents -----------------------------------
check("recent list caps at ten", H.MAX_HISTORY, 10)
check("settings list of one comes back as a list", H._as_path_list("/only/one"), ["/only/one"])
check("empty settings value", H._as_path_list(None), [])
check("blank entries dropped", H._as_path_list(["/a", "", "  "]), ["/a"])

_d = H.MainWindow("hf-does-not-exist")
_d.lookup_debounce.stop()
_d.favorites = []
_d.recents = []
for _i in range(13):
    _d._remember_dest(f"/mnt/models/dir{_i:02d}")
check("only ten recents kept", len(_d.recents), 10)
check("newest first", _d.recents[0], "/mnt/models/dir12")
assert "/mnt/models/dir00" not in _d.recents, "oldest should have aged out"

# a favorite is pinned, so it must not consume a recent slot or age out
_d.dest_combo.setCurrentText("/mnt/nas/loras")
_d._toggle_favorite()
check("favorited", _d.favorites, ["/mnt/nas/loras"])
check("star reflects state", _d.fav_btn.text(), "\u2605")
_d._remember_dest("/mnt/nas/loras")
assert "/mnt/nas/loras" not in _d.recents, "a favorite must not take a recent slot"
for _i in range(20, 32):
    _d._remember_dest(f"/mnt/other/{_i}")
check("favorite survives churn", _d.favorites, ["/mnt/nas/loras"])

# favorites come first, and headers are present but not selectable
_rows = [_d.dest_combo.itemText(_i) for _i in range(_d.dest_combo.count())]
assert _rows[0].startswith("\u2500"), "favorites header should be first"
check("favorite sits above recents", _rows[1], "/mnt/nas/loras")
_model = _d.dest_combo.model()
for _i, _t in enumerate(_rows):
    if _t in _d._header_labels:
        assert not _model.item(_i).isEnabled(), f"header {_t!r} must not be selectable"

# and a header can never end up as the destination, even set programmatically
_d.dest_combo.setCurrentText("/mnt/real/folder")
for _i, _t in enumerate(_rows):
    if _t in _d._header_labels:
        _d.dest_combo.setCurrentIndex(_i)
        assert _d.dest_combo.currentText() not in _d._header_labels, \
            "a header label reached the destination field"

# un-favoriting removes it and drops the star
_d.dest_combo.setCurrentText("/mnt/nas/loras")
_d._toggle_favorite()
check("un-favorited", _d.favorites, [])
check("star cleared", _d.fav_btn.text(), "\u2606")
_d.close()

# ---- the destination dropdown must look like a dropdown -------------------
# The shared sheet styles QComboBox::drop-down but gives it no arrow, and once
# a stylesheet touches a combo Qt stops drawing the native one - so the history
# looked like a plain text field and nobody would know to click it.
from theme import Theme as _Th2  # noqa: E402
_combo_qss = H.extra_stylesheet(_Th2("#2f6fed"))
assert "QComboBox::down-arrow" in _combo_qss, "the dropdown has no arrow"
import re as _re3
_arrow = _re3.search(r"QComboBox::down-arrow \{\s*image: url\(([^)]+)\)", _combo_qss)
assert _arrow, "arrow rule has no image"
assert pathlib.Path(_arrow.group(1)).exists(), "arrow image was never rendered"

# and the widget really is a combo carrying the history
_dd = H.MainWindow("hf-does-not-exist")
_dd.lookup_debounce.stop()
_dd.favorites = ["/mnt/comfy/models"]
_dd.recents = ["/mnt/scratch/a", "/mnt/scratch/b"]
_dd._rebuild_dest_combo("/mnt/scratch/a")
check("destination is editable", _dd.dest_combo.isEditable(), True)
assert _dd.dest_combo.count() >= 5, "history missing from the dropdown"
_dd.close()

# ---- theme integration ----------------------------------------------------
import re as _re2  # noqa: E402
from theme import Theme as _Theme  # noqa: E402

_qss = H.extra_stylesheet(_Theme("#2f6fed"))
for _needed in ["QGroupBox", "QHeaderView::section", "alternate-background-color",
                "QTreeWidget::indicator"]:
    assert _needed in _qss, f"{_needed} missing from the stylesheet extension"
# Views fall back to Qt's light palette for striping, which paints white bands
# on a dark list. The token must be set explicitly.
assert _Theme.surface_2 in _qss, "alternate rows must use a surface token"

# the extension must follow the accent, not hard-code it
_qss_orange = H.extra_stylesheet(_Theme("#c2410c"))
assert _qss != _qss_orange, "the extension ignores the accent"
assert _Theme("#c2410c").accent_subtle in _qss_orange

# no hand-picked colors left in the app: every hex must come from theme.py
_app_src = pathlib.Path(H.__file__).read_text()
_hexes = set(_re2.findall(r"#[0-9a-fA-F]{6}\b", _app_src))
_allowed = {"#FFFFFF", "#2f6fed"}   # white icon fills, and the documented default accent
_stray = _hexes - _allowed
check("no hand-picked colors in the app", sorted(_stray), [])

# ---- child environment ---------------------------------------------------
env = H.download_environment()
# huggingface_hub builds bars with disable=None, so tqdm auto-disables without
# a TTY. A QProcess pipe is never a TTY, so without this the CLI prints nothing.
check("tqdm forced on", env.get("TQDM_POSITION"), "-1")
check("progress bars not disabled", env.get("HF_HUB_DISABLE_PROGRESS_BARS"), "0")
check("xet enabled", env.get("HF_XET_HIGH_PERFORMANCE"), "1")
check("unbuffered", env.get("PYTHONUNBUFFERED"), "1")
# no chunk cache: hf_xet would otherwise hold up to 10 GB outside the folder
check("chunk cache off (child)", env.get("HF_XET_CHUNK_CACHE_SIZE_BYTES"), "0")
# and it must be set in our own process before any huggingface_hub import,
# because constants.py freezes these into module globals at import time
import os as _os
check("chunk cache off (self)", _os.environ.get("HF_XET_CHUNK_CACHE_SIZE_BYTES"), "0")

# Checked in a FRESH process: earlier tests in this file legitimately import
# huggingface_hub, so inspecting sys.modules here would only tell us what the
# suite has done, not what importing the app does. (This assertion used to sit
# inline and passed only because huggingface_hub happened to be absent.)
import subprocess as _sp, sys as _sys
_probe = _sp.run(
    [_sys.executable, "-c",
     "import sys, os;"
     "sys.path.insert(0, os.path.dirname(os.path.abspath(%r)));"
     "import fantastic_huggingface_downloader as a;"
     "print('hub' if 'huggingface_hub' in sys.modules else 'clean');"
     "print(os.environ.get('HF_XET_CHUNK_CACHE_SIZE_BYTES'))" % __file__],
    capture_output=True, text=True, env={**_os.environ, "QT_QPA_PLATFORM": "offscreen"},
)
_lines = _probe.stdout.split()
assert _probe.returncode == 0, f"importing the app failed: {_probe.stderr[-400:]}"
check("app does not import huggingface_hub at module level", _lines[0], "clean")
check("and the cache setting is in place after import", _lines[1], "0")

assert H.human_bytes(1536) == "1.5 KiB"
assert H.human_time(3725) == "1:02:05"
assert H.human_time(None) == "--:--"

if fails:
    print("FAILURES:")
    for f in fails:
        print(" -", f)
    sys.exit(1)
H.wait_for_workers(1000)
print("all tests passed")
