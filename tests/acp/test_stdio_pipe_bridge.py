"""ACP stdout bridge when host redirects stdout off a pipe (#84515)."""

from __future__ import annotations

import os
import stat
import tempfile

from acp_adapter.entry import _ensure_stdio_pipe_for_acp


def test_ensure_stdio_pipe_bridges_regular_file():
    fd, path = tempfile.mkstemp(prefix="acp-pipe-test-")
    try:
        mode_before = os.fstat(fd).st_mode
        assert stat.S_ISREG(mode_before)

        class _S:
            def fileno(self):
                return fd

        _ensure_stdio_pipe_for_acp(_S(), name="test")
        mode_after = os.fstat(fd).st_mode
        assert (
            stat.S_ISFIFO(mode_after)
            or stat.S_ISSOCK(mode_after)
            or stat.S_ISCHR(mode_after)
        ), f"expected pipe-like fd, got mode={mode_after:#o}"
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass
