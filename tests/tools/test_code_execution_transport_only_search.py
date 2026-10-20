"""The execute_code helper set follows the search backend's execution side.

`web.search_backend: openai-native` declares the Responses API `{"type": "web_search"}`
built-in and its provider never executes a search itself, so the transport drops the
client tool before the request goes out. The Python helper, the schema description and
the generated `hermes_tools` stub must stop offering it in that state — and keep
offering it for every backend that really searches in-process (#142175).
"""

import re

import pytest

from tools import code_execution_tool as cet


class _TransportOwned:
    name = "openai-native"

    def supports_client_search(self) -> bool:
        return False


class _ClientSide:
    name = "ddgs"

    def supports_client_search(self) -> bool:
        return True


@pytest.fixture
def active_provider(monkeypatch):
    """Point the registry's resolution at a stub provider."""
    import agent.web_search_registry as registry

    def _set(provider):
        monkeypatch.setattr(registry, "get_active_search_provider", lambda: provider)

    return _set


def test_transport_owned_search_leaves_the_sandbox_set(active_provider):
    active_provider(_TransportOwned())
    assert cet._sandbox_tools_for(["web_search", "terminal"]) == frozenset({"terminal"})


def test_transport_owned_search_is_dropped_from_the_everything_fallback(active_provider):
    active_provider(_TransportOwned())
    # An empty enabled_tools set means "every sandbox tool" — the fallback must not
    # reintroduce the helper it was filtered out of.
    assert "web_search" not in cet._sandbox_tools_for([])
    assert "web_extract" in cet._sandbox_tools_for([])


def test_client_side_search_keeps_the_helper(active_provider):
    active_provider(_ClientSide())
    assert "web_search" in cet._sandbox_tools_for(["web_search", "terminal"])


def test_unresolvable_backend_keeps_todays_advertisement(active_provider):
    active_provider(None)
    assert "web_search" in cet._sandbox_tools_for(["web_search", "terminal"])


def test_schema_stops_advertising_the_helper(active_provider):
    active_provider(_TransportOwned())
    schema = cet.build_execute_code_schema({"web_search", "web_extract", "terminal"})
    assert "web_search(" not in schema["description"]
    assert "web_extract(urls: list[str]" in schema["description"]  # the rest of the set stays
    code_arg = schema["parameters"]["properties"]["code"]["description"]
    assert "from hermes_tools import terminal" in code_arg
    assert "web_search" not in code_arg


def test_schema_keeps_the_helper_for_a_client_side_backend(active_provider):
    active_provider(_ClientSide())
    description = cet.build_execute_code_schema({"web_search", "terminal"})["description"]
    assert "web_search(query: str, limit: int = 5)" in description


def test_generated_module_has_no_stub_for_it(active_provider):
    active_provider(_TransportOwned())
    tools = cet._sandbox_tools_for(["web_search", "terminal"])
    source = cet.generate_hermes_tools_module(list(tools))
    assert "def web_search(" not in source
    assert "def terminal(" in source


def test_import_refusal_names_the_transport(active_provider):
    active_provider(_TransportOwned())
    match = re.search(r"cannot import name '(\w+)' from 'hermes_tools'",
                      "cannot import name 'web_search' from 'hermes_tools'")
    hint = cet._missing_hermes_tools_import_hint(match, ["terminal"])
    assert "server-side tool" in hint
    assert "normal tool call" in hint


def test_openai_native_provider_declares_no_client_side_search():
    from plugins.web.openai_native.provider import OpenAINativeWebSearchProvider

    provider = OpenAINativeWebSearchProvider()
    assert provider.supports_search() is True
    assert provider.supports_client_search() is False
