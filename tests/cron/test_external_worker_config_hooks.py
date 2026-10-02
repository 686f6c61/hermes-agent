"""External cron workers must register the owning profile's config hooks (#131764).

``python -m cron.scheduler --external-worker-file`` is a process of its own: the gateway's
startup registration (``run_startup._register_config_hooks``) never runs there, so the owning
profile's ``hooks:`` block and outbound webhook targets were silently dead for every
gateway-dispatched cron session. In-process cron inherited both from the gateway process.
The worker must run the same non-interactive registration once its secret scope exists, and a
registration failure must never fail the job (best-effort, like the gateway's).
"""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def profile_home(tmp_path, monkeypatch):
    """A launch home without hooks and an owning profile whose config declares them."""
    launch = tmp_path / "launch"
    launch.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(launch))
    profile = tmp_path / "profile"
    profile.mkdir(parents=True)
    (profile / "config.yaml").write_text(
        "hooks:\n"
        "  session_start:\n"
        "    - command: echo started\n"
        "hooks_auto_accept: true\n",
        encoding="utf-8",
    )
    return profile


def _payload(tmp_path, profile):
    payload = tmp_path / "payload.json"
    payload.write_text(
        json.dumps({"job": {"id": "job-1", "execution_id": "exec-1"},
                    "profile_home": str(profile), "multiplex_active": False}),
        encoding="utf-8",
    )
    return payload


def test_worker_registers_owning_profile_hooks_before_the_job(profile_home, tmp_path, monkeypatch):
    import cron.scheduler as scheduler
    from agent.secret_scope import current_secret_scope, current_secret_scope_home

    monkeypatch.setattr(
        "cron.executions.adopt_claimed_execution",
        lambda execution_id: {"id": execution_id, "status": "running"},
    )
    events = []

    def fake_shell_register(cfg, **kwargs):
        events.append({
            "kind": "hooks",
            "cfg": cfg,
            "accept_hooks": kwargs.get("accept_hooks"),
            "scope": current_secret_scope(),
            "scope_home": current_secret_scope_home(),
        })
        return []

    def fake_webhook_register(cfg):
        events.append({"kind": "webhooks", "cfg": cfg})
        return []

    def fake_run_one_job(job, **_kwargs):
        events.append({"kind": "job"})
        return True

    monkeypatch.setattr("agent.shell_hooks.register_from_config", fake_shell_register)
    monkeypatch.setattr("agent.outbound_webhooks.register_from_config", fake_webhook_register)
    monkeypatch.setattr(scheduler, "run_one_job", fake_run_one_job)

    assert scheduler._run_external_worker_payload(
        _payload(tmp_path, profile_home), tmp_path / "exec-1.ready"
    ) is True

    kinds = [event["kind"] for event in events]
    assert kinds.index("hooks") < kinds.index("job"), "shell hooks must register before the job runs"
    assert kinds.index("webhooks") < kinds.index("job"), "outbound webhooks must register before the job runs"

    hook_event = next(event for event in events if event["kind"] == "hooks")
    assert hook_event["accept_hooks"] is False, "the worker has no TTY; consent must come from env/config"
    assert hook_event["cfg"].get("hooks"), "registration must read the OWNING profile's config, not the launch home's"
    assert hook_event["scope"] is not None, "hooks must register inside the owning profile's secret scope"
    assert hook_event["scope_home"] == str(profile_home)

    webhook_event = next(event for event in events if event["kind"] == "webhooks")
    assert webhook_event["cfg"] is hook_event["cfg"], "webhook targets ride the same config read"


def test_worker_job_survives_hook_registration_failure(profile_home, tmp_path, monkeypatch):
    import cron.scheduler as scheduler

    monkeypatch.setattr(
        "cron.executions.adopt_claimed_execution",
        lambda execution_id: {"id": execution_id, "status": "running"},
    )

    def broken_register(cfg, **_kwargs):
        raise RuntimeError("hook registration exploded")

    monkeypatch.setattr("agent.shell_hooks.register_from_config", broken_register)
    ran = []
    monkeypatch.setattr(scheduler, "run_one_job", lambda job, **_kwargs: ran.append(job) or True)

    assert scheduler._run_external_worker_payload(
        _payload(tmp_path, profile_home), tmp_path / "exec-1.ready"
    ) is True, "a hook registration failure must not fail the job"
    assert ran, "the job must still run when hook registration fails"
