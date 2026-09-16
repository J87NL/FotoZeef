from __future__ import annotations

from dataclasses import dataclass, field
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
    write_xmp: bool = False


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
    sort_order: int


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
