"""The slash worker inherits the parent agent's resolved route, base URL included (#141953).

``HermesCLI`` seeds ``base_url`` from ``model.base_url`` when the caller supplies none
(``hermes_cli/cli_init_mixin.py::_init_model_and_provider``). The worker forwarded only
``--model``/``--provider``, so a Codex session under a Claude default route
(``base_url: process://claude-subscription-directsdk-experimental``) built a CLI with
``provider=openai-codex`` and the Claude pseudo-URL — and ``/fast ultrafast`` gated on
``_fast_mode_route_supported``, which allows only ``chatgpt.com`` for that provider, so an
entitled model was refused before the account catalogue was ever read.
"""

from types import SimpleNamespace

from hermes_cli.models import resolve_fast_mode_overrides
from tui_gateway import server


class _Popen:
    """Capture the spawn argv without a real child."""

    def __init__(self, argv, **kw):
        self.argv = list(argv)
        self.stdout = self.stderr = iter(())
        self.stdin = None

    def poll(self):
        return 0


def _spawn(monkeypatch, **worker_kwargs) -> list[str]:
    captured = {}

    def _popen(argv, **kw):
        captured["argv"] = list(argv)
        return _Popen(argv, **kw)

    monkeypatch.setattr(server.subprocess, "Popen", _popen)
    server._SlashWorker("sess", "default", **worker_kwargs)
    return captured["argv"]


def test_slash_worker_argv_carries_the_base_url(monkeypatch):
    argv = _spawn(monkeypatch, provider="openai-codex",
                  base_url="https://chatgpt.com/backend-api/codex")

    assert argv[argv.index("--base-url") + 1] == "https://chatgpt.com/backend-api/codex"
    # the model/provider pins stay as they were
    assert argv[argv.index("--model") + 1] == "default"
    assert argv[argv.index("--provider") + 1] == "openai-codex"


def test_slash_worker_argv_omits_empty_base_url(monkeypatch):
    assert "--base-url" not in _spawn(monkeypatch, provider=None, base_url=None)


def test_restart_slash_worker_pins_the_live_agents_base_url(monkeypatch):
    """A model switch restarts the worker: it must take the session's new route with it."""

    class _Old:
        def close(self):
            pass

    worker_args = None

    class _RecordingWorker:
        def __init__(self, session_key, model, profile_home=None, provider=None, base_url=None):
            nonlocal worker_args
            worker_args = (session_key, model, profile_home, provider, base_url)

    agent = SimpleNamespace(model="gpt-6.1-sol-900k", provider="openai-codex",
                            base_url="https://chatgpt.com/backend-api/codex")
    session = {"session_key": "s-key", "agent": agent, "profile_home": None,
               "slash_worker": _Old()}

    monkeypatch.setattr(server, "_SlashWorker", _RecordingWorker)
    monkeypatch.setattr(server, "_attach_worker", lambda sid, session, worker: None)

    server._restart_slash_worker("sid", session)

    assert worker_args == ("s-key", "gpt-6.1-sol-900k", None, "openai-codex",
                           "https://chatgpt.com/backend-api/codex")


def test_slash_exec_spawns_with_the_live_agents_base_url(monkeypatch):
    """First-use spawn in ``slash.exec`` passes the session agent's resolved endpoint too."""
    worker_args = None

    class _RecordingWorker:
        def __init__(self, session_key, model, profile_home=None, provider=None, base_url=None):
            nonlocal worker_args
            worker_args = (session_key, model, profile_home, provider, base_url)
            self.stderr_tail = []

        def run(self, command):
            return "ok"

        def close(self):
            pass

    agent = SimpleNamespace(model="gpt-6.1-sol-900k", provider="openai-codex",
                            base_url="https://chatgpt.com/backend-api/codex")
    session = {"session_key": "s-key", "agent": agent, "profile_home": None, "running": False}

    monkeypatch.setattr(server, "_sessions", {"sid": session})
    monkeypatch.setattr(server, "_SlashWorker", _RecordingWorker)
    monkeypatch.setattr(server, "_sess_nowait", lambda params, rid: (session, None))
    monkeypatch.setattr(server, "_live_slash_command_output", lambda *a, **k: None)
    monkeypatch.setattr(server, "_is_snapshot_restore", lambda *a, **k: False)
    monkeypatch.setattr(server, "_mirror_slash_side_effects", lambda *a, **k: None)
    monkeypatch.setattr(server, "_resolve_model", lambda: "fallback-model")

    resp = server._methods["slash.exec"](1, {"session_id": "sid", "command": "/fast ultrafast"})

    assert "error" not in resp, resp
    assert worker_args is not None
    assert worker_args[4] == "https://chatgpt.com/backend-api/codex"


def test_slash_worker_child_forwards_base_url_to_hermes_cli(monkeypatch):
    """The child's argparse accepts ``--base-url`` and hands it to ``HermesCLI``: the pinned route
    is what ``/fast`` reads through ``cli.base_url``."""
    import sys as _sys
    import types

    import tui_gateway.slash_worker as sw

    built = {}

    class _FakeCLI:
        def __init__(self, **kwargs):
            built.update(kwargs)

    monkeypatch.setitem(_sys.modules, "cli", types.SimpleNamespace(HermesCLI=_FakeCLI))
    monkeypatch.setattr(sw, "_start_parent_death_watchdog", lambda *a: None)
    monkeypatch.setattr(sw, "_prepare_slash_worker_runtime", lambda: None)
    monkeypatch.setattr(sw.sys, "stdin", type("S", (), {"readline": lambda self: ""})())
    monkeypatch.setattr(_sys, "argv", ["slash_worker", "--session-key", "s", "--model", "m",
                                       "--provider", "openai-codex",
                                       "--base-url", "https://chatgpt.com/backend-api/codex"])

    sw.main()

    assert built.get("base_url") == "https://chatgpt.com/backend-api/codex"
    assert built.get("provider") == "openai-codex"


def test_the_route_gate_is_what_refuses_the_unpinned_seed():
    """Why the pin matters: the Codex gate accepts only ``chatgpt.com`` for this provider, so the
    Claude default's ``process://`` seed reads as unsupported even on an Ultrafast model."""
    model = "gpt-6.1-sol-900k"
    assert resolve_fast_mode_overrides(
        model, provider="openai-codex", base_url="process://claude-subscription-directsdk-experimental",
        tier="ultrafast") is None
    assert resolve_fast_mode_overrides(
        model, provider="openai-codex", base_url="https://chatgpt.com/backend-api/codex",
        tier="ultrafast") == {"service_tier": "ultrafast"}
