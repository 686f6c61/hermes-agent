"""Tests for the launch-time stale-artifact sweep (checkout fingerprint guard).

Bug class: the checkout's source files change (``hermes update``, manual
``git pull``, ZIP update) while build outputs from the previous revision
survive. Two victims share the shape: ``__pycache__`` retaining bytecode
compiled from the old ``.py`` (the next import dies with ``cannot import
name ...``, #6207/#60242), and compiled ``.js`` left next to the current
``.ts``/``.tsx`` sources, where an extensionless import resolves to the stale
``.js`` and the Vite build dies with ``MISSING_EXPORT`` (#132431).

The launch-time guard compares the current checkout fingerprint against the
last-validated stamp and sweeps both artifact classes once when they diverge —
covering paths no update-time clear can reach (manual pulls, pre-hardening
updaters).
"""

import os
import subprocess

from pathlib import Path

from hermes_cli import main as hermes_main
from hermes_cli import main_web_build


def _make_repo(tmp_path: Path, sha: str = "a" * 40) -> Path:
    """Minimal git checkout layout that _read_git_revision_fingerprint groks."""
    repo = tmp_path / "repo"
    git_dir = repo / ".git"
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git_dir / "refs" / "heads" / "main").write_text(sha + "\n", encoding="utf-8")
    return repo


def _make_pycache(repo: Path, subdir: str = "hermes_cli") -> Path:
    cache = repo / subdir / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "main.cpython-311.pyc").write_bytes(b"stale")
    return cache


def test_sweep_clears_pycache_when_checkout_changed(monkeypatch, tmp_path):
    repo = _make_repo(tmp_path, sha="b" * 40)
    cache = _make_pycache(repo)
    monkeypatch.setattr(hermes_main, "PROJECT_ROOT", repo)
    # Stamp records a different (older) fingerprint.
    (repo / main_web_build._BYTECODE_FINGERPRINT_FILE).write_text(
        "git:refs/heads/main:" + "a" * 40, encoding="utf-8"
    )

    hermes_main._sweep_stale_bytecode_if_checkout_changed()

    assert not cache.exists()
    # Stamp updated to the current fingerprint.
    recorded = (repo / main_web_build._BYTECODE_FINGERPRINT_FILE).read_text(encoding="utf-8")
    assert recorded.strip().endswith("b" * 40)







# ---------------------------------------------------------------------------
# Stale compiled .js shadowing the current TypeScript sources (#132431)
# ---------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "tester",
        "GIT_AUTHOR_EMAIL": "tester@example.com",
        "GIT_COMMITTER_NAME": "tester",
        "GIT_COMMITTER_EMAIL": "tester@example.com",
    }
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=env)


def _make_checkout(tmp_path: Path) -> Path:
    """Real checkout: a working git index is what tells tracked from untracked."""
    repo = tmp_path / "checkout"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    return repo


