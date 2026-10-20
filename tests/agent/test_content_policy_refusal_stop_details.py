"""handle_content_policy_refusal: an Anthropic refusal with an empty body still tells the user why.

The structured reason on ``stop_details`` is the provider's verdict; the reasoning channel on a
halted stream carries the model's summarized thinking (a plan for the next step), so it may only
stand in when the provider said nothing (#142213).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.turn_retry_state import TurnRetryState
from agent.turn_truncation import handle_content_policy_refusal


def _agent(reasoning: str = ""):
    import agent.transports.anthropic
    from agent.transports import get_transport

    agent = MagicMock()
    agent.api_mode, agent.provider, agent.model, agent.log_prefix = "anthropic_messages", "anthropic", "claude", ""
    agent._is_anthropic_oauth = False
    agent._get_transport.return_value = get_transport("anthropic_messages")
    agent._has_pending_fallback.return_value = False
    agent._try_activate_fallback.return_value = False
    agent._extract_reasoning.return_value = reasoning
    return agent


def _refuse(agent, response):
    return handle_content_policy_refusal(
        agent, response, TurnRetryState(), thinking_spinner=None, messages=[], api_messages=[], api_kwargs={},
        active_system_prompt=None, conversation_history=[], api_call_count=1, effective_task_id="t", turn_id="u",
        api_request_id="r", api_start_time=0.0, retry_count=0, max_retries=0,
    )


def test_empty_refusal_reports_stop_details_explanation():
    response = SimpleNamespace(
        content=[], stop_reason="refusal", usage=None, model="claude",
        stop_details={"type": "refusal", "category": "general_harms", "explanation": "classifier halt"},
    )
    verdict = _refuse(_agent(), response)
    assert verdict.action == "return"
    assert "classifier halt" in verdict.result["error"]


def test_structured_reason_outranks_summarized_thinking():
    response = SimpleNamespace(
        content=[], stop_reason="refusal", usage=None, model="claude",
        stop_details={
            "type": "refusal",
            "category": "cyber",
            "explanation": "This request triggered restrictions on violative cyber content.",
        },
    )
    verdict = _refuse(_agent(reasoning="The reset reply should speak the menu actions aloud."), response)
    assert verdict.action == "return"
    assert verdict.result is not None
    rendered = f"{verdict.result.get('error')} {verdict.result.get('final_response', '')}"
    assert "violative cyber content" in rendered
    assert "speak the menu actions aloud" not in rendered


def test_reasoning_still_stands_in_when_the_provider_says_nothing():
    response = SimpleNamespace(content=[], stop_reason="refusal", usage=None, model="claude")
    verdict = _refuse(_agent(reasoning="The provider declined without a structured reason."), response)
    assert verdict.action == "return"
    assert verdict.result is not None
    rendered = f"{verdict.result.get('error')} {verdict.result.get('final_response', '')}"
    assert "declined without a structured reason" in rendered


def test_category_names_the_refusal_when_the_explanation_is_absent():
    response = SimpleNamespace(
        content=[], stop_reason="refusal", usage=None, model="claude",
        stop_details={"type": "refusal", "category": "cyber"},
    )
    verdict = _refuse(_agent(reasoning="thinking text that must not be shown"), response)
    assert verdict.action == "return"
    assert verdict.result is not None
    rendered = f"{verdict.result.get('error')} {verdict.result.get('final_response', '')}"
    assert "provider refusal category: cyber" in rendered
    assert "thinking text that must not be shown" not in rendered
