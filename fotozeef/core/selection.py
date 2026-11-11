from __future__ import annotations

import re
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from fotozeef.core.fs import normalize_name, os_path, volume_missing
from fotozeef.core.models import ProjectSettings, Selection, TimelineEntry

_LABEL_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


class SelectionError(RuntimeError):
    pass


class DiskNotConnected(SelectionError):
    """The disk with this folder is not connected; the UI words it for the user."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"The disk with {path} is not connected. Connect it and try again.")
        self.path = path


@dataclass(frozen=True, slots=True)
class WriteResult:
    photo_id: int
    written_name: str
    companion_names: tuple[str, ...]


@dataclass(slots=True)
class ReconcileResult:
    dropped: list[int] = field(default_factory=list)
    adopted: list[tuple[int, str]] = field(default_factory=list)
    unreachable: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.dropped or self.adopted)


class DestinationWriter:
    def __init__(self, destination: Path, settings: ProjectSettings) -> None:
        self._destination = destination
        self._settings = settings

    @property
    def destination(self) -> Path:
        return self._destination

    def ensure_destination(self, had_selections: bool = False) -> None:
        """Creates the destination folder, unless the disk it belongs on is not connected.

        Creating it then would put it on the internal disk, in the empty folder where the
        disk is normally mounted. Besides the usual mount places, a destination that held
        a selection before and whose parent is gone counts as such a disk too.
        """
        self._check_disk(self._destination)
        destination = self._destination
        if had_selections and not destination.is_dir() and not destination.parent.is_dir():
            raise DiskNotConnected(destination)
        self._destination.mkdir(parents=True, exist_ok=True)

    def _check_disk(self, path: Path) -> None:
        if volume_missing(path):
            raise DiskNotConnected(path)

    def select(
        self,
        entry: TimelineEntry,
        reserved: Mapping[str, int],
    ) -> WriteResult:
        self.ensure_destination(had_selections=bool(reserved))
        written_name = self._resolve_name(entry, reserved)
        target = self._destination / written_name
        shutil.copy2(os_path(entry.absolute_path), os_path(target))

        companion_names: list[str] = []
        if self._settings.copy_raw_sidecar:
            stem = PurePosixPath(written_name).stem
            for companion in entry.companion_paths:
                companion_name = f"{stem}{companion.suffix}"
                companion_target = self._destination / companion_name
                if companion_target.exists() and normalize_name(companion_name) in reserved:
                    continue
                shutil.copy2(os_path(companion), os_path(companion_target))
                companion_names.append(companion_name)

        return WriteResult(
            photo_id=entry.photo.id,
            written_name=written_name,
            companion_names=tuple(companion_names),
        )

    def deselect(
        self,
        entry: TimelineEntry,
        selection: Selection,
        reserved: Mapping[str, int] | None = None,
    ) -> None:
        """Removes this photo's copy, and the RAW copied with it if it really is that RAW.

        Refused while the destination's or the original's disk is not connected: the copy
        could not be removed, and it would come back as a stranger's file later.
        """
        self._check_disk(self._destination)
        self._check_disk(entry.absolute_path)
        if not selection.written_by_app:
            raise SelectionError(
                f"{selection.written_name} was not written by this app; remove it yourself"
            )
        target = self._destination / selection.written_name
        target.unlink(missing_ok=True)

        others = reserved or {}
        stem = PurePosixPath(selection.written_name).stem
        for companion, source in zip(entry.photo.companions, entry.companion_paths, strict=True):
            companion_name = f"{stem}{PurePosixPath(companion).suffix}"
            owner = others.get(normalize_name(companion_name))
            if owner is not None and owner != entry.photo.id:
                continue
            copy = self._destination / companion_name
            if _same_size(copy, source):
                copy.unlink(missing_ok=True)

    def _resolve_name(self, entry: TimelineEntry, reserved: Mapping[str, int]) -> str:
        filename = entry.photo.filename
        candidates = [filename, f"{_safe_label(entry.camera_label)}_{filename}"]
        stem = PurePosixPath(candidates[1]).stem
        suffix = PurePosixPath(filename).suffix
        candidates.extend(f"{stem}_{index}{suffix}" for index in range(2, 100))
        for candidate in candidates:
            free = self._is_available(candidate, entry.photo.id, reserved)
            if free and self._room_for_companions(candidate, entry, reserved):
                return candidate
        raise SelectionError(f"No free filename in destination for {filename}")

    def _is_available(self, candidate: str, photo_id: int, reserved: Mapping[str, int]) -> bool:
        key = normalize_name(candidate)
        owner = reserved.get(key)
        if owner is not None and owner != photo_id:
            return False
        if owner == photo_id:
            return True
        return not (self._destination / candidate).exists()

    def _room_for_companions(
        self, candidate: str, entry: TimelineEntry, reserved: Mapping[str, int]
    ) -> bool:
        """A name whose RAW would overwrite a file that is not this photo's is taken."""
        if not self._settings.copy_raw_sidecar:
            return True
        stem = PurePosixPath(candidate).stem
        for companion, source in zip(entry.photo.companions, entry.companion_paths, strict=True):
            name = f"{stem}{PurePosixPath(companion).suffix}"
            if reserved.get(normalize_name(name)) == entry.photo.id:
                continue
            existing = self._destination / name
            if existing.exists() and not _same_size(existing, source):
                return False
        return True


def reserved_names(selections: Iterable[Selection]) -> dict[str, int]:
    return {normalize_name(item.written_name): item.photo_id for item in selections}


def reconcile(
    destination: Path,
    entries: Iterable[TimelineEntry],
    selections: Iterable[Selection],
    settings: ProjectSettings,
) -> ReconcileResult:
    """Destination folder is the source of truth for what is selected.

    A file there counts as a photo's copy only when its name and its size match; a
    leftover copy of a photo from a folder that left the project is never handed to
    another photo that happens to share its name. A destination that cannot be reached,
    because the disk it is on is not connected, changes nothing.
    """
    result = ReconcileResult()
    entry_list = list(entries)
    selection_list = list(selections)

    gone_with_its_parent = not destination.is_dir() and not destination.parent.is_dir()
    if volume_missing(destination) or (selection_list and gone_with_its_parent):
        result.unreachable = True
        return result

    present: dict[str, Path] = {}
    if destination.is_dir():
        present = {
            normalize_name(item.name): item for item in destination.iterdir() if item.is_file()
        }

    claimed: set[str] = set()
    dropped: set[int] = set()
    for selection in selection_list:
        key = normalize_name(selection.written_name)
        if key not in present:
            dropped.add(selection.photo_id)
            continue
        claimed.add(key)
    result.dropped = sorted(dropped)

    selected_ids = {item.photo_id for item in selection_list if item.photo_id not in dropped}
    by_filename: dict[str, list[TimelineEntry]] = {}
    for entry in entry_list:
        by_filename.setdefault(normalize_name(entry.photo.filename), []).append(entry)

    for key, path in present.items():
        if key in claimed:
            continue
        size = _size(path)
        for entry in by_filename.get(key, ()):
            if entry.photo.id in selected_ids or entry.photo.file_size != size:
                continue
            result.adopted.append((entry.photo.id, path.name))
            selected_ids.add(entry.photo.id)
            break

    return result


def _size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def _same_size(copy: Path, original: Path) -> bool:
    """Whether a destination file is plausibly a copy of this original (copy2 keeps size)."""
    size = _size(copy)
    return size is not None and size == _size(original)


def _safe_label(label: str) -> str:
    cleaned = _LABEL_SAFE.sub("_", label).strip("_")
    return cleaned or "src"
