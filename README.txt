Fantastic HuggingFace Downloader
================================

Paste a Hugging Face link, pick a folder, get the file. Linux desktop app,
PySide6, wrapping `hf download` with HF_XET_HIGH_PERFORMANCE=1.


LINUX - INSTALLING WITHOUT A TERMINAL
-------------------------------------

1. Clone the repository somewhere you own:
      git clone https://github.com/Adudeguyman/Fantastic-HuggingFace-Downloader.git
      cd Fantastic-HuggingFace-Downloader
2. Double-click install.sh in your file manager.
3. Your file manager will ask what to do with it. Choose "Run in Terminal"
   (Nemo, Caja, Thunar) or "Run" (Nautilus). A window opens, shows progress,
   and the app starts by itself when it finishes.

If your file manager just opens install.sh in a text editor instead of
offering to run it, the file has lost its executable bit.
Right-click it, go to Properties, Permissions, and tick "Allow executing
file as program". Then double-click again.

NOTHING IS CACHED, NOTHING ACCUMULATES ELSEWHERE

  hf_xet would normally keep up to 10 GB of 64KB file chunks in
  ~/.cache/huggingface/xet to speed up repeat downloads. This app turns that
  off (HF_XET_CHUNK_CACHE_SIZE_BYTES=0) and points the xet runtime directory
  at ./xet-runtime here, so nothing piles up outside the folder. The trade is
  that re-downloading the same file fetches it again rather than reusing
  cached chunks.

  Your Hugging Face auth token is deliberately NOT moved. It stays wherever
  hf put it (~/.cache/huggingface/token), so an existing `hf auth login`
  keeps working.

  Audited by installing into a clean home directory and listing everything
  written outside this folder: nothing.


EVERYTHING STAYS IN THIS FOLDER
  install.sh creates ./venv right here, next to the app. Nothing is copied
  to a hidden directory, and no root is needed. Your settings go in
  ./settings.ini in this folder too.

  Move the folder and the whole install moves with it. Delete the folder and
  it is completely gone. Check the size with `du -sh .` - the venv is about
  1 GB, almost all of it PySide6.

  The one thing that can land outside the folder is a shortcut: an
  applications-menu entry, a desktop shortcut, and a ~/.local/bin command
  are three separate questions, all defaulting to no. Each is just a small
  text file pointing back here, so moving the folder breaks them. Nothing
  optional is ever created silently; if the installer cannot ask you (no
  terminal, no zenity) it assumes no.

AFTER INSTALLING, RUN IT WITH run.sh
  Double-click run.sh in this folder. You never need install.sh again unless
  you are updating.

The install downloads PySide6 and huggingface_hub, a few hundred MB, so give
it a minute on a slow connection.


WINDOWS
-------

UNTESTED. I have no Windows machine to verify these on, so treat the .bat
files and the Windows code paths in the app as a first cut rather than
something proven. The Linux side is the tested one.

1. Clone the repository somewhere you own (not Program Files):
      git clone https://github.com/Adudeguyman/Fantastic-HuggingFace-Downloader.git
2. Double-click install.bat. It needs Python 3.9+ already installed from
   python.org, with "Add python.exe to PATH" ticked during that setup.
3. Afterwards, double-click run.bat to start the app.

Same consent rules: Start Menu shortcut, desktop shortcut and starting the
app are three separate prompts, all defaulting to no.

Everything goes in .\venv inside this folder, same as on Linux, so no admin
rights are needed. Settings go in settings.ini here. Delete the folder to
remove it completely. Do not clone into Program Files - pick somewhere you
own, such as your Desktop.

Most likely to need fixing first: shortcut creation, which shells out to
PowerShell, and whether hf.exe still flashes a console window.


UPDATING
--------

Run install.sh (or install.bat) again. That is the whole procedure - you are
never asked to work out whether anything changed.

The installer offers to run git pull first, and restarts itself if the
installer script was one of the files that changed. If you have uncommitted
edits here it says so and leaves your work alone rather than pulling over
them.

It then compares requirements.txt against what is recorded in ./venv. If
nothing changed it skips pip entirely and finishes in about a second; if the
dependencies moved, it installs them.

There is only one copy of the app - the .py in this folder, which is what
run.sh and run.bat execute - so once the pull lands you are running the new
code. The version number is in the window title and in the log.


USING IT
--------

Paste a link into the top box, for example:

  https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors

The repo, branch and file path get pulled out automatically, and the exact
command that will run is shown in grey above the Download button, so you can
always see what it is about to do.

