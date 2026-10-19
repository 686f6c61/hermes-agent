"""Terminal-subshell PATH completion in ``tools/environments/local.py``.

A backend started by a non-interactive SSH session, systemd or a GUI launcher
inherits a PATH without ``~/.local/bin`` (only the login shell adds it), so CLIs
installed there were ``command not found`` from the terminal tool (#111778).
"""

import os
import sys

import pytest

from tools.environments import local as local_mod
from tools.environments.local import (_append_missing_sane_path_entries, _make_run_env,
                                     terminal_path)

pytestmark = pytest.mark.platforms("posix")  # POSIX PATH completion only


def test_existing_user_local_bin_appended_after_inherited_entries(monkeypatch, tmp_path):
    local_bin = tmp_path / ".local" / "bin"
    local_bin.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(local_mod, "_git_bash_bin_dirs", list)
    monkeypatch.setattr(local_mod, "_managed_runtime_path_entries", list)
    monkeypatch.setattr(local_mod, "_resolve_hermes_bin_dir", lambda: None)

    entries = _make_run_env({})["PATH"].split(os.pathsep)

    assert entries[:2] == ["/usr/bin", "/bin"]
    assert entries.count(str(local_bin)) == 1
    # Already on PATH: position kept, no duplicate appended.
    already = _append_missing_sane_path_entries(f"{local_bin}:/usr/bin").split(":")
    assert already[0] == str(local_bin) and already.count(str(local_bin)) == 1


def test_missing_user_local_bin_not_appended(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(local_mod, "_managed_runtime_path_entries", list)

    assert ".local" not in _append_missing_sane_path_entries("/usr/bin:/bin")


def test_terminal_path_matches_the_spawn_env(monkeypatch, tmp_path):
    """One composition for both callers: what the probe resolves against is what the
    terminal's commands run with (#141700)."""
    local_bin = tmp_path / ".local" / "bin"
    local_bin.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(local_mod, "_git_bash_bin_dirs", list)
    monkeypatch.setattr(local_mod, "_managed_runtime_path_entries", list)
    monkeypatch.setattr(local_mod, "_resolve_hermes_bin_dir", lambda: None)

    assert terminal_path("/usr/bin:/bin") == _make_run_env({})["PATH"]


def test_login_shell_path_reads_the_login_shell(monkeypatch, tmp_path):
    """The terminal's PATH comes from a login shell (``bash -l`` over
    ``shell_init_files``), so the probe asks that shell instead of guessing."""
    shell = tmp_path / "bash"
    shell.write_text(
        "#!/bin/sh\n"
        "echo 'rc noise that must not confuse the parse'\n"
        "printf '__HERMES_LOGIN_PATH__%s' '/home/u/.nvm/bin:/usr/bin:/bin'\n"
    )
    shell.chmod(0o755)
    monkeypatch.setattr(local_mod, "_find_bash", lambda: str(shell))
    monkeypatch.setattr(local_mod, "_resolve_shell_init_files", list)

    assert local_mod.login_shell_path(timeout=5) == "/home/u/.nvm/bin:/usr/bin:/bin"


def test_login_shell_path_gives_up_on_a_failing_shell(monkeypatch, tmp_path):
    shell = tmp_path / "bash"
    shell.write_text("#!/bin/sh\nexit 1\n")
    shell.chmod(0o755)
    monkeypatch.setattr(local_mod, "_find_bash", lambda: str(shell))
    monkeypatch.setattr(local_mod, "_resolve_shell_init_files", list)

    assert local_mod.login_shell_path(timeout=5) is None


def test_terminal_tool_path_falls_back_to_the_composed_path(monkeypatch):
    monkeypatch.setattr(local_mod, "login_shell_path", lambda timeout=8.0: None)

    assert local_mod.terminal_tool_path() == terminal_path(
        local_mod._make_run_env({})["PATH"])
