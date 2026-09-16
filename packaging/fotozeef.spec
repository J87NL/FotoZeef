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
