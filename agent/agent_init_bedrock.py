"""Init glue for the ``bedrock_converse`` wire: boto3 directly, no OpenAI client.

Split out of ``agent/agent_init.py`` so the init facade stays inside its code-health line budget;
the behaviour is unchanged and the call site is ``_build_client``.
"""

from __future__ import annotations


def _init_bedrock_client(agent, base_url):
    """bedrock_converse: boto3 directly, no OpenAI client."""
    from agent.bedrock_adapter import bind_bedrock_runtime
    bind_bedrock_runtime(agent, base_url, "bedrock_converse")
    if not agent.quiet_mode:
        _gr_label = " + Guardrails" if agent._bedrock_guardrail_config else ""
        print(f"🤖 AI Agent initialized with model: {agent.model} (AWS Bedrock, {agent._bedrock_region}{_gr_label})")
