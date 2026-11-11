from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath

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


def test_deselecting_keeps_a_raw_owned_by_another_selected_photo(tmp_path: Path) -> None:
    """Same size, so only the owner check keeps another photo's RAW."""
    from datetime import UTC

    from fotozeef.core.models import (
        CaptureSource,
        Photo,
        Selection,
        Source,
        TimelineEntry,
    )
    from fotozeef.core.selection import DestinationWriter

    folder = tmp_path / "x"
    folder.mkdir()
    (folder / "IMG_1.JPG").write_bytes(b"j" * 10)
    (folder / "IMG_1.CR2").write_bytes(b"x" * 400)
    destination = tmp_path / "out"
    destination.mkdir()
    (destination / "IMG_1.JPG").write_bytes(b"j" * 10)
    (destination / "IMG_1.CR2").write_bytes(b"z" * 400)
    source = Source(1, 1, folder, "x", 0, 0)
    photo = Photo(
        7,
        1,
        "IMG_1.JPG",
        10,
        0.0,
        None,
        CaptureSource.MTIME,
        1,
        None,
        "IMG_1",
        companions=("IMG_1.CR2",),
    )
    entry = TimelineEntry(photo, source, datetime(2024, 1, 1))
    record = Selection(7, 1, "IMG_1.JPG", True, datetime(2024, 1, 1, tzinfo=UTC))

    DestinationWriter(destination, ProjectSettings()).deselect(entry, record, {"img_1.cr2": 99})

    assert not (destination / "IMG_1.JPG").exists()
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


def test_unselecting_waits_for_the_originals_disk_too(
    tmp_path: Path, library: Library, jpeg_factory, monkeypatch
) -> None:
    """The copy is on the internal disk, the original on an unplugged USB disk."""
    from fotozeef.core.selection import DiskNotConnected

    disk = Disk(tmp_path / "usb", monkeypatch)
    jpeg_factory(disk.path / "Vakantie" / "a.jpg")
    destination = tmp_path / "selectie"
    project = library.create_project(
        "split", [disk.path / "Vakantie"], destination, ProjectSettings()
    )
    state = library.open_project(project.id)
    library.select(state, 0)
    disk.connected = False

    with pytest.raises(DiskNotConnected):
        library.deselect(state, 0)
    assert (destination / "a.jpg").is_file()


def test_an_empty_mount_folder_as_source_is_reported(
    tmp_path: Path, library: Library, jpeg_factory, monkeypatch
) -> None:
    """A disk mounted straight at /mnt/usb, unplugged: the empty folder stays."""
    disk = Disk(tmp_path / "usb", monkeypatch)
    jpeg_factory(disk.path / "a.jpg")
    project = library.create_project("root", [disk.path], tmp_path / "out", ProjectSettings())
    library.open_project(project.id)
    disk.unplug()

    state = library.open_project(project.id)

    assert state.scan.unreachable == [disk.path]


