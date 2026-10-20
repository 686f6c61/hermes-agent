"""Paging bounds and output sizing for ``process_manage``.

The ``log`` action forwards ``offset``/``limit`` straight from the tool call and ``wait`` does the
same with ``timeout``, so a model that emits ``{"action": "log", "limit": "50"}`` reaches the
registry with a JSON string where the schema promised an integer. Those values are used as slice
bounds and in ``timeout <= 0``; a string bound raises ``TypeError: slice indices must be integers
or None or have an __index__ method`` and the whole log read fails as an internal crash (#141988).
Coercion lives here, beside the tail helpers it feeds, so the facade keeps only the call sites.
"""
from typing import Any

# Output chars a completion notification carries when the session does not size it.
COMPLETION_OUTPUT_CHARS = 2000
# Lines the ``log`` action pages when the call carries no ``limit`` (the schema default).
DEFAULT_LOG_LIMIT = 200


def int_arg(value: Any, name: str, default: int | None) -> int | None:
    """Coerce a numeric tool argument that arrived as JSON (str, float) to an int.

    An absent or blank value answers *default*. Anything that is not a whole number raises
    ``ValueError`` naming the argument, so the caller can answer with a named tool error instead
    of surfacing the mistake as an internal crash.
    """
    if value is None or value == "" or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer (got {value!r})") from None


def page_bounds(offset: Any, limit: Any) -> tuple[int | None, int, str | None]:
    """Coerce a log page's ``offset``/``limit``; answer ``(offset, limit, error)``."""
    try:
        page_offset = int_arg(offset, "offset", None)
        page_limit = int_arg(limit, "limit", DEFAULT_LOG_LIMIT)
    except ValueError as exc:
        return None, DEFAULT_LOG_LIMIT, str(exc)
    return page_offset, page_limit if page_limit is not None else DEFAULT_LOG_LIMIT, None


def output_tail(session: Any, n: int) -> str:
    """Last *n* chars of the session output with ANSI sequences stripped."""
    from tools.ansi_strip import strip_ansi

    return strip_ansi(session.output_buffer[-n:])


def completion_output(session: Any) -> dict:
    """``output`` sized by the session's ``completion_output_chars`` plus ``output_cut`` when trimmed.

    Shared by the completion notification AND the wait/poll/kill snapshots: a bot in an api_server
    or one-shot session cannot receive notifications and polls instead, so the polled result must
    carry the same whole reply and the same cut marker (#115334)."""
    limit = session.completion_output_chars or COMPLETION_OUTPUT_CHARS
    cut = len(session.output_buffer) - limit
    return {"output": output_tail(session, limit), "output_cut": cut} if cut > 0 else {"output": output_tail(session, limit)}
