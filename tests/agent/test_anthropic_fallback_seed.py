"""A provider listed only in ``fallback_providers`` must seed its borrowed credentials.

#131993: a profile whose ``model.provider`` is another provider and whose Anthropic
credential lives only in the fallback chain never consented via
``is_provider_explicitly_configured("anthropic")``, so ``_seed_anthropic_singletons``
skipped autodiscovery and the pool loaded the borrowed ``claude_code`` row
token-less. ``_available_entries`` then dropped it at the empty-``access_token``
guard and the fallback chain skipped Anthropic as "credential pool exhausted"
even though ``~/.claude/.credentials.json`` held a usable pair.

Naming the provider in the chain is the same consent as a MoA slot: the seeder
must fill the row with the real pair. These tests drive the real
``load_pool()`` path — config.yaml on disk, real gate, real singleton read —
with no monkeypatched gate.
"""

from __future__ import annotations

import json
import time

import pytest

from agent import anthropic_credentials as AA
from agent.credential_pool import load_pool

_ACCESS = "sk-ant-oat01-fallback-seed"
_REFRESH = "sk-ant-ort01-fallback-seed"


def _write_profile(tmp_path, monkeypatch, fallback_entries):
    """HERMES_HOME with a codex primary, the given fallback chain, and a live
    Claude Code singleton to borrow from."""
    home = tmp_path / "hermes"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    import hermes_yaml as yaml
    config = {"model": {"provider": "openai-codex", "default": "gpt-6.1-sol"}}
    if fallback_entries is not None:
        config["fallback_providers"] = fallback_entries
    (home / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    (home / "auth.json").write_text(
        json.dumps({"version": 1, "providers": {}}), encoding="utf-8"
    )
    cred_path = tmp_path / "claude" / ".credentials.json"
    cred_path.parent.mkdir(parents=True, exist_ok=True)
    cred_path.write_text(
        json.dumps(
            {
                "claudeAiOauth": {
                    "accessToken": _ACCESS,
                    "refreshToken": _REFRESH,
                    "expiresAt": int(time.time() * 1000) + 3_600_000,
                    "scopes": ["user:inference", "user:profile"],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(AA, "claude_code_credentials_path", lambda: cred_path)
    monkeypatch.setattr(AA, "_read_claude_code_credentials_from_keychain", lambda: None)
    return home


def test_fallback_chain_naming_anthropic_fills_the_borrowed_row(tmp_path, monkeypatch):
    _write_profile(
        tmp_path, monkeypatch,
        [{"provider": "anthropic", "model": "claude-opus-5-5"}],
    )
    pool = load_pool("anthropic")
    assert pool.has_available(model="claude-opus-5-5") is True


def test_chain_without_the_provider_keeps_the_row_unseeded(tmp_path, monkeypatch):
    """Without the provider in the chain there is no consent: no autodiscovery,
    an empty pool, and the fallback would still be skipped (by design)."""
    _write_profile(
        tmp_path, monkeypatch,
        [{"provider": "xai-oauth", "model": "grok-4.7"}],
    )
    pool = load_pool("anthropic")
    assert pool.has_credentials() is False
    assert pool.has_available(model="claude-opus-5-5") is False