def test_a_disk_mounted_elsewhere_keeps_the_selection(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    """Mounted at /data/usb, outside the usual places: its parent folder vanishes."""
    from fotozeef.core.selection import DiskNotConnected

    local = tmp_path / "local"
    jpeg_factory(local / "a.jpg")
    jpeg_factory(local / "b.jpg")
    mount = tmp_path / "data" / "usb"
    destination = mount / "Vakantie" / "selectie"
    project = library.create_project("elsewhere", [local], destination, ProjectSettings())
    state = library.open_project(project.id)
    library.select(state, 0)
    shutil.move(mount, tmp_path / "away")
    mount.mkdir()

    state = library.open_project(project.id)

    assert len(state.selections) == 1
    assert state.scan.destination_unreachable
    with pytest.raises(DiskNotConnected):
        library.select(state, 1)
    assert list(mount.iterdir()) == []


def test_three_reopens_leave_one_notice(
    app: QApplication, tmp_path: Path, library: Library, usb
) -> None:
    project, disk = usb
    disk.unplug()
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    window.show()

    for _ in range(3):
        window._on_project_opened(library.open_project(project.id))
        app.processEvents()

    from PySide6.QtWidgets import QMessageBox

    visible = [box for box in window.findChildren(QMessageBox) if box.isVisible()]
    assert len(visible) == 1
    assert window._notice is visible[0]
    assert not window._notice.isModal()
    window.close()


def test_a_refused_unselect_explains_itself(
    app: QApplication, tmp_path: Path, library: Library, monkeypatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from fotozeef.core.selection import DiskNotConnected

    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: shown.append(args[2]))

    window._on_selection_failed(1, False, DiskNotConnected(Path("/media/jo/USB/selectie")))

    assert shown and "/media/jo/USB/selectie" in shown[0]
    window.close()


# --- telling a disk that is not there from an ordinary folder -------------------------


@pytest.fixture
def mounts(tmp_path: Path):
    """A fake / with media, mnt and a user, where nothing is ever mounted."""
    root = tmp_path / "root"
    trees = tuple(PurePosixPath(root, *tree[1:]).parts for tree in (("/", "media"), ("/", "mnt")))
    (root / "media" / "jo").mkdir(parents=True)
    (root / "mnt").mkdir(parents=True)

    def missing(path: Path) -> bool:
        from fotozeef.core.fs import volume_missing

        return volume_missing(
            path, platform="linux", ismount=lambda _p: False, user="jo", trees=trees
        )

    return root, missing


def test_an_ordinary_folder_under_mnt_is_there(mounts) -> None:
    root, missing = mounts
    photos = root / "mnt" / "photos"
    photos.mkdir()
    (photos / "a.jpg").write_bytes(b"x")

    assert not missing(photos)
    assert not missing(photos / "a.jpg")
    assert not missing(photos / "selectie" / "new")


def test_a_symlinked_folder_under_mnt_is_there(mounts, tmp_path: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("symlinks need admin rights on Windows")
    root, missing = mounts
    target = tmp_path / "srv"
    target.mkdir()
    (target / "a.jpg").write_bytes(b"x")
    os.symlink(target, root / "mnt" / "photos")

    assert not missing(root / "mnt" / "photos" / "a.jpg")


def test_an_empty_mount_folder_is_a_disk_that_is_not_there(mounts) -> None:
    root, missing = mounts
    (root / "mnt" / "usb").mkdir()

    assert missing(root / "mnt" / "usb")
    assert missing(root / "mnt" / "usb" / "Vakantie" / "selectie")


def test_a_vanished_udisks_folder_is_a_disk_that_is_not_there(mounts) -> None:
    root, missing = mounts

    assert missing(root / "media" / "jo" / "USB" / "Vakantie")
    assert missing(root / "mnt" / "gone" / "x")


def test_another_folder_in_media_is_there(mounts) -> None:
    root, missing = mounts
    archive = root / "media" / "archive"
    archive.mkdir()
    (archive / "2019").mkdir()

    assert not missing(archive / "2019")


def test_an_empty_selection_folder_on_an_ordinary_folder_is_there(mounts) -> None:
    """Everything unselected leaves the selection folder empty; it is still there."""
    root, missing = mounts
    photos = root / "mnt" / "photos"
    (photos / "selectie").mkdir(parents=True)
    (photos / "a.jpg").write_bytes(b"x")

    assert not missing(photos / "selectie")


def test_a_photos_own_raw_left_behind_keeps_its_plain_name(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    shoot = tmp_path / "cam"
    jpeg_factory(shoot / "IMG_1.JPG")
    (shoot / "IMG_1.CR2").write_bytes(b"raw" * 100)
    destination = tmp_path / "out"
    destination.mkdir()
    shutil.copyfile(shoot / "IMG_1.CR2", destination / "IMG_1.CR2")
    project = library.create_project("again", [shoot], destination, ProjectSettings())
    state = library.open_project(project.id)

    record = library.select(state, 0)

    assert record.written_name == "IMG_1.JPG"
    assert sorted(path.name for path in destination.iterdir()) == ["IMG_1.CR2", "IMG_1.JPG"]
