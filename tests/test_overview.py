from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
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


# --- zooming the grid ------------------------------------------------------------------


def _wheel(widget, delta: int, modifiers: Qt.KeyboardModifier) -> None:
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent

    widget.wheelEvent(
        QWheelEvent(
            QPointF(10, 10),
            QPointF(10, 10),
            QPoint(0, 0),
            QPoint(0, delta),
            Qt.MouseButton.NoButton,
            modifiers,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
    )


def _tile_width(window: MainWindow) -> int:
    grid = window._overview.grid
    return grid.itemDelegate().sizeHint(None, grid.model().index(0, 0)).width()


def test_ctrl_and_the_wheel_zoom_the_grid(window: MainWindow) -> None:
    from fotozeef.ui.overview import DEFAULT_ZOOM, TILE_WIDTHS

    window.show_overview()
    window._overview.set_zoom(DEFAULT_ZOOM)
    grid = window._overview.grid

    _wheel(grid, 120, Qt.KeyboardModifier.ControlModifier)
    assert _tile_width(window) == TILE_WIDTHS[DEFAULT_ZOOM + 1]

    _wheel(grid, -120, Qt.KeyboardModifier.ControlModifier)
    _wheel(grid, -120, Qt.KeyboardModifier.ControlModifier)
    assert _tile_width(window) == TILE_WIDTHS[DEFAULT_ZOOM - 1]


def test_a_plain_wheel_still_scrolls(window: MainWindow) -> None:
    window.show_overview()
    before = window._overview.zoom

    _wheel(window._overview.grid, 120, Qt.KeyboardModifier.NoModifier)

    assert window._overview.zoom == before


def test_ctrl_plus_and_minus_zoom_the_grid_not_the_photo(window: MainWindow) -> None:
    from fotozeef.ui.overview import DEFAULT_ZOOM

    window.show_overview()
    window._overview.set_zoom(DEFAULT_ZOOM)
    zoom_in = next(
        action
        for action in window._actions
        if action.shortcut() == QKeySequence(QKeySequence.StandardKey.ZoomIn)
    )
    zoom_in.trigger()

    assert window._overview.zoom == DEFAULT_ZOOM + 1
    assert not window._viewer.zoomed

    window.zoom_out()
    window.zoom_out()
    assert window._overview.zoom == DEFAULT_ZOOM - 1

    window.zoom_to_fit()
    assert window._overview.zoom == DEFAULT_ZOOM


def test_zoom_stops_at_both_ends(window: MainWindow) -> None:
    from fotozeef.ui.overview import TILE_WIDTHS

    window.show_overview()
    for _ in range(20):
        window.zoom_in()
    assert window._overview.zoom == len(TILE_WIDTHS) - 1
    for _ in range(20):
        window.zoom_out()
    assert window._overview.zoom == 0


def test_the_photo_zooms_again_outside_the_overview(window: MainWindow) -> None:
    window.show_overview()
    window.hide_overview()

    window.zoom_in()

    assert window._viewer.zoomed


def test_the_zoom_is_remembered(window: MainWindow) -> None:
    from fotozeef.ui.main_window import _saved_overview_zoom

    window.show_overview()
    window._overview.set_zoom(5)

    assert _saved_overview_zoom() == 5
    window._overview.set_zoom(2)


def test_large_tiles_ask_for_the_sharper_thumbnail(window: MainWindow) -> None:
    from PySide6.QtCore import QSize

    requested: list[int] = []
    service = window._service
    original = service.scaled_pixmap

    def spy(entry, target, size):
        requested.append(target)
        return original(entry, target, size)

    service.scaled_pixmap = spy
    entry = window._state.entries[0]

    window._overview_pixmap(entry, QSize(150, 120))
    assert requested == [service.filmstrip_target]

    requested.clear()
    window._overview_pixmap(entry, QSize(400, 320))
    assert requested[0] == service.grid_target


def test_a_touchpad_zooms_one_step_per_full_notch(window: MainWindow) -> None:
    window.show_overview()
    window._overview.set_zoom(2)

    for _ in range(9):
        _wheel(window._overview.grid, 12, Qt.KeyboardModifier.ControlModifier)
    assert window._overview.zoom == 2

    for _ in range(3):
        _wheel(window._overview.grid, 12, Qt.KeyboardModifier.ControlModifier)
    assert window._overview.zoom == 3


def test_scaled_tiles_stay_within_their_memory_budget(window: MainWindow, monkeypatch) -> None:
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QPixmap

    from fotozeef.ui import thumbnail_service

    monkeypatch.setattr(thumbnail_service, "_SCALED_CACHE_BYTES", 2_000_000)
    service = window._service
    base = QPixmap(800, 600)
    monkeypatch.setattr(service, "pixmap", lambda _entry, _target: base)

    for entry in window._state.entries:
        service.scaled_pixmap(entry, service.grid_target, QSize(420, 336))

    assert 0 < service.scaled_bytes <= 2_000_000
