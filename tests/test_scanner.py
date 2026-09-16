from __future__ import annotations

from pathlib import Path

from fotozeef.core.scanner import scan


def test_scan_collects_supported_files_and_skips_video(tmp_path: Path, jpeg_factory) -> None:
    jpeg_factory(tmp_path / "a.jpg")
    jpeg_factory(tmp_path / "nested" / "b.jpg")
    (tmp_path / "clip.mp4").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("x")

    report = scan(tmp_path)

    assert [group.primary.relative_path for group in report.groups] == ["a.jpg", "nested/b.jpg"]
    assert report.skipped_videos == 1
    assert report.skipped_other == 1


def test_scan_respects_non_recursive(tmp_path: Path, jpeg_factory) -> None:
    jpeg_factory(tmp_path / "a.jpg")
    jpeg_factory(tmp_path / "nested" / "b.jpg")

    report = scan(tmp_path, recursive=False)

    assert [group.primary.relative_path for group in report.groups] == ["a.jpg"]


def test_raw_and_jpeg_pair_become_one_entry(tmp_path: Path, jpeg_factory) -> None:
    jpeg_factory(tmp_path / "IMG_0001.JPG")
    (tmp_path / "IMG_0001.CR2").write_bytes(b"raw")

    report = scan(tmp_path)

    assert len(report.groups) == 1
    group = report.groups[0]
    assert group.primary.relative_path == "IMG_0001.JPG"
    assert [item.relative_path for item in group.companions] == ["IMG_0001.CR2"]
    assert group.group_key == "img_0001"


def test_two_stills_with_the_same_stem_stay_separate(tmp_path: Path, jpeg_factory) -> None:
    jpeg_factory(tmp_path / "shot.jpg")
    jpeg_factory(tmp_path / "shot.png")

    report = scan(tmp_path)

    assert len(report.groups) == 2
    assert all(group.group_key is None for group in report.groups)


def test_scan_is_cancellable(tmp_path: Path, jpeg_factory) -> None:
    for index in range(5):
        jpeg_factory(tmp_path / f"{index}.jpg")

    report = scan(tmp_path, should_cancel=lambda: True)

    assert report.cancelled
    assert report.groups == []
