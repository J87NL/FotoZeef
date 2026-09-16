from __future__ import annotations

import threading
import time

from fotozeef.ui.tasks import SelectionQueue


def test_a_submission_lands_while_the_previous_worker_is_still_alive() -> None:
    """The drain thread outlives its own loop, so aliveness must not gate restarts."""
    queue = SelectionQueue()
    ran = threading.Event()
    release = threading.Event()
    lingering = threading.Thread(target=release.wait, daemon=True)
    lingering.start()
    queue._thread = lingering

    queue.submit(1, True, ran.set)

    assert ran.wait(5)
    release.set()
    queue.flush()
    queue.close()


def test_a_burst_of_submissions_all_run() -> None:
    queue = SelectionQueue()
    completed: list[int] = []

    for index in range(200):
        queue.submit(index, True, lambda index=index: completed.append(index))
        if index % 7 == 0:
            time.sleep(0.001)

    queue.flush()
    queue.close()

    assert sorted(completed) == list(range(200))


def test_operations_run_in_submission_order() -> None:
    queue = SelectionQueue()
    seen: list[int] = []

    for index in range(50):
        queue.submit(index, True, lambda index=index: seen.append(index))
    queue.flush()
    queue.close()

    assert seen == list(range(50))


def test_a_failing_operation_does_not_stop_the_queue() -> None:
    queue = SelectionQueue()
    seen: list[int] = []

    def boom() -> None:
        raise RuntimeError("disk full")

    queue.submit(1, True, boom)
    for index in range(2, 10):
        queue.submit(index, True, lambda index=index: seen.append(index))
    queue.flush()
    queue.close()

    assert seen == list(range(2, 10))
