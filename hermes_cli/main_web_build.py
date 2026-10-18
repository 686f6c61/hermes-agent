"""Dashboard build freshness/serialization and checkout artifact sweep.

Split out of ``hermes_cli/main.py``. Names that still live in main (``PROJECT_ROOT``, ...)
are imported lazily inside the functions that use them (avoids an import cycle).
"""

import logging
import os
import subprocess
import sys

from pathlib import Path

# Log-record parity with the origin module.
logger = logging.getLogger("hermes_cli.main")

# Checkout fingerprint the bytecode cache was last validated against. Lives next
# to the checkout (NOT in HERMES_HOME): __pycache__ is per-checkout state shared
# by every profile.
_BYTECODE_FINGERPRINT_FILE = ".bytecode-fingerprint"

# Where compiled ``.js`` from a previous revision can shadow the current
# TypeScript sources (issue #132431). Both trees are Vite inputs, so an
# extensionless import resolves to the stale ``.js`` first.
_STALE_JS_ROOTS = ("apps/shared/src", "apps/desktop/src")


def _record_bytecode_fingerprint() -> None:
    """Persist the current checkout fingerprint after a bytecode sweep. Never raises."""
    from hermes_cli.main import PROJECT_ROOT, _read_git_revision_fingerprint
    try:
        fingerprint = _read_git_revision_fingerprint(PROJECT_ROOT)
        if not fingerprint:
            return
        stamp_path = PROJECT_ROOT / _BYTECODE_FINGERPRINT_FILE
        tmp_path = stamp_path.with_name(stamp_path.name + ".tmp")
        tmp_path.write_text(fingerprint, encoding="utf-8")
        tmp_path.replace(stamp_path)
    except OSError as exc:
        logger.debug("Could not record bytecode fingerprint: %s", exc)


def _sweep_stale_bytecode_if_checkout_changed() -> None:
    """Clear stale build artifacts at launch when the checkout fingerprint changed.

    Update-time clears can't close the stale-artifact class: ``hermes update`` runs
    the PRE-pull updater code and manual pulls never run it. Cheap file reads plus
    one scoped ``git ls-files`` per checkout change. Never raises.

    The stale-bytecode bug class (issues #6207, #60242; Dhruv's WhatsApp ``cannot import name
    'parse_model_flags_detailed'`` report) has one shared shape: the checkout's ``.py`` files change (git
    pull inside ``hermes update``, a manual ``git pull``, a ZIP update, a file-sync restore) while
    ``__pycache__`` retains bytecode from the previous revision, and a later process trusts the stale
    ``.pyc`` instead of the fresh source.

    The same shape bites the frontend (#132431): an interrupted update leaves compiled ``.js``
    next to the current ``.ts``/``.tsx`` sources, and an extensionless import resolves to the
    stale ``.js``, so the Vite build dies with ``MISSING_EXPORT`` for a symbol the current
    source does export.
    """
    from hermes_cli.main import PROJECT_ROOT, _clear_bytecode_cache, _read_git_revision_fingerprint
    try:
        fingerprint = _read_git_revision_fingerprint(PROJECT_ROOT)
        if not fingerprint:
            return  # non-git install — the ZIP update path clears explicitly
        stamp_path = PROJECT_ROOT / _BYTECODE_FINGERPRINT_FILE
        try:
            recorded = stamp_path.read_text(encoding="utf-8-sig").strip()
        except OSError:
            recorded = ""
        if recorded == fingerprint:
            return
        removed = _clear_bytecode_cache(PROJECT_ROOT)
        if removed:
            logger.info(
                "Checkout changed since last launch (%s -> %s): cleared %d stale __pycache__ director%s",
                recorded or "unknown", fingerprint, removed, "y" if removed == 1 else "ies",
            )
        shadowing = _clear_stale_shadowing_js(PROJECT_ROOT)
        if shadowing:
            logger.info(
                "Checkout changed since last launch (%s -> %s): removed %d stale .js file%s "
                "shadowing TypeScript sources",
                recorded or "unknown", fingerprint, shadowing, "" if shadowing == 1 else "s",
            )
        _record_bytecode_fingerprint()
    except Exception as exc:
        logger.debug("Stale-artifact launch sweep failed: %s", exc)


def _tracked_js_paths(root: Path) -> set[str] | None:
    """Repo-relative paths of the tracked ``.js`` files under the swept roots.

    ``None`` when git can't answer (not a checkout, git missing, git too slow):
    the sweep then removes nothing, because a tracked ``.js`` is source we must
    never delete.
    """
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z", "--", *_STALE_JS_ROOTS],
            cwd=root, capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("Could not list tracked sources under %s: %s", root, exc)
        return None
    if proc.returncode != 0:
        logger.debug("git ls-files failed under %s: %s", root, (proc.stderr or "").strip())
        return None
    return {path for path in proc.stdout.split("\0") if path.endswith(".js")}


