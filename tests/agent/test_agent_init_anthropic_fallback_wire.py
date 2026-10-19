"""Init must leave the Anthropic engine state set when an init-time fallback picks an
Anthropic-wire route.

``_build_client`` chooses the wire from the *primary's* ``api_mode``. When the primary route no
longer resolves, ``_init_openai_client`` walks the fallback chain and
``recompute_init_fallback_api_mode`` moves ``agent.api_mode`` to ``anthropic_messages`` for an
Anthropic-wire rung — after the OpenAI wire was already chosen. Everything downstream
(``_snapshot_primary_runtime`` at init, ``_request_anthropic_client_key`` per request) reads
``_anthropic_api_key``, so init has to bind that route's Anthropic state or the turn cannot start.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent import agent_init
from agent.primary_runtime_snapshot import _snapshot_primary_runtime


def _stub_agent():
    """An agent shaped like the one ``_build_client`` sees: OpenAI wire chosen for the primary."""
    return SimpleNamespace(
        api_mode="chat_completions",
        model="mimo-v2.6-flash",
        provider="commandcode",
        requested_provider="commandcode",
        base_url="https://api.commandcode.ai/provider/v1",
        api_key="primary-key",
        quiet_mode=True,
        request_overrides={},
        _client_kwargs={"api_key": "primary-key"},
        _use_prompt_caching=False,
        _use_native_cache_layout=False,
        _reasoning_echo_flag=False,
        context_compressor=SimpleNamespace(
            model="mimo-v2.6-flash",
            base_url="https://api.commandcode.ai/provider/v1",
            api_key="",
            provider="commandcode",
            context_length=200_000,
            threshold_tokens=150_000,
        ),
    )


def _bind_anthropic_fallback(agent, api_key, base_url, fallback_model, provider_timeout):
    """Stand-in for ``_init_openai_client`` when the primary resolves no credentials.

    This is what ``_routed_client_kwargs`` + ``recompute_init_fallback_api_mode`` leave behind:
    the route rewritten to the fallback rung, whose model is Anthropic-wire, and an OpenAI client
    built from that rung's kwargs.
    """
    agent.provider = agent.requested_provider = "opencode-go"
    agent.model = "claude-haiku-5-5"
    agent.api_mode = "anthropic_messages"
    agent.api_key = api_key = "fallback-key-1234"
    agent.base_url = base_url = "https://api.opencode.example/anthropic"
    agent._client_kwargs = {"api_key": api_key, "base_url": base_url}
    agent.client = MagicMock(name="openai_client_for_the_anthropic_rung")


def test_build_client_binds_the_anthropic_engine_of_an_init_time_fallback():
    agent = _stub_agent()
    built = MagicMock(name="anthropic_client")
    with (
        patch.object(agent_init, "_init_openai_client", _bind_anthropic_fallback),
        patch("agent.anthropic_adapter.build_anthropic_client", return_value=built),
    ):
        agent_init._build_client(agent, None, None, [{"provider": "opencode-go", "model": "claude-haiku-5-5"}])

    assert agent.api_mode == "anthropic_messages"
    assert agent._anthropic_api_key == "fallback-key-1234"
    assert agent._anthropic_base_url == "https://api.opencode.example/anthropic"
    assert agent._anthropic_client is built

    # The reported crash: the snapshot reads the attribute the line above has to have set.
    _snapshot_primary_runtime(agent)
    assert agent._primary_runtime["anthropic_api_key"] == "fallback-key-1234"
    assert agent._primary_runtime["anthropic_base_url"] == "https://api.opencode.example/anthropic"
