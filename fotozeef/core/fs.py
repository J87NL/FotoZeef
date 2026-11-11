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


# Where removable disks are mounted. A path inside one of these trees is on its disk
# when a folder between the tree and the path is a mount point. Without one, it is a
# disk that is not connected only when the folder a disk would be mounted on (the first
# one in the tree, or in /media/<user>) is missing or empty. An ordinary folder with
# files in it, such as /mnt/photos on the system disk, is simply there.
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
    exists: Callable[[str], bool] | None = None,
    user: str | None = None,
    trees: tuple[tuple[str, ...], ...] = _MOUNT_TREES,
) -> bool:
    """Whether the disk this path lives on is not connected.

    On Windows that is a drive letter (or share) that is not there. Elsewhere it is a
    path under /media, /run/media, /mnt or /Volumes whose disk is not mounted.
    """
    if platform == "win32":
        anchor = PureWindowsPath(str(path)).anchor
        return bool(anchor) and not (exists or _anchor_present)(anchor)
    present = exists or os.path.isdir
    parts = PurePosixPath(str(path)).parts
    for tree in trees:
        if parts[: len(tree)] != tree or len(parts) == len(tree):
            continue
        for depth in range(len(tree) + 1, len(parts) + 1):
            if ismount(str(PurePosixPath(*parts[:depth]))):
                return False
        level = len(tree) + 1
        per_user = tree[-1] == "media" and parts[len(tree)] == (user or _user())
        if per_user:
            if len(parts) == level:
                return True
            level += 1
        mount_folder = str(PurePosixPath(*parts[:level]))
        return not present(mount_folder) or _is_empty(mount_folder)
    return False


def _anchor_present(anchor: str) -> bool:
    """A share whose root may not be listed is still there; only a missing one is not."""
    try:
        os.stat(anchor)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _is_empty(folder: str) -> bool:
    try:
        with os.scandir(folder) as entries:
            return next(entries, None) is None
    except OSError:
        return True


def _user() -> str:
    try:
        import getpass

        return getpass.getuser()
    except Exception:
        return ""
