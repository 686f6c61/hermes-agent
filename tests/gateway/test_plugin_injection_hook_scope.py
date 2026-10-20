"""An injected turn gets its own ``post_tool_call`` observers (#141867).

``ctx.inject_message`` called from a tool handler schedules the turn from that handler's thread, and
the sequential executor wraps the handler in ``model_tools.suppress_post_tool_call_hook()`` because
it owns the terminal post-tool event of the *injecting* call. A new task copies the scheduling
context, so before the fix every tool in the injected turn saw the flag set: no observer fired, no
log line, no failure. The injected turn is its own turn and must emit.
"""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

import model_tools
from gateway.config import Platform
from gateway.run_plugin_injection import GatewayPluginInjectionMixin

ORIGIN = {"platform": "telegram", "chat_id": "chat1", "chat_type": "group"}


class _Runner(GatewayPluginInjectionMixin):
    """The scheduling half of the mixin, with admission and dispatch stubbed by the test."""

    def __init__(self, loop):
        self._gateway_loop = loop
        self._running = True
        self._background_tasks = set()
        self.seen: list[bool] = []
        self.hooks: list[str] = []

    def _plugin_origin_source(self, origin, *, plugin_home=None, plugin_id="") -> Any:
        return SimpleNamespace(platform=Platform.TELEGRAM, chat_id=str(origin.get("chat_id", "")))

    def _plugin_origin_admissible(self, source, *, plugin_home=None, plugin_id=""):
        return True

    async def _dispatch_plugin_origin_injection(self, *, source, content, plugin_id):
        self.seen.append(model_tools._post_tool_call_hook_suppressed.get())
        model_tools._emit_post_tool_call_hook(
            function_name="read_file", function_args={"path": "notes.md"}, result="ok",
        )
        return True


@pytest.fixture
def recorded_hooks(monkeypatch):
    """Record the hooks the emitter would invoke, without a plugin manager in the way."""
    from hermes_cli import lifecycle

    names: list[str] = []
    monkeypatch.setattr(lifecycle, "has_hook", lambda name: name == "post_tool_call")
    monkeypatch.setattr(lifecycle, "invoke_hook", lambda name, **kwargs: names.append(name))
    return names


async def _run_one(runner) -> None:
    """Let the injected turn run to completion."""
    tasks = [task for task in runner._background_tasks]
    assert tasks, "the injection was not scheduled"
    await tasks[0]


def test_a_turn_injected_from_inside_a_tool_call_emits_post_tool_call(recorded_hooks):
    async def scenario():
        runner = _Runner(asyncio.get_running_loop())
        with model_tools.suppress_post_tool_call_hook():
            assert runner._schedule_plugin_message_injection(
                content="go", plugin_id="desk", origin=ORIGIN,
            ) is True
            await _run_one(runner)
            caller_flag = model_tools._post_tool_call_hook_suppressed.get()
        return runner, caller_flag

    runner, caller_flag = asyncio.run(scenario())

    assert runner.seen == [False], "the injected turn inherited the injecting call's suppression"
    assert recorded_hooks == ["post_tool_call"]
    assert caller_flag is True, "the injecting call must keep owning its own terminal event"


def test_a_turn_injected_outside_a_tool_call_still_emits(recorded_hooks):
    async def scenario():
        runner = _Runner(asyncio.get_running_loop())
        assert runner._schedule_plugin_message_injection(
            content="go", plugin_id="desk", origin=ORIGIN,
        ) is True
        await _run_one(runner)
        return runner

    runner = asyncio.run(scenario())

    assert runner.seen == [False]
    assert recorded_hooks == ["post_tool_call"]
    assert model_tools._post_tool_call_hook_suppressed.get() is False
