from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from fotozeef.core import ordering
from fotozeef.core import selection as selection_ops
from fotozeef.core.db import (
    Database,
    PhotoRepository,
    ProjectRepository,
    SelectionRepository,
    SourceRepository,
)
from fotozeef.core.metadata import read_metadata
from fotozeef.core.models import (
    Photo,
    PhotoDraft,
    Project,
    ProjectSettings,
    Selection,
    Source,
    TimelineEntry,
)
from fotozeef.core.scanner import ScannedGroup, scan

DEFAULT_DESTINATION_NAME = "selectie"

_log = logging.getLogger(__name__)


@dataclass(slots=True)
class ScanSummary:
    added: int = 0
    missing: int = 0
    skipped_videos: int = 0
    cancelled: bool = False


@dataclass(slots=True)
class ProjectState:
    project: Project
    sources: tuple[Source, ...]
    entries: tuple[TimelineEntry, ...]
    selections: dict[int, Selection] = field(default_factory=dict)
    cursor: int = 0
    scan: ScanSummary = field(default_factory=ScanSummary)

    def index_of(self, photo_id: int) -> int | None:
        for index, entry in enumerate(self.entries):
            if entry.photo.id == photo_id:
                return index
        return None

    def positions(self) -> dict[int, int]:
        return {entry.photo.id: index for index, entry in enumerate(self.entries)}

    @property
    def current(self) -> TimelineEntry | None:
        if not self.entries:
            return None
        return self.entries[min(max(self.cursor, 0), len(self.entries) - 1)]


