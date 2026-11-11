from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath

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


# Where removable disks are mounted. A path inside one of these trees is only on its
# disk when some folder between the tree and the path is a mount point; otherwise the
# disk is not connected and anything created there would land on the internal disk.
_MOUNT_TREES: tuple[tuple[str, ...], ...] = (
    ("/", "media"),
    ("/", "run", "media"),
    ("/", "mnt"),
    ("/", "Volumes"),
)


def volume_missing(
    path: Path | str,
    *,
    platform: str = sys.platform,
    ismount: Callable[[str], bool] = os.path.ismount,
    exists: Callable[[str], bool] = os.path.exists,
) -> bool:
    """Whether the disk this path lives on is not connected.

    On Windows that is a drive letter (or share) that is not there. Elsewhere it is a
    path under /media, /run/media, /mnt or /Volumes with no mount point on the way: an
    unplugged USB disk whose mount folder is missing, or left behind empty.
    """
    if platform == "win32":
        anchor = PureWindowsPath(str(path)).anchor
        return bool(anchor) and not exists(anchor)
    parts = PurePosixPath(str(path)).parts
    for tree in _MOUNT_TREES:
        if parts[: len(tree)] != tree or len(parts) == len(tree):
            continue
        for depth in range(len(tree) + 1, len(parts) + 1):
            if ismount(str(PurePosixPath(*parts[:depth]))):
                return False
        return True
    return False
