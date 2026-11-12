# PyInstaller spec shared by the Linux, macOS and Windows builds.
from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))

from fotozeef.appinfo import APP_BUNDLE_ID, APP_NAME, APP_VERSION

binaries = collect_dynamic_libs("pillow_heif") + collect_dynamic_libs("rawpy")

excludes = [
    "PySide6.Qt3DCore",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtQuick",
    "PySide6.QtQml",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "tkinter",
]

# QtDBus keeps the screensaver away during a slideshow on Linux. It is imported
# lazily, so it is named here; Windows and macOS do not need it.
linux_only = ["PySide6.QtDBus"] if sys.platform.startswith("linux") else []

analysis = Analysis(
    [str(ROOT / "fotozeef" / "app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=[(str(ROOT / "fotozeef" / "resources"), "fotozeef/resources")],
    hiddenimports=["pillow_heif", "rawpy", "exifread", *linux_only],
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# FotoZeef uses QtCore, QtGui and QtWidgets, plus QtDBus on Linux. PySide6's
# hooks pull in the rest of Qt anyway, so the unused halves are dropped here.
# Every pattern below was removed and then verified with `FotoZeef --selftest`.
UNUSED = (
    # Linux libraries every desktop has, from the build machine. Built on the oldest
    # supported Ubuntu, a bundled copy would be older than the user's and shadow it:
    # graphics drivers loaded from the system then miss newer libstdc++ symbols.
    # libmvec is part of glibc itself and reads glibc's private data. Wheels ship
    # their own copies under hashed names (libfreetype-1a2b.so), which stay.
    "libmvec.so",
    "libstdc++.so",
    "libgcc_s.so",
    "libglib-2.0.so",
    "libgobject-2.0.so",
    "libgio-2.0.so",
    "libgmodule-2.0.so",
    "libgthread-2.0.so",
    "libfontconfig.so",
    "libfreetype.so",
    # What only those need. Left in, the system's glib or fontconfig would load an
    # older bundled pcre2 or expat (no symbol versions) instead of its own.
    "libpcre2-8.so",
    "libexpat.so",
    "libz.so",
    "libpng16.so",
    "libbrotli",
    "libbz2.so",
    "libffi.so",
    "libmount.so",
    "libblkid.so",
    "libselinux.so",
    "Qt6Quick",
    "Qt6Qml",
    "Qt6Pdf",
    "Qt6Network",
    "Qt6VirtualKeyboard",
    "Qt6Designer",
    "Qt6Test",
    "Qt6Sql",
    "Qt6Bodymovin",
    "Qt6ShaderTools",
    "Qt6Charts",
    "Qt6DataVisualization",
    "Qt6Multimedia",
    "Qt6OpenGLWidgets",
    "Qt6WebEngine",
    "Qt6WebChannel",
    "Qt6WebSockets",
    "Qt6Sensors",
    "Qt6Positioning",
    "Qt6Nfc",
    "Qt6Bluetooth",
    "Qt6SerialPort",
    "Qt6Help",
    "Qt6SpatialAudio",
    "Qt6TextToSpeech",
    "Qt63D",
    "PySide6/Qt/qml",
    "PySide6/Qt/plugins/platformthemes/libqgtk3",
    "PySide6/Qt/plugins/sqldrivers",
    "PySide6/Qt/plugins/multimedia",
    "PySide6/Qt/plugins/position",
    "PySide6/Qt/plugins/renderers",
    "PySide6/Qt/plugins/sceneparsers",
    "PySide6/Qt/plugins/geometryloaders",
    "PySide6/Qt/plugins/webview",
    "libgtk-3",
    "libgdk-3",
    "libssl.so",
    "libcrypto.so",
)

KEPT_QT_TRANSLATIONS = ("qtbase_nl",)


def _wanted(entry) -> bool:
    name = entry[0].replace("\\", "/")
    source = str(entry[1] or "").replace("\\", "/")
    haystack = f"{name}|{source}"
    if "Qt/translations" in haystack or "PySide6/translations" in haystack:
        return any(keep in haystack for keep in KEPT_QT_TRANSLATIONS)
    return not any(pattern in haystack for pattern in UNUSED)


analysis.binaries = TOC([entry for entry in analysis.binaries if _wanted(entry)])
analysis.datas = TOC([entry for entry in analysis.datas if _wanted(entry)])

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "fotozeef" / "resources" / "icon.png"),
    manifest=str(ROOT / "packaging" / "windows" / "fotozeef.manifest")
    if sys.platform == "win32"
    else None,
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    name=APP_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name=f"{APP_NAME}.app",
        bundle_identifier=APP_BUNDLE_ID,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": APP_VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "13.0",  # PySide6 6.11 wheels need macOS 13
            "NSDesktopFolderUsageDescription": "FotoZeef reads the photo folders you choose.",
            "NSDocumentsFolderUsageDescription": "FotoZeef reads the photo folders you choose.",
            "NSRemovableVolumesUsageDescription": "FotoZeef reads photos from memory cards.",
        },
    )
