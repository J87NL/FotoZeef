from __future__ import annotations

import json
import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath

from fotozeef.core import ordering
from fotozeef.core.metadata import read_metadata
from fotozeef.core.models import Photo, Source, TimelineEntry
from fotozeef.core.scanner import scan

MIN_SECONDS = 1
MAX_SECONDS = 3600
DEFAULT_SECONDS = 5


class PhotoScope(StrEnum):
    ALL = "all"
    SELECTED = "selected"


class SlideOrder(StrEnum):
    CHRONOLOGICAL = "chronological"
    RANDOM = "random"


class Transition(StrEnum):
    """`SLIDE_LEFT` means the new photo enters from the left edge."""

    FADE = "fade"
    SLIDE_LEFT = "slide_left"
    SLIDE_RIGHT = "slide_right"
    SLIDE_TOP = "slide_top"
    SLIDE_BOTTOM = "slide_bottom"


class PauseMode(StrEnum):
    HOLD = "hold"
    BLACK = "black"


@dataclass(frozen=True, slots=True)
class SlideshowSettings:
    scope: PhotoScope = PhotoScope.ALL
    include_subfolders: bool = True
    seconds: int = DEFAULT_SECONDS
    order: SlideOrder = SlideOrder.CHRONOLOGICAL
    transitions: frozenset[Transition] = field(default_factory=lambda: frozenset({Transition.FADE}))
    pause_mode: PauseMode = PauseMode.HOLD

    def to_json(self) -> str:
        return json.dumps(
            {
                "scope": str(self.scope),
                "include_subfolders": self.include_subfolders,
                "seconds": self.seconds,
                "order": str(self.order),
                "transitions": sorted(str(item) for item in self.transitions),
                "pause_mode": str(self.pause_mode),
            },
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, payload: str | None) -> SlideshowSettings:
        """Anything unreadable falls back to its default; a stored value never blocks a show."""
        defaults = cls()
        try:
            data = json.loads(payload) if payload else {}
        except (TypeError, ValueError):
            return defaults
        if not isinstance(data, dict):
            return defaults
        transitions = defaults.transitions
        raw_transitions = data.get("transitions")
        if isinstance(raw_transitions, list):
            transitions = frozenset(
                Transition(item) for item in raw_transitions if item in _values(Transition)
            )
        include_subfolders = data.get("include_subfolders")
        return cls(
            scope=_enum(PhotoScope, data.get("scope"), defaults.scope),
            include_subfolders=include_subfolders
            if isinstance(include_subfolders, bool)
            else defaults.include_subfolders,
            seconds=clamp_seconds(data.get("seconds"), defaults.seconds),
            order=_enum(SlideOrder, data.get("order"), defaults.order),
            transitions=transitions,
            pause_mode=_enum(PauseMode, data.get("pause_mode"), defaults.pause_mode),
        )


def clamp_seconds(value: object, fallback: int = DEFAULT_SECONDS) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return fallback
    return int(min(max(round(value), MIN_SECONDS), MAX_SECONDS))


def is_top_level(relative_path: str) -> bool:
    return len(PurePosixPath(relative_path).parts) <= 1


