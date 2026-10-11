"""Regression coverage for unbounded ``tui_gateway_crash.log`` growth (#136624).

The crash log is best-effort forensics, but every writer appended without a
size cap: recurring benign events (restart/SIGHUP cycles land a
``gateway received`` + ``gateway exit`` pair each time, per-thread panics hit
the hooks) grew the file to 15 MB / 778 records on one host. Both Python
writers must rotate to a single ``.1`` generation before appending once the
file is over the cap, bounding the total at 2x the cap.
"""

from __future__ import annotations

from tui_gateway import entry, server


def test_record_crash_rotates_oversized_log(tmp_path, monkeypatch, capsys):
    crash_log = tmp_path / "tui_gateway_crash.log"
    crash_log.write_bytes(b"x" * 4096)
    monkeypatch.setattr(server, "_CRASH_LOG", str(crash_log))
    monkeypatch.setattr(server, "_CRASH_LOG_MAX_BYTES", 1024)

    server._record_crash("unhandled exception", ValueError, ValueError("boom"), None)

    rotated = tmp_path / "tui_gateway_crash.log.1"
    assert rotated.read_bytes() == b"x" * 4096
    assert "=== unhandled exception" in crash_log.read_text(encoding="utf-8")
    assert crash_log.stat().st_size < 4096


def test_record_crash_keeps_a_small_log_in_place(tmp_path, monkeypatch, capsys):
    crash_log = tmp_path / "tui_gateway_crash.log"
    crash_log.write_bytes(b"x" * 512)
    monkeypatch.setattr(server, "_CRASH_LOG", str(crash_log))
    monkeypatch.setattr(server, "_CRASH_LOG_MAX_BYTES", 1024)

    server._record_crash("unhandled exception", ValueError, ValueError("boom"), None)

    assert not (tmp_path / "tui_gateway_crash.log.1").exists()
    assert crash_log.read_bytes().startswith(b"x" * 512)
    assert b"=== unhandled exception" in crash_log.read_bytes()


def test_record_crash_without_existing_log_does_not_rotate(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(server, "_CRASH_LOG", str(tmp_path / "tui_gateway_crash.log"))

    server._record_crash("unhandled exception", ValueError, ValueError("boom"), None)

    assert (tmp_path / "tui_gateway_crash.log").exists()
    assert not (tmp_path / "tui_gateway_crash.log.1").exists()


def test_append_crash_log_rotates_oversized_log(tmp_path, monkeypatch):
    crash_log = tmp_path / "tui_gateway_crash.log"
    crash_log.write_bytes(b"y" * 4096)
    # entry imports _CRASH_LOG by value at module load, so both module attrs
    # must point at the temporary file for _append_crash_log to hit it.
    monkeypatch.setattr(server, "_CRASH_LOG", str(crash_log))
    monkeypatch.setattr(server, "_CRASH_LOG_MAX_BYTES", 1024)
    monkeypatch.setattr(entry, "_CRASH_LOG", str(crash_log))

    entry._append_crash_log("gateway exit · 2026-10-11 · reason=signal")

    rotated = tmp_path / "tui_gateway_crash.log.1"
    assert rotated.read_bytes() == b"y" * 4096
    assert "=== gateway exit" in crash_log.read_text(encoding="utf-8")


def test_append_crash_log_keeps_a_small_log_in_place(tmp_path, monkeypatch):
    crash_log = tmp_path / "tui_gateway_crash.log"
    crash_log.write_bytes(b"y" * 512)
    monkeypatch.setattr(server, "_CRASH_LOG", str(crash_log))
    monkeypatch.setattr(server, "_CRASH_LOG_MAX_BYTES", 1024)
    monkeypatch.setattr(entry, "_CRASH_LOG", str(crash_log))

    entry._append_crash_log("gateway exit · 2026-10-11 · reason=signal")

    assert not (tmp_path / "tui_gateway_crash.log.1").exists()
    assert crash_log.read_text(encoding="utf-8").startswith("y" * 512)
    assert "=== gateway exit" in crash_log.read_text(encoding="utf-8")
