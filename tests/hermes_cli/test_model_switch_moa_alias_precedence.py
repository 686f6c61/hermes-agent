"""Regression tests for #134162: a user `model_alias` must outrank the stock
MoA preset named `default`.

`_route_from_model_input` checked MoA preset names BEFORE user aliases, and
the stock MoA config ships one enabled preset literally named `default`
(`DEFAULT_MOA_PRESET_NAME`). A user alias named `default` — a natural name for
"my everyday model" — could therefore never be reached: `/model default`
silently switched the session to the paid MoA aggregator. Explicit user
config now wins; MoA stays reachable via the picker, `--provider moa`, or a
non-colliding preset name (the #55187 opt-outs still apply).

Hermetic: alias resolution and every external lookup are mocked (no
network), mirroring `test_model_switch_configured_provider_routing.py`.
"""

from unittest.mock import patch

from hermes_cli.model_switch import switch_model

_ACCEPTED = {"accepted": True, "persist": True, "recognized": True, "message": None}


def _run_switch(*, raw_input, current_provider, alias_result, current_model="old-model"):
    """Drive `switch_model` with the resolution chain mocked out.

    `alias_result` stands in for `resolve_alias()` seeing a user-defined
    `model_aliases` entry; `load_config` returns an empty config so the stock
    MoA defaults (the enabled `default` preset) apply deterministically.
    """
    with patch("hermes_cli.model_switch.resolve_alias", return_value=alias_result), \
         patch("hermes_cli.config.load_config", return_value={}), \
         patch("hermes_cli.model_switch.list_provider_models", return_value=[]), \
         patch("hermes_cli.model_switch.normalize_model_for_provider", side_effect=lambda model, provider: model), \
         patch("hermes_cli.models_validate.validate_requested_model", return_value=_ACCEPTED), \
         patch("hermes_cli.models.detect_provider_for_model", return_value=None), \
         patch("hermes_cli.model_switch.get_model_info", return_value=None), \
         patch("hermes_cli.model_switch.get_model_capabilities", return_value=None), \
         patch(
             "hermes_cli.runtime_provider.resolve_runtime_provider",
             return_value={
                 "api_key": "***",
                 "base_url": "http://resolved/v1",
                 "api_mode": "",
             },
         ):
        return switch_model(
            raw_input=raw_input,
            current_provider=current_provider,
            current_model=current_model,
            current_base_url="",
            user_providers={},
            custom_providers=[],
        )


def test_user_alias_default_outranks_stock_moa_preset():
    """`/model default` with a user alias `default` routes to the alias, never
    to the stock MoA preset of the same name (#134162)."""
    result = _run_switch(
        raw_input="default",
        current_provider="openai-codex",
        alias_result=("openai-codex", "gpt-6.1-sol", "default"),
    )
    assert result.success is True, result.error_message
    assert result.target_provider == "openai-codex"
    assert result.new_model == "gpt-6.1-sol"


def test_non_alias_name_still_reaches_stock_moa_preset():
    """A bare name with no user alias still resolves the stock MoA preset —
    reordering the checks must not make MoA unreachable."""
    result = _run_switch(
        raw_input="default",
        current_provider="openai-codex",
        alias_result=None,
    )
    assert result.success is True, result.error_message
    assert result.target_provider == "moa"
    assert result.new_model == "default"
