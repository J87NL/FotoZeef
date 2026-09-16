from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from fotozeef.core.library import Library
from fotozeef.core.models import ProjectSettings
from fotozeef.core.thumbnails import ThumbnailCache
from fotozeef.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


@pytest.fixture
def window(app: QApplication, tmp_path: Path, library: Library, jpeg_factory) -> MainWindow:
    source = tmp_path / "cam"
    for index in range(5):
        jpeg_factory(source / f"{index}.jpg", captured_at=datetime(2024, 1, 1, 9, index, 0))
    project = library.create_project("shoot", [source], tmp_path / "out", ProjectSettings())
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    state = library.open_project(project.id)
    window._on_project_opened(state)
    yield window
    window.close()


def _press(window: MainWindow, key: Qt.Key) -> None:
    window.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def test_window_shows_the_timeline(window: MainWindow) -> None:
    assert window._model.rowCount() == 5
    assert window._state is not None
    assert window._state.cursor == 0


def test_arrow_keys_move_the_shared_cursor(window: MainWindow) -> None:
    _press(window, Qt.Key.Key_Right)
    _press(window, Qt.Key.Key_Right)

    assert window._state.cursor == 2
    assert window._filmstrip.currentIndex().row() == 2

    _press(window, Qt.Key.Key_Left)
    assert window._state.cursor == 1


def test_home_end_and_paging_clamp(window: MainWindow) -> None:
    _press(window, Qt.Key.Key_End)
    assert window._state.cursor == 4

    _press(window, Qt.Key.Key_PageUp)
    assert window._state.cursor == 0

    _press(window, Qt.Key.Key_PageDown)
    assert window._state.cursor == 4

    _press(window, Qt.Key.Key_Home)
    assert window._state.cursor == 0


def test_space_toggles_selection_and_writes_the_file(window: MainWindow, app: QApplication) -> None:
    _press(window, Qt.Key.Key_Space)
    photo_id = window._state.entries[0].photo.id
    assert photo_id in window._selected

    window._selection_queue.flush()
    app.processEvents()
    destination = window._state.project.destination
    assert (destination / "0.jpg").is_file()

    _press(window, Qt.Key.Key_Space)
    window._selection_queue.flush()
    app.processEvents()
    assert photo_id not in window._selected
    assert not (destination / "0.jpg").exists()


def test_fullscreen_toggle_hides_the_filmstrip(window: MainWindow) -> None:
    window.toggle_fullscreen()
    assert not window._filmstrip.isVisible()

    _press(window, Qt.Key.Key_Escape)
    assert not window.isFullScreen()


def test_status_line_tracks_position_and_selection(window: MainWindow) -> None:
    assert window._status.text().startswith("1/5")

    _press(window, Qt.Key.Key_Right)
    assert window._status.text().startswith("2/5")
    assert "0 selected" in window._status.text()


def test_filmstrip_delegate_paints_every_row(window: MainWindow) -> None:
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QStyleOptionViewItem

    delegate = window._filmstrip.itemDelegate()
    image = QImage(200, 200, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    option = QStyleOptionViewItem()
    option.rect = image.rect()
    for row in range(window._model.rowCount()):
        delegate.paint(painter, option, window._model.index(row, 0))
    painter.end()


def test_refusing_to_remove_a_foreign_file_does_not_block_culling(
    window: MainWindow, app: QApplication
) -> None:
    state = window._state
    destination = state.project.destination
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "0.jpg").write_bytes((state.entries[0].absolute_path).read_bytes())

    reopened = window._library.open_project(state.project.id)
    window._on_project_opened(reopened)
    photo_id = reopened.entries[0].photo.id
    assert photo_id in window._selected

    _press(window, Qt.Key.Key_Space)
    window._selection_queue.flush()
    app.processEvents()

    assert photo_id in window._selected
    assert (destination / "0.jpg").is_file()
    assert "not written by this app" in window.statusBar().currentMessage()


def test_empty_project_states_the_obvious(
    app: QApplication, tmp_path: Path, library: Library
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    project = library.create_project("empty", [empty], tmp_path / "out", ProjectSettings())
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    window._on_project_opened(library.open_project(project.id))

    assert window._viewer._placeholder == "This project has no photos yet"
    assert window._status.text() == "No project open"
    window.close()


def test_unreadable_file_reports_in_the_viewer(
    app: QApplication, tmp_path: Path, library: Library
) -> None:
    source = tmp_path / "cam"
    source.mkdir()
    (source / "broken.jpg").write_bytes(b"not an image")
    project = library.create_project("broken", [source], tmp_path / "out", ProjectSettings())
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    window._on_project_opened(library.open_project(project.id))

    for _ in range(200):
        app.processEvents()
        if window._unreadable:
            break
    assert window._unreadable
    assert window._viewer._message == "This file could not be read"
    window.close()


def test_skipped_videos_are_reported_once(
    app: QApplication, tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "a.jpg")
    (source / "clip.mp4").write_bytes(b"video")
    (source / "clip2.mov").write_bytes(b"video")
    project = library.create_project("mixed", [source], tmp_path / "out", ProjectSettings())
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    window._on_project_opened(library.open_project(project.id))

    assert "2 video files skipped" in window.statusBar().currentMessage()
    window.close()
