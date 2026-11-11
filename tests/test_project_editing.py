from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from fotozeef.core.library import DEFAULT_DESTINATION_NAME, Library
from fotozeef.core.models import ProjectSettings
from fotozeef.core.thumbnails import ThumbnailCache
from fotozeef.ui.main_window import MainWindow
from fotozeef.ui.project_dialog import ProjectDialog
from fotozeef.ui.project_fields import DestinationField
from fotozeef.ui.settings_dialog import SettingsDialog


@pytest.fixture
def shoot(tmp_path: Path, library: Library, jpeg_factory):
    first = tmp_path / "day1"
    second = tmp_path / "day2"
    jpeg_factory(first / "a.jpg", captured_at=datetime(2024, 1, 1, 9))
    jpeg_factory(second / "b.jpg", captured_at=datetime(2024, 1, 2, 9))
    project = library.create_project("trip", [first], tmp_path / "out", ProjectSettings())
    library.open_project(project.id)
    return project, first, second


@pytest.fixture
def window(app: QApplication, tmp_path: Path, library: Library):
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    yield window
    window.close()


# --- destination help ------------------------------------------------------------------


def test_the_destination_explains_what_empty_means(app: QApplication, tmp_path: Path) -> None:
    field = DestinationField()
    assert DEFAULT_DESTINATION_NAME in field.help_text
    assert field.destination() is None

    field.set_first_source(tmp_path / "day1")

    assert str(tmp_path / "day1" / DEFAULT_DESTINATION_NAME) in field.help_text
    assert field.resolved() == tmp_path / "day1" / DEFAULT_DESTINATION_NAME


def test_a_typed_destination_wins(app: QApplication, tmp_path: Path) -> None:
    field = DestinationField()
    field.set_first_source(tmp_path / "day1")
    field.set_text(str(tmp_path / "keepers"))

    assert field.destination() == tmp_path / "keepers"
    assert field.resolved() == tmp_path / "keepers"


def test_the_new_project_dialog_follows_the_first_folder(app: QApplication, tmp_path: Path) -> None:
    dialog = ProjectDialog()
    dialog._sources.add(tmp_path / "day1")

    assert str(tmp_path / "day1" / DEFAULT_DESTINATION_NAME) in dialog._destination.help_text
    assert dialog.request().destination is None
    assert dialog._ok_button.isEnabled()
    dialog.close()


def test_there_is_no_xmp_option_any_more(app: QApplication) -> None:
    from PySide6.QtWidgets import QCheckBox

    dialog = ProjectDialog()
    labels = [box.text() for box in dialog.findChildren(QCheckBox)]

    assert not any("XMP" in label for label in labels)
    dialog.close()


# --- folders ---------------------------------------------------------------------------


def test_folders_can_be_added_and_removed(library: Library, shoot) -> None:
    project, first, second = shoot

    dropped = library.set_sources(project.id, [second])

    assert [source.path for source in dropped] == [first]
    state = library.open_project(project.id)
    assert [entry.photo.relative_path for entry in state.entries] == ["b.jpg"]

    library.set_sources(project.id, [second, first])
    state = library.open_project(project.id)
    assert [entry.photo.relative_path for entry in state.entries] == ["a.jpg", "b.jpg"]


def test_a_project_keeps_at_least_one_folder(library: Library, shoot) -> None:
    project, _first, _second = shoot

    with pytest.raises(ValueError):
        library.set_sources(project.id, [])


def test_the_settings_dialog_shows_and_edits_the_folders(
    app: QApplication, library: Library, shoot
) -> None:
    project, first, second = shoot
    dialog = SettingsDialog(project, library.sources.list(project.id))
    assert dialog.source_paths == (first,)

    dialog._sources.add(second)
    assert dialog.source_paths == (first, second)

    dialog._sources.select_row(0)
    dialog._sources.remove_selected()
    dialog._sources.select_row(0)
    dialog._sources.remove_selected()
    assert not dialog._ok_button.isEnabled()
    dialog.close()


def test_an_emptied_destination_falls_back_to_the_first_folder(
    app: QApplication, library: Library, shoot
) -> None:
    project, first, _second = shoot
    dialog = SettingsDialog(project, library.sources.list(project.id))

    dialog._destination.set_text("")

    assert dialog.destination == first / DEFAULT_DESTINATION_NAME
    dialog.close()


# --- from the start screen -------------------------------------------------------------


def test_settings_open_from_the_start_screen_without_opening_the_project(
    window: MainWindow, library: Library, shoot, monkeypatch
) -> None:
    project, _first, second = shoot
    window.show_start_screen()

    def edit(dialog: SettingsDialog) -> int:
        dialog._name.setText("road trip")
        dialog._sources.add(second)
        return SettingsDialog.DialogCode.Accepted

    monkeypatch.setattr(SettingsDialog, "exec", edit)
    window._start_screen.settings_requested.emit(project.id)

    assert window._state is None
    assert library.projects.get(project.id).name == "road trip"
    assert [source.path for source in library.sources.list(project.id)][-1] == second
    names = [
        window._start_screen._list.item(row).data(Qt.ItemDataRole.UserRole + 1)
        for row in range(window._start_screen._list.count())
    ]
    assert names == ["road trip"]


