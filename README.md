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
  To update, run the newer installer over the old one: it replaces the program
  and keeps your projects. Going back is not possible, because an older
  FotoZeef cannot open projects saved by a newer one: installers from 0.4.0 on
  refuse to go over a newer version, and the 0.3.0 installer, which cannot check
  this yet, should not be run over 0.4.0 or later.
- **macOS** — `FotoZeef-<version>-macos.zip`, for Macs with Apple silicon (M1
  and later) on macOS 13 Ventura or newer. Unzip it and move `FotoZeef.app` to
  *Applications*. The app is not signed by Apple, so the first time macOS
  refuses to open it. Open it once, close the warning, then go to *System
  Settings ▸ Privacy & Security* and choose *Open Anyway* next to FotoZeef.
  (On macOS 14 and older, right-click the app ▸ *Open* also works.) After that
  it opens normally. It is built and started automatically on a Mac
  for every release, but has had less hands-on testing than the other two; if
  something is off, please open an issue.

Windows may warn about an unknown publisher the first time, for the same
reason: choose *More info ▸ Run anyway*.

## First run

Create a project on the start screen, add one or more folders, and leave the
destination blank to get `<first folder>/selectie`. Then arrow keys to move,
space to keep.

Recent projects are listed on the start screen. *Settings…* (or right-click)
changes a project's name, folders and destination without opening it;
*Remove…* takes it off the list. Removing a project or a folder never deletes
photos: the originals and the selection folder stay on disk.

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
| `G` | Overview of all photos (Enter opens one, Esc returns) |
| `Ctrl/Cmd` + scroll, `Ctrl/Cmd` `+` / `-` | Larger or smaller tiles in the overview |
| `Esc` | Unzoom, then leave fullscreen |
| `F5` | Slideshow (see below) |
| `Ctrl/Cmd + N` | New project |
| `Ctrl/Cmd + O` | Open project |
| `Ctrl/Cmd + W` | Close project |
| `Ctrl/Cmd + ,` | Project settings |

## Slideshow

*View ▸ Slideshow…* (`F5`) plays the open project fullscreen. Each photo is as
large as the screen allows without cropping; the space beside it is filled with
a blurred, dimmed copy of the same photo. For a projector, duplicate your screen,
or extend it and pick the projector under *Screen*.

You choose:

- **Photos** — all photos, with or without subfolders, or only the selected ones.
- **Each photo** — how many seconds a photo stays on screen.
- **Order** — chronological (by capture time, camera offsets included) or random.
  Random plays every photo once before reshuffling. Chronological can start at
  the photo you are on in FotoZeef, or the next one in the show after it.
- **Stop after one round** — fade to black after the last photo instead of
  starting over. `Space` or `→` then plays it again, `←` goes back.
- **Transitions** — fade, or slide in from the left, right, top or bottom. Tick
  several and they take turns at random; tick none for a plain cut.
- **When paused** — keep the photo on screen, or go to black.
- **Screen** — only shown with more than one screen: the screen FotoZeef is
  on, or a specific one. A chosen screen that is not connected falls back to
  the screen FotoZeef is on. Two screens of the same model are told apart by
  where they sit. On Wayland the desktop decides where a fullscreen window
  goes; if the show opens on the wrong screen there, move FotoZeef to the
  projector first and choose *The screen FotoZeef is on*.

The settings are stored with the project, also when you only close the window,
so a show can be set up in advance. The selection folder is never played, so
copies of your favourites do not show up twice.

While a show runs, the screen does not go to sleep and the screensaver stays
away:

- **Windows** — the display stays on, and the show window turns down the
  screensaver while it is in front. A lock-screen policy set by an
  organisation still applies.
- **macOS** — via `caffeinate`, which ends by itself if FotoZeef does.
- **Linux** — on desktops that offer the freedesktop screensaver interface
  (GNOME, KDE, Xfce and most others). Not on compositors without it, such as
  sway, and not from inside a Flatpak.

Where none of that is available the show plays on regardless.

| Key | During the show |
|---|---|
| `Space` | Pause / resume |
| `B` / `.` | Black screen / back to the show |
| `→` / `PgDn` / left click | Next photo |
| `←` / `PgUp` / right click | Previous photo |
| `Esc` | Stop |

`PgUp`, `PgDn` and `B` (or `.`) are what most presentation remotes send, so a
remote's black-screen button works whatever *When paused* is set to. Stepping
while the screen is black brings the photo back; the show stays paused until
`Space`.

## Good to know

- **Zoom** decodes the original at full resolution and stays put while you step
  through photos, so you can check focus frame after frame. The wheel zooms
  around the pointer, double click toggles, drag pans.
- **A clock on a thumbnail** means the photo has no EXIF capture time; its place
  in the timeline is guessed from the file date.
- **Two cameras out of sync?** Mark a photo with *Timeline ▸ Set time reference*,
  go to the same moment from the other camera, and apply the delta under
  *Timeline ▸ Time offsets…*. Offsets are set per camera (from EXIF) within each
  folder, so one folder with a subfolder per camera works too. Two bodies of
  the same model in one folder share an offset; add their folders separately to
  set them apart.
- **Lost in a long shoot?** `G` shows every photo as a grid, with a filter for
  just the selected ones. `Ctrl/Cmd` with the mouse wheel, or `Ctrl/Cmd` `+` /
  `-`, makes the tiles larger or smaller; `0` brings them back to normal.
- **Photos on a USB disk?** Opening the project while the disk is not connected
  is safe: FotoZeef says which folders it cannot find, shows their photos as
  missing and keeps your selection. Selecting and unselecting are refused until
  the disk is back. Connect it and open the project again. On Windows the disk
  has to come back under the same drive letter (E:, F:, …); if Windows gives it
  another one, change it back in Disk Management or point the project at the
  new letter under *Settings…*.
- **What counts as selected** is what is in the selection folder. A file there
  counts for a photo when its name and its size match, so an unchanged copy you
  put in by hand is picked up too; an edited or rotated one is not.
- **Language** — English and Dutch, under *View ▸ Language*.
- **Starting over** — FotoZeef keeps its database and thumbnails in
  `~/.local/share/FotoZeef/` and `~/.cache/FotoZeef/`. Delete those; your photos
  are never in there.

## License

MIT; see `LICENSE`. The packaged builds bundle third-party libraries under
LGPL and GPL — see [`THIRD_PARTY.md`](fotozeef/resources/THIRD_PARTY.md).

Building, testing and translating: see [`DEVELOPMENT.md`](DEVELOPMENT.md).
