"""The host's glibc, for gates that have to run before an artifact is fetched.

A pinned Linux archive can only exec against a glibc at or above the floor its
build image gave it; on a host below that floor the install can end in nothing
but a verification error after the download. Every reader here answers "no
floor" off glibc (musl, macOS, Windows), so those hosts are never gated.
"""

from __future__ import annotations

import os
import platform
import re

_CONFSTR = re.compile(r"glibc\s+(\d+)\.(\d+)")


def host_version() -> tuple[int, int] | None:
    """(major, minor) of the host's glibc, or None when the host has none."""
    reported = ""
    try:
        reported = os.confstr("CS_GNU_LIBC_VERSION") or ""
    except (AttributeError, OSError, ValueError):
        reported = ""
    if not reported:
        name, version = platform.libc_ver()
        reported = f"{name} {version}" if name else ""
    match = _CONFSTR.fullmatch(reported.strip())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def version_text(version: tuple[int, int]) -> str:
    return f"{version[0]}.{version[1]}"
