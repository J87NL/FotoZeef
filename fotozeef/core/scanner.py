from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

JPEG_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg"})
STILL_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"}
)
RAW_EXTENSIONS: frozenset[str] = frozenset(
    {".cr2", ".cr3", ".nef", ".arw", ".raf", ".rw2", ".orf", ".dng"}
)
VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp4", ".mov", ".avi", ".mts", ".m2ts", ".mkv", ".m4v", ".3gp", ".wmv", ".mpg", ".mpeg"}
)
SUPPORTED_EXTENSIONS: frozenset[str] = STILL_EXTENSIONS | RAW_EXTENSIONS

_DISPLAY_PREFERENCE: tuple[frozenset[str], ...] = (
    JPEG_EXTENSIONS,
    frozenset({".heic", ".heif"}),
    frozenset({".png", ".webp"}),
    frozenset({".tif", ".tiff"}),
)


@dataclass(frozen=True, slots=True)
class ScannedFile:
    relative_path: str
    absolute_path: Path
    file_size: int
    mtime: float

    @property
    def extension(self) -> str:
        return PurePosixPath(self.relative_path).suffix.lower()

    @property
    def is_raw(self) -> bool:
        return self.extension in RAW_EXTENSIONS


@dataclass(frozen=True, slots=True)
class ScannedGroup:
    primary: ScannedFile
    companions: tuple[ScannedFile, ...]
    group_key: str | None


@dataclass(slots=True)
class ScanReport:
    groups: list[ScannedGroup] = field(default_factory=list)
    skipped_videos: int = 0
    skipped_other: int = 0
    cancelled: bool = False


def is_supported(name: str) -> bool:
    return PurePosixPath(name).suffix.lower() in SUPPORTED_EXTENSIONS


def scan(
    root: Path,
    recursive: bool = True,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[int], None] | None = None,
    exclude: Iterable[Path] = (),
) -> ScanReport:
    """Walks a source folder. `exclude` prunes subtrees, such as the destination."""
    report = ScanReport()
    files: list[ScannedFile] = []
    if should_cancel is not None and should_cancel():
        report.cancelled = True
        return report
    for entry in _walk(root, recursive, _resolve_all(exclude)):
        if should_cancel is not None and should_cancel():
            report.cancelled = True
            return report
        suffix = entry.suffix.lower()
        if suffix in VIDEO_EXTENSIONS:
            report.skipped_videos += 1
            continue
        if suffix not in SUPPORTED_EXTENSIONS:
            report.skipped_other += 1
            continue
        try:
            stat = entry.stat()
        except OSError:
            report.skipped_other += 1
            continue
        files.append(
            ScannedFile(
                relative_path=entry.relative_to(root).as_posix(),
                absolute_path=entry,
                file_size=stat.st_size,
                mtime=stat.st_mtime,
            )
        )
        if on_progress is not None and len(files) % 50 == 0:
            on_progress(len(files))
    if on_progress is not None:
        on_progress(len(files))
    report.groups = list(group_raw_pairs(files))
    return report


def group_raw_pairs(files: Iterable[ScannedFile]) -> Iterator[ScannedGroup]:
    buckets: dict[tuple[str, str], list[ScannedFile]] = {}
    order: list[tuple[str, str]] = []
    for file in files:
        path = PurePosixPath(file.relative_path)
        key = (path.parent.as_posix(), path.stem.casefold())
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(file)

    for key in order:
        bucket = sorted(buckets[key], key=lambda item: item.relative_path)
        if not any(item.is_raw for item in bucket) or len(bucket) == 1:
            for item in bucket:
                yield ScannedGroup(primary=item, companions=(), group_key=None)
            continue
        primary = _pick_display_file(bucket)
        companions = tuple(item for item in bucket if item is not primary)
        yield ScannedGroup(
            primary=primary,
            companions=companions,
            group_key=f"{key[0]}/{key[1]}" if key[0] != "." else key[1],
        )


def _is_excluded(directory: Path, excluded: frozenset[Path]) -> bool:
    if not excluded:
        return False
    try:
        return directory.resolve() in excluded
    except OSError:
        return False


def _pick_display_file(bucket: list[ScannedFile]) -> ScannedFile:
    for preference in _DISPLAY_PREFERENCE:
        for item in bucket:
            if item.extension in preference:
                return item
    return bucket[0]


def _resolve_all(paths: Iterable[Path]) -> frozenset[Path]:
    resolved = set()
    for path in paths:
        try:
            resolved.add(path.resolve())
        except OSError:
            continue
    return frozenset(resolved)


def _walk(root: Path, recursive: bool, excluded: frozenset[Path] = frozenset()) -> Iterator[Path]:
    if not recursive:
        try:
            entries = sorted(root.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.name.startswith(".") or not entry.is_file():
                continue
            yield entry
        return

    for dirpath, dirnames, filenames in os.walk(root):
        directory = Path(dirpath)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not name.startswith(".") and not _is_excluded(directory / name, excluded)
        )
        for filename in sorted(filenames):
            if filename.startswith("."):
                continue
            yield directory / filename
