from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from fotozeef.core.models import (
    CaptureSource,
    Photo,
    PhotoDraft,
    Project,
    ProjectSettings,
    Selection,
    Source,
)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE projects (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,
    destination      TEXT NOT NULL,
    cursor_photo     INTEGER NULL REFERENCES photos(id) ON DELETE SET NULL,
    recursive        INTEGER NOT NULL DEFAULT 1,
    copy_raw_sidecar INTEGER NOT NULL DEFAULT 1,
    write_xmp        INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    opened_at        TEXT NOT NULL
);

CREATE TABLE sources (
    id             INTEGER PRIMARY KEY,
    project_id     INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    path           TEXT NOT NULL,
    label          TEXT NOT NULL,
    time_offset_s  INTEGER NOT NULL DEFAULT 0,
    sort_order     INTEGER NOT NULL
);

CREATE TABLE photos (
    id             INTEGER PRIMARY KEY,
    source_id      INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    relative_path  TEXT NOT NULL,
    file_size      INTEGER NOT NULL,
    mtime          REAL NOT NULL,
    captured_at    TEXT NULL,
    capture_source TEXT NOT NULL,
    orientation    INTEGER NOT NULL DEFAULT 1,
    camera         TEXT NULL,
    group_key      TEXT NULL,
    companions     TEXT NOT NULL DEFAULT '[]',
    missing        INTEGER NOT NULL DEFAULT 0,
    UNIQUE (source_id, relative_path)
);

CREATE TABLE selections (
    photo_id       INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
    project_id     INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    written_name   TEXT NOT NULL,
    written_by_app INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL
);

CREATE INDEX idx_sources_project ON sources(project_id);
CREATE INDEX idx_photos_source ON photos(source_id);
CREATE INDEX idx_selections_project ON selections(project_id);
"""


def utcnow() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _from_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


class Database:
    """Thread-safe SQLite handle; every thread gets its own connection."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._local = threading.local()
        self._write_lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def connection(self) -> sqlite3.Connection:
        existing = getattr(self._local, "connection", None)
        if existing is not None:
            return existing
        connection = sqlite3.connect(self._path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        self._local.connection = connection
        return connection

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock, self.connection as connection:
            yield connection

    def close(self) -> None:
        existing = getattr(self._local, "connection", None)
        if existing is None:
            return
        existing.close()
        self._local.connection = None

    def _migrate(self) -> None:
        connection = self.connection
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == SCHEMA_VERSION:
            return
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema {version} is newer than this build supports ({SCHEMA_VERSION})"
            )
        with self._write_lock, connection:
            if version == 0:
                connection.executescript(_SCHEMA)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


class ProjectRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        name: str,
        destination: Path,
        settings: ProjectSettings,
    ) -> Project:
        now = utcnow()
        with self._db.write() as connection:
            cursor = connection.execute(
                "INSERT INTO projects (name, destination, cursor_photo, recursive,"
                " copy_raw_sidecar, write_xmp, created_at, opened_at)"
                " VALUES (?, ?, NULL, ?, ?, ?, ?, ?)",
                (
                    name,
                    str(destination),
                    int(settings.recursive),
                    int(settings.copy_raw_sidecar),
                    int(settings.write_xmp),
                    _to_iso(now),
                    _to_iso(now),
                ),
            )
        return Project(
            id=int(cursor.lastrowid),
            name=name,
            destination=destination,
            cursor_photo_id=None,
            settings=settings,
            created_at=now,
            opened_at=now,
        )

    def get(self, project_id: int) -> Project | None:
        row = self._db.connection.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            return None
        return _project_from_row(row)

    def list(self) -> tuple[Project, ...]:
        rows = self._db.connection.execute(
            "SELECT * FROM projects ORDER BY opened_at DESC"
        ).fetchall()
        return tuple(_project_from_row(row) for row in rows)

    def update_settings(self, project_id: int, settings: ProjectSettings) -> None:
        with self._db.write() as connection:
            connection.execute(
                "UPDATE projects SET recursive = ?, copy_raw_sidecar = ?, write_xmp = ?"
                " WHERE id = ?",
                (
                    int(settings.recursive),
                    int(settings.copy_raw_sidecar),
                    int(settings.write_xmp),
                    project_id,
                ),
            )

    def rename(self, project_id: int, name: str) -> None:
        with self._db.write() as connection:
            connection.execute("UPDATE projects SET name = ? WHERE id = ?", (name, project_id))

    def set_destination(self, project_id: int, destination: Path) -> None:
        with self._db.write() as connection:
            connection.execute(
                "UPDATE projects SET destination = ? WHERE id = ?",
                (str(destination), project_id),
            )

    def set_cursor(self, project_id: int, photo_id: int | None) -> None:
        with self._db.write() as connection:
            connection.execute(
                "UPDATE projects SET cursor_photo = ? WHERE id = ?", (photo_id, project_id)
            )

    def touch(self, project_id: int) -> None:
        with self._db.write() as connection:
            connection.execute(
                "UPDATE projects SET opened_at = ? WHERE id = ?",
                (_to_iso(utcnow()), project_id),
            )

    def delete(self, project_id: int) -> None:
        with self._db.write() as connection:
            connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))


class SourceRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, project_id: int, path: Path, label: str, sort_order: int) -> Source:
        with self._db.write() as connection:
            cursor = connection.execute(
                "INSERT INTO sources (project_id, path, label, time_offset_s, sort_order)"
                " VALUES (?, ?, ?, 0, ?)",
                (project_id, str(path), label, sort_order),
            )
        return Source(
            id=int(cursor.lastrowid),
            project_id=project_id,
            path=path,
            label=label,
            time_offset_s=0,
            sort_order=sort_order,
        )

    def list(self, project_id: int) -> tuple[Source, ...]:
        rows = self._db.connection.execute(
            "SELECT * FROM sources WHERE project_id = ? ORDER BY sort_order, id",
            (project_id,),
        ).fetchall()
        return tuple(_source_from_row(row) for row in rows)

    def set_offset(self, source_id: int, time_offset_s: int) -> None:
        with self._db.write() as connection:
            connection.execute(
                "UPDATE sources SET time_offset_s = ? WHERE id = ?",
                (time_offset_s, source_id),
            )

    def set_label(self, source_id: int, label: str) -> None:
        with self._db.write() as connection:
            connection.execute("UPDATE sources SET label = ? WHERE id = ?", (label, source_id))

    def remove(self, source_id: int) -> None:
        with self._db.write() as connection:
            connection.execute("DELETE FROM sources WHERE id = ?", (source_id,))


class PhotoRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def list_for_project(self, project_id: int) -> tuple[Photo, ...]:
        rows = self._db.connection.execute(
            "SELECT photos.* FROM photos"
            " JOIN sources ON sources.id = photos.source_id"
            " WHERE sources.project_id = ?",
            (project_id,),
        ).fetchall()
        return tuple(_photo_from_row(row) for row in rows)

    def list_for_source(self, source_id: int) -> tuple[Photo, ...]:
        rows = self._db.connection.execute(
            "SELECT * FROM photos WHERE source_id = ?", (source_id,)
        ).fetchall()
        return tuple(_photo_from_row(row) for row in rows)

    def upsert_many(self, source_id: int, photos: Iterable[PhotoDraft]) -> None:
        payload = [
            (
                source_id,
                photo.relative_path,
                photo.file_size,
                photo.mtime,
                _to_iso(photo.captured_at),
                str(photo.capture_source),
                photo.orientation,
                photo.camera,
                photo.group_key,
                json.dumps(list(photo.companions)),
                0,
            )
            for photo in photos
        ]
        if not payload:
            return
        with self._db.write() as connection:
            connection.executemany(
                "INSERT INTO photos (source_id, relative_path, file_size, mtime, captured_at,"
                " capture_source, orientation, camera, group_key, companions, missing)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (source_id, relative_path) DO UPDATE SET"
                " file_size = excluded.file_size, mtime = excluded.mtime,"
                " captured_at = excluded.captured_at, capture_source = excluded.capture_source,"
                " orientation = excluded.orientation, camera = excluded.camera,"
                " group_key = excluded.group_key, companions = excluded.companions,"
                " missing = excluded.missing",
                payload,
            )

    def set_missing(self, photo_ids: Iterable[int], missing: bool) -> None:
        ids = list(photo_ids)
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        with self._db.write() as connection:
            connection.execute(
                f"UPDATE photos SET missing = ? WHERE id IN ({placeholders})",
                (int(missing), *ids),
            )


class SelectionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def list(self, project_id: int) -> tuple[Selection, ...]:
        rows = self._db.connection.execute(
            "SELECT * FROM selections WHERE project_id = ?", (project_id,)
        ).fetchall()
        return tuple(_selection_from_row(row) for row in rows)

    def get(self, photo_id: int) -> Selection | None:
        row = self._db.connection.execute(
            "SELECT * FROM selections WHERE photo_id = ?", (photo_id,)
        ).fetchone()
        if row is None:
            return None
        return _selection_from_row(row)

    def add(
        self,
        photo_id: int,
        project_id: int,
        written_name: str,
        written_by_app: bool,
    ) -> Selection:
        now = utcnow()
        with self._db.write() as connection:
            connection.execute(
                "INSERT INTO selections (photo_id, project_id, written_name, written_by_app,"
                " created_at) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT (photo_id) DO UPDATE SET written_name = excluded.written_name,"
                " written_by_app = excluded.written_by_app",
                (photo_id, project_id, written_name, int(written_by_app), _to_iso(now)),
            )
        return Selection(
            photo_id=photo_id,
            project_id=project_id,
            written_name=written_name,
            written_by_app=written_by_app,
            created_at=now,
        )

    def remove(self, photo_id: int) -> None:
        with self._db.write() as connection:
            connection.execute("DELETE FROM selections WHERE photo_id = ?", (photo_id,))


def _project_from_row(row: sqlite3.Row) -> Project:
    return Project(
        id=int(row["id"]),
        name=str(row["name"]),
        destination=Path(row["destination"]),
        cursor_photo_id=row["cursor_photo"],
        settings=ProjectSettings(
            recursive=bool(row["recursive"]),
            copy_raw_sidecar=bool(row["copy_raw_sidecar"]),
            write_xmp=bool(row["write_xmp"]),
        ),
        created_at=_from_iso(row["created_at"]) or utcnow(),
        opened_at=_from_iso(row["opened_at"]) or utcnow(),
    )


def _source_from_row(row: sqlite3.Row) -> Source:
    return Source(
        id=int(row["id"]),
        project_id=int(row["project_id"]),
        path=Path(row["path"]),
        label=str(row["label"]),
        time_offset_s=int(row["time_offset_s"]),
        sort_order=int(row["sort_order"]),
    )


def _photo_from_row(row: sqlite3.Row) -> Photo:
    return Photo(
        id=int(row["id"]),
        source_id=int(row["source_id"]),
        relative_path=str(row["relative_path"]),
        file_size=int(row["file_size"]),
        mtime=float(row["mtime"]),
        captured_at=_from_iso(row["captured_at"]),
        capture_source=CaptureSource(row["capture_source"]),
        orientation=int(row["orientation"]),
        camera=row["camera"],
        group_key=row["group_key"],
        companions=tuple(json.loads(row["companions"])),
        missing=bool(row["missing"]),
    )


def _selection_from_row(row: sqlite3.Row) -> Selection:
    return Selection(
        photo_id=int(row["photo_id"]),
        project_id=int(row["project_id"]),
        written_name=str(row["written_name"]),
        written_by_app=bool(row["written_by_app"]),
        created_at=_from_iso(row["created_at"]) or utcnow(),
    )
