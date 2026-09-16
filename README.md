# FotoZeef

Fast, keyboard-driven culling of photo shoots. Point it at one or more folders,
step through with the arrow keys, hit space on the keepers. Selected photos are
copied into a destination folder; originals are never touched.

Runs on Linux, macOS and Windows. Fully local: no account, no cloud, no telemetry.

## Install

```bash
uv sync
uv run fotozeef
```

Requires Python 3.12 or newer.

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

See `packaging/`. CI builds all three platforms on tags:

- Linux: AppImage
- macOS: `.app` via PyInstaller (codesigning/notarisation hooks are present but unused)
- Windows: PyInstaller onedir plus an Inno Setup installer

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
