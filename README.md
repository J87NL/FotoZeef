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
```

## Packaging

See `packaging/`. CI builds all three platforms on tags:

- Linux: AppImage
- macOS: `.app` via PyInstaller (codesigning/notarisation hooks are present but unused)
- Windows: PyInstaller onedir plus an Inno Setup installer

## Open decisions

These are still open from the handoff and are implemented with the documented
default; each is noted here so the choice stays visible.

1. **App name / bundle id** — `FotoZeef`, `nl.j87.FotoZeef`. All identity strings
   live in `fotozeef/appinfo.py`; renaming is a one-file change.
2. **Reject flow** — not implemented. Selection is binary, as §13 of the handoff
   requires. Adding a rejected state means a schema bump (`SCHEMA_VERSION` in
   `core/db.py` already carries the migration hook) and a `Delete` binding.
3. **Copy vs move vs hardlink** — copy (`shutil.copy2`).
4. **XMP sidecars** — shipped, off by default, per-project setting.
5. **Recursive scanning** — on by default, per-project setting.
6. **`copy_raw_sidecar`** — on by default, per-project setting.
