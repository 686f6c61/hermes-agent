"""Unbounded executor for gateway turn bodies (see ``GatewayRunner._get_executor`` in gateway/run.py)."""

from __future__ import annotations

import concurrent.futures
import threading


class _UnboundedThreadExecutor(concurrent.futures.Executor):
    """One thread per submitted work item; no queue, no cap.

    ``ThreadPoolExecutor(max_workers=None)`` is NOT unbounded (it is ``min(32, cpu_count + 4)``),
    which is the same silent queue at a larger number. Exposes ``_threads`` and ``_shutdown`` like
    ``ThreadPoolExecutor`` so ``_stop_pool`` / ``_shutdown_executor`` join and count its workers.
    Not ``tools.daemon_pool.DaemonThreadPoolExecutor(sys.maxsize)``: that keeps idle workers alive
    until shutdown, whereas here each thread exits when its turn ends.
    """

    def __init__(self, thread_name_prefix: str = ""):
        self._prefix = thread_name_prefix
        self._threads: set = set()
        self._shutdown = False
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._spawning = 0
        self._n = 0

    def submit(self, fn, /, *args, **kwargs):
        fut: concurrent.futures.Future = concurrent.futures.Future()
        registered = threading.Event()

        def _run():
            try:
                if not fut.set_running_or_notify_cancel():
                    return
                try:
                    fut.set_result(fn(*args, **kwargs))
                except BaseException as exc:
                    fut.set_exception(exc)
            finally:
                # Blocks until submit() has registered this thread, so the discard never races the add.
                registered.wait()
                with self._lock:
                    self._threads.discard(threading.current_thread())

        # Only bookkeeping runs under _lock. ``t.start()`` is the slow step and it stays out: submit()
        # is reached from the gateway event loop (``run_in_executor``), and a finishing worker takes
        # this same lock to discard itself, so holding it across start() stalled the whole loop --
        # every platform's polling -- for as long as any spawn took (#142061).
        with self._lock:
            if self._shutdown:
                raise RuntimeError("cannot schedule new futures after shutdown")
            self._n += 1
            t = threading.Thread(target=_run, name=f"{self._prefix}_{self._n}", daemon=True)
            # Counted from here until it is registered, so a concurrent shutdown() waits for this
            # spawn instead of snapshotting _threads without it (a live, uncounted worker).
            self._spawning += 1
        try:
            # Start BEFORE registering: at the OS thread limit start() raises, and an unstarted thread
            # left in _threads would make shutdown's join() raise and skip the quiesce decision.
            t.start()
        except BaseException:
            with self._lock:
                self._spawning -= 1
                self._cond.notify_all()
            raise
        with self._lock:
            self._threads.add(t)
            self._spawning -= 1
            self._cond.notify_all()
        registered.set()
        return fut

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False):
        # cancel_futures is accepted for API parity only: there is no queue, so nothing is pending.
        with self._cond:
            self._shutdown = True
            # A submit() already past its _shutdown check is starting its thread outside the lock;
            # wait for it to register, or the snapshot below misses a live worker.
            while self._spawning:
                self._cond.wait()
            threads = list(self._threads)
        if wait:
            for t in threads:
                t.join()
