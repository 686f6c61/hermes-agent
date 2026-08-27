"""Container env transport that never puts values in docker argv.

Two constraints, one mechanism:

- Linux ``/proc/<pid>/cmdline`` is world-readable, so ``-e KEY=VALUE``
  leaks allowlisted secrets to every local account (#96268).
- Copying those values into the docker-client subprocess environment
  would also retarget the CLI (``DOCKER_HOST``, ``DOCKER_CONTEXT``,
  TLS/proxy vars). A container-only ``docker_env.DOCKER_HOST`` must not
  change which daemon receives ``docker run`` / ``docker exec``.

Docker and Podman ``--env-file`` inject KEY=VALUE into the *container*
from a file. A 0600 temp file is owner-readable, not argv, and does not
mutate the client process environment.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Mapping
from typing import Any


_ENV_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ENV_FILE_PREFIX = "hermes-docker-env-"


def format_container_env_file(values: Mapping[str, str]) -> str:
    """Render docker ``--env-file`` contents. Names are validated; order is stable."""
    lines: list[str] = []
    for key in sorted(values):
        if not _ENV_VAR_NAME_RE.fullmatch(key):
            continue
        value = values[key]
        if value is None:
            continue
        # Env-file is line-oriented. Newlines would split a value into a
        # second KEY= line; flatten the same way a shell -e cannot span.
        text = str(value).replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
        lines.append(f"{key}={text}")
    return "\n".join(lines) + ("\n" if lines else "")


class ContainerEnvFile:
    """0600 temp env-file plus the ``--env-file`` argv fragment.

    ``close()`` is idempotent and always unlinks. ``wrap_process`` unlinks
    when the child is reaped so a long-lived ``Popen`` does not leave the
    file on disk after the command finishes.
    """

    def __init__(self, path: str):
        self.path = path
        self._closed = False

    def args(self) -> list[str]:
        return ["--env-file", self.path]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def wrap_process(self, proc: Any) -> Any:
        return _EnvFileProcess(proc, self)

    def __enter__(self) -> "ContainerEnvFile":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def open_container_env_file(
    values: Mapping[str, str] | None,
    *,
    directory: str | None = None,
) -> ContainerEnvFile | None:
    """Write *values* to a private env-file. ``None`` when there is nothing to inject."""
    if not values:
        return None
    body = format_container_env_file(values)
    if not body:
        return None
    fd, path = tempfile.mkstemp(
        prefix=_ENV_FILE_PREFIX, suffix=".env", dir=directory, text=True,
    )
    try:
        try:
            os.fchmod(fd, 0o600)
        except (AttributeError, OSError):
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fd = -1
            fh.write(body)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return ContainerEnvFile(path)


class _EnvFileProcess:
    """``ProcessHandle`` adapter that unlinks the env-file when the child ends."""

    def __init__(self, proc: Any, handle: ContainerEnvFile):
        self._proc = proc
        self._handle = handle

    def poll(self) -> int | None:
        code = self._proc.poll()
        if code is not None:
            self._handle.close()
        return code

    def wait(self, timeout: float | None = None) -> int:
        try:
            return self._proc.wait(timeout=timeout)
        finally:
            self._handle.close()

    def kill(self) -> None:
        self._proc.kill()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._proc, name)

    def __del__(self) -> None:
        self._handle.close()
