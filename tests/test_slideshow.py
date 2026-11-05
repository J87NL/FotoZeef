from __future__ import annotations

import itertools
import random
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from fotozeef.core.db import SCHEMA_VERSION, Database
from fotozeef.core.library import Library
from fotozeef.core.models import ProjectSettings
from fotozeef.core.slideshow import (
    MAX_SECONDS,
    MIN_SECONDS,
    PauseMode,
    PhotoScope,
    Sequencer,
    SlideOrder,
    SlideshowSettings,
    Transition,
    choose_transition,
    collect_slides,
)
from fotozeef.core.thumbnails import BACKDROP_WIDTH, render_slide

# --- settings -------------------------------------------------------------------------


def test_settings_survive_a_json_round_trip() -> None:
    settings = SlideshowSettings(
        scope=PhotoScope.SELECTED,
        include_subfolders=False,
        seconds=12,
        order=SlideOrder.RANDOM,
        transitions=frozenset({Transition.SLIDE_TOP, Transition.FADE}),
        pause_mode=PauseMode.BLACK,
        stop_after_one_round=True,
        start_at_current=True,
        screen="HDMI-1",
    )

    assert SlideshowSettings.from_json(settings.to_json()) == settings


def test_new_options_fall_back_one_by_one() -> None:
    payload = '{"stop_after_one_round": "yes", "start_at_current": 1, "screen": 5}'

    settings = SlideshowSettings.from_json(payload)

    assert settings.stop_after_one_round is False
    assert settings.start_at_current is False
    assert settings.screen == ""


def test_settings_stored_before_these_options_still_load() -> None:
    old = '{"scope": "all", "seconds": 7, "order": "random", "transitions": ["fade"]}'

    settings = SlideshowSettings.from_json(old)

    assert settings.seconds == 7
    assert settings.stop_after_one_round is False
    assert settings.screen == ""


def test_no_transitions_is_a_valid_choice_and_is_kept() -> None:
    settings = SlideshowSettings(transitions=frozenset())

    assert SlideshowSettings.from_json(settings.to_json()).transitions == frozenset()


@pytest.mark.parametrize("payload", [None, "", "not json", "[]", "42", '{"scope": 3}'])
def test_unreadable_settings_fall_back_to_the_defaults(payload: str | None) -> None:
    assert SlideshowSettings.from_json(payload) == SlideshowSettings()


def test_unknown_values_are_dropped_one_by_one() -> None:
    payload = (
        '{"scope": "everything", "seconds": "ten", "order": "random",'
        ' "transitions": ["fade", "spin", 7], "pause_mode": "black", "include_subfolders": 1}'
    )

    settings = SlideshowSettings.from_json(payload)

    assert settings.scope is PhotoScope.ALL
    assert settings.seconds == SlideshowSettings().seconds
    assert settings.order is SlideOrder.RANDOM
    assert settings.transitions == frozenset({Transition.FADE})
    assert settings.pause_mode is PauseMode.BLACK
    assert settings.include_subfolders is True


@pytest.mark.parametrize(
    ("stored", "expected"),
    [(0, MIN_SECONDS), (-5, MIN_SECONDS), (10**9, MAX_SECONDS), (7.6, 8), (True, 5)],
)
def test_seconds_are_clamped(stored: object, expected: int) -> None:
    payload = SlideshowSettings().to_json().replace('"seconds": 5', f'"seconds": {stored!r}')
    payload = payload.replace("True", "true")

    assert SlideshowSettings.from_json(payload).seconds == expected


# --- order ----------------------------------------------------------------------------


def test_chronological_plays_in_order_and_loops() -> None:
    sequencer = Sequencer(3, SlideOrder.CHRONOLOGICAL)

    shown = [sequencer.current] + [sequencer.next() for _ in range(5)]

    assert shown == [0, 1, 2, 0, 1, 2]


def test_random_plays_every_photo_once_per_round() -> None:
    sequencer = Sequencer(6, SlideOrder.RANDOM, random.Random(3))

    shown = [sequencer.current] + [sequencer.next() for _ in range(6 * 20 - 1)]

    for start in range(0, len(shown), 6):
        assert sorted(shown[start : start + 6]) == list(range(6))


def test_random_never_repeats_a_photo_across_a_reshuffle() -> None:
    for seed in range(200):
        sequencer = Sequencer(3, SlideOrder.RANDOM, random.Random(seed))
        shown = [sequencer.current] + [sequencer.next() for _ in range(30)]
        assert all(a != b for a, b in itertools.pairwise(shown)), seed