def test_dropping_a_folder_asks_first(
    window: MainWindow, library: Library, shoot, monkeypatch
) -> None:
    project, first, second = shoot
    library.set_sources(project.id, [first, second])
    asked: list[str] = []

    def edit(dialog: SettingsDialog) -> int:
        dialog._sources.select_row(0)
        dialog._sources.remove_selected()
        return SettingsDialog.DialogCode.Accepted

    def refuse(*args) -> QMessageBox.StandardButton:
        asked.append(args[2])
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(SettingsDialog, "exec", edit)
    monkeypatch.setattr(QMessageBox, "question", refuse)
    window.edit_project_settings(project.id)

    assert asked and str(first) in asked[0]
    assert [source.path for source in library.sources.list(project.id)] == [first, second]


def test_a_project_is_removed_from_the_start_screen_after_asking(
    window: MainWindow, library: Library, shoot, monkeypatch
) -> None:
    project, first, _second = shoot
    window.show_start_screen()
    answers = [QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Ok]
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: answers.pop(0))

    window._start_screen.remove_requested.emit(project.id)
    assert library.projects.get(project.id) is not None

    window._start_screen.remove_requested.emit(project.id)
    assert library.projects.get(project.id) is None
    assert first.joinpath("a.jpg").is_file(), "photos stay on disk"
    assert window._start_screen._list.count() == 0


def test_the_start_screen_buttons_and_delete_key_name_the_selected_project(
    window: MainWindow, shoot
) -> None:
    project, _first, _second = shoot
    window.show_start_screen()
    screen = window._start_screen
    seen: list[tuple[str, int]] = []
    screen.settings_requested.disconnect()
    screen.remove_requested.disconnect()
    screen.settings_requested.connect(lambda project_id: seen.append(("settings", project_id)))
    screen.remove_requested.connect(lambda project_id: seen.append(("remove", project_id)))

    screen._settings_button.click()
    screen._remove_button.click()
    screen.keyPressEvent(
        QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
    )

    assert seen == [("settings", project.id), ("remove", project.id), ("remove", project.id)]


def test_the_open_project_reopens_after_its_settings_change(
    window: MainWindow, library: Library, shoot, monkeypatch
) -> None:
    project, _first, _second = shoot
    window._on_project_opened(library.open_project(project.id))
    opened: list[int] = []
    monkeypatch.setattr(window, "_start_open", opened.append)
    monkeypatch.setattr(SettingsDialog, "exec", lambda _dialog: SettingsDialog.DialogCode.Accepted)

    window.edit_settings()

    assert opened == [project.id]


def test_the_settings_menu_item_opens_the_settings_of_the_open_project(
    window: MainWindow, library: Library, shoot, monkeypatch
) -> None:
    project, _first, _second = shoot
    window._on_project_opened(library.open_project(project.id))
    shown: list[int] = []
    monkeypatch.setattr(window, "_start_open", lambda _project_id: None)

    def record(dialog: SettingsDialog) -> int:
        shown.append(len(dialog.source_paths))
        return SettingsDialog.DialogCode.Rejected

    monkeypatch.setattr(SettingsDialog, "exec", record)
    action = next(action for action in window._actions if "Settings" in action.text())

    action.trigger()

    assert shown == [1], "the real menu action must reach the dialog"


def test_dropping_a_folder_takes_its_copies_out_of_the_destination(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    jpeg_factory(first / "IMG_0001.JPG", captured_at=datetime(2024, 1, 1, 9))
    jpeg_factory(second / "IMG_0001.JPG", captured_at=datetime(2024, 1, 1, 10))
    destination = tmp_path / "out"
    project = library.create_project("two", [first, second], destination, ProjectSettings())
    state = library.open_project(project.id)
    library.select(state, 0)
    assert library.copies_from(project.id, [state.sources[0].id]) == 1

    library.set_sources(project.id, [second])

    assert not (destination / "IMG_0001.JPG").exists()
    reopened = library.open_project(project.id)
    assert reopened.selections == {}, "the other folder's IMG_0001 must not inherit it"
    assert library.selections.list(project.id) == ()


def test_the_drop_confirmation_says_how_many_copies_go(
    window: MainWindow, library: Library, shoot, monkeypatch
) -> None:
    project, first, second = shoot
    library.set_sources(project.id, [first, second])
    state = library.open_project(project.id)
    library.select(state, 0)
    asked: list[str] = []

    def edit(dialog: SettingsDialog) -> int:
        dialog._sources.select_row(0)
        dialog._sources.remove_selected()
        return SettingsDialog.DialogCode.Accepted

    def refuse(*args) -> QMessageBox.StandardButton:
        asked.append(args[2])
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(SettingsDialog, "exec", edit)
    monkeypatch.setattr(QMessageBox, "question", refuse)
    window.edit_project_settings(project.id)

    assert "1" in asked[0].split(str(first))[1]
    assert (first.parent / "out" / "a.jpg").is_file(), "cancel leaves the copy alone"


def test_the_same_folder_is_never_added_twice(
    app: QApplication, tmp_path: Path, library: Library, jpeg_factory
) -> None:
    from fotozeef.ui.project_fields import SourceList

    folder = tmp_path / "cam"
    jpeg_factory(folder / "a.jpg")
    sources = SourceList()
    assert sources.add(folder)
    assert not sources.add(f"{folder}/")
    assert not sources.add(str(folder) + "/.")
    assert sources.paths == (folder,)

    project = library.create_project("once", [folder, Path(f"{folder}/")], None, ProjectSettings())
    assert len(library.sources.list(project.id)) == 1
    assert len(library.open_project(project.id).entries) == 1
