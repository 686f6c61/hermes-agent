"""submit_stdin line terminator: LF on POSIX/pipe, CR on Windows PTY (#83773)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from tools import process_registry as pr
from tools.process_registry import ProcessRegistry


def _put_session(registry: ProcessRegistry, session) -> None:
    with registry._lock:
        registry._running[session.id] = session


def test_submit_stdin_appends_lf_on_posix_pty(monkeypatch):
    monkeypatch.setattr(pr, "_IS_WINDOWS", False)
    registry = ProcessRegistry()
    session = MagicMock()
    session.id = "s1"
    session.exited = False
    session._pty = object()
    session.process = None
    _put_session(registry, session)

    with patch.object(registry, "write_stdin", return_value={"status": "ok"}) as w:
        registry.submit_stdin("s1", "hello")
    w.assert_called_once_with("s1", "hello\n")


def test_submit_stdin_appends_cr_on_windows_pty(monkeypatch):
    monkeypatch.setattr(pr, "_IS_WINDOWS", True)
    registry = ProcessRegistry()
    session = MagicMock()
    session.id = "s1"
    session.exited = False
    session._pty = object()
    session.process = None
    _put_session(registry, session)

    with patch.object(registry, "write_stdin", return_value={"status": "ok"}) as w:
        registry.submit_stdin("s1", "hello")
    w.assert_called_once_with("s1", "hello\r")


def test_submit_stdin_appends_lf_on_windows_pipe(monkeypatch):
    """Pipe (non-PTY) backend still uses LF even on Windows."""
    monkeypatch.setattr(pr, "_IS_WINDOWS", True)
    registry = ProcessRegistry()
    session = MagicMock()
    session.id = "s1"
    session.exited = False
    session._pty = None
    session.process = MagicMock()
    _put_session(registry, session)

    with patch.object(registry, "write_stdin", return_value={"status": "ok"}) as w:
        registry.submit_stdin("s1", "hello")
    w.assert_called_once_with("s1", "hello\n")
