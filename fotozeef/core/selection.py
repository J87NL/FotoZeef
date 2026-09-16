from __future__ import annotations

import re
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from fotozeef.core import xmp
from fotozeef.core.fs import normalize_name, os_path
from fotozeef.core.models import ProjectSettings, Selection, TimelineEntry

_LABEL_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


class SelectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WriteResult:
    photo_id: int
    written_name: str
    companion_names: tuple[str, ...]
    sidecar: Path | None


@dataclass(slots=True)
class ReconcileResult:
    dropped: list[int] = field(default_factory=list)
    adopted: list[tuple[int, str]] = field(default_factory=list)
    adopted_from_sidecar: list[int] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.dropped or self.adopted or self.adopted_from_sidecar)


class DestinationWriter:
    def __init__(self, destination: Path, settings: ProjectSettings) -> None:
        self._destination = destination
        self._settings = settings

    @property
    def destination(self) -> Path:
        return self._destination

    def ensure_destination(self) -> None:
        self._destination.mkdir(parents=True, exist_ok=True)

    def select(
        self,
        entry: TimelineEntry,
        reserved: Mapping[str, int],
    ) -> WriteResult:
        self.ensure_destination()
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

        sidecar: Path | None = None
        if self._settings.write_xmp:
            sidecar = xmp.write_sidecar(entry.absolute_path)

        return WriteResult(
            photo_id=entry.photo.id,
            written_name=written_name,
            companion_names=tuple(companion_names),
            sidecar=sidecar,
        )

    def deselect(self, entry: TimelineEntry, selection: Selection) -> None:
        if not selection.written_by_app:
            raise SelectionError(
                f"{selection.written_name} was not written by this app; remove it yourself"
            )
        target = self._destination / selection.written_name
        target.unlink(missing_ok=True)

        stem = PurePosixPath(selection.written_name).stem
        for companion in entry.photo.companions:
            companion_name = f"{stem}{PurePosixPath(companion).suffix}"
            (self._destination / companion_name).unlink(missing_ok=True)

        xmp.remove_sidecar(entry.absolute_path)

    def _resolve_name(self, entry: TimelineEntry, reserved: Mapping[str, int]) -> str:
        filename = entry.photo.filename
        candidates = [filename, f"{_safe_label(entry.source.label)}_{filename}"]
        stem = PurePosixPath(candidates[1]).stem
        suffix = PurePosixPath(filename).suffix
        candidates.extend(f"{stem}_{index}{suffix}" for index in range(2, 100))
        for candidate in candidates:
            if self._is_available(candidate, entry.photo.id, reserved):
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


def reserved_names(selections: Iterable[Selection]) -> dict[str, int]:
    return {normalize_name(item.written_name): item.photo_id for item in selections}


def reconcile(
    destination: Path,
    entries: Iterable[TimelineEntry],
    selections: Iterable[Selection],
    settings: ProjectSettings,
) -> ReconcileResult:
    """Destination folder is the source of truth for what is selected."""
    result = ReconcileResult()
    entry_list = list(entries)
    selection_list = list(selections)

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
    by_filename: dict[str, TimelineEntry] = {}
    for entry in entry_list:
        by_filename.setdefault(normalize_name(entry.photo.filename), entry)

    for key, _path in present.items():
        if key in claimed:
            continue
        entry = by_filename.get(key)
        if entry is None or entry.photo.id in selected_ids:
            continue
        result.adopted.append((entry.photo.id, _path.name))
        selected_ids.add(entry.photo.id)

    if settings.write_xmp:
        for entry in entry_list:
            if entry.photo.id in selected_ids:
                continue
            rating = xmp.read_rating(entry.absolute_path)
            if rating is None or rating < 1:
                continue
            result.adopted_from_sidecar.append(entry.photo.id)
            selected_ids.add(entry.photo.id)

    return result


def _safe_label(label: str) -> str:
    cleaned = _LABEL_SAFE.sub("_", label).strip("_")
    return cleaned or "src"
