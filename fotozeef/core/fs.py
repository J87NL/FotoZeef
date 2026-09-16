from __future__ import annotations

import sys
from pathlib import Path

_WINDOWS_PATH_LIMIT = 240


def os_path(path: Path) -> str:
    """Windows rejects paths over MAX_PATH unless they carry the extended-length prefix."""
    if sys.platform != "win32":
        return str(path)
    resolved = str(path if path.is_absolute() else path.absolute())
    if len(resolved) < _WINDOWS_PATH_LIMIT or resolved.startswith("\\\\?\\"):
        return resolved
    if resolved.startswith("\\\\"):
        return "\\\\?\\UNC\\" + resolved[2:]
    return "\\\\?\\" + resolved


def normalize_name(name: str) -> str:
    return name.casefold()
