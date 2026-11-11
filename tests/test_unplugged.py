from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from fotozeef.core.library import Library, folder_key
from fotozeef.core.models import ProjectSettings
from fotozeef.core.thumbnails import ThumbnailCache
from fotozeef.ui.main_window import MainWindow


@pytest.fixture
def usb(tmp_path: Path, library: Library, jpeg_factory):
    """Photos on a USB disk, with the default selection folder on that same disk."""
    disk = tmp_path / "usb"
    shoot = disk / "Vakantie"
    for index in range(3):
        jpeg_factory(shoot / f"{index}.jpg", captured_at=datetime(2024, 1, 1, 9, index))
    project = library.create_project("vakantie", [shoot], None, ProjectSettings())
    state = library.open_project(project.id)
    library.select(state, 0)
    library.select(state, 2)
    return project, disk, tmp_path / "unplugged"


def test_unplugging_the_disk_keeps_the_selection(library: Library, usb) -> None:
    project, disk, away = usb
    shutil.move(disk, away)

    state = library.open_project(project.id)

    assert all(entry.photo.missing for entry in state.entries)
    assert len(state.selections) == 2
    assert state.scan.unreachable == [disk / "Vakantie"]
    assert state.scan.destination_unreachable


def test_plugging_it_back_in_restores_everything(library: Library, usb) -> None:
    project, disk, away = usb
    shutil.move(disk, away)
    library.open_project(project.id)
    shutil.move(away, disk)

    state = library.open_project(project.id)

    assert not any(entry.photo.missing for entry in state.entries)
    assert all(record.written_by_app for record in state.selections.values())
    library.deselect(state, 0)
    assert not (disk / "Vakantie" / "selectie" / "0.jpg").exists()


def test_selecting_while_unplugged_never_creates_the_folder_elsewhere(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    from fotozeef.core.selection import SelectionError

    local = tmp_path / "local"
    jpeg_factory(local / "a.jpg")
    destination = tmp_path / "usb" / "Selectie"
    project = library.create_project("local", [local], destination, ProjectSettings())
    state = library.open_project(project.id)

    with pytest.raises(SelectionError):
        library.select(state, 0)
    assert not (tmp_path / "usb").exists()


def test_the_window_says_which_folders_are_missing(
    app: QApplication, tmp_path: Path, library: Library, usb
) -> None:
    project, disk, away = usb
    shutil.move(disk, away)
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))

    window._on_project_opened(library.open_project(project.id))

    notice = window._notice
    assert notice is not None
    assert str(disk / "Vakantie") in notice.text()
    assert "kept" in notice.text()
    notice.close()
    window.close()


def test_no_notice_when_everything_is_there(
    app: QApplication, tmp_path: Path, library: Library, usb
) -> None:
    project, _disk, _away = usb
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))

    window._on_project_opened(library.open_project(project.id))

    assert window._notice is None
    window.close()


def test_a_deleted_selection_folder_still_clears_the_selection(library: Library, usb) -> None:
    project, disk, _away = usb
    shutil.rmtree(disk / "Vakantie" / "selectie")

    state = library.open_project(project.id)

    assert state.selections == {}
    assert not state.scan.destination_unreachable


def test_deselecting_leaves_another_folders_raw_alone(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    kept = tmp_path / "z"
    dropped = tmp_path / "x"
    kept.mkdir()
    (kept / "IMG_1.CR2").write_bytes(b"raw of z" * 50)
    jpeg_factory(dropped / "IMG_1.JPG")
    (dropped / "IMG_1.CR2").write_bytes(b"raw of x")
    destination = tmp_path / "out"
    project = library.create_project("raw", [kept, dropped], destination, ProjectSettings())
    state = library.open_project(project.id)
    by_name = {entry.photo.relative_path: index for index, entry in enumerate(state.entries)}
    library.select(state, by_name["IMG_1.CR2"])
    library.select(state, by_name["IMG_1.JPG"])

    library.deselect(state, by_name["IMG_1.JPG"])

    assert (destination / "IMG_1.CR2").read_bytes() == b"raw of z" * 50


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin rights on Windows")
def test_a_folder_reached_two_ways_is_one_folder(tmp_path: Path) -> None:
    folder = tmp_path / "Photos"
    folder.mkdir()
    link = tmp_path / "link"
    os.symlink(folder, link)

    assert folder_key(link) == folder_key(folder)
    assert folder_key(f"{folder}{os.sep}") == folder_key(folder)
    assert folder_key(tmp_path / "gone") == folder_key(tmp_path / "gone" / "x" / "..")
