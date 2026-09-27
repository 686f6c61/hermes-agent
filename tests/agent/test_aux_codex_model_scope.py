"""Auxiliary Codex selection must be scoped to the task model.

A year-long ``model_entitlement`` cooldown on one model name was hiding the
token from every other Codex auxiliary task, because selection did not pass
the model. See #125695.
"""

from agent.auxiliary_client import _resolve_codex_credential_and_base


class _Entry:
    runtime_api_key = "tok"
    base_url = "https://example.test/v1"


class _Pool:
    def __init__(self, seen):
        self._seen = seen

    def select(self, *, model=None):
        self._seen["model"] = model
        return _Entry()


def test_codex_aux_selection_passes_the_task_model(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "agent.auxiliary_client._load_pool_with_credentials",
        lambda *_args, **_kwargs: _Pool(seen),
    )
    monkeypatch.setattr("agent.auxiliary_client._codex_base_url_override", lambda: "")
    monkeypatch.setattr(
        "hermes_cli.auth_codex._codex_pool_route_base_url",
        lambda url: url,
    )

    token, base = _resolve_codex_credential_and_base(model="gpt-6-luna")

    assert seen["model"] == "gpt-6-luna"
    assert token == "tok"
    assert base == "https://example.test/v1"


def test_codex_aux_selection_without_a_model_stays_unscoped(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "agent.auxiliary_client._load_pool_with_credentials",
        lambda *_args, **_kwargs: _Pool(seen),
    )
    monkeypatch.setattr("agent.auxiliary_client._codex_base_url_override", lambda: "")
    monkeypatch.setattr(
        "hermes_cli.auth_codex._codex_pool_route_base_url",
        lambda url: url,
    )

    _resolve_codex_credential_and_base()

    assert seen["model"] is None
