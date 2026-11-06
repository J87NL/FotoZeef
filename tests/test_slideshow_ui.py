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


# --- review fixes ---------------------------------------------------------------------


def test_a_long_run_of_known_unreadable_photos_is_skipped_without_recursion(
    app: QApplication, state
) -> None:
    entries = tuple(state.entries[index % 4] for index in range(1500))
    show = SlideshowWindow(entries, SlideshowSettings(seconds=60, transitions=frozenset()))
    show.setGeometry(QRect(0, 0, 320, 200))
    show.show()
    _pump(app, lambda: show._shown == 0)
    show._unreadable.update(range(1, 1400))

    show.next()
    _pump(app, lambda: show._shown == 1400)
    show.close()


def test_stepping_back_skips_an_unreadable_photo_in_the_middle(app: QApplication, state) -> None:
    show = _show(app, state)
    for target in (1, 2):
        show.next()
        _pump(app, lambda target=target: show._shown == target)
    show._unreadable.add(1)

    show.previous()
    _pump(app, lambda: show._shown == 0)
    show.close()


def test_failures_are_retried_in_the_next_round(app: QApplication, state) -> None:
    show = _show(app, state)
    show._unreadable.add(2)

    for _ in range(3):
        show.next()
    _pump(app, lambda: show._shown == 0 and show._pending is None)
    assert show._unreadable == set()

    show.next()
    show.next()
    _pump(app, lambda: show._shown == 2)
    show.close()


def test_resuming_from_black_restarts_the_full_duration(app: QApplication, state) -> None:
    show = _show(app, state, pause_mode=PauseMode.BLACK)
    show._dwell.start(2_000)

    _press(show, Qt.Key.Key_Space)
    _press(show, Qt.Key.Key_Space)

    assert show._dwell.remainingTime() > 50_000
    show.close()


def test_each_photo_is_decoded_once(app: QApplication, state, monkeypatch) -> None:
    from fotozeef.ui import slideshow_window

    decoded: list[str] = []
    real = slideshow_window.render_slide

    def counting(path, width, height):
        decoded.append(path.name)
        time.sleep(0.05)
        return real(path, width, height)

    monkeypatch.setattr(slideshow_window, "render_slide", counting)
    show = _show(app, state)
    for target in (1, 2):
        show.next()
        _pump(app, lambda target=target: show._shown == target)
    _pump(app, lambda: not show._loader._running)

    assert decoded == ["0.jpg", "1.jpg", "2.jpg", "3.jpg"]
    show.close()


def test_closing_during_a_slow_decode_returns_at_once(
    app: QApplication, state, monkeypatch
) -> None:
    import threading

    from fotozeef.ui import slideshow_window

    release = threading.Event()
    started = threading.Event()

    def slow(path, width, height):
        started.set()
        release.wait(10)
        raise OSError("gone")

    monkeypatch.setattr(slideshow_window, "render_slide", slow)
    show = SlideshowWindow(state.entries, SlideshowSettings())
    show.show()
    assert started.wait(5)
    failures: list[int] = []
    show._loader.failed.connect(lambda key, _message: failures.append(key))

    began = time.monotonic()
    show.close()
    assert time.monotonic() - began < 1.0

    release.set()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert failures == []


def test_a_cancelled_preparation_never_opens_a_show(
    app: QApplication, tmp_path: Path, library: Library, state
) -> None:
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    window._on_project_opened(state)
    window._preparer.cancel()

    window._on_slideshow_prepared(state.project.id, state.entries, SlideshowSettings())

    assert window._slideshow is None
    window.close()


def test_a_preparation_for_another_project_is_dropped(
    app: QApplication, tmp_path: Path, library: Library, state
) -> None:
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    window._on_project_opened(state)

    window._on_slideshow_prepared(state.project.id + 1, state.entries, SlideshowSettings())

    assert window._slideshow is None
    window.close()


def test_keys_reaching_the_main_window_during_a_show_do_not_select(
    app: QApplication, tmp_path: Path, library: Library, state
) -> None:
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    window._on_project_opened(state)
    window._on_slideshow_prepared(
        state.project.id, state.entries, SlideshowSettings(seconds=60, transitions=frozenset())
    )
    show = window._slideshow
    assert show is not None

    _press(window, Qt.Key.Key_Space)

    assert window._selected == set()
    assert show.paused
    show.close()
    _pump(app, lambda: window._slideshow is None)
    window.close()


# --- presenter black key, screen sleep, second review ------------------------------


