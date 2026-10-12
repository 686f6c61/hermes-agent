"""`hermes import` reports every durable store it replaces with an older copy.

Regression for #137157: the older-over-newer guard counted only the session
store's ``sessions``/``messages`` tables. A kanban board has neither table, so
the count came back ``None`` for that member, the guard was skipped and a board
replaced with an older copy discarded committed cards and events with nothing
printed at all. Classify the database by what it holds instead.
"""

import sqlite3
import zipfile
from argparse import Namespace
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _no_real_gateway_service(monkeypatch):
    """``run_import`` auto-installs the gateway service; tests must not touch the host's."""
    import hermes_cli.gateway as gateway_mod

    monkeypatch.setattr(gateway_mod, "ensure_gateway_service", lambda **kw: False)
    monkeypatch.setattr(gateway_mod, "_is_service_running", lambda: False)


def _write_session_store(path: Path, sessions: int, messages: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT)")
        for i in range(sessions):
            conn.execute("INSERT INTO sessions (id) VALUES (?)", (f"s{i}",))
        for _ in range(messages):
            conn.execute("INSERT INTO messages (session_id) VALUES ('s0')")


def _write_board(path: Path, tasks: int, events: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, status TEXT)")
        conn.execute("CREATE TABLE task_events (id INTEGER PRIMARY KEY, kind TEXT)")
        for _ in range(tasks):
            conn.execute("INSERT INTO tasks (status) VALUES ('todo')")
        for _ in range(events):
            conn.execute("INSERT INTO task_events (kind) VALUES ('created')")


def _home(tmp_path, monkeypatch) -> Path:
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text("model: live\n")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return hermes_home


def _archive(tmp_path: Path, members: dict[str, Path]) -> Path:
    zip_path = tmp_path / "backup.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("config.yaml", "model: restored\n")
        for name, src in members.items():
            zf.write(src, name)
    return zip_path


def _import(zip_path: Path):
    from hermes_cli.backup import run_import

    return run_import(Namespace(zipfile=str(zip_path), force=True))


class TestCountStoreRows:
    def test_session_store_is_classified(self, tmp_path):
        path = tmp_path / "state.db"
        _write_session_store(path, 2, 5)

        from hermes_cli.backup_restore import _count_store_rows

        assert _count_store_rows(path) == ((2, 5), "session", "message")

    def test_board_is_classified(self, tmp_path):
        path = tmp_path / "kanban.db"
        _write_board(path, 3, 7)

        from hermes_cli.backup_restore import _count_store_rows

        assert _count_store_rows(path) == ((3, 7), "task", "event")

    def test_a_database_that_is_neither_store_is_unknown(self, tmp_path):
        path = tmp_path / "plugin.db"
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE sample (value TEXT)")

        from hermes_cli.backup_restore import _count_store_rows

        assert _count_store_rows(path) is None

    def test_a_missing_file_is_unknown(self, tmp_path):
        from hermes_cli.backup_restore import _count_store_rows

        assert _count_store_rows(tmp_path / "nope.db") is None


def test_import_reports_a_board_replaced_by_an_older_copy(tmp_path, monkeypatch, capsys):
    hermes_home = _home(tmp_path, monkeypatch)
    _write_session_store(hermes_home / "state.db", 9, 27)
    _write_board(hermes_home / "kanban.db", 6, 40)
    older = tmp_path / "older"
    _write_session_store(older / "state.db", 3, 9)
    _write_board(older / "kanban.db", 2, 10)

    zip_path = _archive(tmp_path, {"state.db": older / "state.db", "kanban.db": older / "kanban.db"})
    assert _import(zip_path) is None

    out = capsys.readouterr().out
    assert "Data replaced by older backup contents:" in out
    assert "state.db: 9 session(s) / 27 message(s) -> 3 / 9" in out
    assert "kanban.db: 6 task(s) / 40 event(s) -> 2 / 10" in out


def test_import_reports_a_board_with_no_session_store_in_the_archive(tmp_path, monkeypatch, capsys):
    """The board is the whole archive: a session-only count printed nothing at all."""
    hermes_home = _home(tmp_path, monkeypatch)
    _write_board(hermes_home / "kanban.db", 6, 40)
    older = tmp_path / "older"
    _write_board(older / "kanban.db", 2, 10)

    assert _import(_archive(tmp_path, {"kanban.db": older / "kanban.db"})) is None

    out = capsys.readouterr().out
    assert "Data replaced by older backup contents:" in out
    assert "kanban.db: 6 task(s) / 40 event(s) -> 2 / 10" in out


def test_import_reports_a_non_default_board_by_its_path(tmp_path, monkeypatch, capsys):
    """Same shape applies to ``kanban/boards/<slug>/kanban.db``."""
    hermes_home = _home(tmp_path, monkeypatch)
    rel = "kanban/boards/work/kanban.db"
    _write_board(hermes_home / rel, 6, 40)
    older = tmp_path / "older"
    _write_board(older / "kanban.db", 2, 10)

    assert _import(_archive(tmp_path, {rel: older / "kanban.db"})) is None

    out = capsys.readouterr().out
    assert f"{rel}: 6 task(s) / 40 event(s) -> 2 / 10" in out


def test_import_stays_silent_when_the_imported_board_is_newer(tmp_path, monkeypatch, capsys):
    hermes_home = _home(tmp_path, monkeypatch)
    _write_board(hermes_home / "kanban.db", 2, 10)
    newer = tmp_path / "newer"
    _write_board(newer / "kanban.db", 6, 40)

    assert _import(_archive(tmp_path, {"kanban.db": newer / "kanban.db"})) is None

    out = capsys.readouterr().out
    assert "older backup contents" not in out
    assert "kanban.db:" not in out


def test_import_does_not_report_a_database_that_is_neither_store(tmp_path, monkeypatch, capsys):
    hermes_home = _home(tmp_path, monkeypatch)
    with sqlite3.connect(hermes_home / "plugin.db") as conn:
        conn.execute("CREATE TABLE sample (value TEXT)")
        conn.executemany("INSERT INTO sample VALUES (?)", [("live",)] * 5)
    older = tmp_path / "older"
    older.mkdir()
    with sqlite3.connect(older / "plugin.db") as conn:
        conn.execute("CREATE TABLE sample (value TEXT)")
        conn.execute("INSERT INTO sample VALUES ('backup')")

    assert _import(_archive(tmp_path, {"plugin.db": older / "plugin.db"})) is None

    out = capsys.readouterr().out
    assert "older backup contents" not in out
    assert "plugin.db:" not in out
