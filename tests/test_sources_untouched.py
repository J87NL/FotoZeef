from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from fotozeef.core.library import Library
from fotozeef.core.models import ProjectSettings


def _fingerprint(root: Path) -> dict[str, tuple[int, str]]:
    prints: dict[str, tuple[int, str]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        payload = path.read_bytes()
        prints[path.relative_to(root).as_posix()] = (
            path.stat().st_size,
            hashlib.sha256(payload).hexdigest(),
        )
    return prints


def _shoot(root: Path, jpeg_factory) -> Path:
    source = root / "cam"
    for index in range(4):
        jpeg_factory(source / f"IMG_{index:04d}.JPG", captured_at=datetime(2024, 1, 1, 9, index))
    (source / "IMG_0000.CR2").write_bytes(b"raw payload")
    return source


def test_selecting_and_deselecting_never_touches_the_source_folder(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = _shoot(tmp_path, jpeg_factory)
    before = _fingerprint(source)
    project = library.create_project("shoot", [source], tmp_path / "out", ProjectSettings())
    state = library.open_project(project.id)

    for index in range(len(state.entries)):
        library.select(state, index)
    for index in range(len(state.entries)):
        library.deselect(state, index)

    assert _fingerprint(source) == before


def test_the_destination_is_a_copy_not_a_move(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = _shoot(tmp_path, jpeg_factory)
    destination = tmp_path / "out"
    project = library.create_project("shoot", [source], destination, ProjectSettings())
    state = library.open_project(project.id)

    library.select(state, 0)

    entry = state.entries[0]
    original = entry.absolute_path
    copied = destination / state.selections[entry.photo.id].written_name
    assert original.is_file()
    assert copied.read_bytes() == original.read_bytes()
    assert copied.resolve() != original.resolve()
    assert copied.stat().st_ino != original.stat().st_ino
    assert not copied.is_symlink()


def test_a_default_destination_inside_a_source_stays_out_of_the_timeline(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = _shoot(tmp_path, jpeg_factory)
    project = library.create_project("shoot", [source], None, ProjectSettings())
    state = library.open_project(project.id)
    original_count = len(state.entries)

    library.select(state, 0)
    reopened = library.open_project(project.id)

    assert len(reopened.entries) == original_count


def test_xmp_is_the_only_thing_that_may_write_into_a_source(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = _shoot(tmp_path, jpeg_factory)
    before = set(_fingerprint(source))
    settings = ProjectSettings(write_xmp=True)
    project = library.create_project("shoot", [source], tmp_path / "out", settings)
    state = library.open_project(project.id)

    library.select(state, 0)
    added = set(_fingerprint(source)) - before
    assert all(name.endswith(".xmp") for name in added)

    library.deselect(state, 0)
    assert set(_fingerprint(source)) == before
