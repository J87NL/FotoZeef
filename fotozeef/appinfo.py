from __future__ import annotations

from pathlib import Path

import platformdirs

APP_NAME = "FotoZeef"
APP_AUTHOR = "ComfyCoders"
APP_BUNDLE_ID = "nl.j87.FotoZeef"
APP_VERSION = "0.1.0"

DATABASE_FILENAME = "fotozeef.sqlite"

RESOURCES_DIR = Path(__file__).resolve().parent / "resources"
ICON_PATH = RESOURCES_DIR / "icon.png"
I18N_DIR = RESOURCES_DIR / "i18n"


def data_dir() -> Path:
    return Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR))


def cache_dir() -> Path:
    return Path(platformdirs.user_cache_dir(APP_NAME, APP_AUTHOR))


def database_path() -> Path:
    return data_dir() / DATABASE_FILENAME
