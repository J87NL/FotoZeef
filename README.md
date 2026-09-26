# FotoZeef

FotoZeef ("photo sieve" in Dutch) is fast, keyboard-driven culling of photo
shoots. Point it at one or more folders, step through with the arrow keys, hit
space on the keepers. Selected photos are copied into a destination folder;
originals are never touched.

Runs on Linux, macOS and Windows. Fully local: no account, no cloud, no telemetry.

## Install

Downloads are on the [releases page](https://github.com/J87NL/FotoZeef/releases).

- **Linux** — `FotoZeef-<version>-x86_64.AppImage`. Make it executable and run
  it; nothing to install. Needs only the graphics stack (`libegl1`, `libgl1`),
  which every desktop already has.
- **Windows** — `FotoZeef-<version>-setup.exe`. Installs per user, no admin rights.
- **macOS** — no release build yet, since I have no Mac to build and test it on.
  Run it [from source](DEVELOPMENT.md#run-from-source) for now. If you build and
  test a macOS version, I'd love to hear from you.

## First run

Create a project on the start screen, add one or more folders, and leave the
destination blank to get `<first folder>/selectie`. Then arrow keys to move,
space to keep.

## Keyboard

| Key | Action |
|---|---|
| `←` / `→` | Previous / next photo |
| `Space` | Keep / unkeep the current photo |
| `Home` / `End` | First / last photo |
| `PgUp` / `PgDn` | Jump 10 |
| `+` / `-` | Zoom in / out |
| `0` | Fit to window |
| `1` | Actual size |
| `F` | Fullscreen |
| `Esc` | Unzoom, then leave fullscreen |
| `Ctrl/Cmd + N` | New project |
| `Ctrl/Cmd + O` | Open project |
| `Ctrl/Cmd + W` | Close project |
| `Ctrl/Cmd + ,` | Project settings |

## Good to know

- **Zoom** decodes the original at full resolution and stays put while you step
  through photos, so you can check focus frame after frame. The wheel zooms
  around the pointer, double click toggles, drag pans.
- **A clock on a thumbnail** means the photo has no EXIF capture time; its place
  in the timeline is guessed from the file date.
- **Two cameras out of sync?** Mark a photo with *Timeline ▸ Set time reference*,
  go to the same moment from the other camera, and apply the delta under
  *Timeline ▸ Time offsets…*.
- **Language** — English and Dutch, under *View ▸ Language*.
- **Starting over** — FotoZeef keeps its database and thumbnails in
  `~/.local/share/FotoZeef/` and `~/.cache/FotoZeef/`. Delete those; your photos
  are never in there.

## License

MIT; see `LICENSE`. The packaged builds bundle third-party libraries under
LGPL and GPL — see [`THIRD_PARTY.md`](fotozeef/resources/THIRD_PARTY.md).

Building, testing and translating: see [`DEVELOPMENT.md`](DEVELOPMENT.md).
