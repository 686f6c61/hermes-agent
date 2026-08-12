"""ACP stdout bridge when host redirects stdout off a pipe (#84515)."""

from __future__ import annotations

import os
import stat
import tempfile

from acp_adapter.entry import _ensure_stdio_pipe_for_acp


def test_ensure_stdio_pipe_bridges_regular_file_and_restores():
    fd, path = tempfile.mkstemp(prefix="acp-pipe-test-")
    try:
        mode_before = os.fstat(fd).st_mode
        assert stat.S_ISREG(mode_before)

        class _S:
            def fileno(self):
                return fd

        restore = _ensure_stdio_pipe_for_acp(_S(), name="test")
        mode_bridged = os.fstat(fd).st_mode
        assert (
            stat.S_ISFIFO(mode_bridged)
            or stat.S_ISSOCK(mode_bridged)
            or stat.S_ISCHR(mode_bridged)
        ), f"expected pipe-like fd, got mode={mode_bridged:#o}"

        restore()
        mode_restored = os.fstat(fd).st_mode
        assert stat.S_ISREG(mode_restored), f"expected regular file after restore, got {mode_restored:#o}"
        # Restored fd must accept seeks again (pytest capture relies on this).
        os.lseek(fd, 0, os.SEEK_SET)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass


def test_pipe_like_stream_is_a_noop():
    r_fd, w_fd = os.pipe()
    try:
        class _S:
            def fileno(self):
                return w_fd

        restore = _ensure_stdio_pipe_for_acp(_S(), name="pipe")
        mode = os.fstat(w_fd).st_mode
        assert stat.S_ISFIFO(mode)
        restore()  # no-op path must still be callable
    finally:
        os.close(r_fd)
        os.close(w_fd)
