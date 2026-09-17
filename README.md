# FotoZeef

Fast, keyboard-driven culling of photo shoots. Point it at one or more folders,
step through with the arrow keys, hit space on the keepers. Selected photos are
copied into a destination folder; originals are never touched.

Runs on Linux, macOS and Windows. Fully local: no account, no cloud, no telemetry.

## Run it

### The AppImage (nothing to install)

Download `FotoZeef-x86_64.AppImage`, make it executable, run it:

```bash
chmod +x FotoZeef-x86_64.AppImage
./FotoZeef-x86_64.AppImage
```

It carries its own Python, Qt, libheif and libraw. The only thing it takes from
the machine is the graphics stack (`libegl1`, `libgl1`), which every Ubuntu
desktop already has — those deliberately are not bundled, because they must
match the host's drivers.

### From source

```bash
uv sync
uv run fotozeef
```

Python 3.12 or newer. On Ubuntu, Qt 6 needs a few system libraries that a
desktop install does not necessarily have — `libxcb-cursor0` in particular is
missing on 22.04 and later, and without it Qt fails with *"could not load the
Qt platform plugin xcb"*:

```bash
sudo apt-get install -y libegl1 libgl1 libxkbcommon-x11-0 libfontconfig1 \
  libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xkb1 \
  libxcb-randr0 libxcb-render-util0 libdbus-1-3
```

### First run

There is no project yet, so the window opens empty. *Project ▸ New project…*,
add one or more folders, and leave the destination blank to get
`<first folder>/selectie`. Then arrow keys to move, space to keep.

Its own files live in `~/.local/share/FotoZeef/` (the database) and
`~/.cache/FotoZeef/` (thumbnails). Delete those to start over; your photos are
never in there.

## Keyboard

| Key | Action |
|---|---|
| `←` / `→` | Previous / next photo |
| `Space` | Toggle selection |
| `Home` / `End` | First / last photo |
| `PgUp` / `PgDn` | Jump 10 |
| `F` | Toggle fullscreen |
| `Ctrl/Cmd + N` | New project |
| `Ctrl/Cmd + O` | Open project |
| `Ctrl/Cmd + ,` | Project settings |
| `Esc` | Leave fullscreen |

Time offsets live under *Timeline*. To align two cameras: put the cursor on a
photo from the first camera, choose *Timeline ▸ Set time reference*, move to the
photo of the same moment from the second camera, then open *Timeline ▸ Time
offsets…* and apply the computed delta. Re-sorting is in memory — no rescan.

## Layout

```
fotozeef/
  core/      pure Python, no Qt imports — scanning, metadata, ordering, selection, thumbnails
  ui/        PySide6 widgets
  app.py     entry point
```

`core` never imports Qt; `tests/test_core_is_headless.py` enforces that in a
subprocess. Everything in `core` runs without a display server, which keeps the
test suite fast and leaves the door open for a CLI later.

## Storage

| What | Where |
|---|---|
| Database | `platformdirs.user_data_dir("FotoZeef", "ComfyCoders")/fotozeef.sqlite` |
| Thumbnails | `platformdirs.user_cache_dir("FotoZeef", "ComfyCoders")` |

One database for the whole installation, never next to the photos. The only thing
written into a source folder is the optional XMP sidecar, which is off by default.

## Development

```bash
uv run ruff check .
uv run ruff format .
uv run pytest
uv run fotozeef --selftest   # boots the whole stack offscreen
```

`--selftest` is what CI runs against each packaged build: it reports whether
HEIF and RAW decoding are live in that bundle and opens a window offscreen.

## Measured

On a generated 3000-photo shoot (this container, cold cache):

| | |
|---|---|
| Folder walk | 0.27 s |
| First open, EXIF for 3000 photos | 0.76 s |
| Reopen, metadata cached | 0.34 s |
| Window populate and first paint | 0.03 s |
| Arrow-key step | 9 ms median, 87 ms worst |

Metadata is only re-read when a file's size or mtime changed, so reopening a
shoot never pays for EXIF twice.

## Packaging

PyInstaller does not cross-compile: each installer must be built on its own
operating system. CI does all three on a `v*` tag; locally you build the one
you are sitting in front of.

### Ubuntu — AppImage

```bash
sudo apt-get install -y libegl1 libgl1 libxkbcommon-x11-0 libfontconfig1 libfuse2
uv sync
bash packaging/linux/build_appimage.sh
./dist/FotoZeef-x86_64.AppImage
```

Produces a single ~88 MB `dist/FotoZeef-x86_64.AppImage`; mark it executable and
double-click it. It carries its own Python, Qt and the libheif/libraw natives.
It deliberately does **not** bundle `libEGL`/`libGL` — graphics drivers have to
match the host, so those come from the machine. Every Ubuntu desktop has them;
a bare server image needs `libegl1 libgl1`.

### Windows — .exe and installer

Must be built on Windows (or by CI). With Python and [uv] installed:

```powershell
uv sync
uv run pyinstaller --noconfirm --clean packaging\fotozeef.spec
.\dist\FotoZeef\FotoZeef.exe --selftest
```

`dist\FotoZeef\` is a self-contained folder; `FotoZeef.exe` runs from it. For a
real installer, with [Inno Setup] 6 installed:

```powershell
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" packaging\windows\installer.iss
```

That writes `packaging\windows\Output\FotoZeef-0.1.0-setup.exe`, which installs
per-user without admin rights. The bundled manifest turns on long-path awareness
and PerMonitorV2 DPI.

### macOS — .app

```bash
uv sync
bash packaging/macos/build_app.sh
```

Unsigned, so the first launch needs right-click ▸ Open. Set
`MACOS_SIGN_IDENTITY` and `MACOS_NOTARY_PROFILE` to sign and notarise; those
paths are wired but untested, since there is no certificate yet.

### Via CI

Pushing a tag builds and uploads all three as workflow artifacts:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

[uv]: https://docs.astral.sh/uv/
[Inno Setup]: https://jrsoftware.org/isinfo.php

## Decisions

1. **App name / bundle id** — `FotoZeef`, `nl.j87.FotoZeef`. Settled. Both live in
   `fotozeef/appinfo.py`, which the PyInstaller spec reads, so there is one source
   of truth for the macOS bundle identifier and the app name.
2. **Selection is binary** — in or out. Settled. No rejected state, no star counts,
   no colour labels. `Delete` is deliberately unbound.
3. **Copy, never move** — `shutil.copy2` into the destination. Settled. The source
   folders are left alone; `tests/test_sources_untouched.py` fingerprints the whole
   source tree and asserts a full select/deselect cycle leaves it byte-identical.
   The destination is excluded from scanning, so a `selectie/` folder inside a
   source never reappears in the timeline.
4. **Recursive scanning** — on by default, per-project setting.
5. **`copy_raw_sidecar`** — on by default, per-project setting.
6. **XMP sidecars** — shipped but **off by default**, per-project setting. This is
   the one feature that writes into a source folder (a `.xmp` next to the original,
   removed again on deselect if this app wrote it). Everything else treats the
   source folders as read-only. Say the word if it should not be offered at all.
