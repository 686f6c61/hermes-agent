"""Tests for the launch-time stale-bytecode sweep (checkout fingerprint guard).

Bug class: the checkout's ``.py`` files change (``hermes update``, manual
``git pull``, ZIP update) while ``__pycache__`` retains bytecode compiled
from the previous revision; the next process to import trusts the stale
``.pyc`` and dies with ``cannot import name ...`` (#6207, #60242).

The launch-time guard compares the current checkout fingerprint against the
last-validated stamp and sweeps ``__pycache__`` once when they diverge —
covering paths no update-time clear can reach (manual pulls, pre-hardening
updaters).
"""

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
# Stale generated .js shadowing current TypeScript sources (#132431)
# ---------------------------------------------------------------------------

def _make_generated_js(repo: Path) -> Path:
    """app source tree with two shadowing artifacts and a legitimate standalone .js."""
    src = repo / "apps" / "desktop" / "src"
    src.mkdir(parents=True)
    (src / "index.ts").write_text("export const compactNumber = 1;\n", encoding="utf-8")
    (src / "index.js").write_text("stale compiled artifact\n", encoding="utf-8")
    (src / "widget.tsx").write_text("export default 1;\n", encoding="utf-8")
    (src / "widget.js").write_text("stale compiled artifact\n", encoding="utf-8")
    (src / "plugin.js").write_text("legitimate standalone .js\n", encoding="utf-8")
    deps = src / "node_modules" / "dep"
    deps.mkdir(parents=True)
    (deps / "index.js").write_text("dep\n", encoding="utf-8")
    return src


def test_sweep_clears_stale_generated_js_when_checkout_changed(monkeypatch, tmp_path):
    repo = _make_repo(tmp_path, sha="c" * 40)
    src = _make_generated_js(repo)
    monkeypatch.setattr(hermes_main, "PROJECT_ROOT", repo)
    (repo / main_web_build._BYTECODE_FINGERPRINT_FILE).write_text(
        "git:refs/heads/main:" + "a" * 40, encoding="utf-8"
    )

    hermes_main._sweep_stale_bytecode_if_checkout_changed()

    assert not (src / "index.js").exists()
    assert not (src / "widget.js").exists()
    # A .js with no .ts/.tsx sibling is legitimate; node_modules is never entered.
    assert (src / "plugin.js").exists()
    assert (src / "node_modules" / "dep" / "index.js").exists()
    # Sources survive.
    assert (src / "index.ts").exists()
    assert (src / "widget.tsx").exists()


def test_js_sweep_skipped_when_fingerprint_matches(monkeypatch, tmp_path):
    repo = _make_repo(tmp_path, sha="d" * 40)
    src = _make_generated_js(repo)
    monkeypatch.setattr(hermes_main, "PROJECT_ROOT", repo)
    from hermes_cli.main import _read_git_revision_fingerprint

    (repo / main_web_build._BYTECODE_FINGERPRINT_FILE).write_text(
        _read_git_revision_fingerprint(repo) or "", encoding="utf-8"
    )

    hermes_main._sweep_stale_bytecode_if_checkout_changed()

    assert (src / "index.js").exists()
    assert (src / "widget.js").exists()


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