What to download
  This file      just the one the link points at
  Its folder     everything in the same repo directory
  Whole repo     all of it
  Choose files   only the ones you tick

  Either click "Choose files..." or select "Choose files" - both open
  the repo's file listing with sizes. Everything starts ticked, so the job is
  unchecking what you do not want rather than hunting for what you do.

  If your link pointed at a subfolder, only that subfolder is listed - being
  shown every file in the repo buries what you asked for. A checkbox at the
  top widens it to the whole repo, and anything you had already ticked stays
  ticked.
  Reopening the picker keeps whatever you chose last time. If you close it
  having unticked everything, you go back to whichever option you were on. The filter box takes several space-separated terms and a row
  must match all of them, so "safetensors diffusion" narrows to the diffusion
  models. Select All / Clear All / Invert Selection act on everything listed;
  start typing a filter and they become Select Shown / Clear Shown / Invert
  Shown, acting only on the matching rows, so you can filter, select, filter
  again and keep adding without losing earlier picks. The running total tells you how much you are about to pull.

  The file listing is fetched once per repo and revision, so switching between
  these four options and reopening the picker costs nothing extra.

  Picked files go into the queue as one job each, so there is no practical
  limit on how many you select.

Destination
  Where the files themselves should end up, for the NEXT thing you add to the
  queue. Existing queue items keep the destination they were given.

  A link to one specific file always lands in the folder you pick, with no
  subfolders created. That is the point of pointing at a folder.

  Getting there takes one of two routes. hf writes to
  <--local-dir>/<the file's path inside the repo>, so when the folder you pick
  already ends with the repo's own subfolder - picking
  .../ComfyUI/models/diffusion_models for a file at
  diffusion_models/model.safetensors - the app hands hf the parent instead and
  the file arrives exactly where you wanted with nothing moved. Otherwise the
  file is moved into your folder once it finishes.

  That move has a cost worth knowing: hf looks for a file at its repo-relative
  path when you download it again, so a file that was moved is fetched again
  rather than hash-checked. Lining your destination up with the repo's folder
  name avoids the move and keeps the check.

  Folder, whole-repo and chosen-files downloads keep the repo's structure
  underneath the folder you pick - there the layout is usually the point. A
  line under the box tells you where files will land, and the command preview
  always shows the real --local-dir.

  If the folder you pick is itself a separate disk, mounted or symlinked into
  the tree, nothing is stripped - otherwise the download would be staged on
  the parent drive rather than the one you chose and made room on.

  While a file is downloading it lives in a hidden staging folder,
  .cache/huggingface/download, next to the --local-dir. It only appears at its
  real name once it is complete, so a half-finished file can never be mistaken
  for a usable one. That staging folder is always on the same drive as the
  destination, and it is cleaned up when the item finishes.

  There is no "flatten" option. Moving a file after downloading it breaks
  hf's ability to find and verify it later, so the app never does.

  Browse opens a Qt file dialog with every mounted drive in the sidebar, and
  your favorites pinned at the top of it.

  The dropdown has two sections. Favorites stay put; the star button beside
  the box adds or removes the folder currently in it. Recent holds the last
  ten destinations you actually downloaded to, newest first, and older ones
  drop off. A favorite never takes up a recent slot and never ages out.

  Both lists live in settings.ini in this folder, so they survive a restart
  and travel with the folder if you move it.
  Free space is shown, and you get a warning before starting if the download
  will not fit.

Progress
  Two independent sources feed the bar, speed and ETA, and either one alone
  is enough: the hf CLI's own progress text (plain tqdm, the two Xet bars,
  and the snapshot "Fetching N files" aggregate are all understood), and
  bytes actually landing on disk, measured once a second.

  Xet reports two byte counts: bytes flushed to disk and bytes pulled off the
  network. On a large file it buffers, so the disk figure can legitimately sit
  at zero for a long time while the network figure climbs. The readout tracks
  both plus the file on disk and shows whichever is furthest along, so it
  keeps moving instead of sitting at 0. It never goes backwards.

  The percentage is derived from those same bytes rather than from the
  percentage the CLI prints, because the reconstruction bar reports 0% for as
  long as it is buffering. A printed percentage is used as a floor when it is
  ahead. The bar never moves backwards.

  Speed and ETA come from that one byte figure too, averaged over the last few
  seconds rather than taken from the last tick. Xet writes to disk in bursts,
  so a per-tick rate swings between almost nothing and hundreds of MB/s while
  the real rate is steady. If the transfer stalls the rate reads zero rather
  than holding a stale number.

  Because of that buffering, the byte count and percentage can run ahead of
  what has actually been written to disk. It catches up.

  If you ever see a line tagged [unparsed progress] in the log, the CLI has
  started printing a shape this app does not recognise. Paste that line into
  an issue at https://github.com/Adudeguyman/Fantastic-HuggingFace-Downloader/issues
  - it is exactly what is needed to fix it.

  The command is run with `--format human` on purpose. The hf CLI otherwise
  defaults to `--format auto`, which picks its output mode from whether it
  sees a terminal, and every mode except human silently switches the progress
  bars off. The flag is only added if your installed hf actually supports it.

