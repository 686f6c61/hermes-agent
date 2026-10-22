"""#142876: an uploaded payload is the attachment; the gateway's same-path file is not.

``file.attach`` resolved ``path`` on the gateway first and only fell back to ``data_url`` when
that path did not exist there. Two machines with the same username — or a container backend on
the same host — therefore staged the gateway's copy of the name the user picked, with no error.
"""

import base64
from pathlib import Path

import pytest

from tui_gateway import server

CLIENT_BYTES = b"NEW: written on the desktop\n"
GATEWAY_BYTES = b"OLD: already on the gateway host\n"


def _data_url(payload: bytes, mime: str = "text/markdown") -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"


@pytest.fixture
def gateway_home(tmp_path, monkeypatch):
    """The gateway's own tree: it holds files with the same names the client picked."""
    home = tmp_path / "gateway-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(server, "_hermes_home", home)
    monkeypatch.delenv("TERMINAL_ENV", raising=False)
    monkeypatch.delenv("TERMINAL_CWD", raising=False)
    monkeypatch.chdir(home)
    return home


def _session(workspace: Path, home: Path) -> dict:
    return {"cwd": str(workspace), "profile_home": str(home)}


def test_uploaded_bytes_win_over_a_same_path_file_outside_the_workspace(gateway_home, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    picked = gateway_home / "Downloads" / "report.md"
    picked.parent.mkdir()
    picked.write_bytes(GATEWAY_BYTES)

    stored, uploaded = server._stage_session_file_attachment(
        _session(workspace, gateway_home), raw_path=str(picked),
        data_url=_data_url(CLIENT_BYTES), name="report.md")

    assert uploaded is True
    assert stored.read_bytes() == CLIENT_BYTES
    assert stored.parent == (gateway_home / "attachments").resolve()


def test_uploaded_bytes_win_even_when_the_name_exists_in_the_workspace(gateway_home, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    twin = workspace / "report.md"
    twin.write_bytes(GATEWAY_BYTES)

    stored, uploaded = server._stage_session_file_attachment(
        _session(workspace, gateway_home), raw_path=str(twin),
        data_url=_data_url(CLIENT_BYTES), name="report.md")

    assert uploaded is True
    assert stored.read_bytes() == CLIENT_BYTES
    assert stored.parent == (gateway_home / "attachments").resolve()


def test_a_path_attachment_without_an_upload_keeps_the_gateway_file(gateway_home, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    inside = workspace / "notes.md"
    inside.write_bytes(GATEWAY_BYTES)
    outside = gateway_home / "Downloads" / "report.md"
    outside.parent.mkdir()
    outside.write_bytes(GATEWAY_BYTES)
    session = _session(workspace, gateway_home)

    in_place, uploaded_in_place = server._stage_session_file_attachment(
        session, raw_path=str(inside), data_url="", name="")
    copied, uploaded_copy = server._stage_session_file_attachment(
        session, raw_path=str(outside), data_url="", name="")

    assert (in_place, uploaded_in_place) == (inside.resolve(), False)
    assert uploaded_copy is True
    assert copied.read_bytes() == GATEWAY_BYTES


def test_neither_a_resolved_path_nor_a_payload_still_raises(gateway_home, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = _session(workspace, gateway_home)

    with pytest.raises(ValueError):
        server._stage_session_file_attachment(
            session, raw_path=str(workspace / "absent.md"), data_url="", name="")
    with pytest.raises(ValueError):
        server._stage_session_file_attachment(session, raw_path="", data_url="", name="")
