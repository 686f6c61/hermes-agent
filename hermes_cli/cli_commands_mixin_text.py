"""Text helpers split out of :mod:`hermes_cli.cli_commands_mixin` (file-line cap).
Re-imported there at call time so monkeypatches keep working."""


def _ellipsize(text: str, limit: int) -> str:
    """``text[:limit]`` plus ``...`` when truncated."""
    return f"{text[:limit]}{'...' if len(text) > limit else ''}"
