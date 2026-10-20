"""A plugin tool's declared ``execution_timeout`` must survive ``PluginContext.register_tool``.

``tools.registry.register`` takes ``execution_timeout`` and the MCP path passes it
(``tools/mcp_tool_registration.py``), and ``agent.tool_dispatch_helpers._extend_tool_timeout``
lifts the generic per-call deadline up to it. Plugin tools had no way to declare one: the context
neither accepted nor forwarded the parameter, so a plugin that runs its own bounded subprocess was
cut off at ``_DEFAULT_CONCURRENT_TOOL_TIMEOUT_S`` (420 s) no matter what it declared (#141862).
"""
from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest


def _context(plugin_id: str) -> PluginContext:
    return PluginContext(manifest=PluginManifest(name=plugin_id, source="user"), manager=PluginManager())


def _schema(name: str) -> dict:
    return {"name": name, "description": "Plugin tool", "parameters": {"type": "object", "properties": {}}}


def test_register_tool_forwards_execution_timeout_to_the_registry():
    from agent.tool_dispatch_helpers import _extend_tool_timeout
    from tools.registry import registry

    ctx = _context("slow-review-plugin")
    try:
        assert ctx.register_tool(
            name="asked_agent_review",
            toolset="slow_review_plugin",
            schema=_schema("asked_agent_review"),
            handler=lambda args, **kw: "ok",
            execution_timeout=900,
        ) is not None
        entry = registry.get_entry("asked_agent_review")
        assert entry is not None
        assert entry.execution_timeout == 900
        # The executor raises the generic deadline to the declared one instead of cutting the tool short.
        assert _extend_tool_timeout("asked_agent_review", 420) == 900
    finally:
        registry.deregister("asked_agent_review")


def test_register_tool_without_execution_timeout_keeps_the_generic_deadline():
    from agent.tool_dispatch_helpers import _extend_tool_timeout
    from tools.registry import registry

    ctx = _context("plain-plugin")
    try:
        assert ctx.register_tool(
            name="plain_plugin_tool",
            toolset="plain_plugin",
            schema=_schema("plain_plugin_tool"),
            handler=lambda args, **kw: "ok",
        ) is not None
        entry = registry.get_entry("plain_plugin_tool")
        assert entry is not None and entry.execution_timeout is None
        assert _extend_tool_timeout("plain_plugin_tool", 420) == 420
    finally:
        registry.deregister("plain_plugin_tool")