Cancel is safe. Partial data is kept and the next run resumes.

Verification and cleanup
  hf keeps a small .cache/huggingface folder next to your downloads holding
  one .metadata file per download. On a later run it compares the stored tag
  against the Hub and skips the file without looking at it.

  This app deletes those .metadata files once an item finishes. That is
  deliberate: with them gone, downloading the same file again makes hf read
  the file off your disk, compute its sha256 and compare it to the Hub's,
  re-downloading only if they differ. You get a real integrity check instead
  of a trusted tag, at the cost of reading the file.

  Only finished items are cleaned. Interrupted downloads keep their partial
  data - it lives in the same folder - so cancelling and requeuing still
  resumes. The folder itself is removed once nothing is left in it.

  One asymmetry worth knowing: the hash check only applies to LFS files, which
  is every .safetensors and .gguf. Small files stored in git, like config.json,
  carry a different kind of tag, so those simply re-download. They are
  kilobytes.


PRIVATE OR GATED REPOS
----------------------

The app uses whatever token the hf CLI already has. There is no token field.
If a download fails with a 401 or 403, log in once from a terminal:

  ~/.local/share/fantastic-huggingface-downloader/venv/bin/hf auth login


TROUBLESHOOTING
---------------

Nothing appears when I run it
  The app needs a graphical session. Over SSH you would need X forwarding.

The progress bar sits at 0 but the download is clearly running
  Two independent sources feed the bar, so this should not happen: the hf
  CLI's own output, and bytes measured on disk. If both are dead, check
  whether HF_HUB_DISABLE_PROGRESS_BARS is exported in your shell profile.
  The app forces it to 0 for the download it launches, but a badly broken
  environment can still surprise it. Percentage parsing lives in
  parse_progress_line() near the top of the app; disk measurement is in
  _measure(), which globs .cache/huggingface/download for *.incomplete.

A "Hint: the hf-cli skill is not installed" message
  That is the hf CLI advertising an optional add-on for AI coding agents. It
  has nothing to do with your download and you do not need to run it. Newer
  builds of this app filter it out of the log.

Size and the free-space warning are missing
  The Hub metadata lookup failed (rate limit, gated repo, no network at that
  moment). The download itself still runs, and progress still works - it is
  read from the CLI's output and from bytes on disk. The reason is written to
  the log. Sidecar cleanup is skipped too, since it needs the file list.


UNINSTALLING
------------

Delete this folder. That is the whole uninstall.

If you accepted any of the optional shortcuts, run uninstall.sh (or
uninstall.bat) first to clear those up, since they live outside the folder.
It also deletes ./venv, which is the bulk of the disk usage. Downloaded
models are never touched.


APPEARANCE
----------

The app uses the shared dark theme from theme.py, the same one as the
Fantastic Upgraded Captioning Kit, so the two look like siblings.

The accent colour is the only thing meant to be adjusted. Put a line in
settings.ini in this folder and restart:

  accent=#c2410c

Hover, pressed, selection tints and borders are all derived from it, so any
sane colour works without touching anything else. Everything else - surfaces,
borders, the text ramp, the success/warning/error colours - is fixed on
purpose.

Status colours in the queue follow that scheme: green for done, red for
failed, amber for canceled, accent for the one downloading.


FILES IN THIS REPOSITORY
------------------------

  fantastic_huggingface_downloader.py       the application
  theme.py                                  shared dark theme; the app
      imports it, so it must stay next to the app
  run.sh / run.bat                          start it (use this day to day)
  install.sh / install.bat                  one-time setup
  requirements.txt                          what install.sh installs; it
      only touches pip when this file changes
  uninstall.sh / uninstall.bat              removal
  test_fantastic_huggingface_downloader.py  test suite, not installed. Self
      contained - no fixture files. Run it after editing the app:
        QT_QPA_PLATFORM=offscreen python3 test_fantastic_huggingface_downloader.py
  LICENSE                                   MIT
  README.md                                 the GitHub landing page
  screenshot.png                            used by README.md
  README.txt                                this file
