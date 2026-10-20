"""Gemini thought signatures survive a ``codex_responses`` round trip.

Gemini puts the signature on the ``function_call`` item itself
(``extra_content.google.thought_signature``); the chat-completions transport already replays that
sidecar, but the Responses adapter dropped it on both ends, so every tool step started a fresh
reasoning chain. These pin the capture, the replay and the preflight gate together.
"""

from types import SimpleNamespace

from agent.codex_responses_adapter import (
    _chat_messages_to_responses_input,
    _normalize_codex_response,
    _preflight_codex_input_items,
)
from agent.transports.codex import ResponsesApiTransport

_SIGNATURE = "sig-gemini-abc"
_EXTRA = {"google": {"thought_signature": _SIGNATURE}}


def _assistant_with_signed_call(extra_content=_EXTRA):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": "call_1", "call_id": "call_1", "type": "function",
            "function": {"name": "read", "arguments": "{\"path\": \"probe.txt\"}"},
            "extra_content": extra_content,
        }],
    }


def _function_call_items(items):
    return [item for item in items if item.get("type") == "function_call"]


def test_normalize_keeps_the_signature_on_the_tool_call():
    response = SimpleNamespace(
        status="completed",
        output=[SimpleNamespace(
            type="function_call", name="read", arguments="{\"path\": \"probe.txt\"}",
            call_id="call_1", id="fc_1", extra_content=_EXTRA,
        )],
    )
    message, finish_reason = _normalize_codex_response(response)
    assert finish_reason == "tool_calls"
    assert message.tool_calls[0].extra_content == _EXTRA


def test_normalize_reads_the_signature_from_model_extra():
    """Some SDKs park unknown response fields on ``model_extra`` instead of an attribute."""
    item = SimpleNamespace(
        type="function_call", name="read", arguments="{}", call_id="call_1", id="fc_1",
        model_extra={"extra_content": _EXTRA},
    )
    response = SimpleNamespace(status="completed", output=[item])
    message, _ = _normalize_codex_response(response)
    assert message.tool_calls[0].extra_content == _EXTRA


def test_replay_carries_the_signature_on_a_gemini_route():
    items = _chat_messages_to_responses_input([_assistant_with_signed_call()], replay_thought_signature=True)
    calls = _function_call_items(items)
    assert len(calls) == 1
    assert calls[0]["extra_content"] == _EXTRA


def test_replay_strips_the_signature_on_strict_routes():
    """Every non-Gemini Responses provider 400s on the unknown field, so the default wire has no sidecar."""
    items = _chat_messages_to_responses_input([_assistant_with_signed_call()])
    calls = _function_call_items(items)
    assert len(calls) == 1
    assert "extra_content" not in calls[0]


def test_replay_drops_an_empty_signature_even_on_a_gemini_route():
    """An empty sidecar makes a multimodal request fail with ``Corrupted thought signature``."""
    empty = {"google": {"thought_signature": ""}}
    items = _chat_messages_to_responses_input(
        [_assistant_with_signed_call(extra_content=empty)], replay_thought_signature=True,
    )
    calls = _function_call_items(items)
    assert len(calls) == 1
    assert "extra_content" not in calls[0]


def test_preflight_keeps_a_replayable_signature():
    raw = [{
        "type": "function_call", "call_id": "call_1", "name": "read",
        "arguments": "{}", "extra_content": _EXTRA,
    }]
    normalized = _preflight_codex_input_items(raw)
    assert normalized[0]["extra_content"] == _EXTRA


def test_preflight_drops_an_unusable_signature():
    raw = [{
        "type": "function_call", "call_id": "call_1", "name": "read",
        "arguments": "{}", "extra_content": {"google": {"thought_signature": ""}},
    }]
    normalized = _preflight_codex_input_items(raw)
    assert "extra_content" not in normalized[0]


def test_transport_gates_the_sidecar_on_the_wire_model():
    transport = ResponsesApiTransport()
    messages = [_assistant_with_signed_call()]

    gemini = transport.convert_messages(messages, model="google-antigravity/gemini-3.8-flash")
    assert _function_call_items(gemini)[0]["extra_content"] == _EXTRA

    openai = transport.convert_messages(messages, model="gpt-5.1")
    assert "extra_content" not in _function_call_items(openai)[0]
