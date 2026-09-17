from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QImage,
    QKeyEvent,
    QKeySequence,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from fotozeef.appinfo import APP_NAME
from fotozeef.core.library import Library, ProjectState
from fotozeef.core.models import TimelineEntry
from fotozeef.core.thumbnails import ThumbnailCache
from fotozeef.ui.filmstrip import Filmstrip, FilmstripModel
from fotozeef.ui.full_image import FullImageLoader
from fotozeef.ui.offset_dialog import OffsetDialog
from fotozeef.ui.open_dialog import OpenProjectDialog
from fotozeef.ui.project_dialog import ProjectDialog
from fotozeef.ui.settings_dialog import SettingsDialog
from fotozeef.ui.start_screen import StartScreen
from fotozeef.ui.tasks import ProjectOpener, SelectionQueue
from fotozeef.ui.thumbnail_service import ThumbnailService
from fotozeef.ui.translations import available_languages, current_language, install, save_language
from fotozeef.ui.viewer import Viewer

PREFETCH_RADIUS = 3
PAGE_JUMP = 10
CURSOR_SAVE_DELAY_MS = 400
HINT_VISIBLE_MS = 3500


class MainWindow(QMainWindow):
    def __init__(self, library: Library, cache: ThumbnailCache) -> None:
        super().__init__()
        self._library = library
        self._state: ProjectState | None = None
        self._selected: set[int] = set()
        self._reference: TimelineEntry | None = None
        self._progress: QProgressDialog | None = None
        self._fullscreen = False
        self._was_maximized = False

        scale = self.screen().devicePixelRatio() if self.screen() is not None else 1.0
        self._service = ThumbnailService(cache, scale=scale, parent=self)
        self._service.ready.connect(self._on_thumbnail_ready)
        self._service.failed.connect(self._on_thumbnail_failed)
        self._unreadable: set[int] = set()

        self._model = FilmstripModel(self._service, self)
        self._filmstrip = Filmstrip(self._model, self)
        self._filmstrip.cursor_moved.connect(self._on_filmstrip_cursor)
        self._viewer = Viewer(self)
        self._viewer.zoom_changed.connect(self._on_zoom_changed)

        self._full_loader = FullImageLoader(self)
        self._full_loader.loaded.connect(self._on_full_image)
        self._full_loader.failed.connect(self._on_full_image_failed)
        self._full: tuple[int, QPixmap] | None = None

        culling = QWidget(self)
        layout = QVBoxLayout(culling)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._viewer, 1)
        layout.addWidget(self._filmstrip)

        self._start_screen = StartScreen(self)
        self._start_screen.new_requested.connect(self.new_project)
        self._start_screen.browse_requested.connect(self.open_project)
        self._start_screen.open_requested.connect(self._start_open)

        self._pages = QStackedWidget(self)
        self._pages.addWidget(self._start_screen)
        self._pages.addWidget(culling)
        self.setCentralWidget(self._pages)

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

        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.setInterval(HINT_VISIBLE_MS)
        self._hint_timer.timeout.connect(lambda: self._viewer.show_hint(None))

        self.setWindowTitle(APP_NAME)
        self.resize(1280, 860)
        self._build_menu()
        self.show_start_screen()

    def open_last_project(self) -> None:
        projects = self._library.projects.list()
        if not projects:
            return
        self._start_open(projects[0].id)

    def show_start_screen(self) -> None:
        self._refresh_start_screen()
        self._pages.setCurrentWidget(self._start_screen)
        self._update_status()

    def _refresh_start_screen(self) -> None:
        self._start_screen.set_projects(
            self._library.projects.list(), self._library.selections.counts_by_project()
        )

    def close_project(self) -> None:
        if self._state is None:
            return
        self.leave_fullscreen()
        self._cursor_timer.stop()
        self._persist_cursor()
        self._selection_queue.flush()
        self._state = None
        self._selected = set()
        self._unreadable = set()
        self._reference = None
        self._full = None
        self._full_loader.cancel()
        self._viewer.zoom_to_fit()
        self._service.clear()
        self._model.set_entries(())
        self._viewer.show_entry(None, None, False)
        self.setWindowTitle(APP_NAME)
        self.show_start_screen()

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
        dialog.forget_requested.connect(self.forget_project)
        if dialog.exec() != OpenProjectDialog.DialogCode.Accepted:
            return
        project_id = dialog.selected_project_id()
        if project_id is None:
            return
        self._start_open(project_id)

    def forget_project(self, project_id: int) -> None:
        self._library.projects.delete(project_id)
        if self._state is not None and self._state.project.id == project_id:
            self.close_project()
            return
        self._refresh_start_screen()

    def edit_settings(self) -> None:
        if self._state is None:
            return
        dialog = SettingsDialog(self._state.project, self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        if dialog.destination != self._state.project.destination and not self._confirm_move():
            return
        project_id = self._state.project.id
        if dialog.name:
            self._library.projects.rename(project_id, dialog.name)
        self._library.projects.set_destination(project_id, dialog.destination)
        self._library.projects.update_settings(project_id, dialog.settings)
        self._start_open(project_id)

    def _confirm_move(self) -> bool:
        answer = QMessageBox.question(
            self,
            APP_NAME,
            self.tr(
                "The selection is read back from the destination folder, so pointing the"
                " project at a different folder starts from whatever is already in there.\n\n"
                "Photos already copied stay where they are. Continue?"
            ),
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Ok

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
            self.statusBar().showMessage(
                self.tr("Time reference: {0}").format(self._reference.photo.filename), 4000
            )

    def toggle_fullscreen(self) -> None:
        if self._fullscreen:
            self.leave_fullscreen()
            return
        self._fullscreen = True
        self._was_maximized = self.isMaximized()
        self.menuBar().setVisible(False)
        self.statusBar().setVisible(False)
        self._filmstrip.setVisible(False)
        self.showFullScreen()
        self._viewer.show_hint(self.tr("Esc or F to leave fullscreen"))
        self._hint_timer.start()

    def leave_fullscreen(self) -> None:
        """Restores the window state it came from; showNormal would unmaximise."""
        if not self._fullscreen:
            return
        self._fullscreen = False
        self._hint_timer.stop()
        self._viewer.show_hint(None)
        if self._was_maximized:
            self.showMaximized()
        else:
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
            self.statusBar().showMessage(
                self.tr("That file is missing from its source folder"), 4000
            )
            return
        photo_id = entry.photo.id
        wanted = photo_id not in self._selected
        self._apply_selection_locally(photo_id, wanted)
        if wanted:
            self._selection_queue.submit(photo_id, True, lambda: self._library.select(state, index))
            return
        self._selection_queue.submit(photo_id, False, lambda: self._library.deselect(state, index))

    def zoom_in(self) -> None:
        self._viewer.zoom_in()

    def zoom_out(self) -> None:
        self._viewer.zoom_out()

    def zoom_to_fit(self) -> None:
        self._viewer.zoom_to_fit()

    def zoom_to_actual_size(self) -> None:
        self._viewer.zoom_to_actual_size()

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
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_in()
        elif key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self.zoom_out()
        elif key == Qt.Key.Key_0:
            self.zoom_to_fit()
        elif key == Qt.Key.Key_1:
            self.zoom_to_actual_size()
        elif key == Qt.Key.Key_Escape:
            if self._viewer.zoomed:
                self.zoom_to_fit()
            else:
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
        self._full_loader.shutdown()
        self._service.shutdown()
        super().closeEvent(event)

    def _build_menu(self) -> None:
        keys = QKeySequence.StandardKey
        project_menu = self.menuBar().addMenu(self.tr("&Project"))
        self._add(project_menu, self.tr("&New project…"), keys.New, self.new_project)
        self._add(project_menu, self.tr("&Open project…"), keys.Open, self.open_project)
        self._add(project_menu, self.tr("&Close project"), keys.Close, self.close_project)
        project_menu.addSeparator()
        self._add(project_menu, self.tr("&Settings…"), keys.Preferences, self.edit_settings)
        project_menu.addSeparator()
        self._add(project_menu, self.tr("&Quit"), keys.Quit, self.close)

        timeline_menu = self.menuBar().addMenu(self.tr("&Timeline"))
        self._add(timeline_menu, self.tr("Set time &reference"), None, self.set_time_reference)
        self._add(timeline_menu, self.tr("Time &offsets…"), None, self.edit_offsets)

        view_menu = self.menuBar().addMenu(self.tr("&View"))
        self._add(view_menu, self.tr("&Fullscreen"), "F", self.toggle_fullscreen)
        view_menu.addSeparator()
        self._add(view_menu, self.tr("Zoom &in"), keys.ZoomIn, self.zoom_in)
        self._add(view_menu, self.tr("Zoom &out"), keys.ZoomOut, self.zoom_out)
        self._add(view_menu, self.tr("&Fit to window"), "0", self.zoom_to_fit)
        self._add(view_menu, self.tr("&Actual size"), "1", self.zoom_to_actual_size)
        view_menu.addSeparator()
        self._build_language_menu(view_menu.addMenu(self.tr("&Language")))

    def _build_language_menu(self, menu: QMenu) -> None:
        group = QActionGroup(menu)
        group.setExclusive(True)
        active = current_language()
        for code, label in available_languages():
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(code == active)
            action.triggered.connect(lambda _checked=False, code=code: self.set_language(code))
            group.addAction(action)
            menu.addAction(action)

    def set_language(self, language: str) -> None:
        if language == current_language():
            return
        application = QApplication.instance()
        if application is None:
            return
        save_language(language)
        install(application, language)
        QTimer.singleShot(0, self.retranslate)

    def retranslate(self) -> None:
        """Menus and one-off labels hold their text, so they are rebuilt in place."""
        self.menuBar().clear()
        self._build_menu()
        self._start_screen.retranslate()
        self._refresh_start_screen()
        self._render_current()
        self._update_status()

    def _add(
        self,
        menu: QMenu,
        text: str,
        shortcut: QKeySequence.StandardKey | str | None,
        handler: Callable[[], None],
    ) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(handler)
        menu.addAction(action)
        return action

    def _start_open(self, project_id: int) -> None:
        if self._opener.busy:
            return
        self._selection_queue.flush()
        self._show_progress()
        self._opener.start(project_id)

    def _show_progress(self) -> None:
        progress = QProgressDialog(self.tr("Scanning…"), self.tr("Cancel"), 0, 0, self)
        progress.setWindowTitle(APP_NAME)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(300)
        progress.canceled.connect(self._opener.cancel)
        self._progress = progress

    def _on_scan_progress(self, label: str, count: int) -> None:
        if self._progress is not None:
            self._progress.setLabelText(self.tr("Scanning {0}: {1} photos").format(label, count))

    def _on_project_opened(self, state: ProjectState) -> None:
        self._close_progress()
        self._state = state
        self._reference = None
        self._unreadable = set()
        self._full = None
        self._selected = set(state.selections)
        self._service.clear()
        self._model.set_entries(state.entries)
        self._model.set_selected(self._selected)
        self._service.set_positions(state.positions())
        self.setWindowTitle(f"{state.project.name} — {APP_NAME}")
        self._pages.setCurrentIndex(1)
        self._set_cursor(state.cursor, persist=False)
        self._render_current()
        self._update_status()
        self._report_scan(state)

    def _report_scan(self, state: ProjectState) -> None:
        if state.scan.cancelled:
            self.statusBar().showMessage(
                self.tr("Scan cancelled; showing what was found so far"), 6000
            )
            return
        notes: list[str] = []
        if state.scan.added:
            notes.append(self.tr("{0} new").format(state.scan.added))
        if state.scan.missing:
            notes.append(self.tr("{0} missing").format(state.scan.missing))
        if state.scan.skipped_videos:
            notes.append(self.tr("{0} video files skipped").format(state.scan.skipped_videos))
        if notes:
            self.statusBar().showMessage(", ".join(notes), 6000)

    def _on_project_failed(self, message: str) -> None:
        self._close_progress()
        QMessageBox.critical(
            self, APP_NAME, self.tr("Could not open the project:\n{0}").format(message)
        )

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
        if self._viewer.zoomed:
            self._request_full_image()
        self._prefetch()
        if persist:
            self._cursor_timer.start()

    def _on_zoom_changed(self, zoom: float) -> None:
        self._update_status()
        if self._viewer.zoomed:
            self._request_full_image()

    def _request_full_image(self) -> None:
        state = self._state
        entry = state.current if state is not None else None
        if entry is None or entry.photo.missing:
            return
        if self._full is not None and self._full[0] == entry.photo.id:
            return
        self._full_loader.request(entry.photo.id, entry.absolute_path)

    def _on_full_image(self, photo_id: int, image: QImage) -> None:
        state = self._state
        entry = state.current if state is not None else None
        if entry is None or entry.photo.id != photo_id:
            return
        self._full = (photo_id, QPixmap.fromImage(image))
        self._render_current()

    def _on_full_image_failed(self, photo_id: int, message: str) -> None:
        state = self._state
        entry = state.current if state is not None else None
        if entry is None or entry.photo.id != photo_id:
            return
        self.statusBar().showMessage(
            self.tr("Could not load this photo at full size: {0}").format(message), 6000
        )

    def _render_current(self) -> None:
        state = self._state
        entry = state.current if state is not None else None
        if entry is None:
            self._viewer.set_placeholder(
                self.tr("This project has no photos yet")
                if state is not None
                else self.tr("Open or create a project to start culling")
            )
            self._viewer.show_entry(None, None, False)
            return
        natural_width = 0
        pixmap = None
        if self._full is not None and self._full[0] == entry.photo.id:
            pixmap = self._full[1]
            natural_width = pixmap.width()
        if pixmap is None:
            pixmap = self._service.pixmap(entry, self._service.preview_target)
        if pixmap is None:
            pixmap = self._service.pixmap(entry, self._service.filmstrip_target)
        self._viewer.show_entry(
            entry, pixmap, entry.photo.id in self._selected, natural_width=natural_width
        )
        if pixmap is None and entry.photo.id in self._unreadable:
            self._viewer.show_message(self._unreadable_text(entry))
        self._update_status()

    def _unreadable_text(self, entry: TimelineEntry) -> str:
        if entry.photo.missing:
            return self.tr("This file is missing from its source folder")
        return self.tr("This file could not be read")

    def _prefetch(self) -> None:
        state = self._state
        if state is None:
            return
        for offset in range(-PREFETCH_RADIUS, PREFETCH_RADIUS + 1):
            index = state.cursor + offset
            if 0 <= index < len(state.entries):
                self._service.request(state.entries[index], self._service.preview_target)

    def _on_thumbnail_failed(self, photo_id: int, _target: int, _message: str) -> None:
        self._unreadable.add(photo_id)
        state = self._state
        if state is not None and state.current is not None and state.current.photo.id == photo_id:
            self._render_current()

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
        QMessageBox.warning(
            self, APP_NAME, self.tr("Could not copy the photo:\n{0}").format(message)
        )

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

    def _thumbnail_for(self, entry: TimelineEntry | None) -> QPixmap | None:
        if entry is None:
            return None
        return self._service.pixmap(entry, self._service.filmstrip_target)

    def _update_status(self) -> None:
        state = self._state
        if state is None or not state.entries:
            self._status.setText(self.tr("No project open"))
            return
        position = state.cursor + 1
        total = len(state.entries)
        destination = _short_path(state.project.destination)
        zoom = f"    {self._viewer.zoom * 100:.0f}%" if self._viewer.zoomed else ""
        self._status.setText(
            self.tr("{0}/{1}    {2} selected{3}    → {4}").format(
                position, total, len(self._selected), zoom, destination
            )
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