def test_previous_retraces_what_was_shown_across_rounds() -> None:
    sequencer = Sequencer(4, SlideOrder.RANDOM, random.Random(1))
    shown = [sequencer.current] + [sequencer.next() for _ in range(9)]

    retraced = [sequencer.current] + [sequencer.previous() for _ in range(9)]

    assert retraced == list(reversed(shown))


def test_previous_on_the_very_first_photo_stays_put() -> None:
    sequencer = Sequencer(4, SlideOrder.CHRONOLOGICAL)

    assert sequencer.previous() == 0


def test_peek_announces_the_next_photo() -> None:
    sequencer = Sequencer(5, SlideOrder.RANDOM, random.Random(9))
    for _ in range(23):
        expected = sequencer.peek()
        assert sequencer.next() == expected


def test_a_single_photo_simply_repeats() -> None:
    sequencer = Sequencer(1, SlideOrder.RANDOM)

    assert [sequencer.next() for _ in range(3)] == [0, 0, 0]


def test_an_empty_show_is_refused() -> None:
    with pytest.raises(ValueError):
        Sequencer(0, SlideOrder.CHRONOLOGICAL)


def test_transitions_come_only_from_the_ticked_ones() -> None:
    rng = random.Random(4)
    ticked = {Transition.FADE, Transition.SLIDE_BOTTOM}

    picks = {choose_transition(ticked, rng) for _ in range(200)}

    assert picks == ticked
    assert choose_transition(set(), rng) is None


# --- which photos ---------------------------------------------------------------------


def _project(library: Library, sources: list[Path], destination: Path, recursive: bool):
    project = library.create_project(
        "show", sources, destination, ProjectSettings(recursive=recursive)
    )
    return library.open_project(project.id)


def _names(entries) -> list[str]:
    return [entry.photo.relative_path for entry in entries]


def _collect(state, settings: SlideshowSettings, selected=()):
    return collect_slides(
        state.entries,
        state.sources,
        selected,
        settings,
        project_scans_subfolders=state.project.settings.recursive,
        destination=state.project.destination,
    )


def test_subfolders_can_be_left_out(tmp_path: Path, library: Library, jpeg_factory) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "top.jpg", captured_at=datetime(2024, 1, 1, 9))
    jpeg_factory(source / "day2" / "deep.jpg", captured_at=datetime(2024, 1, 1, 8))
    state = _project(library, [source], tmp_path / "out", recursive=True)

    assert _names(_collect(state, SlideshowSettings(include_subfolders=True))) == [
        "day2/deep.jpg",
        "top.jpg",
    ]
    assert _names(_collect(state, SlideshowSettings(include_subfolders=False))) == ["top.jpg"]


def test_subfolders_are_scanned_when_the_project_skipped_them(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "top.jpg", captured_at=datetime(2024, 1, 1, 9))
    jpeg_factory(source / "day2" / "deep.jpg", captured_at=datetime(2024, 1, 1, 8))
    state = _project(library, [source], tmp_path / "out", recursive=False)
    assert _names(state.entries) == ["top.jpg"]

    slides = _collect(state, SlideshowSettings(include_subfolders=True))

    assert _names(slides) == ["day2/deep.jpg", "top.jpg"]
    assert slides[0].photo.captured_at == datetime(2024, 1, 1, 8)


def test_a_destination_inside_the_source_never_shows_twice(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "a.jpg", captured_at=datetime(2024, 1, 1, 9))
    jpeg_factory(source / "selectie" / "a.jpg", captured_at=datetime(2024, 1, 1, 9))
    for recursive in (True, False):
        state = _project(library, [source], source / "selectie", recursive=recursive)

        slides = _collect(state, SlideshowSettings(include_subfolders=True))

        assert _names(slides) == ["a.jpg"], recursive


def test_overlapping_sources_show_each_file_once(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "a.jpg", captured_at=datetime(2024, 1, 1, 9))
    jpeg_factory(source / "sub" / "b.jpg", captured_at=datetime(2024, 1, 1, 10))
    state = _project(library, [source, source / "sub"], tmp_path / "out", recursive=True)

    slides = _collect(state, SlideshowSettings())

    assert sorted(entry.absolute_path.name for entry in slides) == ["a.jpg", "b.jpg"]


