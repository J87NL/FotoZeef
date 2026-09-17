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

analysis = Analysis(
    [str(ROOT / "fotozeef" / "app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=[(str(ROOT / "fotozeef" / "resources"), "fotozeef/resources")],
    hiddenimports=["pillow_heif", "rawpy", "exifread"],
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# FotoZeef uses only QtCore, QtGui and QtWidgets. PySide6's hooks pull in the
# rest of Qt anyway, so the unused halves are dropped here. Every pattern below
# was removed and then verified with `FotoZeef --selftest`.
UNUSED = (
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
            "LSMinimumSystemVersion": "12.0",
            "NSDesktopFolderUsageDescription": "FotoZeef reads the photo folders you choose.",
            "NSDocumentsFolderUsageDescription": "FotoZeef reads the photo folders you choose.",
            "NSRemovableVolumesUsageDescription": "FotoZeef reads photos from memory cards.",
        },
    )
