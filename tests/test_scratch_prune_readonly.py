"""A read-only Git object inside an idle scratch entry does not wedge the prune.

Git writes loose objects and packfiles with ``FILE_ATTRIBUTE_READONLY`` on Windows, and
``os.unlink`` refuses those with ``WinError 5`` (``PermissionError``). The scratch collector used
to report that as an unremovable entry, so the clone stayed on disk and every session start
re-walked and re-failed it. POSIX has no such refusal — ``unlink`` only consults the parent
directory — so the Windows rule is injected in the two shape tests below.
"""

import errno
import os
import stat
import time

import pytest

import hermes_constants_scratch as scratch
import hermes_constants_scratch_stuck as stuck

OLD = time.time() - 48 * 3600
_READ_ONLY = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH


@pytest.fixture
def windows_unlink(monkeypatch):
    """Refuse to unlink a file whose write bit is clear, exactly as Windows does.

    ``shutil`` reaches ``os.unlink`` with a name relative to an inherited directory descriptor
    when the fd-based walk is available, so the paths created read-only by the test are resolved
    by basename against that set.
    """
    read_only: set[str] = set()
    real_unlink = os.unlink

    def unlink(path, *args, **kwargs):
        target = os.fspath(path)
        if not os.path.isabs(target):
            target = next((p for p in read_only if os.path.basename(p) == target), target)
        try:
            mode = os.lstat(target).st_mode
        except OSError:
            return real_unlink(path, *args, **kwargs)
        if not mode & stat.S_IWUSR:
            raise PermissionError(errno.EACCES, "Access is denied", target)
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", unlink)
    return read_only


def _read_only_clone(root, read_only, name="lane"):
    """``<name>/.git/objects/pack/pack-abc123.pack`` with the packfile read-only, plus one
    writable file so the walk has something to remove before it reaches the pack."""
    entry = root / name
    pack = entry / ".git" / "objects" / "pack"
    pack.mkdir(parents=True)
    (entry / "notes.txt").write_text("x", encoding="utf-8")
    packfile = pack / "pack-abc123.pack"
    packfile.write_text("pack", encoding="utf-8")
    for path in (entry / "notes.txt", packfile, pack, pack.parent, pack.parent.parent,
                 pack.parent.parent.parent, entry):
        os.utime(path, (OLD, OLD))
    packfile.chmod(_READ_ONLY)
    read_only.add(os.fspath(packfile))
    return entry, packfile


def test_read_only_object_is_removed_instead_of_reported(tmp_path, windows_unlink):
    entry, packfile = _read_only_clone(tmp_path, windows_unlink)
    assert stuck.rmtree_collecting_permission_errors(entry) == []
    assert not entry.exists()
    assert not packfile.exists()


def test_prune_removes_the_clone_and_does_not_record_it(tmp_path, windows_unlink, monkeypatch):
    root = tmp_path / "scratch"
    entry, _packfile = _read_only_clone(root, windows_unlink)
    monkeypatch.setattr(scratch, "reap_processes_rooted_in", lambda *_a, **_k: 0)
    log_file = tmp_path / "logs" / "scratch-prune.log"

    assert scratch.prune_idle_entries(root, 24, frozenset(), log_file) == 1
    assert not entry.exists()
    log = log_file.read_text(encoding="utf-8-sig")
    assert "could not fully remove" not in log
    assert "cannot remove" not in log


def test_owned_directory_this_user_cannot_write_is_still_a_blocker(tmp_path, windows_unlink):
    """The retry only helps where the write bit is the obstacle: an unwritable *parent* owned by
    this user is the case the stuck record exists for, and it must keep reporting."""
    entry = tmp_path / "lane"
    locked = entry / "locked"
    locked.mkdir(parents=True)
    (locked / "blob").write_text("x", encoding="utf-8")
    (entry / "notes.txt").write_text("x", encoding="utf-8")
    locked.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        blockers = stuck.rmtree_collecting_permission_errors(entry)
        assert blockers == [os.fspath(locked)]
        assert (locked / "blob").exists()
    finally:
        locked.chmod(0o700)