@pytest.mark.parametrize("key", [Qt.Key.Key_B, Qt.Key.Key_Period])
def test_the_black_key_blacks_out_even_when_pausing_holds(
    app: QApplication, state, key: Qt.Key
) -> None:
    show = _show(app, state, pause_mode=PauseMode.HOLD)

    _press(show, key)
    assert show.paused
    assert show.blacked_out

    _press(show, key)
    assert not show.paused
    assert not show.blacked_out
    assert show._dwell.isActive()
    show.close()


def test_the_black_key_during_a_held_pause_stays_paused(app: QApplication, state) -> None:
    show = _show(app, state, pause_mode=PauseMode.HOLD)
    _press(show, Qt.Key.Key_Space)

    _press(show, Qt.Key.Key_B)
    assert show.paused
    assert show.blacked_out

    _press(show, Qt.Key.Key_B)
    assert show.paused, "the pause from before the black screen is kept"
    assert not show.blacked_out
    assert not show._dwell.isActive()
    show.close()


def test_the_black_key_after_stepping_out_of_black_stays_paused(app: QApplication, state) -> None:
    show = _show(app, state)
    _press(show, Qt.Key.Key_B)
    _press(show, Qt.Key.Key_Right)
    _pump(app, lambda: show._shown == 1)

    _press(show, Qt.Key.Key_B)
    _press(show, Qt.Key.Key_B)

    assert show.paused
    assert not show._dwell.isActive()
    show.close()


def test_space_ends_a_black_screen_from_the_black_key(app: QApplication, state) -> None:
    show = _show(app, state, pause_mode=PauseMode.HOLD)
    _press(show, Qt.Key.Key_B)

    _press(show, Qt.Key.Key_Space)

    assert not show.paused
    assert not show.blacked_out
    show.close()


class RecordingGuard:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def acquire(self) -> None:
        self.calls.append("acquire")

    def release(self) -> None:
        self.calls.append("release")


def test_the_screen_is_kept_awake_for_the_whole_show(app: QApplication, state) -> None:
    guard = RecordingGuard()
    show = SlideshowWindow(state.entries, SlideshowSettings(), sleep_guard=guard)

    show.start()
    _press(show, Qt.Key.Key_Space)
    assert guard.calls == ["acquire"]

    show.close()
    assert guard.calls == ["acquire", "release"]


def test_stepping_back_past_unreadable_photos_at_the_start_keeps_playing(
    app: QApplication, state
) -> None:
    entries = tuple(state.entries[index % 4] for index in range(10))
    show = SlideshowWindow(entries, SlideshowSettings(seconds=60, transitions=frozenset()))
    show.setGeometry(QRect(0, 0, 320, 200))
    show._unreadable.update(range(8))
    show._go(0, 1)
    show.show()
    _pump(app, lambda: show._shown == 8)

    show.previous()
    _pump(app, lambda: show._pending is None)

    assert show._shown == 8
    assert show._dwell.isActive()
    assert show._direction == 1
    show.close()


def test_menu_shortcuts_are_off_while_a_show_runs(
    app: QApplication, tmp_path: Path, library: Library, state
) -> None:
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    window._on_project_opened(state)

    window._on_slideshow_prepared(state.project.id, state.entries, SlideshowSettings())
    assert window._actions
    assert not any(action.isEnabled() for action in window._actions)

    window.retranslate()
    assert not any(action.isEnabled() for action in window._actions)

    window._slideshow.close()
    _pump(app, lambda: window._slideshow is None)
    assert all(action.isEnabled() for action in window._actions)
    window.close()


def test_an_error_after_cancel_stays_quiet(
    app: QApplication, tmp_path: Path, library: Library, state, monkeypatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    window._on_project_opened(state)
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: shown.append(args[2]))
    window._preparer.cancel()

    window._on_slideshow_failed("share went away")

    assert shown == []
    window.close()


def test_a_decode_finishing_after_the_window_is_gone_is_harmless(
    app: QApplication, state, monkeypatch
) -> None:
    import gc
    import threading

    from PySide6.QtCore import QCoreApplication, QEvent

    from fotozeef.ui import slideshow_window

    release = threading.Event()
    started = threading.Event()
    real = slideshow_window.render_slide

    def slow(path, width, height):
        started.set()
        release.wait(10)
        return real(path, width, height)

    monkeypatch.setattr(slideshow_window, "render_slide", slow)
    for _ in range(5):
        release.clear()
        started.clear()
        show = SlideshowWindow(state.entries, SlideshowSettings())
        show.show()
        assert started.wait(5)
        loader = show._loader
        assert loader.parent() is show, "Qt must delete the loader on the GUI thread"
        thread = loader._thread
        show.close()
        show.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        del show, loader
        gc.collect()

        release.set()
        thread.join(5)
        assert not thread.is_alive()
        for _ in range(20):
            app.processEvents()
        gc.collect()


