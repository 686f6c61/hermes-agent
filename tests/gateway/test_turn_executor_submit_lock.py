"""submit() must not hold the executor's bookkeeping lock across ``Thread.start()`` (#142061).

Every ``loop.run_in_executor(executor, ...)`` call enters ``_UnboundedThreadExecutor.submit()``
synchronously on the gateway event loop, and each worker re-takes the same lock in its ``finally``
to discard itself. With start() inside that critical section, one slow spawn or one exiting worker
stalled the whole loop -- all messaging platforms -- for the duration, which surfaced as Telegram
polling timeouts indistinguishable from network failures on a multi-profile gateway.
"""

from __future__ import annotations

import threading

import pytest

from gateway.turn_executor import _UnboundedThreadExecutor


def test_start_runs_outside_the_bookkeeping_lock(monkeypatch):
    pool = _UnboundedThreadExecutor(thread_name_prefix="executor-lock-probe")
    real_start = threading.Thread.start
    observed: dict[str, bool] = {}

    def probing_start(self):
        # What a finishing worker does in its ``finally``; it must never wait for a spawn.
        acquired = pool._lock.acquire(timeout=0.5)
        observed["lock_free_during_start"] = acquired
        if acquired:
            pool._lock.release()
        real_start(self)

    monkeypatch.setattr(threading.Thread, "start", probing_start)
    try:
        assert pool.submit(lambda: "done").result(timeout=5) == "done"
    finally:
        monkeypatch.undo()
        pool.shutdown(wait=True)

    assert observed["lock_free_during_start"] is True, (
        "submit() held the bookkeeping lock across Thread.start(), which blocks the event loop"
    )


def test_workers_still_deregister_and_shutdown_joins_them():
    pool = _UnboundedThreadExecutor(thread_name_prefix="executor-drain-probe")
    release = threading.Event()
    started = threading.Event()

    def body():
        started.set()
        assert release.wait(5)

    fut = pool.submit(body)
    assert started.wait(5)

    release.set()
    fut.result(timeout=5)
    pool.shutdown(wait=True)

    deadline = threading.Event()
    for _ in range(200):
        if not pool._threads:
            break
        deadline.wait(0.01)
    assert not pool._threads, f"workers left registered after exit: {pool._threads}"
    with pytest.raises(RuntimeError):
        pool.submit(lambda: None)