def _write(path: Path, text: str = "// stale\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_sweep_removes_untracked_js_shadowing_a_typescript_sibling(tmp_path):
    repo = _make_checkout(tmp_path)
    stale_desktop = _write(repo / "apps/desktop/src/chat/panel.js")
    _write(repo / "apps/desktop/src/chat/panel.ts")
    stale_shared = _write(repo / "apps/shared/src/ansi.js")
    _write(repo / "apps/shared/src/ansi.tsx")
    stale_nested = _write(repo / "apps/desktop/src/store/deep/nested.js")
    _write(repo / "apps/desktop/src/store/deep/nested.tsx")
    standalone = _write(repo / "apps/desktop/src/legacy/vendor.js")  # no TS sibling
    committed = _write(repo / "apps/desktop/src/shipped/contract.js")  # tracked source
    _write(repo / "apps/desktop/src/shipped/contract.ts")
    _git(repo, "add", "apps/desktop/src/shipped/contract.js")
    outside = _write(repo / "web/src/panel.js")  # not a swept tree
    _write(repo / "web/src/panel.ts")

    removed = main_web_build._clear_stale_shadowing_js(repo)

    assert removed == 3
    for gone in (stale_desktop, stale_shared, stale_nested):
        assert not gone.exists(), f"{gone} should have been swept"
    for kept in (standalone, committed, outside):
        assert kept.exists(), f"{kept} must be left alone"


def test_launch_sweep_removes_shadowing_js_when_checkout_changed(monkeypatch, tmp_path):
    repo = _make_checkout(tmp_path)
    stale = _write(repo / "apps/desktop/src/chat/panel.js")
    _write(repo / "apps/desktop/src/chat/panel.ts")
    _git(repo, "add", "apps/desktop/src/chat/panel.ts")
    _git(repo, "commit", "-q", "-m", "init")
    monkeypatch.setattr(hermes_main, "PROJECT_ROOT", repo)
    monkeypatch.setattr(hermes_main, "_clear_bytecode_cache", lambda *a, **k: 0)
    (repo / main_web_build._BYTECODE_FINGERPRINT_FILE).write_text(
        "git:refs/heads/main:" + "0" * 40, encoding="utf-8"
    )

    hermes_main._sweep_stale_bytecode_if_checkout_changed()

    assert not stale.exists()


def test_launch_sweep_leaves_js_alone_when_fingerprint_matches(monkeypatch, tmp_path):
    repo = _make_checkout(tmp_path)
    stale = _write(repo / "apps/desktop/src/chat/panel.js")
    _write(repo / "apps/desktop/src/chat/panel.ts")
    _git(repo, "add", "apps/desktop/src/chat/panel.ts")
    _git(repo, "commit", "-q", "-m", "init")
    monkeypatch.setattr(hermes_main, "PROJECT_ROOT", repo)
    monkeypatch.setattr(hermes_main, "_clear_bytecode_cache", lambda *a, **k: 0)
    # Stamp the current fingerprint: the sweep is one walk per checkout change.
    hermes_main._record_bytecode_fingerprint()

    hermes_main._sweep_stale_bytecode_if_checkout_changed()

    assert stale.exists()


def test_sweep_keeps_js_when_git_is_missing(monkeypatch, tmp_path):
    repo = tmp_path / "checkout"
    stale = _write(repo / "apps/desktop/src/chat/panel.js")
    _write(repo / "apps/desktop/src/chat/panel.ts")

    def _no_git(*args, **kwargs):
        raise OSError("git: command not found")

    monkeypatch.setattr(main_web_build.subprocess, "run", _no_git)

    assert main_web_build._clear_stale_shadowing_js(repo) == 0
    assert stale.exists()


def test_sweep_keeps_js_when_ls_files_fails(monkeypatch, tmp_path):
    repo = tmp_path / "checkout"
    stale = _write(repo / "apps/desktop/src/chat/panel.js")
    _write(repo / "apps/desktop/src/chat/panel.ts")
    failed = subprocess.CompletedProcess(
        args=["git"], returncode=128, stdout="", stderr="fatal: not a git repository"
    )
    monkeypatch.setattr(main_web_build.subprocess, "run", lambda *a, **k: failed)

    assert main_web_build._clear_stale_shadowing_js(repo) == 0
    assert stale.exists()


# ---------------------------------------------------------------------------
# Plugin-update sibling site: __pycache__ under ~/.hermes/plugins/<name>
# ---------------------------------------------------------------------------

def test_clear_plugin_bytecode_removes_nested_caches(tmp_path):
    from hermes_cli import plugins_cmd

    plugin = tmp_path / "myplugin"
    top = plugin / "__pycache__"
    nested = plugin / "sub" / "__pycache__"
    top.mkdir(parents=True)
    nested.mkdir(parents=True)
    (top / "a.pyc").write_bytes(b"stale")
    (nested / "b.pyc").write_bytes(b"stale")

    removed = plugins_cmd._clear_plugin_bytecode(plugin)

    assert removed == 2
    assert not top.exists()
    assert not nested.exists()


