from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fotozeef.core.library import DEFAULT_DESTINATION_NAME, Library
from fotozeef.core.models import ProjectSettings


def test_default_destination_lives_under_the_first_source(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "a.jpg")

    project = library.create_project("shoot", [source], None, ProjectSettings())

    assert project.destination == source / DEFAULT_DESTINATION_NAME


def test_reopening_picks_up_new_files_in_order(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "late.jpg", captured_at=datetime(2024, 1, 1, 12, 0, 0))
    project = library.create_project("shoot", [source], tmp_path / "out", ProjectSettings())
    library.open_project(project.id)

    jpeg_factory(source / "early.jpg", captured_at=datetime(2024, 1, 1, 9, 0, 0))
    state = library.open_project(project.id)

    assert [entry.photo.relative_path for entry in state.entries] == ["early.jpg", "late.jpg"]
    assert state.scan.added == 1


def test_vanished_files_are_marked_missing_not_deleted(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "a.jpg", captured_at=datetime(2024, 1, 1, 9, 0, 0))
    jpeg_factory(source / "b.jpg", captured_at=datetime(2024, 1, 1, 10, 0, 0))
    project = library.create_project("shoot", [source], tmp_path / "out", ProjectSettings())
    library.open_project(project.id)

    (source / "b.jpg").unlink()
    state = library.open_project(project.id)

    assert len(state.entries) == 2
    assert [entry.photo.missing for entry in state.entries] == [False, True]


def test_cursor_is_restored_on_reopen(tmp_path: Path, library: Library, jpeg_factory) -> None:
    source = tmp_path / "cam"
    for index in range(4):
        jpeg_factory(source / f"{index}.jpg", captured_at=datetime(2024, 1, 1, 9, index, 0))
    project = library.create_project("shoot", [source], tmp_path / "out", ProjectSettings())
    state = library.open_project(project.id)

    library.set_cursor(state, 2)
    reopened = library.open_project(project.id)

    assert reopened.cursor == 2
    assert reopened.current is not None
    assert reopened.current.photo.relative_path == "2.jpg"


def test_cursor_falls_back_to_nearest_surviving_photo(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = tmp_path / "cam"
    for index in range(4):
        jpeg_factory(source / f"{index}.jpg", captured_at=datetime(2024, 1, 1, 9, index, 0))
    project = library.create_project("shoot", [source], tmp_path / "out", ProjectSettings())
    state = library.open_project(project.id)
    library.set_cursor(state, 3)

    (source / "3.jpg").unlink()
    reopened = library.open_project(project.id)

    assert reopened.current is not None
    assert reopened.current.photo.relative_path == "2.jpg"


def test_source_label_falls_back_to_camera(tmp_path: Path, library: Library, jpeg_factory) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "a.jpg", captured_at=datetime(2024, 1, 1, 9, 0, 0))
    project = library.create_project("shoot", [source], tmp_path / "out", ProjectSettings())

    state = library.open_project(project.id)

    assert state.sources[0].label == "Canon EOS R6"


def test_user_label_survives_a_rescan(tmp_path: Path, library: Library, jpeg_factory) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "a.jpg", captured_at=datetime(2024, 1, 1, 9, 0, 0))
    project = library.create_project("shoot", [source], tmp_path / "out", ProjectSettings())
    state = library.open_project(project.id)
    library.sources.set_label(state.sources[0].id, "Tweede body")

    reopened = library.open_project(project.id)

    assert reopened.sources[0].label == "Tweede body"


def test_offset_change_resorts_without_rescanning(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    jpeg_factory(first / "a.jpg", captured_at=datetime(2024, 1, 1, 12, 0, 0))
    jpeg_factory(second / "b.jpg", captured_at=datetime(2024, 1, 1, 11, 30, 0))
    project = library.create_project("shoot", [first, second], tmp_path / "out", ProjectSettings())
    state = library.open_project(project.id)
    assert [entry.photo.relative_path for entry in state.entries] == ["b.jpg", "a.jpg"]

    second_source = next(item for item in state.sources if item.path == second)
    library.set_offset(state, second_source.id, 3600)

    assert [entry.photo.relative_path for entry in state.entries] == ["a.jpg", "b.jpg"]


def test_metadata_is_not_reread_when_the_file_is_unchanged(
    tmp_path: Path, library: Library, jpeg_factory, monkeypatch
) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "a.jpg", captured_at=datetime(2024, 1, 1, 9, 0, 0))
    project = library.create_project("shoot", [source], tmp_path / "out", ProjectSettings())
    library.open_project(project.id)

    calls = []
    original = library._draft

    def spy(group, known):
        calls.append(known)
        return original(group, known)

    monkeypatch.setattr(library, "_draft", spy)
    state = library.open_project(project.id)

    assert calls and calls[0] is not None
    assert state.entries[0].photo.captured_at == datetime(2024, 1, 1, 9, 0, 0)