def test_the_black_key_ignores_what_happened_before(app: QApplication, state) -> None:
    """B, B, Space, B in black mode must end like Space, B: paused with the photo back."""
    show = _show(app, state, pause_mode=PauseMode.BLACK)
    _press(show, Qt.Key.Key_B)
    _press(show, Qt.Key.Key_B)
    _press(show, Qt.Key.Key_Space)

    _press(show, Qt.Key.Key_B)

    assert show.paused
    assert not show.blacked_out
    show.close()


def _pointer(structure):
    """What Qt hands nativeEvent: a shiboken VoidPtr to the native message."""
    import ctypes

    from shiboken6 import VoidPtr

    return VoidPtr(ctypes.addressof(structure))


def _windows_message(command: int, argument: int = 0):
    from ctypes import wintypes

    message = wintypes.MSG()
    message.message = 0x0112
    message.wParam = command
    message.lParam = argument
    return message


@pytest.mark.parametrize(
    ("command", "argument", "swallowed"),
    [(0xF140, 0, True), (0xF170, 2, True), (0xF170, -1, False), (0xF060, 0, False)],
)
def test_on_windows_the_show_window_turns_down_the_screensaver(
    app: QApplication, state, monkeypatch, command: int, argument: int, swallowed: bool
) -> None:

    from PySide6.QtCore import QByteArray

    from fotozeef.ui import slideshow_window

    monkeypatch.setattr(slideshow_window, "_ON_WINDOWS", True)
    show = SlideshowWindow(state.entries, SlideshowSettings())
    message = _windows_message(command, argument)

    handled, result = show.nativeEvent(QByteArray(b"windows_generic_MSG"), _pointer(message))

    assert handled is swallowed
    assert result == 0
    show.close()


def test_other_platforms_never_read_native_events(app: QApplication, state, monkeypatch) -> None:

    from PySide6.QtCore import QByteArray

    from fotozeef.ui import slideshow_window

    monkeypatch.setattr(slideshow_window, "_ON_WINDOWS", False)
    show = SlideshowWindow(state.entries, SlideshowSettings())
    message = _windows_message(0xF140)

    assert show.nativeEvent(QByteArray(b"windows_generic_MSG"), _pointer(message)) == (False, 0)
    monkeypatch.setattr(slideshow_window, "_ON_WINDOWS", True)
    assert show.nativeEvent(QByteArray(b"xcb_generic_event_t"), _pointer(message)) == (False, 0)
    show.close()


# --- one round, start photo, screen, mouse --------------------------------------------


def test_a_one_round_show_ends_on_black_after_the_last_photo(app: QApplication, state) -> None:
    show = _show(app, state, stop_after_one_round=True)
    for target in (1, 2, 3):
        show._advance()
        _pump(app, lambda target=target: show._shown == target)

    show._advance()

    assert show.ended
    assert show.paused
    assert show.blacked_out
    assert show._shown == 3
    assert not show._dwell.isActive()
    show.close()


def test_space_at_the_end_plays_again_from_the_start(app: QApplication, state) -> None:
    show = _show(app, state, stop_after_one_round=True)
    _play_to_the_end(app, show)

    _press(show, Qt.Key.Key_Space)

    _pump(app, lambda: show._shown == 0)
    assert not show.ended
    assert not show.paused
    assert show._dwell.isActive()
    show.close()


def test_back_at_the_end_shows_the_last_photo_paused(app: QApplication, state) -> None:
    show = _show(app, state, stop_after_one_round=True)
    _play_to_the_end(app, show)

    _press(show, Qt.Key.Key_Left)

    _pump(app, lambda: show._veil == 0.0)
    assert show._shown == 3, "the photo the round ended on, not the one before"
    assert show.paused
    assert not show.ended
    show.close()


def test_stepping_by_hand_past_the_end_plays_on(app: QApplication, state) -> None:
    show = _show(app, state, stop_after_one_round=True)
    for target in (1, 2, 3, 0):
        _press(show, Qt.Key.Key_Right)
        _pump(app, lambda target=target: show._shown == target)

    assert not show.ended
    show.close()


def test_a_one_round_show_ends_even_when_its_last_photo_is_unreadable(
    app: QApplication, state
) -> None:
    state.entries[3].absolute_path.write_bytes(b"broken")
    show = _show(app, state, stop_after_one_round=True)
    show._advance()
    _pump(app, lambda: show._shown == 1)
    show._advance()
    _pump(app, lambda: show._shown == 2)

    show._advance()
    _pump(app, lambda: show.ended)

    assert show._shown == 2
    assert show.blacked_out
    show.close()


