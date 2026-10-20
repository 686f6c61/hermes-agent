"""``process_manage`` bounds that arrive as JSON text instead of integers (#141988).

The tool schema declares ``offset``/``limit``/``timeout`` as integers, but a model can emit
``{"action": "log", "limit": "50"}`` and the handler forwards the value unchanged. An uncoerced
string bound reached ``lines[offset:offset + limit]`` and raised
``TypeError: slice indices must be integers or None or have an __index__ method``, so paging a
background process's log failed outright. These cover the paging path and the ``wait`` guard.
"""

import time

import pytest

from tools.process_registry import ProcessRegistry, ProcessSession


@pytest.fixture()
def registry():
    """Create a fresh ProcessRegistry."""
    return ProcessRegistry()


def _make_session(sid="proc_test123", output="", exited=False, exit_code=None) -> ProcessSession:
    """Helper to create a ProcessSession for testing."""
    return ProcessSession(
        id=sid,
        command="echo hello",
        task_id="t1",
        started_at=time.time(),
        exited=exited,
        exit_code=exit_code,
        output_buffer=output,
    )


def _log_of(n: int) -> str:
    return "\n".join([f"line {i}" for i in range(n)])


def test_paging_bounds_arriving_as_strings_page_the_log(registry):
    """A JSON tool argument can be a string; the slice must not raise TypeError (#141988)."""
    s = _make_session(output=_log_of(50))
    registry._running[s.id] = s
    result = registry.read_log(s.id, offset="10", limit="5")
    assert result["output"].splitlines() == [f"line {i}" for i in range(10, 15)]
    assert result["total_lines"] == 50
    # limit alone: the default offset is the tail, and the string must size it
    tail = registry.read_log(s.id, limit="3")
    assert tail["output"].splitlines() == [f"line {i}" for i in range(47, 50)]


def test_paging_bounds_arriving_as_floats_page_the_log(registry):
    """A float bound truncates to the whole line it names instead of raising (#141988)."""
    s = _make_session(output=_log_of(20))
    registry._running[s.id] = s
    result = registry.read_log(s.id, offset=5.0, limit=2.0)
    assert result["output"].splitlines() == ["line 5", "line 6"]


def test_unparseable_offset_is_a_tool_error_not_a_crash(registry):
    s = _make_session(output=_log_of(10))
    registry._running[s.id] = s
    result = registry.read_log(s.id, offset="all", limit="5")
    assert result["status"] == "error"
    assert "offset must be an integer" in result["error"]


def test_wait_timeout_arriving_as_a_string_is_a_tool_error():
    """Same JSON-argument class as the log bounds: compare ints, not str (#141988)."""
    result = ProcessRegistry().wait("proc_missing", timeout="soon")
    assert result["status"] == "error"
    assert "timeout must be an integer" in result["error"]


def test_int_arg_accepts_the_shapes_a_tool_call_sends():
    from tools.process_registry_paging import int_arg

    assert int_arg("12", "limit", 200) == 12
    assert int_arg(12.9, "limit", 200) == 12
    assert int_arg(None, "limit", 200) == 200
    assert int_arg("", "limit", 200) == 200
    assert int_arg(True, "limit", 200) == 200
    with pytest.raises(ValueError, match="limit must be an integer"):
        int_arg("many", "limit", 200)