def collect_slides(
    entries: Sequence[TimelineEntry],
    sources: Sequence[Source],
    selected_ids: Iterable[int],
    settings: SlideshowSettings,
    project_scans_subfolders: bool,
    destination: Path,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[TimelineEntry, ...]:
    """The photos a show plays, in timeline order and without duplicates.

    The selection is explicit, so it ignores the subfolder choice. For all photos, a
    project that did not scan its subfolders gets an extra scan here; the destination
    is always left out, so copies of the selection never show up twice.
    """
    if settings.scope is PhotoScope.SELECTED:
        wanted = set(selected_ids)
        chosen = [entry for entry in entries if entry.photo.id in wanted]
    elif settings.include_subfolders and not project_scans_subfolders:
        chosen = list(entries) + _scan_subfolders(entries, sources, destination, should_cancel)
    elif settings.include_subfolders:
        chosen = list(entries)
    else:
        chosen = [entry for entry in entries if is_top_level(entry.photo.relative_path)]

    unique: list[TimelineEntry] = []
    seen: set[Path] = set()
    excluded = _resolved(destination)
    for entry in ordering.resort(chosen, sources):
        if entry.photo.missing:
            continue
        path = _resolved(entry.absolute_path)
        if path in seen or (excluded is not None and _is_inside(path, excluded)):
            continue
        seen.add(path)
        unique.append(entry)
    return tuple(unique)


def _scan_subfolders(
    entries: Sequence[TimelineEntry],
    sources: Sequence[Source],
    destination: Path,
    should_cancel: Callable[[], bool] | None,
) -> list[TimelineEntry]:
    """Photos below the top level that the project never indexed; ids are negative."""
    known = {(entry.source.id, entry.photo.relative_path) for entry in entries}
    extra: list[Photo] = []
    for source in sources:
        if not source.path.is_dir():
            continue
        report = scan(
            source.path, recursive=True, should_cancel=should_cancel, exclude=(destination,)
        )
        if report.cancelled:
            break
        for group in report.groups:
            primary = group.primary
            if is_top_level(primary.relative_path):
                continue
            if (source.id, primary.relative_path) in known:
                continue
            if should_cancel is not None and should_cancel():
                return []
            meta = read_metadata(primary.absolute_path, primary.mtime)
            extra.append(
                Photo(
                    id=-(len(extra) + 1),
                    source_id=source.id,
                    relative_path=primary.relative_path,
                    file_size=primary.file_size,
                    mtime=primary.mtime,
                    captured_at=meta.captured_at,
                    capture_source=meta.capture_source,
                    orientation=meta.orientation,
                    camera=meta.camera,
                    group_key=group.group_key,
                )
            )
    return list(ordering.build_timeline(extra, sources))


class Sequencer:
    """Which photo comes next. Random plays every photo once per round, then reshuffles."""

    def __init__(
        self,
        count: int,
        order: SlideOrder,
        rng: random.Random | None = None,
    ) -> None:
        if count <= 0:
            raise ValueError("A slideshow needs at least one photo")
        self._count = count
        self._order = order
        self._rng = rng or random.Random()
        self._rounds: list[list[int]] = [self._new_round(previous=None)]
        self._round = 0
        self._step = 0

    @property
    def round(self) -> int:
        """How many times the show has gone all the way round."""
        return self._round

    @property
    def current(self) -> int:
        return self._rounds[self._round][self._step]

    def next(self) -> int:
        self._step += 1
        if self._step >= self._count:
            self._step = 0
            self._round += 1
            if self._round == len(self._rounds):
                self._rounds.append(self._new_round(previous=self._rounds[-1][-1]))
        return self.current

    def previous(self) -> int:
        """Steps back through what was actually shown; the very first photo stays put."""
        if self._step > 0:
            self._step -= 1
        elif self._round > 0:
            self._round -= 1
            self._step = self._count - 1
        return self.current

    def peek(self) -> int:
        """The photo `next()` will return, so it can be decoded ahead of time."""
        if self._step + 1 < self._count:
            return self._rounds[self._round][self._step + 1]
        if self._round + 1 == len(self._rounds):
            self._rounds.append(self._new_round(previous=self._rounds[-1][-1]))
        return self._rounds[self._round + 1][0]

    def _new_round(self, previous: int | None) -> list[int]:
        indices = list(range(self._count))
        if self._order is SlideOrder.CHRONOLOGICAL:
            return indices
        self._rng.shuffle(indices)
        if self._count > 1 and previous is not None and indices[0] == previous:
            indices[0], indices[-1] = indices[-1], indices[0]
        return indices


def choose_transition(
    enabled: Iterable[Transition],
    rng: random.Random | None = None,
) -> Transition | None:
    """A random pick among the ticked effects; None means a plain cut."""
    options = sorted(set(enabled))
    if not options:
        return None
    return (rng or random).choice(options)


def _enum[E: StrEnum](kind: type[E], value: object, fallback: E) -> E:
    if isinstance(value, str) and value in _values(kind):
        return kind(value)
    return fallback


def _values(kind: type[StrEnum]) -> frozenset[str]:
    return frozenset(item.value for item in kind)


def _resolved(path: Path) -> Path | None:
    try:
        return path.resolve()
    except OSError:
        return None


def _is_inside(path: Path | None, folder: Path) -> bool:
    if path is None:
        return False
    return path == folder or folder in path.parents