def test_the_show_starts_at_the_given_photo(app: QApplication, state) -> None:
    show = SlideshowWindow(
        state.entries, SlideshowSettings(seconds=60, transitions=frozenset()), start_index=2
    )
    show.setGeometry(QRect(0, 0, 320, 200))
    show.show()

    _pump(app, lambda: show._shown == 2)
    show.close()


def test_mouse_clicks_step(app: QApplication, state) -> None:
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    show = _show(app, state)

    def click(button: Qt.MouseButton) -> None:
        show.mousePressEvent(
            QMouseEvent(
                QMouseEvent.Type.MouseButtonPress,
                QPointF(10, 10),
                QPointF(10, 10),
                button,
                button,
                Qt.KeyboardModifier.NoModifier,
            )
        )

    click(Qt.MouseButton.LeftButton)
    _pump(app, lambda: show._shown == 1)
    click(Qt.MouseButton.RightButton)
    _pump(app, lambda: show._shown == 0)
    show.close()


def test_the_dialog_keeps_the_new_options(app: QApplication) -> None:
    chosen = SlideshowSettings(stop_after_one_round=True, start_at_current=True, screen="HDMI-1")
    dialog = SlideshowDialog(
        chosen, selected_count=0, screens=(("eDP-1", "Laptop"), ("HDMI-1", "Beamer"))
    )

    assert dialog.settings == chosen
    assert dialog._screen.isVisibleTo(dialog)
    assert dialog._screen.currentText() == "Beamer"

    dialog._random.setChecked(True)
    assert not dialog._start_at_current.isEnabled()
    dialog.close()


def test_the_screen_choice_hides_with_one_screen_but_keeps_a_stored_one(
    app: QApplication,
) -> None:
    dialog = SlideshowDialog(
        SlideshowSettings(screen="HDMI-1"), selected_count=0, screens=(("eDP-1", "Laptop"),)
    )

    assert not dialog._screen.isVisibleTo(dialog)
    assert dialog.settings.screen == "HDMI-1", "a beamer that is unplugged now stays chosen"
    dialog.close()


def test_start_at_current_begins_at_the_cursor(
    app: QApplication, tmp_path: Path, library: Library, state
) -> None:
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    window._on_project_opened(state)
    window.go_to(2)

    window._on_slideshow_prepared(
        state.project.id,
        state.entries,
        SlideshowSettings(seconds=60, transitions=frozenset(), start_at_current=True),
    )

    show = window._slideshow
    _pump(app, lambda: show._shown == 2)
    show.close()
    _pump(app, lambda: window._slideshow is None)
    window.close()


def test_a_missing_screen_falls_back_to_the_one_fotozeef_is_on(
    app: QApplication, tmp_path: Path, library: Library, state
) -> None:
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))

    assert window._slideshow_screen(SlideshowSettings(screen="nope")) is window.screen()
    window.close()


def _click(show, button: Qt.MouseButton) -> None:
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    show.mousePressEvent(
        QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(10, 10),
            QPointF(10, 10),
            button,
            button,
            Qt.KeyboardModifier.NoModifier,
        )
    )


def _play_to_the_end(app: QApplication, show) -> None:
    """As the timer does: each step only once the photo before it is on screen."""
    for target in (1, 2, 3):
        show._advance()
        _pump(app, lambda target=target: show._shown == target)
    show._advance()
    _pump(app, lambda: show.ended)


def test_a_right_click_at_the_end_shows_the_last_photo(app: QApplication, state) -> None:
    show = _show(app, state, stop_after_one_round=True)
    _play_to_the_end(app, show)

    _click(show, Qt.MouseButton.RightButton)

    _pump(app, lambda: show._veil == 0.0)
    assert show._shown == 3
    assert show.paused
    show.close()


def test_a_left_click_at_the_end_plays_again(app: QApplication, state) -> None:
    show = _show(app, state, stop_after_one_round=True)
    _play_to_the_end(app, show)

    _click(show, Qt.MouseButton.LeftButton)

    _pump(app, lambda: show._shown == 0)
    assert not show.paused
    show.close()


def test_back_after_an_unreadable_tail_shows_the_last_readable_photo(
    app: QApplication, state
) -> None:
    state.entries[3].absolute_path.write_bytes(b"broken")
    show = _show(app, state, stop_after_one_round=True)
    for target in (1, 2):
        show._advance()
        _pump(app, lambda target=target: show._shown == target)
    show._advance()
    _pump(app, lambda: show.ended)

    _press(show, Qt.Key.Key_Left)

    _pump(app, lambda: show._veil == 0.0)
    assert show._shown == 2
    show.close()


