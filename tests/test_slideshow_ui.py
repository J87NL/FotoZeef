from __future__ import annotations

import random
import time
from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from fotozeef.core.library import Library
from fotozeef.core.models import ProjectSettings
from fotozeef.core.slideshow import (
    PauseMode,
    PhotoScope,
    SlideOrder,
    SlideshowSettings,
    Transition,
)
from fotozeef.core.thumbnails import ThumbnailCache
from fotozeef.ui.main_window import MainWindow
from fotozeef.ui.slideshow_dialog import SlideshowDialog
from fotozeef.ui.slideshow_window import SlideshowWindow, fit_rect, slide_offset


def _pump(app: QApplication, until, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not until():
        assert time.monotonic() < deadline, "timed out"
        app.processEvents()
        time.sleep(0.005)


def _press(widget, key: Qt.Key) -> None:
    widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


@pytest.fixture
def state(tmp_path: Path, library: Library, jpeg_factory):
    source = tmp_path / "cam"
    for index in range(4):
        jpeg_factory(
            source / f"{index}.jpg",
            captured_at=datetime(2024, 1, 1, 9, index),
            size=(120, 80),
            color=(40 * index, 80, 160),
        )
    project = library.create_project("show", [source], tmp_path / "out", ProjectSettings())
    return library.open_project(project.id)


def _show(app, state, **overrides) -> SlideshowWindow:
    settings = SlideshowSettings(**{"seconds": 60, "transitions": frozenset(), **overrides})
    show = SlideshowWindow(state.entries, settings, rng=random.Random(5))
    show.setGeometry(QRect(0, 0, 640, 360))
    show.show()
    _pump(app, lambda: show._shown is not None)
    return show


# --- dialog ---------------------------------------------------------------------------


def test_the_dialog_shows_and_returns_every_setting(app: QApplication) -> None:
    chosen = SlideshowSettings(
        scope=PhotoScope.SELECTED,
        include_subfolders=False,
        seconds=17,
        order=SlideOrder.RANDOM,
        transitions=frozenset({Transition.SLIDE_LEFT, Transition.SLIDE_BOTTOM}),
        pause_mode=PauseMode.BLACK,
    )
    dialog = SlideshowDialog(chosen, selected_count=3)

    assert dialog.settings == chosen
    assert not dialog._subfolders.isEnabled()
    assert "3" in dialog._selected.text()

    dialog._all.setChecked(True)
    assert dialog._subfolders.isEnabled()
    dialog.close()


def test_start_is_only_reported_for_the_start_button(app: QApplication) -> None:
    dialog = SlideshowDialog(SlideshowSettings(), selected_count=0)
    dialog.reject()
    assert not dialog.start_requested

    dialog._start_button.click()
    assert dialog.start_requested


def test_closing_the_dialog_still_saves_the_settings(
    app: QApplication, tmp_path: Path, library: Library, state, monkeypatch
) -> None:
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    window._on_project_opened(state)

    def fake_exec(dialog: SlideshowDialog) -> int:
        dialog._seconds.setValue(42)
        dialog._black.setChecked(True)
        dialog.reject()
        return 0

    monkeypatch.setattr(SlideshowDialog, "exec", fake_exec)
    window.start_slideshow()

    stored = library.slideshow_settings(state.project.id)
    assert stored.seconds == 42
    assert stored.pause_mode is PauseMode.BLACK
    assert window._slideshow is None
    assert not window._preparer.busy
    window.close()


def test_start_opens_the_show_and_esc_returns(
    app: QApplication, tmp_path: Path, library: Library, state, monkeypatch
) -> None:
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    window._on_project_opened(state)

    def fake_exec(dialog: SlideshowDialog) -> int:
        dialog._start_button.click()
        return 1

    monkeypatch.setattr(SlideshowDialog, "exec", fake_exec)
    window.start_slideshow()
    _pump(app, lambda: window._slideshow is not None)
    show = window._slideshow
    assert len(show._entries) == 4

    _press(show, Qt.Key.Key_Escape)
    _pump(app, lambda: window._slideshow is None)
    window.close()


def test_only_selected_with_nothing_selected_does_not_start(
    app: QApplication, tmp_path: Path, library: Library, state, monkeypatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    window._on_project_opened(state)
    library.save_slideshow_settings(state.project.id, SlideshowSettings(scope=PhotoScope.SELECTED))
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: shown.append(args[2]))
    monkeypatch.setattr(SlideshowDialog, "exec", lambda dialog: dialog._start_button.click())

    window.start_slideshow()
    _pump(app, lambda: bool(shown))

    assert window._slideshow is None
    window.close()


# --- the show -------------------------------------------------------------------------


def test_the_show_starts_on_the_first_photo_and_advances(app: QApplication, state) -> None:
    show = _show(app, state)
    assert show._shown == 0
    assert show._dwell.isActive()
    assert show._dwell.interval() == 60_000

    show.next()
    _pump(app, lambda: show._shown == 1)
    show.close()


def test_the_timer_advances_on_its_own(app: QApplication, state) -> None:
    show = _show(app, state, seconds=1)

    _pump(app, lambda: show._shown == 1, timeout=4)
    show.close()


def test_arrows_and_presenter_keys_step(app: QApplication, state) -> None:
    show = _show(app, state)

    _press(show, Qt.Key.Key_Right)
    _pump(app, lambda: show._shown == 1)
    _press(show, Qt.Key.Key_PageDown)
    _pump(app, lambda: show._shown == 2)
    _press(show, Qt.Key.Key_Left)
    _pump(app, lambda: show._shown == 1)
    _press(show, Qt.Key.Key_PageUp)
    _pump(app, lambda: show._shown == 0)
    show.close()


def test_space_holds_the_photo_and_resumes(app: QApplication, state) -> None:
    show = _show(app, state, pause_mode=PauseMode.HOLD)
    show._dwell.start(10_000)

    _press(show, Qt.Key.Key_Space)
    assert show.paused
    assert not show._dwell.isActive()
    assert not show.blacked_out
    assert show._shown == 0

    _press(show, Qt.Key.Key_Space)
    assert not show.paused
    assert show._dwell.isActive()
    assert 0 < show._dwell.remainingTime() <= 11_000, "the rest of the time, not a restart"
    show.close()


def test_space_blacks_out_and_brings_the_photo_back(app: QApplication, state) -> None:
    show = _show(app, state, pause_mode=PauseMode.BLACK)

    _press(show, Qt.Key.Key_Space)
    assert show.blacked_out
    _pump(app, lambda: show._veil == 1.0)
    image = show.grab().toImage()
    assert image.pixelColor(320, 180).value() == 0

    _press(show, Qt.Key.Key_Space)
    assert not show.paused
    _pump(app, lambda: show._veil == 0.0)
    assert show.grab().toImage().pixelColor(320, 180).value() > 0
    show.close()


def test_stepping_during_a_black_pause_reveals_the_photo_but_stays_paused(
    app: QApplication, state
) -> None:
    show = _show(app, state, pause_mode=PauseMode.BLACK)
    _press(show, Qt.Key.Key_Space)

    _press(show, Qt.Key.Key_Right)
    _pump(app, lambda: show._shown == 1 and show._veil == 0.0)

    assert show.paused
    assert not show._dwell.isActive()
    show.close()


def test_a_transition_runs_and_settles(app: QApplication, state) -> None:
    show = _show(app, state, transitions=frozenset({Transition.FADE}))

    show.next()
    _pump(app, lambda: show._shown == 1)
    assert show._transition is Transition.FADE
    _pump(app, lambda: show._outgoing is None)
    assert show._progress == 1.0
    show.close()


def test_unreadable_photos_are_skipped(app: QApplication, state) -> None:
    broken = state.entries[1].absolute_path
    broken.write_bytes(b"not a photo")
    show = _show(app, state)

    show.next()
    _pump(app, lambda: show._shown == 2)
    assert 1 in show._unreadable
    show.close()


def test_stepping_back_onto_an_unreadable_first_photo_does_not_hang(
    app: QApplication, state
) -> None:
    state.entries[0].absolute_path.write_bytes(b"broken")
    show = SlideshowWindow(state.entries, SlideshowSettings(seconds=60, transitions=frozenset()))
    show.setGeometry(QRect(0, 0, 320, 200))
    show.show()
    _pump(app, lambda: show._shown == 1)

    show.previous()
    _pump(app, lambda: show._pending is None)

    assert show._shown == 1
    show.close()


def test_a_show_of_only_unreadable_files_waits_quietly(app: QApplication, state) -> None:
    for entry in state.entries:
        entry.absolute_path.write_bytes(b"broken")
    show = SlideshowWindow(state.entries, SlideshowSettings(seconds=1))
    show.setGeometry(QRect(0, 0, 320, 200))
    show.show()

    _pump(app, lambda: len(show._unreadable) == len(state.entries))
    app.processEvents()

    assert show._shown is None
    assert not show._dwell.isActive()
    show.close()


def test_closing_emits_closed(app: QApplication, state) -> None:
    show = _show(app, state)
    seen: list[bool] = []
    show.closed.connect(lambda: seen.append(True))

    show.close()

    assert seen == [True]


# --- geometry -------------------------------------------------------------------------


def test_fit_rect_keeps_proportions_and_centres() -> None:
    frame = QRectF(0, 0, 1600, 900)

    portrait = fit_rect(2000, 3000, frame)
    landscape = fit_rect(3000, 1000, frame)

    assert portrait == QRectF(500, 0, 600, 900)
    assert landscape == QRectF(0, 183.33333333333334, 1600, 533.3333333333334)


@pytest.mark.parametrize(
    ("transition", "start"),
    [
        (Transition.SLIDE_LEFT, QPointF(-800, 0)),
        (Transition.SLIDE_RIGHT, QPointF(800, 0)),
        (Transition.SLIDE_TOP, QPointF(0, -450)),
        (Transition.SLIDE_BOTTOM, QPointF(0, 450)),
        (Transition.FADE, QPointF(0, 0)),
    ],
)
def test_slides_enter_from_their_own_side(transition: Transition, start: QPointF) -> None:
    canvas = QRectF(0, 0, 800, 450)

    assert slide_offset(transition, 0.0, canvas) == start
    assert slide_offset(transition, 1.0, canvas) == QPointF(0, 0)
