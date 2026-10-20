"""Regression tests for GitHub #142011 — an ESTALE rename must take ``atomic_replace``'s fallback.

On overlayfs (and NFS) ``os.replace(tmp, target)`` can answer ``ESTALE`` ("Stale file handle")
when the target's dentry went stale underneath the mount, while the file itself is still writable
through its own path — the reporter's ``vim`` edit worked on it. ``atomic_replace`` only fell back
on EXDEV/EBUSY, so the write behind ``hermes model`` (``hermes_cli/config.py::save_env_value`` →
``_write_env_lines`` → ``atomic_replace``) re-raised and the model could not be committed.

The fix: ESTALE is one of the failures that never clears on retry, so it joins the copy fallback
bucket instead of being raised.
"""
from __future__ import annotations

import errno
import os
import sys
from pathlib import Path

import pytest

# Ensure the repo root is importable when running via `pytest tests/...`.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import utils

needs_estale = pytest.mark.skipif(not hasattr(errno, "ESTALE"), reason="platform errno has no ESTALE")


def _write_tmp(dir_: Path, content: str) -> Path:
    tmp = dir_ / ".env.tmp"
    tmp.write_text(content, encoding="utf-8")
    return tmp


@needs_estale
def test_stale_handle_rename_takes_the_copy_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / ".env"
    target.write_text("OLD=1\n", encoding="utf-8")
    tmp = _write_tmp(tmp_path, "NEW=1\n")

    calls: list[tuple[str, str]] = []

    def stale_rename(src: str, dst: str, *args: object, **kwargs: object) -> None:
        calls.append((src, dst))
        raise OSError(errno.ESTALE, os.strerror(errno.ESTALE))

    monkeypatch.setattr(utils.os, "replace", stale_rename)

    returned = utils.atomic_replace(tmp, target)

    assert Path(returned) == target
    # The rename is attempted once on the real target, then the fallback writes through the path.
    assert calls == [(str(tmp), str(target))]
    assert target.read_text(encoding="utf-8") == "NEW=1\n"
    assert not tmp.exists(), "the staged temp file must not survive a successful fallback"


@needs_estale
def test_stale_handle_is_in_the_rename_fallback_set() -> None:
    assert errno.ESTALE in utils._RENAME_FALLBACK_ERRNOS


@needs_estale
def test_stale_handle_on_a_symlinked_target_writes_the_real_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "profile" / "env"
    real.parent.mkdir()
    real.write_text("OLD=1\n", encoding="utf-8")
    link = tmp_path / ".env"
    link.symlink_to(real)
    tmp = _write_tmp(tmp_path, "NEW=1\n")

    def stale_rename(src: str, dst: str, *args: object, **kwargs: object) -> None:
        raise OSError(errno.ESTALE, os.strerror(errno.ESTALE))

    monkeypatch.setattr(utils.os, "replace", stale_rename)

    returned = utils.atomic_replace(tmp, link)

    assert link.is_symlink(), "the fallback must not detach a managed symlink"
    assert Path(returned) == real
    assert real.read_text(encoding="utf-8") == "NEW=1\n"
    assert not tmp.exists()


def test_an_errno_outside_the_fallback_set_still_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / ".env"
    target.write_text("OLD=1\n", encoding="utf-8")
    tmp = _write_tmp(tmp_path, "NEW=1\n")

    def denied(src: str, dst: str, *args: object, **kwargs: object) -> None:
        raise OSError(errno.EACCES, os.strerror(errno.EACCES))

    monkeypatch.setattr(utils.os, "replace", denied)

    with pytest.raises(OSError) as excinfo:
        utils.atomic_replace(tmp, target)

    assert excinfo.value.errno == errno.EACCES
    assert target.read_text(encoding="utf-8") == "OLD=1\n"
    assert tmp.exists(), "a failed write must leave the staged temp file for the caller"
