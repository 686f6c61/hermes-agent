"""Unit tests for the Docker container-env file transport (#96268 / #96316)."""

from __future__ import annotations

import stat
from pathlib import Path

from tools.environments.docker_env_transport import (
    format_container_env_file,
    open_container_env_file,
)


def test_format_env_file_is_stable_and_line_oriented():
    body = format_container_env_file({
        "GITLAB_TOKEN": "glpat-secret",
        "EMPTY": "",
        "DOCKER_HOST": "tcp://evil:2375",
    })
    assert body.splitlines() == [
        "DOCKER_HOST=tcp://evil:2375",
        "EMPTY=",
        "GITLAB_TOKEN=glpat-secret",
    ]


def test_format_skips_invalid_names():
    body = format_container_env_file({
        "GOOD": "ok",
        "123bad": "no",
        "also bad": "no",
    })
    assert body == "GOOD=ok\n"


def test_open_env_file_is_owner_only_and_unlinks(tmp_path):
    handle = open_container_env_file(
        {"GITLAB_TOKEN": "glpat-secret"},
        directory=str(tmp_path),
    )
    assert handle is not None
    path = Path(handle.path)
    assert path.is_file()
    mode = path.stat().st_mode
    assert stat.S_IMODE(mode) & 0o077 == 0
    assert "GITLAB_TOKEN=glpat-secret" in path.read_text(encoding="utf-8")
    handle.close()
    assert not path.exists()
    handle.close()  # idempotent


def test_open_env_file_none_when_empty():
    assert open_container_env_file({}) is None
    assert open_container_env_file(None) is None
