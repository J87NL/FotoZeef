# Third-party components

FotoZeef itself is MIT licensed. The packaged builds (AppImage, .app, Windows
installer) bundle the components below, each under its own license. Running
from source pulls the same components through `uv`.

| Component | Used for | License |
|---|---|---|
| Qt 6 / PySide6 / shiboken6 | the entire interface | LGPL-3.0 |
| Pillow | decoding, EXIF, thumbnails | MIT-CMU |
| pillow-heif | HEIC/HEIF support | BSD-3-Clause |
| libheif | HEIC/HEIF decoding | LGPL-3.0 |
| libde265 | HEVC decoding inside libheif | LGPL-3.0 |
| libx265 | HEVC encoding inside libheif | **GPL-2.0** |
| rawpy | RAW embedded previews | MIT |
| LibRaw | RAW reading inside rawpy | LGPL-2.1 |
| libjpeg, liblcms2, libjasper | image codecs inside LibRaw | BSD-style / MIT |
| exifread | EXIF fallback for RAW containers | BSD-3-Clause |
| platformdirs | per-platform data and cache paths | MIT |
| NumPy | array handling inside rawpy | BSD-3-Clause |

## Before distributing a build

These obligations attach to **distribution**, not to running the app yourself.

- **libx265 is GPL-2.0**, and `libheif` links it as a hard dependency
  (`readelf -d libheif.so` lists `NEEDED: libx265`), so it cannot simply be
  dropped from the bundle while HEIC support stays. GPL-2.0 is a copyleft
  license: shipping it inside a binary has consequences for the terms under
  which that whole binary may be offered. Decide this before publishing
  installers. The options are roughly: publish under GPL-compatible terms,
  build `libheif` without the x265 encoder, drop HEIC support, or keep builds
  private.
- **LGPL components** (Qt, libheif, libde265, LibRaw) require that their
  license text is provided and that the user can replace the library with a
  modified version. The PyInstaller bundles keep these as separate shared
  libraries, which is what makes that possible.

This file is a starting point, not legal advice.