def _clear_stale_shadowing_js(root: Path) -> int:
    """Remove untracked ``.js`` whose same-directory ``.ts``/``.tsx`` sibling exists.

    Only ``apps/shared/src`` and ``apps/desktop/src`` are walked, and only files git
    does not track are candidates: a ``.js`` without a TypeScript sibling and a
    committed ``.js`` are both left alone. Returns the number of files removed;
    a failure on one file never stops the sweep.
    """
    tracked = _tracked_js_paths(root)
    if tracked is None:
        return 0
    removed = 0
    for relative_root in _STALE_JS_ROOTS:
        walk_root = root / relative_root
        if not walk_root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(walk_root):
            dirnames[:] = [d for d in dirnames if d != "node_modules" and not d.startswith(".")]
            for name in filenames:
                if not name.endswith(".js"):
                    continue
                js_path = Path(dirpath) / name
                shadows = js_path.with_suffix(".ts").exists() or js_path.with_suffix(".tsx").exists()
                if not shadows:
                    continue
                if js_path.relative_to(root).as_posix() in tracked:
                    continue
                try:
                    js_path.unlink()
                    removed += 1
                except OSError as exc:
                    logger.debug("Could not remove stale %s: %s", js_path, exc)
    return removed


def _web_project_root(web_dir: Path) -> Path:
    """Repo root for a frontend dir (``web/`` or ``apps/<name>/``)."""
    return web_dir.parent.parent if web_dir.parent.name == "apps" else web_dir.parent


def _web_dist_dir(web_dir: Path) -> Path:
    """Vite outputs to ``hermes_cli/web_dist/`` (vite.config.ts outDir), NOT ``web/dist/``."""
    return _web_project_root(web_dir) / "hermes_cli" / "web_dist"


def _web_ui_build_needed(web_dir: Path) -> bool:
    from hermes_cli.source_build import source_product_current

    return not source_product_current(_web_project_root(web_dir), "web", _web_dist_dir(web_dir))


def _write_web_ui_build_stamp(project_root: Path, web_dir: Path) -> None:
    """Historical updater entrypoint; current builders publish their own receipts."""
    from hermes_cli._old_updater import stop_for_relaunch
    stop_for_relaunch()


def _console_print(text: str) -> None:
    """print() that survives cp1252-style consoles (arrow/check glyphs) via errors="replace"."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def _run_with_idle_timeout(
    cmd: list[str], cwd: Path, *, idle_timeout_seconds: int = 180, indent: str = "    ",
    env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Stop an old updater instead of running the retired build path."""
    from hermes_cli._old_updater import stop_for_relaunch
    stop_for_relaunch()


def _nixos_build_env() -> dict[str, str] | None:
    """Stop an old updater instead of running the retired build path."""
    from hermes_cli._old_updater import stop_for_relaunch
    stop_for_relaunch()


def _run_npm_install_deterministic(
    npm: str, cwd: Path, *, extra_args: tuple[str, ...] = (), capture_output: bool = True,
    env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Stop an old updater instead of running the retired build path."""
    from hermes_cli._old_updater import stop_for_relaunch
    stop_for_relaunch()


def _build_web_ui(web_dir: Path, *, fatal: bool = False) -> bool:
    """Serialize dashboard rebuilds, checking freshness only after acquiring the lock."""
    from hermes_cli.runtime_state import _lock

    if not (web_dir / "package.json").exists():
        return True
    try:
        with (_web_project_root(web_dir) / ".web_ui_build.lock").open("ab") as lock_file:
            _lock(lock_file.fileno(), wait=True)
            return _do_build_web_ui(web_dir, fatal=fatal)
    except OSError as exc:
        _console_print(f"  ✗ Could not lock the web UI build: {exc}")
        return False


def _do_build_web_ui(web_dir: Path, *, fatal: bool = False) -> bool:
    """Build stale dashboard sources; failure is never reported as a usable build."""
    from hermes_cli.source_build import build_source_web, prepare_launch_dependencies, source_build_env

    if not (web_dir / "package.json").exists() or not _web_ui_build_needed(web_dir):
        return True
    project_root = _web_project_root(web_dir)
    _console_print("→ Building web UI...")
    try:
        env = source_build_env()
        prepare_launch_dependencies(project_root, env=env)
        build_source_web(project_root, env=env)
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        _console_print(f"  {'✗' if fatal else '⚠'} Web UI build failed: {exc}")
        return False
    _console_print("  ✓ Web UI built")
    return True
