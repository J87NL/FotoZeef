from __future__ import annotations

import sys
from pathlib import Path

from fotozeef.core.fs import os_path
from fotozeef.core.library import Library
from fotozeef.core.models import ProjectSettings


def _deep_folder(root: Path) -> Path:
    folder = root
    for index in range(12):
        folder = folder / f"a-very-long-subfolder-name-number-{index:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def test_deeply_nested_sources_scan_and_copy(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = tmp_path / "cam"
    deep = _deep_folder(source)
    jpeg_factory(deep / "IMG_0001.JPG")
    assert len(str(deep)) > 260 - len(str(tmp_path))

    project = library.create_project("deep", [source], tmp_path / "out", ProjectSettings())
    state = library.open_project(project.id)

    assert len(state.entries) == 1
    library.select(state, 0)
    assert (state.project.destination / "IMG_0001.JPG").is_file()


def test_relative_paths_are_stored_posix_style(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "day01" / "IMG_0001.JPG")
    project = library.create_project("nested", [source], tmp_path / "out", ProjectSettings())

    state = library.open_project(project.id)

    assert state.entries[0].photo.relative_path == "day01/IMG_0001.JPG"
    assert state.entries[0].absolute_path.is_file()


def test_os_path_is_a_no_op_off_windows(tmp_path: Path) -> None:
    if sys.platform == "win32":
        long = _deep_folder(tmp_path) / "x.jpg"
        assert os_path(long).startswith("\\\\?\\")
        return
    assert os_path(tmp_path / "x.jpg") == str(tmp_path / "x.jpg")
