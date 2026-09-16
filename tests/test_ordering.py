from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fotozeef.core.models import CaptureSource, Photo, Source
from fotozeef.core.ordering import build_timeline, calibration_offset, nearest_index


def _source(source_id: int, offset: int = 0, order: int = 0) -> Source:
    return Source(
        id=source_id,
        project_id=1,
        path=Path(f"/tmp/src{source_id}"),
        label=f"src{source_id}",
        time_offset_s=offset,
        sort_order=order,
    )


def _photo(photo_id: int, source_id: int, captured_at: datetime, name: str = "a.jpg") -> Photo:
    return Photo(
        id=photo_id,
        source_id=source_id,
        relative_path=name,
        file_size=1,
        mtime=0.0,
        captured_at=captured_at,
        capture_source=CaptureSource.EXIF,
        orientation=1,
        camera=None,
        group_key=None,
    )


def test_timeline_merges_sources_chronologically() -> None:
    sources = [_source(1), _source(2, order=1)]
    photos = [
        _photo(1, 1, datetime(2024, 1, 1, 12, 0, 0)),
        _photo(2, 2, datetime(2024, 1, 1, 11, 0, 0)),
        _photo(3, 1, datetime(2024, 1, 1, 13, 0, 0)),
    ]

    timeline = build_timeline(photos, sources)

    assert [entry.photo.id for entry in timeline] == [2, 1, 3]


def test_time_offset_shifts_a_source() -> None:
    sources = [_source(1), _source(2, offset=3600, order=1)]
    photos = [
        _photo(1, 1, datetime(2024, 1, 1, 12, 0, 0)),
        _photo(2, 2, datetime(2024, 1, 1, 11, 30, 0)),
    ]

    timeline = build_timeline(photos, sources)

    assert [entry.photo.id for entry in timeline] == [1, 2]


def test_ties_break_on_source_order_then_path() -> None:
    sources = [_source(1, order=1), _source(2, order=0)]
    moment = datetime(2024, 1, 1, 12, 0, 0)
    photos = [
        _photo(1, 1, moment, name="b.jpg"),
        _photo(2, 2, moment, name="z.jpg"),
        _photo(3, 1, moment, name="a.jpg"),
    ]

    timeline = build_timeline(photos, sources)

    assert [entry.photo.id for entry in timeline] == [2, 3, 1]


def test_calibration_offset_aligns_two_cameras() -> None:
    sources = [_source(1), _source(2, order=1)]
    reference = _photo(1, 1, datetime(2024, 1, 1, 12, 0, 0))
    target = _photo(2, 2, datetime(2024, 1, 1, 11, 58, 0))
    timeline = build_timeline([reference, target], sources)
    by_id = {entry.photo.id: entry for entry in timeline}

    offset = calibration_offset(by_id[1], by_id[2])

    assert offset == 120


def test_nearest_index_picks_closest_moment() -> None:
    sources = [_source(1)]
    photos = [
        _photo(1, 1, datetime(2024, 1, 1, 12, 0, 0)),
        _photo(2, 1, datetime(2024, 1, 1, 12, 5, 0), name="b.jpg"),
        _photo(3, 1, datetime(2024, 1, 1, 12, 30, 0), name="c.jpg"),
    ]
    timeline = build_timeline(photos, sources)

    assert nearest_index(timeline, datetime(2024, 1, 1, 12, 4, 0)) == 1
