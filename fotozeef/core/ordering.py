from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta

from fotozeef.core.models import Photo, Source, TimelineEntry

_EPOCH = datetime(1970, 1, 1)


def effective_time(photo: Photo, source: Source) -> datetime:
    base = photo.captured_at or _EPOCH
    return base + timedelta(seconds=source.time_offset_s)


def build_timeline(
    photos: Iterable[Photo],
    sources: Iterable[Source],
) -> tuple[TimelineEntry, ...]:
    by_id: Mapping[int, Source] = {source.id: source for source in sources}
    entries = []
    for photo in photos:
        source = by_id.get(photo.source_id)
        if source is None:
            continue
        entries.append(
            TimelineEntry(photo=photo, source=source, effective_at=effective_time(photo, source))
        )
    return tuple(sorted(entries, key=_sort_key))


def resort(
    entries: Iterable[TimelineEntry],
    sources: Iterable[Source],
) -> tuple[TimelineEntry, ...]:
    return build_timeline((entry.photo for entry in entries), sources)


def nearest_index(entries: Iterable[TimelineEntry], moment: datetime) -> int:
    best_index = 0
    best_delta: timedelta | None = None
    for index, entry in enumerate(entries):
        delta = abs(entry.effective_at - moment)
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_index = index
    return best_index


def calibration_offset(
    reference: TimelineEntry,
    target: TimelineEntry,
) -> int:
    """Seconds to add to the target's source so both photos land on the same moment."""
    reference_raw = reference.photo.captured_at or _EPOCH
    target_raw = target.photo.captured_at or _EPOCH
    shifted_reference = reference_raw + timedelta(seconds=reference.source.time_offset_s)
    return round((shifted_reference - target_raw).total_seconds())


def _sort_key(entry: TimelineEntry) -> tuple[datetime, int, str]:
    return (entry.effective_at, entry.source.sort_order, entry.photo.relative_path)