def test_the_black_key_at_the_end_shows_the_last_photo(app: QApplication, state) -> None:
    show = _show(app, state, stop_after_one_round=True)
    _play_to_the_end(app, show)

    _press(show, Qt.Key.Key_B)

    _pump(app, lambda: show._veil == 0.0)
    assert show._shown == 3
    assert not show.ended
    show.close()


def test_a_slow_last_photo_is_shown_before_a_one_round_show_ends(
    app: QApplication, state, monkeypatch
) -> None:
    import threading

    from fotozeef.ui import slideshow_window

    gate = threading.Event()
    real = slideshow_window.render_slide

    def slow_last(path, width, height):
        if path.name == "3.jpg":
            gate.wait(5)
        return real(path, width, height)

    monkeypatch.setattr(slideshow_window, "render_slide", slow_last)
    show = _show(app, state, stop_after_one_round=True, seconds=1)
    _press(show, Qt.Key.Key_Right)
    _pump(app, lambda: show._shown == 1)
    _press(show, Qt.Key.Key_Right)
    _pump(app, lambda: show._shown == 2)
    _press(show, Qt.Key.Key_Right)

    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert not show.ended, "the old timer must not end the show while the last photo loads"

    gate.set()
    _pump(app, lambda: show._shown == 3)
    assert not show.ended
    show.close()


def test_left_from_a_mid_show_start_goes_to_the_earlier_photo(app: QApplication, state) -> None:
    show = SlideshowWindow(
        state.entries, SlideshowSettings(seconds=60, transitions=frozenset()), start_index=2
    )
    show.setGeometry(QRect(0, 0, 320, 200))
    show.show()
    _pump(app, lambda: show._shown == 2)

    _press(show, Qt.Key.Key_Left)

    _pump(app, lambda: show._shown == 1)
    show.close()


def test_a_one_round_show_starting_on_an_unreadable_last_photo_ends(
    app: QApplication, state
) -> None:
    state.entries[3].absolute_path.write_bytes(b"broken")
    show = SlideshowWindow(
        state.entries,
        SlideshowSettings(seconds=60, transitions=frozenset(), stop_after_one_round=True),
        start_index=3,
    )
    show.setGeometry(QRect(0, 0, 320, 200))
    show.show()

    _pump(app, lambda: show.ended)
    assert show._shown is None
    show.close()


def test_a_connected_stored_screen_is_used(
    app: QApplication, tmp_path: Path, library: Library
) -> None:
    from PySide6.QtGui import QGuiApplication

    from fotozeef.ui.main_window import screen_key

    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    screens = QGuiApplication.screens()
    target = screens[-1]

    chosen = window._slideshow_screen(SlideshowSettings(screen=screen_key(target, screens)))

    assert chosen is target
    window.close()


def test_random_order_ignores_start_at_current(
    app: QApplication, tmp_path: Path, library: Library, state
) -> None:
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    window._on_project_opened(state)
    window.go_to(3)

    window._on_slideshow_prepared(
        state.project.id,
        state.entries[:1],
        SlideshowSettings(order=SlideOrder.RANDOM, start_at_current=True, seconds=60),
    )

    show = window._slideshow
    _pump(app, lambda: show._shown == 0)
    show.close()
    _pump(app, lambda: window._slideshow is None)
    window.close()


class FakeScreen:
    def __init__(self, name: str, x: int, y: int = 0) -> None:
        self._name = name
        self._corner = (x, y)

    def name(self) -> str:
        return self._name

    def geometry(self):
        from PySide6.QtCore import QRect

        return QRect(self._corner[0], self._corner[1], 1920, 1080)


def test_screens_with_the_same_name_are_told_apart_by_place() -> None:
    from fotozeef.ui.main_window import find_screen, screen_key

    laptop = FakeScreen("Built-in Retina Display", 0)
    left = FakeScreen("DELL U2415", 1920)
    right = FakeScreen("DELL U2415", 3840)
    screens = [laptop, left, right]

    keys = [screen_key(screen, screens) for screen in screens]

    assert keys == ["Built-in Retina Display", "DELL U2415@1920,0", "DELL U2415@3840,0"]
    assert find_screen(keys[2], screens) is right
    assert find_screen("DELL U2415@9999,0", screens) is left, "moved: the first with that name"
    assert find_screen("DELL U2415", [laptop, right]) is right
    assert find_screen("HDMI-9", screens) is None
    assert find_screen("", screens) is None
