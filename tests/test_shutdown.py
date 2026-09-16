from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from fotozeef.core.db import Database, ProjectRepository
from fotozeef.core.models import ProjectSettings
from fotozeef.core.thumbnails import ThumbnailCache, ThumbnailRequest, ThumbnailWorker


def test_shutdown_waits_for_in_flight_renders(tmp_path: Path, jpeg_factory) -> None:
    """Callbacks reach into Qt objects, so none may fire after shutdown returns."""
    path = jpeg_factory(tmp_path / "a.jpg")
    stat = path.stat()
    started = threading.Event()
    late: list[int] = []

    class SlowCache(ThumbnailCache):
        def get_or_create(self, request: ThumbnailRequest) -> Path:
            started.set()
            time.sleep(0.4)
            return super().get_or_create(request)

    worker = ThumbnailWorker(
        SlowCache(tmp_path / "cache"),
        max_workers=2,
        on_ready=lambda request, _path: late.append(request.photo_id),
        on_failed=lambda request, _error: late.append(request.photo_id),
    )
    for photo_id in range(4):
        worker.submit(
            ThumbnailRequest(
                photo_id=photo_id,
                path=path,
                mtime=stat.st_mtime,
                file_size=stat.st_size,
                target=200,
            )
        )

    assert started.wait(5)
    worker.shutdown()
    time.sleep(0.6)

    assert late == [], "a callback fired after shutdown returned"


def test_close_closes_connections_opened_on_other_threads(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.sqlite")
    ProjectRepository(db).create("a", tmp_path / "out", ProjectSettings())
    from_worker: list[sqlite3.Connection] = []

    def use_from_thread() -> None:
        from_worker.append(db.connection)
        db.connection.execute("SELECT count(*) FROM projects").fetchone()

    worker = threading.Thread(target=use_from_thread)
    worker.start()
    worker.join()
    assert from_worker

    db.close()

    with pytest.raises(sqlite3.ProgrammingError):
        from_worker[0].execute("SELECT 1")


def test_a_closed_database_refuses_new_connections(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.sqlite")
    db.close()

    with pytest.raises(RuntimeError):
        db.connection.execute("SELECT 1")


def test_a_closed_database_releases_the_file(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    db = Database(path)
    ProjectRepository(db).create("a", tmp_path / "out", ProjectSettings())
    db.close()

    path.unlink()
    for leftover in tmp_path.glob("state.sqlite*"):
        leftover.unlink()

    assert not list(tmp_path.glob("state.sqlite*"))


def test_writes_still_work_while_another_thread_opens_a_connection(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.sqlite")
    projects = ProjectRepository(db)
    errors: list[Exception] = []

    def writer(index: int) -> None:
        try:
            projects.create(f"p{index}", tmp_path / "out", ProjectSettings())
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert not any(thread.is_alive() for thread in threads), "database write deadlocked"
    assert not errors
    assert len(projects.list()) == 8
    db.close()
