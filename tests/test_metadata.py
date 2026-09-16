from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fotozeef.core.metadata import read_metadata
from fotozeef.core.models import CaptureSource


def test_reads_exif_capture_time_and_camera(tmp_path: Path, jpeg_factory) -> None:
    moment = datetime(2024, 5, 4, 13, 45, 12)
    path = jpeg_factory(tmp_path / "shot.jpg", captured_at=moment)

    meta = read_metadata(path)

    assert meta.captured_at == moment
    assert meta.capture_source is CaptureSource.EXIF
    assert meta.camera == "Canon EOS R6"


def test_falls_back_to_mtime(tmp_path: Path, jpeg_factory) -> None:
    path = jpeg_factory(tmp_path / "shot.jpg")

    meta = read_metadata(path, mtime=1_700_000_000.0)

    assert meta.capture_source is CaptureSource.MTIME
    assert meta.captured_at == datetime.fromtimestamp(1_700_000_000.0)


def test_unreadable_file_still_yields_metadata(tmp_path: Path) -> None:
    path = tmp_path / "broken.jpg"
    path.write_bytes(b"not an image")

    meta = read_metadata(path, mtime=10.0)

    assert meta.capture_source is CaptureSource.MTIME
    assert meta.orientation == 1
