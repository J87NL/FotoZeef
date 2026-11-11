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


class Disk:
    """A USB disk mounted at `path`. Unplugged, its mount folder stays behind, empty."""

    def __init__(self, path: Path, monkeypatch) -> None:
        self.path = path
        self._away = path.parent / "unplugged"
        self.connected = True
        from fotozeef.core import fs, library, selection

        def missing(target) -> bool:
            inside = Path(target) == self.path or self.path in Path(target).parents
            return inside and not self.connected

        for module in (fs, library, selection):
            monkeypatch.setattr(module, "volume_missing", missing)

    def unplug(self) -> None:
        shutil.move(self.path, self._away)
        self.path.mkdir()
        self.connected = False

    def plug_in(self) -> None:
        self.path.rmdir()
        shutil.move(self._away, self.path)
        self.connected = True


@pytest.fixture
def usb(tmp_path: Path, library: Library, jpeg_factory, monkeypatch):
    """Photos on a USB disk, with the default selection folder on that same disk."""
    disk = Disk(tmp_path / "usb", monkeypatch)
    shoot = disk.path / "Vakantie"
    for index in range(3):
        jpeg_factory(shoot / f"{index}.jpg", captured_at=datetime(2024, 1, 1, 9, index))
    project = library.create_project("vakantie", [shoot], None, ProjectSettings())
    state = library.open_project(project.id)
    library.select(state, 0)
    library.select(state, 2)
    return project, disk


def test_unplugging_the_disk_keeps_the_selection(library: Library, usb) -> None:
    project, disk = usb
    disk.unplug()

    state = library.open_project(project.id)

    assert all(entry.photo.missing for entry in state.entries)
    assert len(state.selections) == 2
    assert state.scan.unreachable == [disk.path / "Vakantie"]
    assert state.scan.destination_unreachable


def test_plugging_it_back_in_restores_everything(library: Library, usb) -> None:
    project, disk = usb
    disk.unplug()
    library.open_project(project.id)
    disk.plug_in()

    state = library.open_project(project.id)

    assert not any(entry.photo.missing for entry in state.entries)
    assert all(record.written_by_app for record in state.selections.values())
    library.deselect(state, 0)
    assert not (disk.path / "Vakantie" / "selectie" / "0.jpg").exists()


def test_deselecting_while_unplugged_is_refused(library: Library, usb) -> None:
    from fotozeef.core.selection import SelectionError

    project, disk = usb
    disk.unplug()
    state = library.open_project(project.id)

    with pytest.raises(SelectionError):
        library.deselect(state, 0)

    disk.plug_in()
    state = library.open_project(project.id)
    assert all(record.written_by_app for record in state.selections.values())


def test_selecting_while_unplugged_never_creates_the_folder_elsewhere(
    tmp_path: Path, library: Library, jpeg_factory, monkeypatch
) -> None:
    from fotozeef.core.selection import SelectionError

    local = tmp_path / "local"
    jpeg_factory(local / "a.jpg")
    disk = Disk(tmp_path / "usb", monkeypatch)
    disk.path.mkdir()
    disk.connected = False
    project = library.create_project("local", [local], disk.path / "Selectie", ProjectSettings())
    state = library.open_project(project.id)

    with pytest.raises(SelectionError):
        library.select(state, 0)
    assert list(disk.path.iterdir()) == []


def test_the_window_says_which_folders_are_missing(
    app: QApplication, tmp_path: Path, library: Library, usb
) -> None:
    project, disk = usb
    disk.unplug()
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))

    window._on_project_opened(library.open_project(project.id))

    notice = window._notice
    assert notice is not None
    assert str(disk.path / "Vakantie") in notice.text()
    assert "kept" in notice.text()
    notice.close()
    window.close()


def test_no_notice_when_everything_is_there(
    app: QApplication, tmp_path: Path, library: Library, usb
) -> None:
    project, _disk = usb
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))

    window._on_project_opened(library.open_project(project.id))

    assert window._notice is None
    window.close()


def test_a_deleted_selection_folder_still_clears_the_selection(library: Library, usb) -> None:
    project, disk = usb
    shutil.rmtree(disk.path / "Vakantie" / "selectie")

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


def test_deselecting_keeps_a_raw_owned_by_another_selected_photo(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    """Same-sized RAWs: only the owner check can tell them apart."""
    kept = tmp_path / "z"
    dropped = tmp_path / "x"
    kept.mkdir()
    (kept / "IMG_1.CR2").write_bytes(b"z" * 400)
    jpeg_factory(dropped / "IMG_1.JPG")
    (dropped / "IMG_1.CR2").write_bytes(b"x" * 400)
    destination = tmp_path / "out"
    project = library.create_project("raw", [kept, dropped], destination, ProjectSettings())
    state = library.open_project(project.id)
    by_name = {entry.photo.relative_path: index for index, entry in enumerate(state.entries)}
    library.select(state, by_name["IMG_1.CR2"])
    library.select(state, by_name["IMG_1.JPG"])

    library.deselect(state, by_name["IMG_1.JPG"])

    assert (destination / "IMG_1.CR2").read_bytes() == b"z" * 400


def test_a_raw_that_is_already_there_is_never_overwritten(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    shoot = tmp_path / "b"
    jpeg_factory(shoot / "IMG_1.JPG")
    (shoot / "IMG_1.CR2").write_bytes(b"new raw")
    destination = tmp_path / "out"
    destination.mkdir()
    (destination / "IMG_1.CR2").write_bytes(b"the only copy of an older raw")
    project = library.create_project("raw", [shoot], destination, ProjectSettings())
    state = library.open_project(project.id)

    record = library.select(state, 0)

    assert (destination / "IMG_1.CR2").read_bytes() == b"the only copy of an older raw"
    assert record.written_name != "IMG_1.JPG"


def test_an_unchanged_copy_put_in_by_hand_counts_as_selected(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    shoot = tmp_path / "cam"
    original = jpeg_factory(shoot / "IMG_7.JPG")
    destination = tmp_path / "out"
    destination.mkdir()
    shutil.copyfile(original, destination / "IMG_7.JPG")
    project = library.create_project("hand", [shoot], destination, ProjectSettings())

    state = library.open_project(project.id)

    assert len(state.selections) == 1


@pytest.mark.parametrize(
    ("path", "platform", "mounted", "missing"),
    [
        ("/home/jo/Pictures/x", "linux", (), False),
        ("/media/jo/USB/Vakantie", "linux", (), True),
        ("/media/jo/USB/Vakantie", "linux", ("/media/jo/USB",), False),
        ("/run/media/jo/USB/x", "linux", (), True),
        ("/mnt/usb/selectie", "linux", (), True),
        ("/mnt/usb/selectie", "linux", ("/mnt/usb",), False),
        ("/Volumes/Fotos/2024", "darwin", (), True),
        ("/Volumes/Fotos/2024", "darwin", ("/Volumes/Fotos",), False),
        ("/media", "linux", (), False),
    ],
)
def test_a_disk_that_is_not_connected_is_recognised(
    path: str, platform: str, mounted: tuple[str, ...], missing: bool
) -> None:
    from fotozeef.core.fs import volume_missing

    assert volume_missing(path, platform=platform, ismount=mounted.__contains__) is missing


def test_a_missing_drive_letter_is_a_disk_that_is_not_connected() -> None:
    from fotozeef.core.fs import volume_missing

    assert volume_missing("E:\\Foto's", platform="win32", exists=lambda anchor: False)
    assert not volume_missing("C:\\Foto's", platform="win32", exists=lambda anchor: True)
