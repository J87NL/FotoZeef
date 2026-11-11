from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath


class CaptureSource(StrEnum):
    EXIF = "exif"
    MTIME = "mtime"


@dataclass(frozen=True, slots=True)
class ProjectSettings:
    recursive: bool = True
    copy_raw_sidecar: bool = True


@dataclass(frozen=True, slots=True)
class Project:
    id: int
    name: str
    destination: Path
    cursor_photo_id: int | None
    settings: ProjectSettings
    created_at: datetime
    opened_at: datetime


@dataclass(frozen=True, slots=True)
class Source:
    id: int
    project_id: int
    path: Path
    label: str
    time_offset_s: int
    """The offset for every camera in this folder without one of its own."""
    sort_order: int
    camera_offsets: tuple[tuple[str, int], ...] = ()
    """Per camera in this folder: (camera key, seconds). See `camera_key`."""

    def offset_for(self, camera: str | None) -> int:
        key = camera_key(camera)
        for name, offset in self.camera_offsets:
            if name == key:
                return offset
        return self.time_offset_s

    def with_camera_offset(self, camera: str | None, offset: int) -> Source:
        key = camera_key(camera)
        offsets = tuple(item for item in self.camera_offsets if item[0] != key)
        return replace(self, camera_offsets=(*offsets, (key, offset)))


def camera_key(camera: str | None) -> str:
    """A photo's clock within its folder: its EXIF camera, or "" when that is unknown."""
    return (camera or "").strip()


@dataclass(frozen=True, slots=True)
class PhotoMetadata:
    captured_at: datetime | None
    capture_source: CaptureSource
    orientation: int
    camera: str | None


@dataclass(frozen=True, slots=True)
class Photo:
    id: int
    source_id: int
    relative_path: str
    file_size: int
    mtime: float
    captured_at: datetime | None
    capture_source: CaptureSource
    orientation: int
    camera: str | None
    group_key: str | None
    companions: tuple[str, ...] = field(default=())
    missing: bool = False

    @property
    def filename(self) -> str:
        return PurePosixPath(self.relative_path).name


@dataclass(frozen=True, slots=True)
class PhotoDraft:
    relative_path: str
    file_size: int
    mtime: float
    captured_at: datetime | None
    capture_source: CaptureSource
    orientation: int
    camera: str | None
    group_key: str | None
    companions: tuple[str, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class Selection:
    photo_id: int
    project_id: int
    written_name: str
    written_by_app: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    photo: Photo
    source: Source
    effective_at: datetime

    @property
    def absolute_path(self) -> Path:
        return self.source.path / self.photo.relative_path

    @property
    def companion_paths(self) -> tuple[Path, ...]:
        return tuple(self.source.path / name for name in self.photo.companions)

    @property
    def is_estimated_time(self) -> bool:
        return self.photo.capture_source is CaptureSource.MTIME

    @property
    def camera_label(self) -> str:
        """This photo's own camera; the folder's label when EXIF names none."""
        return camera_key(self.photo.camera) or self.source.label

    @property
    def clock(self) -> tuple[int, str]:
        """The clock that took this photo: one camera within one source folder."""
        return (self.source.id, camera_key(self.photo.camera))
