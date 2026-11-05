from __future__ import annotations

import logging
import os
import subprocess
import sys
from collections.abc import Callable
from typing import Protocol

from fotozeef.appinfo import APP_NAME

_log = logging.getLogger(__name__)

REASON = "Playing a slideshow"

# SetThreadExecutionState flags, from winbase.h.
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

_FREEDESKTOP = (
    "org.freedesktop.ScreenSaver",
    "/org/freedesktop/ScreenSaver",
    "org.freedesktop.ScreenSaver",
)


class Backend(Protocol):
    def acquire(self) -> bool: ...

    def release(self) -> None: ...


class SleepGuard:
    """Keeps the screen awake and the screensaver away while a show runs.

    Each platform has its own way, so this never raises: when keeping the screen
    awake is not possible, the show simply plays on without it.
    """

    def __init__(self, backend: Backend | None = None) -> None:
        self._backend = backend if backend is not None else default_backend()
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def acquire(self) -> None:
        if self._active or self._backend is None:
            return
        try:
            self._active = bool(self._backend.acquire())
        except Exception:
            _log.warning("could not keep the screen awake", exc_info=True)
            self._active = False

    def release(self) -> None:
        if not self._active or self._backend is None:
            return
        self._active = False
        try:
            self._backend.release()
        except Exception:
            _log.warning("could not let the screen sleep again", exc_info=True)


def default_backend(platform: str = sys.platform) -> Backend | None:
    if platform == "win32":
        return WindowsBackend()
    if platform == "darwin":
        return MacBackend()
    if platform.startswith("linux") or "bsd" in platform:
        return DBusBackend()
    return None


class WindowsBackend:
    """SetThreadExecutionState; it belongs to the calling thread, the GUI thread here."""

    def __init__(self, set_state: Callable[[int], int] | None = None) -> None:
        self._set_state = set_state

    def acquire(self) -> bool:
        return self._call(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED) != 0

    def release(self) -> None:
        self._call(ES_CONTINUOUS)

    def _call(self, flags: int) -> int:
        if self._set_state is None:
            import ctypes

            function = ctypes.windll.kernel32.SetThreadExecutionState  # type: ignore[attr-defined]
            function.argtypes = [ctypes.c_uint32]
            function.restype = ctypes.c_uint32
            self._set_state = function
        return int(self._set_state(flags))


class MacBackend:
    """`caffeinate`, which ships with macOS; `-w` ends it if FotoZeef itself dies."""

    def __init__(
        self,
        popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        pid: int | None = None,
    ) -> None:
        self._popen = popen
        self._pid = pid if pid is not None else os.getpid()
        self._process: subprocess.Popen[bytes] | None = None

    def acquire(self) -> bool:
        self._process = self._popen(
            ["/usr/bin/caffeinate", "-d", "-i", "-w", str(self._pid)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True

    def release(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()


class InhibitSession(Protocol):
    def inhibit(self) -> bool: ...

    def close(self) -> None: ...


class DBusBackend:
    """The freedesktop screensaver inhibit, on a D-Bus connection of its own.

    Closing that connection ends the inhibit: screensavers drop the requests of a
    client that disconnects. That also sidesteps `UnInhibit`, whose unsigned cookie
    PySide cannot send back with the right D-Bus type.
    """

    def __init__(self, open_session: Callable[[], InhibitSession] | None = None) -> None:
        self._open_session = open_session or QtDBusSession
        self._session: InhibitSession | None = None

    def acquire(self) -> bool:
        session = self._open_session()
        try:
            held = session.inhibit()
        except Exception:
            session.close()
            raise
        if not held:
            session.close()
            return False
        self._session = session
        return True

    def release(self) -> None:
        session, self._session = self._session, None
        if session is not None:
            session.close()


class QtDBusSession:
    _counter = 0

    def __init__(self) -> None:
        from PySide6.QtDBus import QDBusConnection

        QtDBusSession._counter += 1
        self._name = f"fotozeef-sleep-guard-{os.getpid()}-{QtDBusSession._counter}"
        self._bus = QDBusConnection.connectToBus(QDBusConnection.BusType.SessionBus, self._name)

    def inhibit(self) -> bool:
        from PySide6.QtDBus import QDBusInterface, QDBusMessage

        if not self._bus.isConnected():
            _log.info("no D-Bus session bus; the screensaver may start during the show")
            return False
        service, path, interface = _FREEDESKTOP
        proxy = QDBusInterface(service, path, interface, self._bus)
        if not proxy.isValid():
            _log.info("%s is not available; the screensaver may start", service)
            return False
        reply = proxy.call("Inhibit", APP_NAME, REASON)
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            _log.info("the screensaver refused to stay away: %s", reply.errorMessage())
            return False
        return True

    def close(self) -> None:
        from PySide6.QtDBus import QDBusConnection

        QDBusConnection.disconnectFromBus(self._name)