def test_only_the_selection_ignores_the_subfolder_choice(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "a.jpg", captured_at=datetime(2024, 1, 1, 9))
    jpeg_factory(source / "b.jpg", captured_at=datetime(2024, 1, 1, 10))
    jpeg_factory(source / "sub" / "c.jpg", captured_at=datetime(2024, 1, 1, 11))
    state = _project(library, [source], tmp_path / "out", recursive=True)
    chosen = {state.entries[1].photo.id, state.entries[2].photo.id}

    slides = _collect(
        state,
        SlideshowSettings(scope=PhotoScope.SELECTED, include_subfolders=False),
        selected=chosen,
    )

    assert _names(slides) == ["b.jpg", "sub/c.jpg"]


def test_missing_files_are_skipped(tmp_path: Path, library: Library, jpeg_factory) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "a.jpg", captured_at=datetime(2024, 1, 1, 9))
    jpeg_factory(source / "b.jpg", captured_at=datetime(2024, 1, 1, 10))
    project = library.create_project("show", [source], tmp_path / "out", ProjectSettings())
    library.open_project(project.id)
    (source / "b.jpg").unlink()
    state = library.open_project(project.id)

    assert _names(_collect(state, SlideshowSettings())) == ["a.jpg"]


def test_chronological_order_follows_the_camera_offsets(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    first = tmp_path / "cam1"
    second = tmp_path / "cam2"
    jpeg_factory(first / "a.jpg", captured_at=datetime(2024, 1, 1, 9, 0))
    jpeg_factory(second / "b.jpg", captured_at=datetime(2024, 1, 1, 9, 30))
    state = _project(library, [first, second], tmp_path / "out", recursive=True)
    library.set_offset(state, state.sources[1].id, -3600)

    assert _names(_collect(state, SlideshowSettings())) == ["b.jpg", "a.jpg"]


# --- storage --------------------------------------------------------------------------


def test_settings_are_kept_per_project_across_a_restart(tmp_path: Path, jpeg_factory) -> None:
    path = tmp_path / "state.sqlite"
    source = tmp_path / "cam"
    jpeg_factory(source / "a.jpg")
    library = Library(Database(path))
    first = library.create_project("one", [source], tmp_path / "o1", ProjectSettings())
    second = library.create_project("two", [source], tmp_path / "o2", ProjectSettings())
    chosen = SlideshowSettings(seconds=9, pause_mode=PauseMode.BLACK, transitions=frozenset())
    library.save_slideshow_settings(first.id, chosen)
    library.close()

    reopened = Library(Database(path))

    assert reopened.slideshow_settings(first.id) == chosen
    assert reopened.slideshow_settings(second.id) == SlideshowSettings()
    reopened.close()


def test_forgetting_a_project_drops_its_slideshow_settings(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    source = tmp_path / "cam"
    jpeg_factory(source / "a.jpg")
    project = library.create_project("one", [source], tmp_path / "o", ProjectSettings())
    library.save_slideshow_settings(project.id, SlideshowSettings(seconds=30))

    library.projects.delete(project.id)

    assert library.slideshows.get(project.id) is None


def test_a_version_1_database_is_upgraded_in_place(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite"
    connection = sqlite3.connect(path)
    from fotozeef.core import db as db_module

    connection.executescript(db_module._SCHEMA)
    connection.execute(
        "INSERT INTO projects (name, destination, created_at, opened_at)"
        " VALUES ('old', '/x', '2024-01-01T00:00:00+00:00', '2024-01-01T00:00:00+00:00')"
    )
    connection.execute("PRAGMA user_version = 1")
    connection.commit()
    connection.close()

    library = Library(Database(path))

    assert [project.name for project in library.projects.list()] == ["old"]
    project_id = library.projects.list()[0].id
    library.save_slideshow_settings(project_id, SlideshowSettings(seconds=3))
    assert library.slideshow_settings(project_id).seconds == 3
    version = library._db.connection.execute("PRAGMA user_version").fetchone()[0]
    assert version == SCHEMA_VERSION
    library.close()


# --- rendering ------------------------------------------------------------------------


def test_a_slide_fits_the_screen_and_keeps_its_proportions(tmp_path: Path) -> None:
    path = tmp_path / "portrait.jpg"
    Image.new("RGB", (3000, 4500), (10, 200, 30)).save(path)

    slide = render_slide(path, 1920, 1080)

    assert (slide.width, slide.height) == (720, 1080)
    assert len(slide.photo) == slide.width * slide.height * 3
    assert slide.backdrop_width == BACKDROP_WIDTH
    assert slide.backdrop_height == 108
    assert len(slide.backdrop) == slide.backdrop_width * slide.backdrop_height * 3


def test_a_small_photo_is_not_upscaled_here(tmp_path: Path) -> None:
    path = tmp_path / "small.png"
    Image.new("RGB", (300, 200), (10, 20, 30)).save(path)

    slide = render_slide(path, 1920, 1080)

    assert (slide.width, slide.height) == (300, 200)


def test_the_backdrop_is_darker_than_the_photo(tmp_path: Path) -> None:
    path = tmp_path / "bright.jpg"
    Image.new("RGB", (800, 600), (240, 240, 240)).save(path)

    slide = render_slide(path, 1600, 900)

    assert max(slide.backdrop) < min(slide.photo)


def test_exif_rotation_is_applied(tmp_path: Path) -> None:
    path = tmp_path / "rotated.jpg"
    image = Image.new("RGB", (400, 200), (90, 90, 90))
    exif = image.getexif()
    exif[0x0112] = 6
    image.save(path, exif=exif)

    slide = render_slide(path, 1000, 1000)

    assert (slide.width, slide.height) == (200, 400)


def test_cancel_stops_reading_metadata_of_subfolders(
    tmp_path: Path, library: Library, jpeg_factory, monkeypatch
) -> None:
    from fotozeef.core import slideshow

    source = tmp_path / "cam"
    jpeg_factory(source / "top.jpg")
    for index in range(20):
        jpeg_factory(source / "sub" / f"{index}.jpg")
    state = _project(library, [source], tmp_path / "out", recursive=False)
    reads: list[Path] = []
    real = slideshow.read_metadata
    monkeypatch.setattr(
        slideshow, "read_metadata", lambda path, mtime: reads.append(path) or real(path, mtime)
    )

    collect_slides(
        state.entries,
        state.sources,
        (),
        SlideshowSettings(),
        project_scans_subfolders=False,
        destination=state.project.destination,
        should_cancel=lambda: len(reads) >= 3,
    )

    assert len(reads) == 3


def test_the_round_counter_follows_the_show() -> None:
    sequencer = Sequencer(2, SlideOrder.CHRONOLOGICAL)
    assert sequencer.round == 0

    sequencer.next()
    sequencer.next()

    assert sequencer.round == 1


# --- start and end ----------------------------------------------------------------------


def test_a_chronological_show_can_start_midway() -> None:
    sequencer = Sequencer(5, SlideOrder.CHRONOLOGICAL, start=3)

    shown = [sequencer.current] + [sequencer.next() for _ in range(4)]

    assert shown == [3, 4, 0, 1, 2]
    assert sequencer.round == 1


def test_a_start_out_of_range_is_clamped() -> None:
    assert Sequencer(3, SlideOrder.CHRONOLOGICAL, start=9).current == 2
    assert Sequencer(3, SlideOrder.CHRONOLOGICAL, start=-4).current == 0


def test_random_ignores_the_start() -> None:
    sequencer = Sequencer(4, SlideOrder.RANDOM, random.Random(2), start=3)
    shown = [sequencer.current] + [sequencer.next() for _ in range(3)]

    assert sorted(shown) == [0, 1, 2, 3]


def test_round_end_is_the_last_step() -> None:
    sequencer = Sequencer(3, SlideOrder.CHRONOLOGICAL, start=1)
    assert not sequencer.at_round_end

    sequencer.next()
    assert sequencer.at_round_end

    sequencer.next()
    assert not sequencer.at_round_end


def test_the_start_is_the_current_photo_or_the_next_in_time(
    tmp_path: Path, library: Library, jpeg_factory
) -> None:
    from fotozeef.core.slideshow import start_position

    source = tmp_path / "cam"
    for index in range(5):
        jpeg_factory(source / f"{index}.jpg", captured_at=datetime(2024, 1, 1, 9, index))
    state = _project(library, [source], tmp_path / "out", recursive=True)
    entries = state.entries
    chosen = (entries[0], entries[3])

    assert start_position(entries, entries[2]) == 2
    assert start_position(chosen, entries[3]) == 1
    assert start_position(chosen, entries[1]) == 1, "the next selected photo in time"
    assert start_position(chosen, entries[4]) == 0, "nothing later: from the start"
    assert start_position(chosen, None) == 0
    assert start_position((), entries[1]) == 0
