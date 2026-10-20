"""Regression tests: background spawns source ``terminal.shell_init_files`` (#142264).

The foreground snapshot (``LocalEnvironment._run_bash(login=True)``) prefixes the
command with a guarded ``source`` for every configured init file, so a ``PATH``
entry that lives only in one of those files is visible to foreground calls. The
background path (``ProcessRegistry._scope_argv``) builds ``$SHELL -lic`` and used
to skip that prelude, so the same command resolved a different interpreter.

Only an *explicit* ``terminal.shell_init_files`` needs the prelude: ``-lic``
already reads ~/.profile and ~/.bashrc by itself.
"""

import platform
import time

import pytest

import tools.environments.local as _local
import tools.process_registry as _pr
from tools.process_registry import ProcessRegistry


@pytest.fixture()
def registry():
    return ProcessRegistry()


@pytest.fixture(autouse=True)
def _no_systemd_scope(monkeypatch):
    """Keep the argv deterministic: no transient scope on a Linux dev host."""
    monkeypatch.setattr(_pr, "_SYSTEMD_SCOPE_AVAILABLE", False)
    monkeypatch.setattr(_pr, "_is_supervised_gateway_process", lambda: False)


def _init_file(tmp_path, body: str):
    path = tmp_path / "env.sh"
    path.write_text(body)
    return path


def test_configured_init_files_are_empty_without_an_explicit_list(monkeypatch):
    """The default list is what ``-lic`` reads anyway: no prelude, no double startup."""
    monkeypatch.setattr(_local, "_read_terminal_shell_init_config", lambda: ([], True))
    monkeypatch.setattr(_local, "_resolve_shell_init_files", lambda: ["/home/u/.profile"])

    assert _local._configured_shell_init_files() == []


def test_configured_init_files_follow_an_explicit_list(monkeypatch):
    monkeypatch.setattr(_local, "_read_terminal_shell_init_config", lambda: (["~/mytools/env.sh"], True))
    monkeypatch.setattr(_local, "_resolve_shell_init_files", lambda: ["/home/u/mytools/env.sh"])

    assert _local._configured_shell_init_files() == ["/home/u/mytools/env.sh"]


def test_scope_argv_sources_configured_init_files(registry, monkeypatch, tmp_path):
    """The spawn argv carries the same guarded source prelude as the foreground."""
    init_file = _init_file(tmp_path, 'export PATH="/mytools/bin:$PATH"\n')
    monkeypatch.setattr(_pr, "_find_shell", lambda: "/bin/bash")
    monkeypatch.setattr(
        _pr, "_configured_shell_init_files", lambda: [str(init_file)], raising=False
    )

    session = registry._new_session("echo hi", "", "", "", str(tmp_path))
    argv = registry._scope_argv(session, "echo hi", "unit", "Local")

    assert argv[:2] == ["/bin/bash", "-lic"]
    command = argv[2]
    assert f"[ -r '{init_file}' ] && . '{init_file}' 2>/dev/null || true" in command
    assert command.startswith("set +m; ")
    assert command.rstrip().endswith("echo hi")


def test_scope_argv_without_init_files_keeps_the_bare_command(registry, monkeypatch, tmp_path):
    """No explicit list means no prelude: the spawn stays exactly as before."""
    monkeypatch.setattr(_pr, "_find_shell", lambda: "/bin/bash")
    monkeypatch.setattr(_pr, "_configured_shell_init_files", list, raising=False)

    session = registry._new_session("echo hi", "", "", "", str(tmp_path))
    argv = registry._scope_argv(session, "echo hi", "unit", "Local")

    assert argv == ["/bin/bash", "-lic", "set +m; echo hi"]


@pytest.mark.skipif(platform.system() == "Windows", reason="POSIX login shell only")
def test_background_spawn_resolves_a_path_from_an_init_file(registry, monkeypatch, tmp_path):
    """End to end: a tool that exists only on the init-file PATH is found."""
    probe_dir = tmp_path / "mytools"
    probe_dir.mkdir()
    probe = probe_dir / "hermes-init-probe"
    probe.write_text("#!/bin/sh\necho from-init-file\n")
    probe.chmod(0o755)

    init_file = _init_file(tmp_path, f'export PATH="{probe_dir}:$PATH"\n')
    monkeypatch.setattr(
        _pr, "_configured_shell_init_files", lambda: [str(init_file)], raising=False
    )

    session = registry.spawn_local("command -v hermes-init-probe", cwd=str(tmp_path))
    deadline = time.time() + 30
    while time.time() < deadline:
        if registry.poll(session.id).get("status") == "exited":
            break
        time.sleep(0.1)

    output = registry.read_log(session.id)["output"]
    assert str(probe) in output, f"background spawn did not source the init file: {output!r}"
