from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QVBoxLayout,
    QWidget,
)

from fotozeef.appinfo import APP_NAME
from fotozeef.core.library import Library, ProjectState
from fotozeef.core.models import TimelineEntry
from fotozeef.core.thumbnails import ThumbnailCache
from fotozeef.ui.filmstrip import Filmstrip, FilmstripModel
from fotozeef.ui.offset_dialog import OffsetDialog
from fotozeef.ui.open_dialog import OpenProjectDialog
from fotozeef.ui.project_dialog import ProjectDialog
from fotozeef.ui.settings_dialog import SettingsDialog
from fotozeef.ui.tasks import ProjectOpener, SelectionQueue
from fotozeef.ui.thumbnail_service import ThumbnailService
from fotozeef.ui.viewer import Viewer

PREFETCH_RADIUS = 3
PAGE_JUMP = 10
CURSOR_SAVE_DELAY_MS = 400


class MainWindow(QMainWindow):
    def __init__(self, library: Library, cache: ThumbnailCache) -> None:
        super().__init__()
        self._library = library
        self._state: ProjectState | None = None
        self._selected: set[int] = set()
        self._reference: TimelineEntry | None = None
        self._progress: QProgressDialog | None = None

        scale = self.screen().devicePixelRatio() if self.screen() is not None else 1.0
        self._service = ThumbnailService(cache, scale=scale, parent=self)
        self._service.ready.connect(self._on_thumbnail_ready)

        self._model = FilmstripModel(self._service, self)
        self._filmstrip = Filmstrip(self._model, self)
        self._filmstrip.cursor_moved.connect(self._on_filmstrip_cursor)
        self._viewer = Viewer(self)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._viewer, 1)
        layout.addWidget(self._filmstrip)
        self.setCentralWidget(central)

        self._status = QLabel("", self)
        self.statusBar().addPermanentWidget(self._status)

        self._opener = ProjectOpener(library, self)
        self._opener.opened.connect(self._on_project_opened)
        self._opener.failed.connect(self._on_project_failed)
        self._opener.progress.connect(self._on_scan_progress)

        self._selection_queue = SelectionQueue(self)
        self._selection_queue.failed.connect(self._on_selection_failed)

        self._cursor_timer = QTimer(self)
        self._cursor_timer.setSingleShot(True)
        self._cursor_timer.setInterval(CURSOR_SAVE_DELAY_MS)
        self._cursor_timer.timeout.connect(self._persist_cursor)

        self.setWindowTitle(APP_NAME)
        self.resize(1280, 860)
        self._build_menu()
        self._update_status()

    def open_last_project(self) -> None:
        projects = self._library.projects.list()
        if not projects:
            return
        self._start_open(projects[0].id)

    def new_project(self) -> None:
        dialog = ProjectDialog(self)
        if dialog.exec() != ProjectDialog.DialogCode.Accepted:
            return
        request = dialog.request()
        if not request.sources:
            return
        project = self._library.create_project(
            request.name, list(request.sources), request.destination, request.settings
        )
        self._start_open(project.id)

    def open_project(self) -> None:
        dialog = OpenProjectDialog(self._library.projects.list(), self)
        dialog.forget_requested.connect(self._library.projects.delete)
        if dialog.exec() != OpenProjectDialog.DialogCode.Accepted:
            return
        project_id = dialog.selected_project_id()
        if project_id is None:
            return
        self._start_open(project_id)

    def edit_settings(self) -> None:
        if self._state is None:
            return
        dialog = SettingsDialog(self._state.project, self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        project_id = self._state.project.id
        if dialog.name:
            self._library.projects.rename(project_id, dialog.name)
        self._library.projects.set_destination(project_id, dialog.destination)
        self._library.projects.update_settings(project_id, dialog.settings)
        self._start_open(project_id)

    def edit_offsets(self) -> None:
        if self._state is None:
            return
        current = self._state.current
        dialog = OffsetDialog(
            self._state.sources,
            reference=self._reference,
            target=current,
            reference_pixmap=self._thumbnail_for(self._reference),
            target_pixmap=self._thumbnail_for(current),
            parent=self,
        )
        if dialog.exec() != OffsetDialog.DialogCode.Accepted:
            return
        changed = dialog.changed_offsets()
        if not changed:
            return
        for source_id, offset in changed.items():
            self._library.set_offset(self._state, source_id, offset)
        self._rebuild_timeline()

    def set_time_reference(self) -> None:
        if self._state is None:
            return
        self._reference = self._state.current
        if self._reference is not None:
            self.statusBar().showMessage(f"Time reference: {self._reference.photo.filename}", 4000)

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.leave_fullscreen()
            return
        self.menuBar().setVisible(False)
        self.statusBar().setVisible(False)
        self._filmstrip.setVisible(False)
        self.showFullScreen()

    def leave_fullscreen(self) -> None:
        if not self.isFullScreen():
            return
        self.showNormal()
        self.menuBar().setVisible(True)
        self.statusBar().setVisible(True)
        self._filmstrip.setVisible(True)

    def toggle_selection(self) -> None:
        state = self._state
        if state is None or not state.entries:
            return
        index = state.cursor
        entry = state.entries[index]
        if entry.photo.missing:
            self.statusBar().showMessage("That file is missing from its source folder", 4000)
            return
        photo_id = entry.photo.id
        wanted = photo_id not in self._selected
        self._apply_selection_locally(photo_id, wanted)
        if wanted:
            self._selection_queue.submit(photo_id, True, lambda: self._library.select(state, index))
            return
        self._selection_queue.submit(photo_id, False, lambda: self._library.deselect(state, index))

    def move_cursor(self, delta: int) -> None:
        if self._state is None or not self._state.entries:
            return
        self._set_cursor(self._state.cursor + delta)

    def go_to(self, index: int) -> None:
        self._set_cursor(index)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Right:
            self.move_cursor(1)
        elif key == Qt.Key.Key_Left:
            self.move_cursor(-1)
        elif key == Qt.Key.Key_Space:
            self.toggle_selection()
        elif key == Qt.Key.Key_Home:
            self.go_to(0)
        elif key == Qt.Key.Key_End:
            self.go_to(len(self._state.entries) - 1 if self._state else 0)
        elif key == Qt.Key.Key_PageDown:
            self.move_cursor(PAGE_JUMP)
        elif key == Qt.Key.Key_PageUp:
            self.move_cursor(-PAGE_JUMP)
        elif key == Qt.Key.Key_F:
            self.toggle_fullscreen()
        elif key == Qt.Key.Key_Escape:
            self.leave_fullscreen()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._cursor_timer.stop()
        self._persist_cursor()
        self._opener.cancel()
        self._opener.wait()
        self._selection_queue.close()
        self._service.shutdown()
        super().closeEvent(event)

    def _build_menu(self) -> None:
        project_menu = self.menuBar().addMenu("&Project")
        project_menu.addAction(
            self._action("&New project…", QKeySequence.StandardKey.New, self.new_project)
        )
        project_menu.addAction(
            self._action("&Open project…", QKeySequence.StandardKey.Open, self.open_project)
        )
        project_menu.addSeparator()
        project_menu.addAction(
            self._action("&Settings…", QKeySequence.StandardKey.Preferences, self.edit_settings)
        )
        project_menu.addSeparator()
        project_menu.addAction(self._action("&Quit", QKeySequence.StandardKey.Quit, self.close))

        timeline_menu = self.menuBar().addMenu("&Timeline")
        timeline_menu.addAction(self._action("Set time &reference", None, self.set_time_reference))
        timeline_menu.addAction(self._action("Time &offsets…", None, self.edit_offsets))

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self._action("&Fullscreen", "F", self.toggle_fullscreen))

    def _action(self, text: str, shortcut: object, handler: object) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(handler)
        return action

    def _start_open(self, project_id: int) -> None:
        if self._opener.busy:
            return
        self._show_progress()
        self._opener.start(project_id)

    def _show_progress(self) -> None:
        progress = QProgressDialog("Scanning…", "Cancel", 0, 0, self)
        progress.setWindowTitle(APP_NAME)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(300)
        progress.canceled.connect(self._opener.cancel)
        self._progress = progress

    def _on_scan_progress(self, label: str, count: int) -> None:
        if self._progress is not None:
            self._progress.setLabelText(f"Scanning {label}: {count} photos")

    def _on_project_opened(self, state: ProjectState) -> None:
        self._close_progress()
        self._state = state
        self._reference = None
        self._selected = set(state.selections)
        self._service.clear()
        self._model.set_entries(state.entries)
        self._model.set_selected(self._selected)
        self._service.set_positions(state.positions())
        self.setWindowTitle(f"{state.project.name} — {APP_NAME}")
        self._set_cursor(state.cursor, persist=False)
        self._update_status()
        if state.scan.cancelled:
            self.statusBar().showMessage("Scan cancelled; showing what was found so far", 5000)

    def _on_project_failed(self, message: str) -> None:
        self._close_progress()
        QMessageBox.critical(self, APP_NAME, f"Could not open the project:\n{message}")

    def _close_progress(self) -> None:
        if self._progress is None:
            return
        self._progress.close()
        self._progress = None

    def _on_filmstrip_cursor(self, row: int) -> None:
        if self._state is None or row == self._state.cursor:
            return
        self._set_cursor(row)

    def _set_cursor(self, index: int, persist: bool = True) -> None:
        state = self._state
        if state is None or not state.entries:
            return
        state.cursor = min(max(index, 0), len(state.entries) - 1)
        self._filmstrip.set_cursor(state.cursor)
        self._service.set_cursor(state.cursor)
        self._render_current()
        self._prefetch()
        if persist:
            self._cursor_timer.start()

    def _render_current(self) -> None:
        state = self._state
        entry = state.current if state is not None else None
        if entry is None:
            self._viewer.show_entry(None, None, False)
            return
        pixmap = self._service.pixmap(entry, self._service.preview_target)
        if pixmap is None:
            pixmap = self._service.pixmap(entry, self._service.filmstrip_target)
        self._viewer.show_entry(entry, pixmap, entry.photo.id in self._selected)
        self._update_status()

    def _prefetch(self) -> None:
        state = self._state
        if state is None:
            return
        for offset in range(-PREFETCH_RADIUS, PREFETCH_RADIUS + 1):
            index = state.cursor + offset
            if 0 <= index < len(state.entries):
                self._service.request(state.entries[index], self._service.preview_target)

    def _on_thumbnail_ready(self, photo_id: int, target: int) -> None:
        if target == self._service.filmstrip_target:
            self._model.refresh_photo(photo_id)
            return
        state = self._state
        if state is not None and state.current is not None and state.current.photo.id == photo_id:
            self._render_current()

    def _apply_selection_locally(self, photo_id: int, selected: bool) -> None:
        if selected:
            self._selected.add(photo_id)
        else:
            self._selected.discard(photo_id)
        self._model.mark_selected(photo_id, selected)
        state = self._state
        if state is not None and state.current is not None and state.current.photo.id == photo_id:
            self._viewer.set_selected(selected)
        self._update_status()

    def _on_selection_failed(self, photo_id: int, intended: bool, message: str) -> None:
        self._apply_selection_locally(photo_id, not intended)
        if not intended:
            self.statusBar().showMessage(message, 6000)
            return
        QMessageBox.warning(self, APP_NAME, f"Could not copy the photo:\n{message}")

    def _rebuild_timeline(self) -> None:
        state = self._state
        if state is None:
            return
        self._model.set_entries(state.entries)
        self._model.set_selected(self._selected)
        self._service.set_positions(state.positions())
        self._set_cursor(state.cursor, persist=False)

    def _persist_cursor(self) -> None:
        state = self._state
        if state is None or not state.entries:
            return
        self._library.set_cursor(state, state.cursor)

    def _thumbnail_for(self, entry: TimelineEntry | None) -> object:
        if entry is None:
            return None
        return self._service.pixmap(entry, self._service.filmstrip_target)

    def _update_status(self) -> None:
        state = self._state
        if state is None or not state.entries:
            self._status.setText("No project open")
            return
        position = state.cursor + 1
        total = len(state.entries)
        destination = _short_path(state.project.destination)
        self._status.setText(
            f"{position}/{total}    {len(self._selected)} selected    → {destination}"
        )


def _short_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.home()).as_posix())
    except ValueError:
        return str(path)


def screen_scale(app: QApplication) -> float:
    screen = app.primaryScreen()
    if screen is None:
        return 1.0
    return screen.devicePixelRatio()
