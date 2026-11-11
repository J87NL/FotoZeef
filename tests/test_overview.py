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


@pytest.fixture
def window(app: QApplication, tmp_path: Path, library: Library, jpeg_factory) -> MainWindow:
    source = tmp_path / "cam"
    for index in range(30):
        jpeg_factory(source / f"{index:02d}.jpg", captured_at=datetime(2024, 1, 1, 9, index, 0))
    project = library.create_project("shoot", [source], tmp_path / "out", ProjectSettings())
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    window.resize(1000, 700)
    window._on_project_opened(library.open_project(project.id))
    yield window
    window._selection_queue.flush()
    window.close()


def _press(widget, key: Qt.Key) -> None:
    widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def _grid_rows(window: MainWindow) -> int:
    return window._overview.grid.model().rowCount()


def _overview_action(window: MainWindow):
    return next(action for action in window._actions if action.shortcut().toString() == "G")


def test_g_shows_every_photo_and_hides_the_filmstrip(window: MainWindow) -> None:
    window.show()
    _overview_action(window).trigger()

    assert window.overview_shown
    assert _grid_rows(window) == 30
    assert not window._filmstrip.isVisible()

    _overview_action(window).trigger()
    assert not window.overview_shown
    assert window._filmstrip.isVisible()


def test_the_grid_starts_on_the_current_photo(window: MainWindow) -> None:
    window.go_to(17)

    window.show_overview()

    grid = window._overview.grid
    assert grid.source_row(grid.currentIndex()) == 17


def test_enter_opens_the_chosen_photo(window: MainWindow) -> None:
    window.show_overview()
    grid = window._overview.grid
    grid.setCurrentIndex(grid.model().index(22, 0))

    _press(grid, Qt.Key.Key_Return)

    assert not window.overview_shown
    assert window._state.cursor == 22


def test_a_click_opens_the_photo(window: MainWindow) -> None:
    window.show_overview()
    grid = window._overview.grid

    grid.clicked.emit(grid.model().index(5, 0))

    assert window._state.cursor == 5
    assert not window.overview_shown


def test_escape_returns_without_moving(window: MainWindow) -> None:
    window.go_to(3)
    window.show_overview()
    grid = window._overview.grid
    grid.setCurrentIndex(grid.model().index(20, 0))

    _press(grid, Qt.Key.Key_Escape)

    assert not window.overview_shown
    assert window._state.cursor == 3


def test_space_selects_in_the_grid_and_stays_there(window: MainWindow) -> None:
    window.show_overview()
    grid = window._overview.grid
    grid.setCurrentIndex(grid.model().index(8, 0))

    _press(grid, Qt.Key.Key_Space)

    assert window.overview_shown
    assert window._state.entries[8].photo.id in window._selected


def test_only_selected_filters_the_grid(window: MainWindow, app: QApplication) -> None:
    for row in (4, 12):
        window.go_to(row)
        window.toggle_selection()
    window.show_overview()

    window._overview.set_only_selected(True)

    grid = window._overview.grid
    assert _grid_rows(window) == 2
    assert [grid.source_row(grid.model().index(row, 0)) for row in range(2)] == [4, 12]

    _press(grid, Qt.Key.Key_Return)
    assert window._state.cursor in (4, 12)


def test_unselecting_in_a_filtered_grid_removes_the_photo(window: MainWindow) -> None:
    for row in (4, 12):
        window.go_to(row)
        window.toggle_selection()
    window.show_overview()
    window._overview.set_only_selected(True)
    grid = window._overview.grid
    grid.setCurrentIndex(grid.model().index(0, 0))

    _press(grid, Qt.Key.Key_Space)

    assert _grid_rows(window) == 1


def test_the_summary_counts_photos_and_selection(window: MainWindow) -> None:
    window.go_to(2)
    window.toggle_selection()
    window.show_overview()

    assert window._overview._summary.text() == "30 photos, 1 selected"


def test_closing_the_project_leaves_the_overview(window: MainWindow) -> None:
    window.show_overview()
    window._overview.set_only_selected(True)

    window.close_project()

    assert not window.overview_shown
    assert not window._overview.only_selected


def test_leaving_fullscreen_keeps_the_filmstrip_hidden_in_the_overview(
    window: MainWindow,
) -> None:
    window.show()
    window.toggle_fullscreen()
    window.show_overview()

    window.leave_fullscreen()

    assert window.overview_shown
    assert not window._filmstrip.isVisible()


def test_the_filter_never_takes_the_keyboard_from_the_grid(window: MainWindow) -> None:
    window.show()
    window.show_overview()

    window._overview._only_selected.click()

    assert window._overview._only_selected.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert window._overview.grid.hasFocus() or not window.isActiveWindow()


def test_opening_a_project_leaves_the_overview_and_its_filter(
    window: MainWindow, library: Library
) -> None:
    window.show_overview()
    window._overview.set_only_selected(True)

    window._on_project_opened(library.open_project(window._state.project.id))

    assert not window.overview_shown
    assert not window._overview.only_selected
