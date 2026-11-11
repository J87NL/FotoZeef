from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from fotozeef.core.db import SCHEMA_VERSION, Database
from fotozeef.core.library import Library, clocks
from fotozeef.core.models import ProjectSettings, camera_key


def _photo(path: Path, camera: str | None, at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (64, 48), (120, 80, 40))
    exif = image.getexif()
    exif[36867] = at.strftime("%Y:%m:%d %H:%M:%S")
    if camera is not None:
        exif[272] = camera
    image.save(path, format="JPEG", exif=exif)


@pytest.fixture
def two_cameras_in_one_folder(tmp_path: Path, library: Library):
    """One source folder with a subfolder per camera, the layout that hid the second camera."""
    shoot = tmp_path / "wedding"
    _photo(shoot / "canon" / "c1.jpg", "Canon EOS R6", datetime(2024, 6, 1, 14, 0, 0))
    _photo(shoot / "canon" / "c2.jpg", "Canon EOS R6", datetime(2024, 6, 1, 14, 10, 0))
    _photo(shoot / "sony" / "s1.jpg", "ILCE-7M3", datetime(2024, 6, 1, 13, 5, 0))
    project = library.create_project("wedding", [shoot], tmp_path / "out", ProjectSettings())
    return library.open_project(project.id)


def _names(state) -> list[str]:
    return [entry.photo.relative_path for entry in state.entries]


def test_each_photo_names_its_own_camera(two_cameras_in_one_folder) -> None:
    labels = {
        entry.photo.filename: entry.camera_label for entry in two_cameras_in_one_folder.entries
    }

    assert labels == {"c1.jpg": "Canon EOS R6", "c2.jpg": "Canon EOS R6", "s1.jpg": "ILCE-7M3"}


def test_a_photo_without_a_camera_falls_back_to_the_folder_label(
    tmp_path: Path, library: Library
) -> None:
    _photo(tmp_path / "scans" / "a.jpg", None, datetime(2024, 1, 1, 9))
    project = library.create_project("scans", [tmp_path / "scans"], None, ProjectSettings())
    state = library.open_project(project.id)

    assert state.entries[0].camera_label == "scans"


def test_every_camera_in_a_folder_is_its_own_clock(two_cameras_in_one_folder) -> None:
    state = two_cameras_in_one_folder

    found = clocks(state.entries, state.sources)

    assert [(clock.camera, clock.photos) for clock in found] == [
        ("Canon EOS R6", 2),
        ("ILCE-7M3", 1),
    ]


def test_one_camera_in_a_folder_can_be_shifted_alone(
    two_cameras_in_one_folder, library: Library
) -> None:
    state = two_cameras_in_one_folder
    assert _names(state) == ["sony/s1.jpg", "canon/c1.jpg", "canon/c2.jpg"]

    library.set_offset(state, state.sources[0].id, 3600, camera="ILCE-7M3")

    assert _names(state) == ["canon/c1.jpg", "sony/s1.jpg", "canon/c2.jpg"]
    canon = [entry for entry in state.entries if entry.photo.camera == "Canon EOS R6"]
    assert [entry.effective_at for entry in canon] == [
        datetime(2024, 6, 1, 14, 0, 0),
        datetime(2024, 6, 1, 14, 10, 0),
    ]


def test_a_camera_offset_survives_reopening(two_cameras_in_one_folder, library: Library) -> None:
    state = two_cameras_in_one_folder
    library.set_offset(state, state.sources[0].id, 3600, camera="ILCE-7M3")

    reopened = library.open_project(state.project.id)

    assert _names(reopened) == ["canon/c1.jpg", "sony/s1.jpg", "canon/c2.jpg"]
    assert reopened.sources[0].offset_for("ILCE-7M3") == 3600
    assert reopened.sources[0].offset_for("Canon EOS R6") == 0


def test_a_folder_offset_still_applies_to_cameras_without_their_own(
    two_cameras_in_one_folder, library: Library
) -> None:
    state = two_cameras_in_one_folder
    source_id = state.sources[0].id
    library.set_offset(state, source_id, -600)
    library.set_offset(state, source_id, 0, camera="Canon EOS R6")

    source = library.open_project(state.project.id).sources[0]

    assert source.offset_for("Canon EOS R6") == 0
    assert source.offset_for("ILCE-7M3") == -600
    assert source.offset_for(None) == -600


def test_camera_keys_ignore_surrounding_space() -> None:
    assert camera_key("  Canon EOS R6 ") == "Canon EOS R6"
    assert camera_key(None) == ""


def test_a_version_2_database_keeps_its_folder_offsets(tmp_path: Path) -> None:
    from fotozeef.core import db as db_module

    path = tmp_path / "old.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(db_module._SCHEMA)
    connection.executescript(db_module._MIGRATIONS[2])
    connection.execute(
        "INSERT INTO projects (name, destination, created_at, opened_at)"
        " VALUES ('old', '/x', '2024-01-01T00:00:00+00:00', '2024-01-01T00:00:00+00:00')"
    )
    connection.execute(
        "INSERT INTO sources (project_id, path, label, time_offset_s, sort_order)"
        " VALUES (1, '/photos', 'R6', 120, 0)"
    )
    connection.execute("PRAGMA user_version = 2")
    connection.commit()
    connection.close()

    library = Library(Database(path))

    source = library.sources.list(1)[0]
    assert source.offset_for("Canon EOS R6") == 120
    library.sources.set_camera_offset(source.id, "Canon EOS R6", 30)
    assert library.sources.list(1)[0].offset_for("Canon EOS R6") == 30
    version = library._db.connection.execute("PRAGMA user_version").fetchone()[0]
    assert version == SCHEMA_VERSION
    library.close()


