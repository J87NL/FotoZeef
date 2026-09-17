from __future__ import annotations

import time
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


@pytest.fixture
def window(app: QApplication, tmp_path: Path, library: Library, jpeg_factory) -> MainWindow:
    source = tmp_path / "cam"
    for index in range(4):
        jpeg_factory(
            source / f"{index}.jpg",
            captured_at=datetime(2024, 1, 1, 9, index, 0),
            size=(1600, 1200),
        )
    project = library.create_project("shoot", [source], tmp_path / "out", ProjectSettings())
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    window.resize(1200, 800)
    window.show()
    window._on_project_opened(library.open_project(project.id))
    app.processEvents()
    yield window
    window.close()


def _press(window: MainWindow, key: Qt.Key) -> None:
    window.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def test_plus_and_minus_zoom(window: MainWindow) -> None:
    assert not window._viewer.zoomed

    _press(window, Qt.Key.Key_Plus)
    assert window._viewer.zoomed
    zoomed = window._viewer.zoom

    _press(window, Qt.Key.Key_Minus)
    assert window._viewer.zoom < zoomed


def test_zoom_never_goes_below_fit(window: MainWindow) -> None:
    for _ in range(10):
        _press(window, Qt.Key.Key_Minus)

    assert window._viewer.zoom == pytest.approx(1.0)
    assert not window._viewer.zoomed


def test_zero_returns_to_fit(window: MainWindow) -> None:
    for _ in range(4):
        _press(window, Qt.Key.Key_Plus)
    assert window._viewer.zoomed

    _press(window, Qt.Key.Key_0)

    assert window._viewer.zoom == pytest.approx(1.0)


def test_escape_first_unzooms_then_leaves_fullscreen(window: MainWindow) -> None:
    window.toggle_fullscreen()
    _press(window, Qt.Key.Key_Plus)
    assert window._viewer.zoomed

    _press(window, Qt.Key.Key_Escape)
    assert not window._viewer.zoomed
    assert window._fullscreen

    _press(window, Qt.Key.Key_Escape)
    assert not window._fullscreen


def test_zoom_survives_stepping_to_the_next_photo(window: MainWindow) -> None:
    _press(window, Qt.Key.Key_Plus)
    _press(window, Qt.Key.Key_Plus)
    zoomed = window._viewer.zoom

    _press(window, Qt.Key.Key_Right)

    assert window._viewer.zoom == pytest.approx(zoomed)


def test_panning_is_clamped_to_the_image(window: MainWindow) -> None:
    _press(window, Qt.Key.Key_Plus)
    viewer = window._viewer
    viewer._pan.setX(100_000)
    viewer._clamp_pan()

    canvas = viewer._canvas()
    target = viewer._target_rect(canvas)
    assert target.left() <= canvas.left()
    assert target.right() >= canvas.right()


def test_zoom_shows_in_the_status_line(window: MainWindow) -> None:
    assert "%" not in window._status.text()

    _press(window, Qt.Key.Key_Plus)

    assert "%" in window._status.text()


def test_full_resolution_image_replaces_the_preview(window: MainWindow, app: QApplication) -> None:
    _press(window, Qt.Key.Key_Plus)

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and window._full is None:
        app.processEvents()
        time.sleep(0.01)

    assert window._full is not None
    photo_id, pixmap = window._full
    assert photo_id == window._state.entries[0].photo.id
    assert pixmap.width() == 1600