class Library:
    def __init__(self, db: Database) -> None:
        self._db = db
        self.projects = ProjectRepository(db)
        self.sources = SourceRepository(db)
        self.photos = PhotoRepository(db)
        self.selections = SelectionRepository(db)

    def create_project(
        self,
        name: str,
        source_paths: Sequence[Path],
        destination: Path | None,
        settings: ProjectSettings,
    ) -> Project:
        if not source_paths:
            raise ValueError("A project needs at least one source folder")
        target = destination or (source_paths[0] / DEFAULT_DESTINATION_NAME)
        project = self.projects.create(name=name, destination=target, settings=settings)
        for index, path in enumerate(source_paths):
            self.sources.add(project.id, path, label=path.name or str(path), sort_order=index)
        return project

    def open_project(
        self,
        project_id: int,
        should_cancel: Callable[[], bool] | None = None,
        on_progress: Callable[[str, int], None] | None = None,
    ) -> ProjectState:
        project = self.projects.get(project_id)
        if project is None:
            raise LookupError(f"Project {project_id} does not exist")
        self.projects.touch(project_id)

        summary = ScanSummary()
        for source in self.sources.list(project_id):
            source_summary = self.refresh_source(
                source,
                project.settings,
                should_cancel,
                on_progress,
                exclude=(project.destination,),
            )
            summary.added += source_summary.added
            summary.missing += source_summary.missing
            summary.skipped_videos += source_summary.skipped_videos
            summary.cancelled = summary.cancelled or source_summary.cancelled

        state = self.load_state(project_id)
        state.scan = summary
        self.reconcile_state(state)
        state.cursor = self._restore_cursor(state, project.cursor_photo_id)
        return state

    def load_state(self, project_id: int) -> ProjectState:
        project = self.projects.get(project_id)
        if project is None:
            raise LookupError(f"Project {project_id} does not exist")
        sources = self.sources.list(project_id)
        photos = self.photos.list_for_project(project_id)
        entries = ordering.build_timeline(photos, sources)
        selections = {item.photo_id: item for item in self.selections.list(project_id)}
        return ProjectState(
            project=project,
            sources=sources,
            entries=entries,
            selections=selections,
        )

    def refresh_source(
        self,
        source: Source,
        settings: ProjectSettings,
        should_cancel: Callable[[], bool] | None = None,
        on_progress: Callable[[str, int], None] | None = None,
        exclude: Iterable[Path] = (),
    ) -> ScanSummary:
        summary = ScanSummary()
        if not source.path.is_dir():
            known = self.photos.list_for_source(source.id)
            self.photos.set_missing([photo.id for photo in known], True)
            summary.missing = len(known)
            return summary

        report = scan(
            source.path,
            recursive=settings.recursive,
            should_cancel=should_cancel,
            on_progress=(lambda count: on_progress(source.label, count)) if on_progress else None,
            exclude=exclude,
        )
        summary.skipped_videos = report.skipped_videos
        if report.skipped_videos:
            _log.info("skipped %d video files in %s", report.skipped_videos, source.path)
        if report.cancelled:
            summary.cancelled = True
            return summary

        known = {photo.relative_path: photo for photo in self.photos.list_for_source(source.id)}
        drafts = [
            self._draft(group, known.get(group.primary.relative_path)) for group in report.groups
        ]
        self.photos.upsert_many(source.id, drafts)
        summary.added = sum(
            1 for group in report.groups if group.primary.relative_path not in known
        )

        seen = {group.primary.relative_path for group in report.groups}
        gone = [photo.id for path, photo in known.items() if path not in seen]
        self.photos.set_missing(gone, True)
        summary.missing = len(gone)

        self._maybe_relabel(source)
        _log.info(
            "scanned %s: %d photos, %d new, %d missing",
            source.path,
            len(report.groups),
            summary.added,
            summary.missing,
        )
        return summary

    def reconcile_state(self, state: ProjectState) -> selection_ops.ReconcileResult:
        result = selection_ops.reconcile(
            state.project.destination,
            state.entries,
            state.selections.values(),
            state.project.settings,
        )
        for photo_id in result.dropped:
            self.selections.remove(photo_id)
            state.selections.pop(photo_id, None)
        for photo_id, written_name in result.adopted:
            state.selections[photo_id] = self.selections.add(
                photo_id, state.project.id, written_name, written_by_app=False
            )
        for photo_id in result.adopted_from_sidecar:
            index = state.index_of(photo_id)
            if index is None:
                continue
            self.select(state, index)
        return result

    def select(self, state: ProjectState, index: int) -> Selection:
        entry = state.entries[index]
        writer = selection_ops.DestinationWriter(state.project.destination, state.project.settings)
        reserved = selection_ops.reserved_names(state.selections.values())
        written = writer.select(entry, reserved)
        record = self.selections.add(
            entry.photo.id, state.project.id, written.written_name, written_by_app=True
        )
        state.selections[entry.photo.id] = record
        return record

    def deselect(self, state: ProjectState, index: int) -> None:
        entry = state.entries[index]
        record = state.selections.get(entry.photo.id)
        if record is None:
            return
        writer = selection_ops.DestinationWriter(state.project.destination, state.project.settings)
        writer.deselect(entry, record)
        self.selections.remove(entry.photo.id)
        state.selections.pop(entry.photo.id, None)

    def set_offset(self, state: ProjectState, source_id: int, time_offset_s: int) -> ProjectState:
        self.sources.set_offset(source_id, time_offset_s)
        state.sources = tuple(
            Source(
                id=source.id,
                project_id=source.project_id,
                path=source.path,
                label=source.label,
                time_offset_s=time_offset_s if source.id == source_id else source.time_offset_s,
                sort_order=source.sort_order,
            )
            for source in state.sources
        )
        current = state.current
        state.entries = ordering.resort(state.entries, state.sources)
        if current is not None:
            restored = state.index_of(current.photo.id)
            state.cursor = restored if restored is not None else state.cursor
        return state

    def set_cursor(self, state: ProjectState, index: int) -> None:
        if not state.entries:
            return
        state.cursor = min(max(index, 0), len(state.entries) - 1)
        self.projects.set_cursor(state.project.id, state.entries[state.cursor].photo.id)

    def update_settings(self, state: ProjectState, settings: ProjectSettings) -> ProjectState:
        self.projects.update_settings(state.project.id, settings)
        state.project = Project(
            id=state.project.id,
            name=state.project.name,
            destination=state.project.destination,
            cursor_photo_id=state.project.cursor_photo_id,
            settings=settings,
            created_at=state.project.created_at,
            opened_at=state.project.opened_at,
        )
        return state

    def _draft(self, group: ScannedGroup, known: Photo | None) -> PhotoDraft:
        primary = group.primary
        companions = tuple(item.relative_path for item in group.companions)
        if (
            known is not None
            and known.mtime == primary.mtime
            and known.file_size == primary.file_size
        ):
            return PhotoDraft(
                relative_path=primary.relative_path,
                file_size=primary.file_size,
                mtime=primary.mtime,
                captured_at=known.captured_at,
                capture_source=known.capture_source,
                orientation=known.orientation,
                camera=known.camera,
                group_key=group.group_key,
                companions=companions,
            )
        meta = read_metadata(primary.absolute_path, primary.mtime)
        return PhotoDraft(
            relative_path=primary.relative_path,
            file_size=primary.file_size,
            mtime=primary.mtime,
            captured_at=meta.captured_at,
            capture_source=meta.capture_source,
            orientation=meta.orientation,
            camera=meta.camera,
            group_key=group.group_key,
            companions=companions,
        )

    def _maybe_relabel(self, source: Source) -> None:
        if source.label != (source.path.name or str(source.path)):
            return
        cameras = Counter(
            photo.camera for photo in self.photos.list_for_source(source.id) if photo.camera
        )
        if not cameras:
            return
        self.sources.set_label(source.id, cameras.most_common(1)[0][0])

    def _restore_cursor(self, state: ProjectState, photo_id: int | None) -> int:
        if not state.entries or photo_id is None:
            return 0
        index = state.index_of(photo_id)
        if index is None:
            return 0
        if not state.entries[index].photo.missing:
            return index
        surviving = [entry for entry in state.entries if not entry.photo.missing]
        if not surviving:
            return index
        nearest = surviving[ordering.nearest_index(surviving, state.entries[index].effective_at)]
        return state.index_of(nearest.photo.id) or 0


def derive_label(source: Source, photos: Iterable[Photo]) -> str:
    cameras = Counter(photo.camera for photo in photos if photo.camera)
    if cameras:
        return cameras.most_common(1)[0][0]
    return source.path.name or str(source.path)