def test_removing_a_folder_drops_its_camera_offsets(
    two_cameras_in_one_folder, library: Library
) -> None:
    state = two_cameras_in_one_folder
    source_id = state.sources[0].id
    library.set_offset(state, source_id, 60, camera="ILCE-7M3")

    library.sources.remove(source_id)

    rows = library._db.connection.execute(
        "SELECT COUNT(*) FROM camera_offsets WHERE source_id = ?", (source_id,)
    ).fetchone()[0]
    assert rows == 0


# --- the offsets dialog -----------------------------------------------------------------


def test_the_offsets_dialog_lists_every_camera(app, two_cameras_in_one_folder) -> None:
    from fotozeef.ui.offset_dialog import OffsetDialog

    state = two_cameras_in_one_folder
    dialog = OffsetDialog(clocks(state.entries, state.sources))
    source_id = state.sources[0].id

    assert set(dialog.offsets()) == {(source_id, "Canon EOS R6"), (source_id, "ILCE-7M3")}

    dialog._spins[(source_id, "ILCE-7M3")].setValue(90)
    assert dialog.changed_offsets() == {(source_id, "ILCE-7M3"): 90}
    dialog.close()


def test_calibration_works_between_two_cameras_of_one_folder(
    app, two_cameras_in_one_folder
) -> None:
    from PySide6.QtWidgets import QPushButton

    from fotozeef.ui.offset_dialog import OffsetDialog

    state = two_cameras_in_one_folder
    canon = next(entry for entry in state.entries if entry.photo.filename == "c1.jpg")
    sony = next(entry for entry in state.entries if entry.photo.filename == "s1.jpg")
    dialog = OffsetDialog(clocks(state.entries, state.sources), reference=canon, target=sony)

    buttons = [button for button in dialog.findChildren(QPushButton) if "ILCE-7M3" in button.text()]
    assert len(buttons) == 1
    buttons[0].click()

    assert dialog.changed_offsets() == {(state.sources[0].id, "ILCE-7M3"): 3300}
    dialog.close()


def test_the_main_window_applies_a_camera_offset(
    app, tmp_path: Path, library: Library, two_cameras_in_one_folder, monkeypatch
) -> None:
    from fotozeef.core.thumbnails import ThumbnailCache
    from fotozeef.ui.main_window import MainWindow
    from fotozeef.ui.offset_dialog import OffsetDialog

    state = two_cameras_in_one_folder
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    window._on_project_opened(state)
    source_id = state.sources[0].id

    def accept(dialog: OffsetDialog) -> int:
        dialog._spins[(source_id, "ILCE-7M3")].setValue(3600)
        return OffsetDialog.DialogCode.Accepted

    monkeypatch.setattr(OffsetDialog, "exec", accept)
    window.edit_offsets()

    assert _names(window._state) == ["canon/c1.jpg", "sony/s1.jpg", "canon/c2.jpg"]
    window.close()


def test_the_viewer_caption_names_the_photos_camera(app, two_cameras_in_one_folder) -> None:
    from fotozeef.ui.viewer import Viewer

    viewer = Viewer()
    sony = next(
        entry for entry in two_cameras_in_one_folder.entries if entry.photo.camera == "ILCE-7M3"
    )

    assert viewer._detail_text(sony).startswith("ILCE-7M3")


def test_the_time_reference_follows_a_new_offset(
    app, tmp_path: Path, library: Library, two_cameras_in_one_folder, monkeypatch
) -> None:
    from fotozeef.core.thumbnails import ThumbnailCache
    from fotozeef.ui.main_window import MainWindow
    from fotozeef.ui.offset_dialog import OffsetDialog

    state = two_cameras_in_one_folder
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    window._on_project_opened(state)
    window.go_to(
        window._state.index_of(
            next(e.photo.id for e in state.entries if e.photo.filename == "s1.jpg")
        )
    )
    window.set_time_reference()
    source_id = state.sources[0].id

    def shift_sony(dialog: OffsetDialog) -> int:
        dialog._spins[(source_id, "ILCE-7M3")].setValue(3600)
        return OffsetDialog.DialogCode.Accepted

    monkeypatch.setattr(OffsetDialog, "exec", shift_sony)
    window.edit_offsets()

    assert window._reference.effective_at == datetime(2024, 6, 1, 14, 5, 0)
    window.close()


def test_a_name_clash_is_prefixed_with_the_photos_own_camera(
    tmp_path: Path, library: Library
) -> None:
    shoot = tmp_path / "shoot"
    _photo(shoot / "canon" / "IMG_0001.JPG", "Canon EOS R6", datetime(2024, 6, 1, 14, 0))
    _photo(shoot / "canon" / "IMG_0002.JPG", "Canon EOS R6", datetime(2024, 6, 1, 14, 1))
    _photo(shoot / "sony" / "IMG_0001.JPG", "ILCE-7M3", datetime(2024, 6, 1, 14, 2))
    destination = tmp_path / "out"
    project = library.create_project("clash", [shoot], destination, ProjectSettings())
    state = library.open_project(project.id)

    for index in range(len(state.entries)):
        if state.entries[index].photo.filename == "IMG_0001.JPG":
            library.select(state, index)

    assert sorted(path.name for path in destination.iterdir()) == [
        "ILCE-7M3_IMG_0001.JPG",
        "IMG_0001.JPG",
    ]
