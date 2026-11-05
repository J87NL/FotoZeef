from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from fotozeef.ui import sleep_guard
from fotozeef.ui.sleep_guard import (
    ES_CONTINUOUS,
    ES_DISPLAY_REQUIRED,
    ES_SYSTEM_REQUIRED,
    DBusBackend,
    MacBackend,
    SleepGuard,
    WindowsBackend,
)


class FakeBackend:
    def __init__(self, result: bool = True, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[str] = []

    def acquire(self) -> bool:
        self.calls.append("acquire")
        if self.error is not None:
            raise self.error
        return self.result

    def release(self) -> None:
        self.calls.append("release")


def test_acquire_and_release_once() -> None:
    backend = FakeBackend()
    guard = SleepGuard(backend)

    guard.acquire()
    guard.acquire()
    assert guard.active
    guard.release()
    guard.release()

    assert backend.calls == ["acquire", "release"]
    assert not guard.active


def test_a_failing_platform_never_stops_the_show() -> None:
    backend = FakeBackend(error=OSError("no"))
    guard = SleepGuard(backend)

    guard.acquire()
    guard.release()

    assert not guard.active
    assert backend.calls == ["acquire"]


def test_a_refusal_is_not_released() -> None:
    backend = FakeBackend(result=False)
    guard = SleepGuard(backend)

    guard.acquire()
    guard.release()

    assert backend.calls == ["acquire"]


def test_an_unknown_platform_has_no_guard() -> None:
    guard = SleepGuard(None)
    guard.acquire()
    assert not guard.active


@pytest.mark.parametrize(
    ("platform", "kind"),
    [
        ("win32", WindowsBackend),
        ("darwin", MacBackend),
        ("linux", DBusBackend),
        ("freebsd14", DBusBackend),
        ("emscripten", type(None)),
    ],
)
def test_each_platform_gets_its_own_way(monkeypatch, platform: str, kind: type) -> None:
    monkeypatch.undo()
    assert isinstance(sleep_guard.default_backend(platform), kind)


def test_windows_keeps_display_and_system_awake_then_lets_go() -> None:
    flags: list[int] = []

    def set_state(value: int) -> int:
        flags.append(value)
        return ES_CONTINUOUS

    backend = WindowsBackend(set_state)

    assert backend.acquire()
    backend.release()

    assert flags == [ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED, ES_CONTINUOUS]


def test_windows_reports_a_failed_call() -> None:
    assert not WindowsBackend(lambda _flags: 0).acquire()


class FakeProcess:
    def __init__(self, hangs: bool = False) -> None:
        self.hangs = hangs
        self.events: list[str] = []

    def terminate(self) -> None:
        self.events.append("terminate")

    def wait(self, timeout: float) -> int:
        if self.hangs:
            raise subprocess.TimeoutExpired("caffeinate", timeout)
        return 0

    def kill(self) -> None:
        self.events.append("kill")


def test_macos_runs_caffeinate_tied_to_this_process() -> None:
    started: list[list[str]] = []
    process = FakeProcess()

    def popen(arguments, **_options):
        started.append(arguments)
        return process

    backend = MacBackend(popen, pid=4321)
    assert backend.acquire()
    backend.release()

    assert started == [["/usr/bin/caffeinate", "-d", "-i", "-w", "4321"]]
    assert process.events == ["terminate"]


def test_macos_kills_a_caffeinate_that_will_not_stop() -> None:
    process = FakeProcess(hangs=True)
    backend = MacBackend(lambda *_args, **_kwargs: process, pid=1)

    backend.acquire()
    backend.release()

    assert process.events == ["terminate", "kill"]


class FakeSession:
    def __init__(self, result: bool = True, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.closed = False

    def inhibit(self) -> bool:
        if self.error is not None:
            raise self.error
        return self.result

    def close(self) -> None:
        self.closed = True


def test_linux_keeps_its_connection_until_release() -> None:
    session = FakeSession()
    backend = DBusBackend(lambda: session)

    assert backend.acquire()
    assert not session.closed
    backend.release()

    assert session.closed


@pytest.mark.parametrize("session", [FakeSession(result=False), FakeSession(error=OSError("x"))])
def test_linux_closes_the_connection_when_refused(session: FakeSession) -> None:
    guard = SleepGuard(DBusBackend(lambda: session))

    guard.acquire()

    assert not guard.active
    assert session.closed


FAKE_SCREENSAVER = textwrap.dedent(
    """
    from PySide6.QtCore import ClassInfo, QCoreApplication, QObject, Slot
    from PySide6.QtDBus import QDBusConnection

    app = QCoreApplication([])

    @ClassInfo({"D-Bus Interface": "org.freedesktop.ScreenSaver"})
    class Saver(QObject):
        @Slot(str, str, result=int)
        def Inhibit(self, name, reason):
            print("INHIBIT", name, reason, flush=True)
            return 7

    bus = QDBusConnection.sessionBus()
    saver = Saver()
    bus.registerObject(
        "/org/freedesktop/ScreenSaver", saver, QDBusConnection.RegisterOption.ExportAllSlots
    )
    bus.registerService("org.freedesktop.ScreenSaver")
    print("READY", flush=True)
    app.exec()
    """
)

CLIENT = textwrap.dedent(
    """
    import subprocess, sys, time
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtDBus import QDBusConnection, QDBusInterface
    from fotozeef.ui.sleep_guard import DBusBackend, SleepGuard

    app = QCoreApplication([])
    saver = subprocess.Popen([sys.executable, sys.argv[1]], stdout=subprocess.PIPE, text=True)
    assert saver.stdout.readline().strip() == "READY"
    bus = QDBusInterface(
        "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
        QDBusConnection.sessionBus(),
    )

    def clients():
        return {n for n in bus.call("ListNames").arguments()[0] if n.startswith(":")}

    before = clients()
    guard = SleepGuard(DBusBackend())
    guard.acquire()
    print("active", guard.active, saver.stdout.readline().strip())
    print("held", len(clients() - before))
    guard.release()
    time.sleep(0.3)
    print("after", len(clients() - before))
    saver.kill()
    """
)


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or shutil.which("dbus-run-session") is None,
    reason="needs a Linux D-Bus daemon",
)
def test_linux_inhibits_on_a_real_session_bus(tmp_path: Path) -> None:
    saver = tmp_path / "saver.py"
    client = tmp_path / "client.py"
    saver.write_text(FAKE_SCREENSAVER)
    client.write_text(CLIENT)

    result = subprocess.run(
        ["dbus-run-session", "--", sys.executable, str(client), str(saver)],
        capture_output=True,
        text=True,
        timeout=60,
        env={**__import__("os").environ, "QT_QPA_PLATFORM": "offscreen"},
    )

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "active True INHIBIT FotoZeef Playing a slideshow"
    assert lines[1] == "held 1"
    assert lines[2] == "after 0"
