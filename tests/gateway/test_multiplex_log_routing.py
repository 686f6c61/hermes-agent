"""Multiplex gateway log routing (#82936, salvage of #84954).

``setup_logging(mode="gateway")`` binds agent.log/errors.log/gateway.log to
the launch home. Under ``multiplex_profiles`` every secondary profile's
records — emitted inside ``_profile_runtime_scope`` — used to fan out into
the DEFAULT profile's files. The gateway now enables the #99440 profile
routers at startup so each record lands in its owner's ``logs/``.
"""

import logging
import types
from pathlib import Path

import pytest

import hermes_logging
from gateway import run


@pytest.fixture
def clean_logging():
    hermes_logging._reset_queued_handlers()
    hermes_logging._logging_initialized = False
    yield
    hermes_logging._reset_queued_handlers()
    hermes_logging._logging_initialized = False


def _emit_under(home: Path, name: str, level: int, msg: str) -> None:
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    token = set_hermes_home_override(home)
    try:
        logging.getLogger(name).log(level, msg)
    finally:
        reset_hermes_home_override(token)


def _contains(home: Path, filename: str, needle: str) -> bool:
    path = home / "logs" / filename
    return path.exists() and needle in path.read_text()


def test_multiplex_gateway_routes_profile_records_to_their_own_logs(
    tmp_path, monkeypatch, clean_logging
):
    default_home = tmp_path / "default"
    beta_home = tmp_path / "default" / "profiles" / "beta"
    beta_home.mkdir(parents=True)
    homes = [("default", default_home), ("beta", beta_home)]
    monkeypatch.setattr(run, "_multiplex_profile_homes", lambda _cfg: homes)

    hermes_logging.setup_logging(hermes_home=default_home, mode="gateway")

    # Single-profile gateway: wiring is inert and handlers stay static.
    assert run._enable_multiplex_log_routing(types.SimpleNamespace(multiplex_profiles=False)) is False
    assert run._enable_multiplex_log_routing(types.SimpleNamespace(multiplex_profiles=True)) is True

    _emit_under(beta_home, "gateway.run", logging.WARNING, "BETA-GATEWAY-WARN")
    _emit_under(default_home, "gateway.run", logging.INFO, "DEFAULT-GATEWAY-INFO")
    hermes_logging.flush_log_queue()

    for filename in ("agent.log", "errors.log", "gateway.log"):
        assert _contains(beta_home, filename, "BETA-GATEWAY-WARN"), filename
        assert not _contains(default_home, filename, "BETA-GATEWAY-WARN"), filename
    assert _contains(default_home, "gateway.log", "DEFAULT-GATEWAY-INFO")
    assert not _contains(beta_home, "gateway.log", "DEFAULT-GATEWAY-INFO")


def test_a_swap_that_cannot_build_its_routers_keeps_the_launch_home_sink(
    tmp_path, monkeypatch, clean_logging, capsys
):
    """#141958: a router that will not construct must not take the file sink with it.

    The swap used to stop the listener and close every static handler before it knew the
    replacements were constructible, and the caller reported the failure through the
    handlers it had just closed — the gateway kept serving with no log file open at all.
    """
    default_home = tmp_path / "default"
    beta_home = tmp_path / "default" / "profiles" / "beta"
    beta_home.mkdir(parents=True)
    homes = [("default", default_home), ("beta", beta_home)]
    monkeypatch.setattr(run, "_multiplex_profile_homes", lambda _cfg: homes)

    hermes_logging.setup_logging(hermes_home=default_home, mode="gateway")
    static_handlers = list(hermes_logging._queued_file_handlers)

    class RouterRefused(RuntimeError):
        pass

    def _refuse(*_args, **_kwargs):
        raise RouterRefused("profile home is not readable")

    monkeypatch.setattr(hermes_logging, "_ProfileRoutingFileHandler", _refuse)

    assert run._enable_multiplex_log_routing(types.SimpleNamespace(multiplex_profiles=True)) is False

    # Still the same static handlers, still open, and the listener never went away.
    assert hermes_logging._queued_file_handlers == static_handlers
    assert hermes_logging._queue_listener is not None
    assert all(not handler.stream is None for handler in static_handlers if hasattr(handler, "stream"))

    # The launch home's files keep receiving records instead of a queue with nothing behind it.
    _emit_under(default_home, "gateway.run", logging.INFO, "AFTER-REFUSED-SWAP")
    hermes_logging.flush_log_queue()
    assert _contains(default_home, "gateway.log", "AFTER-REFUSED-SWAP")

    # ... and the operator hears about it: stderr is the only sink gateway mode always has.
    assert "per-profile log routing is off" in capsys.readouterr().err
