from __future__ import annotations

import logging
import random
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QObject,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPixmap,
    QScreen,
)
from PySide6.QtWidgets import QWidget

from fotozeef.core.models import TimelineEntry
from fotozeef.core.slideshow import (
    PauseMode,
    Sequencer,
    SlideshowSettings,
    Transition,
    choose_transition,
)
from fotozeef.core.thumbnails import render_slide
from fotozeef.ui.sleep_guard import SleepGuard, blocks_power_command

_log = logging.getLogger(__name__)

try:
    from ctypes import wintypes
except (ImportError, ValueError):  # pragma: no cover - only very old non-Windows builds
    wintypes = None  # type: ignore[assignment]

# Only Windows pays for reading native events; elsewhere nativeEvent returns at once.
_ON_WINDOWS = sys.platform == "win32" and wintypes is not None
_WINDOWS_MESSAGE = b"windows_generic_MSG"

TRANSITION_MS = 800
VEIL_MS = 400
CAPTION = QColor(150, 150, 156)


class SlideLoader(QObject):
    """Decodes slides off the GUI thread, most wanted first; stale requests are dropped."""

    loaded = Signal(int, QImage, QImage)
    failed = Signal(int, str)

    def __init__(self, width: int, height: int, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._size = (width, height)
        self._lock = threading.Lock()
        self._wanted: dict[int, Path] = {}
        self._decoding: int | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._closed = False

    def want(self, requests: list[tuple[int, Path]]) -> None:
        """Replaces whatever was queued; the first request is decoded first."""
        with self._lock:
            if self._closed:
                return
            self._wanted = {key: path for key, path in requests if key != self._decoding}
            if self._running or not self._wanted:
                return
            self._running = True
            self._thread = threading.Thread(target=self._drain, name="slides", daemon=True)
            self._thread.start()

    def shutdown(self) -> None:
        """Returns at once: a decode in flight finishes on its own and is never emitted."""
        with self._lock:
            self._closed = True
            self._wanted = {}

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self._wanted or self._closed:
                    self._running = False
                    return
                key = next(iter(self._wanted))
                path = self._wanted.pop(key)
                self._decoding = key
            try:
                slide = render_slide(path, *self._size)
            except Exception as error:
                with self._lock:
                    self._decoding = None
                    if not self._closed:
                        self.failed.emit(key, str(error))
                continue
            if self._is_closed():
                with self._lock:
                    self._decoding = None
                continue
            photo = QImage(
                slide.photo, slide.width, slide.height, slide.width * 3, QImage.Format.Format_RGB888
            ).copy()
            backdrop = QImage(
                slide.backdrop,
                slide.backdrop_width,
                slide.backdrop_height,
                slide.backdrop_width * 3,
                QImage.Format.Format_RGB888,
            ).copy()
            with self._lock:
                self._decoding = None
                if not self._closed:
                    self.loaded.emit(key, photo, backdrop)

    def _is_closed(self) -> bool:
        with self._lock:
            return self._closed


class SlideshowWindow(QWidget):
    """A fullscreen show. Space pauses, arrows or page keys step, Esc stops."""

    closed = Signal()

    def __init__(
        self,
        entries: tuple[TimelineEntry, ...],
        settings: SlideshowSettings,
        screen: QScreen | None = None,
        rng: random.Random | None = None,
        sleep_guard: SleepGuard | None = None,
        start_index: int = 0,
    ) -> None:
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self._sleep_guard = sleep_guard if sleep_guard is not None else SleepGuard()
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setWindowTitle(self.tr("Slideshow"))

        self._entries = entries
        self._settings = settings
        self._rng = rng or random.Random()
        self._sequencer = Sequencer(len(entries), settings.order, self._rng, start=start_index)
        self._ended = False
        self._automatic = False
        self._reached_end = False
        self._slides: dict[int, tuple[QPixmap, QPixmap]] = {}
        self._unreadable: set[int] = set()
        self._unreadable_round = 0
        self._shown: int | None = None
        self._outgoing: int | None = None
        self._pending: int | None = None
        self._direction = 1
        self._transition: Transition | None = None
        self._progress = 1.0
        self._paused = False
        self._black_resumes = False
        self._remaining_ms: int | None = None

        screen = screen or QGuiApplication.primaryScreen()
        if screen is not None:
            self.setScreen(screen)
            self.setGeometry(screen.geometry())
            ratio = screen.devicePixelRatio()
            size = screen.geometry().size()
            width, height = round(size.width() * ratio), round(size.height() * ratio)
        else:
            width, height = 1920, 1080
        # Parented, so Qt deletes it on this thread. The decode thread may outlive
        # the window by one photo; it then only touches plain Python state and,
        # being closed, never emits.
        self._loader = SlideLoader(max(1, width), max(1, height), self)
        self._loader.loaded.connect(self._on_loaded)
        self._loader.failed.connect(self._on_failed)

        self._dwell = QTimer(self)
        self._dwell.setSingleShot(True)
        self._dwell.timeout.connect(self._advance)

        self._animation = QVariantAnimation(self)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setDuration(TRANSITION_MS)
        self._animation.valueChanged.connect(self._on_progress)

        self._veil = 0.0
        self._veil_animation = QVariantAnimation(self)
        self._veil_animation.setDuration(VEIL_MS)
        self._veil_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._veil_animation.valueChanged.connect(self._on_veil)

        self._pending = self._sequencer.current
        self._request_slides()

    @property
    def current_index(self) -> int | None:
        """Playlist index on screen, or the one being waited for."""
        return self._pending if self._pending is not None else self._shown

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def blacked_out(self) -> bool:
        return self._paused and self._veil_target() > 0

    def start(self) -> None:
        self._sleep_guard.acquire()
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def next(self) -> None:
        self._go(self._sequencer.next(), direction=1)

    def previous(self) -> None:
        self._go(self._sequencer.previous(), direction=-1)

    def toggle_pause(self) -> None:
        if self._ended:
            self._restart()
        elif self._paused:
            self._resume()
        else:
            self._pause(black=self._settings.pause_mode is PauseMode.BLACK)

    def toggle_black(self) -> None:
        """The black-screen key of a presenter remote, whatever pausing is set to.

        Pressed again it goes back to how things were: playing, or a pause that
        was already there before the screen went black.
        """
        if self._paused and self._veil_target() > 0:
            self._ended = False
            if self._black_resumes:
                self._resume()
            else:
                self._fade_veil(0.0)
        elif self._paused:
            self._black_resumes = False
            self._fade_veil(1.0)
        else:
            self._pause(black=True)
            self._black_resumes = True

    def nativeEvent(self, event_type: object, message: object) -> tuple[bool, int]:
        """On Windows, turns down the screensaver and monitor-off while the show is in front."""
        if _ON_WINDOWS and event_type == _WINDOWS_MESSAGE:
            try:
                msg = wintypes.MSG.from_address(int(message))  # type: ignore[call-overload]
                if blocks_power_command(msg.message, msg.wParam, msg.lParam):
                    return True, 0
            except Exception:
                _log.debug("could not read a native event", exc_info=True)
        return super().nativeEvent(event_type, message)  # type: ignore[arg-type]

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
        elif key == Qt.Key.Key_Space:
            self.toggle_pause()
        elif key in (Qt.Key.Key_B, Qt.Key.Key_Period):
            self.toggle_black()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_PageDown):
            self.forward()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_PageUp):
            self.back()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """A click steps too, for a laptop beside the projector without a remote."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.forward()
        elif event.button() == Qt.MouseButton.RightButton:
            self.back()
        else:
            super().mousePressEvent(event)
            return
        event.accept()

    @property
    def ended(self) -> bool:
        """A show that stops after one round has played its last photo."""
        return self._ended

    def forward(self) -> None:
        self._automatic = False
        if self._ended:
            self._restart()
        else:
            self._step(self.next)

    def back(self) -> None:
        self._automatic = False
        self._ended = False
        self._step(self.previous)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._dwell.stop()
        self._animation.stop()
        self._veil_animation.stop()
        self._loader.shutdown()
        self._sleep_guard.release()
        super().closeEvent(event)
        self.closed.emit()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        canvas = QRectF(self.rect())
        if self._shown is None:
            self._draw_waiting(painter, canvas)
        elif self._outgoing is None or self._progress >= 1.0:
            self._draw_slide(painter, canvas, self._shown, QPointF(0, 0), 1.0)
        else:
            self._draw_transition(painter, canvas)
        if self._veil > 0:
            painter.fillRect(self.rect(), QColor(0, 0, 0, round(255 * self._veil)))
        painter.end()

    def _advance(self) -> None:
        """The timer's step. Unlike a step by hand, it may end a one-round show,
        also when the last photos of the round turn out to be unreadable."""
        self._automatic = True
        if self._stops_here():
            self._end()
            return
        self.next()

    def _stops_here(self) -> bool:
        return (
            self._automatic and self._settings.stop_after_one_round and self._sequencer.at_round_end
        )

    def _end(self) -> None:
        """Fades to black after the last photo and stays there."""
        self._pause(black=True)
        self._ended = True

    def _restart(self) -> None:
        """From the end, plays again from the start of the next round."""
        self._ended = False
        self._automatic = False
        self._remaining_ms = None
        self._resume()
        self.next()

    def _step(self, move: Callable[[], None]) -> None:
        """Manual steps keep a pause; a black pause turns into a held one."""
        if self._paused and self._veil_target() > 0:
            self._black_resumes = False
            self._fade_veil(0.0)
        self._remaining_ms = None
        move()

    def _go(self, index: int, direction: int) -> None:
        self._reached_end = False
        readable, self._direction = self._first_readable(index, direction)
        self._pending = readable
        if self._reached_end:
            self._end()
        elif readable is None:
            self._dwell.stop()
            self.update()
        elif readable in self._slides:
            self._show(readable)
        else:
            self._request_slides()

    def _first_readable(self, index: int, direction: int) -> tuple[int | None, int]:
        """Steps past photos that failed to decode, and says which way it ended up going.

        `index` must be the sequencer's current photo. Going back past the very first
        photo turns around. The bound covers a walk all the way back and forward
        again; only "every photo failed" stops the show. Failures are forgotten at
        each new round once something played, so a brief hiccup costs one round.
        """
        for _ in range(2 * len(self._entries) + 2):
            if self._shown is not None and self._sequencer.round > self._unreadable_round:
                self._unreadable.clear()
                self._unreadable_round = self._sequencer.round
            if index not in self._unreadable:
                return index, direction
            if len(self._unreadable) >= len(self._entries):
                return None, direction
            if direction < 0:
                earlier = self._sequencer.previous()
                if earlier != index:
                    index = earlier
                    continue
                direction = 1
            if self._stops_here():
                self._reached_end = True
                return None, direction
            index = self._sequencer.next()
        return None, direction

    def _show(self, index: int) -> None:
        self._pending = None
        if self._shown is None:
            self._outgoing = None
            self._transition = None
            self._progress = 1.0
        elif index != self._shown:
            self._outgoing = self._shown
            self._transition = choose_transition(self._settings.transitions, self._rng)
            self._progress = 0.0 if self._transition is not None else 1.0
        self._shown = index
        self._animation.stop()
        if self._transition is not None and self._progress < 1.0:
            curve = (
                QEasingCurve.Type.InOutQuad
                if self._transition is Transition.FADE
                else QEasingCurve.Type.OutCubic
            )
            self._animation.setEasingCurve(curve)
            self._animation.start()
        if not self._paused:
            self._dwell.start(self._settings.seconds * 1000)
        self._request_slides()
        self.update()

    def _request_slides(self) -> None:
        """Keeps the photo on screen and the next one; everything else is let go."""
        keep = [
            index
            for index in (self._pending, self._shown, self._sequencer.peek())
            if index is not None
        ]
        if self._outgoing is not None and self._progress < 1.0:
            keep.append(self._outgoing)
        for index in list(self._slides):
            if index not in keep:
                del self._slides[index]
        missing = [
            (index, self._entries[index].absolute_path)
            for index in dict.fromkeys(keep)
            if index not in self._slides and index not in self._unreadable
        ]
        self._loader.want(missing)

    def _on_loaded(self, index: int, photo: QImage, backdrop: QImage) -> None:
        self._slides[index] = (QPixmap.fromImage(photo), QPixmap.fromImage(backdrop))
        if index == self._pending:
            self._show(index)

    def _on_failed(self, index: int, _message: str) -> None:
        self._unreadable.add(index)
        if index == self._pending:
            self._go(index, self._direction)

    def _pause(self, black: bool) -> None:
        self._paused = True
        self._black_resumes = False
        if self._dwell.isActive():
            self._remaining_ms = self._dwell.remainingTime()
        self._dwell.stop()
        if black:
            self._fade_veil(1.0)

    def _resume(self) -> None:
        self._paused = False
        self._black_resumes = False
        black = self._veil_target() > 0
        if black:
            self._fade_veil(0.0)
        if self._shown is None or self._pending is not None:
            return
        remaining = self._remaining_ms
        self._remaining_ms = None
        if black or remaining is None or remaining <= 0:
            remaining = self._settings.seconds * 1000
        self._dwell.start(remaining)

    def _veil_target(self) -> float:
        if self._veil_animation.state() == QAbstractAnimation.State.Running:
            return float(self._veil_animation.endValue())
        return self._veil

    def _fade_veil(self, target: float) -> None:
        self._veil_animation.stop()
        self._veil_animation.setStartValue(self._veil)
        self._veil_animation.setEndValue(target)
        self._veil_animation.start()

    def _on_veil(self, value: object) -> None:
        self._veil = float(value)  # type: ignore[arg-type]
        self.update()

    def _on_progress(self, value: object) -> None:
        self._progress = float(value)  # type: ignore[arg-type]
        if self._progress >= 1.0:
            self._outgoing = None
        self.update()

    def _draw_transition(self, painter: QPainter, canvas: QRectF) -> None:
        assert self._outgoing is not None and self._shown is not None
        self._draw_slide(painter, canvas, self._outgoing, QPointF(0, 0), 1.0)
        progress = self._progress
        if self._transition is Transition.FADE:
            self._draw_slide(painter, canvas, self._shown, QPointF(0, 0), progress)
            return
        self._draw_slide(
            painter, canvas, self._shown, slide_offset(self._transition, progress, canvas), 1.0
        )

    def _draw_slide(
        self,
        painter: QPainter,
        canvas: QRectF,
        index: int,
        offset: QPointF,
        opacity: float,
    ) -> None:
        slide = self._slides.get(index)
        if slide is None:
            return
        photo, backdrop = slide
        frame = canvas.translated(offset)
        painter.save()
        painter.setOpacity(opacity)
        painter.drawPixmap(frame, backdrop, QRectF(backdrop.rect()))
        target = fit_rect(photo.width(), photo.height(), frame)
        painter.drawPixmap(target, photo, QRectF(photo.rect()))
        painter.restore()

    def _draw_waiting(self, painter: QPainter, canvas: QRectF) -> None:
        if len(self._unreadable) < len(self._entries):
            return
        painter.setPen(CAPTION)
        painter.drawText(
            canvas,
            int(Qt.AlignmentFlag.AlignCenter),
            self.tr("None of these photos could be read. Esc closes the slideshow."),
        )


def slide_offset(transition: Transition | None, progress: float, canvas: QRectF) -> QPointF:
    """Where an incoming photo sits: off screen on its own side at 0, in place at 1."""
    left = 1.0 - min(max(progress, 0.0), 1.0)
    if transition is Transition.SLIDE_LEFT:
        return QPointF(-canvas.width() * left, 0)
    if transition is Transition.SLIDE_RIGHT:
        return QPointF(canvas.width() * left, 0)
    if transition is Transition.SLIDE_TOP:
        return QPointF(0, -canvas.height() * left)
    if transition is Transition.SLIDE_BOTTOM:
        return QPointF(0, canvas.height() * left)
    return QPointF(0, 0)


def fit_rect(width: int, height: int, frame: QRectF) -> QRectF:
    """The largest rectangle with the photo's proportions that fits the frame, centred."""
    if width <= 0 or height <= 0:
        return QRectF(frame)
    scale = min(frame.width() / width, frame.height() / height)
    target = QRectF(0, 0, width * scale, height * scale)
    target.moveCenter(frame.center())
    return target
