from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from fotozeef.core.library import Library
from fotozeef.core.models import ProjectSettings
from fotozeef.core.selection import (
    DestinationWriter,
    SelectionError,
    reconcile,
    reserved_names,
)


def _open(library: Library, sources: list[Path], destination: Path, **kwargs) -> object:
    settings = ProjectSettings(**kwargs)
    project = library.create_project("shoot", sources, destination, settings)
    return library.open_project(project.id)


def test_select_copies_into_destination(tmp_path: Path, library: Library, jpeg_factory) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "IMG_0001.JPG", captured_at=datetime(2024, 1, 1, 10, 0, 0))
    destination = tmp_path / "out"

    state = _open(library, [source], destination)
    library.select(state, 0)

    assert (destination / "IMG_0001.JPG").is_file()
    assert (source / "IMG_0001.JPG").is_file()
    assert state.selections[state.entries[0].photo.id].written_name == "IMG_0001.JPG"


def test_deselect_removes_only_files_written_by_app(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "IMG_0001.JPG")
    destination = tmp_path / "out"

    state = _open(library, [source], destination)
    library.select(state, 0)
    library.deselect(state, 0)

    assert not (destination / "IMG_0001.JPG").exists()
    assert state.selections == {}


def test_deselect_refuses_foreign_files(tmp_path: Path, library: Library, jpeg_factory) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "IMG_0001.JPG")
    destination = tmp_path / "out"
    destination.mkdir()
    jpeg_factory(destination / "IMG_0001.JPG")

    state = _open(library, [source], destination)

    assert state.selections
    with pytest.raises(SelectionError):
        library.deselect(state, 0)
    assert (destination / "IMG_0001.JPG").is_file()


def test_colliding_names_get_the_source_label(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    first = tmp_path / "cam-a"
    second = tmp_path / "cam-b"
    jpeg_factory(first / "IMG_1234.JPG", captured_at=datetime(2024, 1, 1, 10, 0, 0))
    jpeg_factory(second / "IMG_1234.JPG", captured_at=datetime(2024, 1, 1, 10, 0, 1))
    destination = tmp_path / "out"

    state = _open(library, [first, second], destination)
    library.select(state, 0)
    library.select(state, 1)

    written = [state.selections[entry.photo.id].written_name for entry in state.entries[:2]]
    assert written[0] == "IMG_1234.JPG"
    assert written[1].endswith("_IMG_1234.JPG")
    assert all((destination / name).is_file() for name in written)


def test_collisions_are_case_insensitive(tmp_path: Path, library: Library, jpeg_factory) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "a" / "IMG_1.JPG", captured_at=datetime(2024, 1, 1, 10, 0, 0))
    jpeg_factory(source / "b" / "img_1.jpg", captured_at=datetime(2024, 1, 1, 10, 0, 1))
    destination = tmp_path / "out"

    state = _open(library, [source], destination)
    library.select(state, 0)
    library.select(state, 1)

    names = {item.written_name.casefold() for item in state.selections.values()}
    assert len(names) == 2


def test_raw_companion_is_copied_when_enabled(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "IMG_0001.JPG")
    (source / "IMG_0001.CR2").write_bytes(b"raw")
    destination = tmp_path / "out"

    state = _open(library, [source], destination)
    library.select(state, 0)

    assert (destination / "IMG_0001.JPG").is_file()
    assert (destination / "IMG_0001.CR2").is_file()


def test_raw_companion_is_skipped_when_disabled(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "IMG_0001.JPG")
    (source / "IMG_0001.CR2").write_bytes(b"raw")
    destination = tmp_path / "out"

    state = _open(library, [source], destination, copy_raw_sidecar=False)
    library.select(state, 0)

    assert (destination / "IMG_0001.JPG").is_file()
    assert not (destination / "IMG_0001.CR2").exists()


def test_reconcile_drops_selections_deleted_outside_the_app(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "IMG_0001.JPG")
    destination = tmp_path / "out"

    state = _open(library, [source], destination)
    library.select(state, 0)
    (destination / "IMG_0001.JPG").unlink()

    reopened = library.open_project(state.project.id)

    assert reopened.selections == {}


def test_reconcile_adopts_unknown_destination_files(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "IMG_0001.JPG")
    destination = tmp_path / "out"
    destination.mkdir()

    state = _open(library, [source], destination)
    assert state.selections == {}

    jpeg_factory(destination / "IMG_0001.JPG")
    reopened = library.open_project(state.project.id)

    photo_id = reopened.entries[0].photo.id
    assert photo_id in reopened.selections
    assert reopened.selections[photo_id].written_by_app is False


def test_reserved_names_are_case_folded(tmp_path: Path, library: Library, jpeg_factory) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "IMG_0001.JPG")
    destination = tmp_path / "out"

    state = _open(library, [source], destination)
    library.select(state, 0)

    assert "img_0001.jpg" in reserved_names(state.selections.values())


def test_reconcile_is_stable_when_nothing_changed(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "IMG_0001.JPG")
    destination = tmp_path / "out"

    state = _open(library, [source], destination)
    library.select(state, 0)

    result = reconcile(
        destination, state.entries, state.selections.values(), state.project.settings
    )

    assert not result.changed


def test_writer_creates_the_destination_folder(tmp_path: Path) -> None:
    writer = DestinationWriter(tmp_path / "out", ProjectSettings())
    writer.ensure_destination()

    assert (tmp_path / "out").is_dir()


def test_writer_creates_a_typed_folder_that_does_not_exist_yet(tmp_path: Path) -> None:
    writer = DestinationWriter(tmp_path / "2026" / "trip" / "selectie", ProjectSettings())

    writer.ensure_destination()

    assert (tmp_path / "2026" / "trip" / "selectie").is_dir()


def test_writer_never_builds_a_path_on_a_missing_disk(tmp_path: Path, monkeypatch) -> None:
    """An unplugged USB disk's mount point must not get a folder tree on the internal disk."""
    from fotozeef.core import selection
    from fotozeef.core.selection import SelectionError

    monkeypatch.setattr(selection, "volume_missing", lambda path: "usb" in str(path))
    writer = DestinationWriter(tmp_path / "usb" / "Vakantie" / "selectie", ProjectSettings())

    with pytest.raises(SelectionError):
        writer.ensure_destination()
    assert not (tmp_path / "usb").exists()
