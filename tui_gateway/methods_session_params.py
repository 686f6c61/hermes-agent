"""Small parameter-parsing helpers split out of :mod:`tui_gateway.methods_session`
(file-line cap). Published onto server as ``_str_param``/``_flag``/``_int_param``
by that module's ``bind_module`` (split-module helpers keep their bare call sites)."""

from utils import is_truthy_value


def _str_param_impl(params: dict, key: str, default: str = "") -> str:
    """``str(params[key]).strip()`` with ``default`` for missing / falsy values."""
    return str(params.get(key) or "").strip() or default


def _flag_impl(params: dict, name: str) -> bool:
    return is_truthy_value(params.get(name, False))


def _int_param_impl(params: dict, key: str, default: int) -> int:
    """``int(params[key])`` with ``default`` for missing / unparsable values."""
    try:
        return int(params.get(key, default))
    except (TypeError, ValueError):
        return default
