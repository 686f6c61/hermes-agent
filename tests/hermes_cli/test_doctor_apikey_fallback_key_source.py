"""Regression for #136791: a provider's API-key probe must name the variable that supplied the key,
and must not report a hard failure for a region whose own variable the user never set.

``alibaba-token-plan-cn`` lists ``ALIBABA_TOKEN_PLAN_CN_API_KEY`` first and falls back to
``ALIBABA_TOKEN_PLAN_API_KEY`` (``plugins/model-providers/alibaba/__init__.py``). A user who sets only
the international Token Plan key used to get a permanent ``✗`` on the China row plus a hint telling
them to check a variable their setup never defines: the probe kept only the *value* of the first
non-empty variable, so ``env_vars[0]`` was the only name it could print.
"""

from __future__ import annotations

import types

from hermes_cli import doctor_connectivity as dc

_TOKEN_PLAN_CN = "Alibaba Cloud (Token Plan, China)"
_ENV_KEYS = (
    "ALIBABA_TOKEN_PLAN_CN_API_KEY",
    "ALIBABA_TOKEN_PLAN_API_KEY",
    "ALIBABA_TOKEN_PLAN_CN_BASE_URL",
    "ALIBABA_TOKEN_PLAN_BASE_URL",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_BASE_URL",
    "DASHSCOPE_CN_BASE_URL",
)


def _status(result) -> str:
    """Probe status, read from the row glyph — the only status carrier ProbeResult exposes."""
    glyph = result.lines[0][0]
    for status, (mark, _color) in dc._GLYPH.items():
        if mark in glyph:
            return status
    raise AssertionError(f"unknown row glyph: {result.lines!r}")


def _probe_row(monkeypatch, monkeypatch_env, status_code, row):
    """Run one provider row (name, key vars, url, base var, supports_health_check) with a stubbed HTTP call."""
    for var in _ENV_KEYS:
        monkeypatch.delenv(var, raising=False)
    for var, value in monkeypatch_env.items():
        monkeypatch.setenv(var, value)

    import httpx

    def fake_get(url, headers=None, timeout=None):
        assert url == row[2], f"probe called {url!r}, expected {row[2]!r}"
        return types.SimpleNamespace(status_code=status_code)

    monkeypatch.setattr(httpx, "get", fake_get)
    return dc._probe_apikey_provider(*row)


def _china_token_plan_row() -> tuple:
    """The shipped China Token Plan row, so the test is anchored to the real profile and chain."""
    dc._APIKEY_PROVIDERS_CACHE = None
    rows = {row[0]: row for row in dc._build_apikey_providers_list()}
    return rows[_TOKEN_PLAN_CN]


def test_key_source_reports_the_variable_that_supplied_the_key(monkeypatch):
    monkeypatch.delenv("OWN_KEY", raising=False)
    monkeypatch.setenv("FALLBACK_KEY", "fallback-value")

    assert dc._key_source(("OWN_KEY", "FALLBACK_KEY")) == ("FALLBACK_KEY", "fallback-value")
    assert dc._key_source(("OWN_KEY", "OTHER_UNSET")) == (None, "")


def test_china_token_plan_row_falls_back_to_the_international_key():
    """Anchor: without the fallback chain in the profile, the rest of this file would test nothing real."""
    row = _china_token_plan_row()

    assert row[1] == ("ALIBABA_TOKEN_PLAN_CN_API_KEY", "ALIBABA_TOKEN_PLAN_API_KEY")


def test_fallback_key_rejection_warns_and_names_its_source(monkeypatch):
    """Only the international key is set and the China endpoint rejects it → warning, not ✗."""
    row = _china_token_plan_row()
    result = _probe_row(monkeypatch, {"ALIBABA_TOKEN_PLAN_API_KEY": "intl-token-plan-key"}, 401, row)

    assert _status(result) == "warn", f"a borrowed key must not be a hard failure: {result.lines!r}"
    assert len(result.issues) == 1
    hint = result.issues[0]
    assert hint.startswith("The key from ALIBABA_TOKEN_PLAN_API_KEY"), hint
    assert "ALIBABA_TOKEN_PLAN_CN_API_KEY" in hint, "the remedy must name this profile's own variable"


def test_own_key_rejection_still_fails_with_its_own_hint(monkeypatch):
    """A key configured for this region and rejected by it stays a hard failure."""
    row = _china_token_plan_row()
    result = _probe_row(monkeypatch, {"ALIBABA_TOKEN_PLAN_CN_API_KEY": "cn-token-plan-key"}, 401, row)

    assert _status(result) == "fail"
    assert result.issues == ["Check ALIBABA_TOKEN_PLAN_CN_API_KEY in .env"]


def test_fallback_key_accepted_on_this_region_is_ok(monkeypatch):
    """A fallback key that the region does accept proves the route — no issue is raised."""
    row = _china_token_plan_row()
    result = _probe_row(monkeypatch, {"ALIBABA_TOKEN_PLAN_API_KEY": "intl-token-plan-key"}, 200, row)

    assert _status(result) == "ok"
    assert result.issues == []


def test_borrowed_key_access_denial_is_also_a_warning():
    """The Anthropic-gateway 403 path shares the same rule as the 401 one."""
    denied = dc._key_rejected("Some gateway", "access denied", "OWN_KEY", "OTHER_KEY", "label")

    assert _status(denied) == "warn"
    assert "OTHER_KEY" in denied.issues[0]
    assert "OWN_KEY" in denied.issues[0]


def test_own_key_access_denial_still_fails():
    denied = dc._key_rejected("Some gateway", "access denied", "OWN_KEY", "OWN_KEY", "label")

    assert _status(denied) == "fail"
    assert denied.issues == ["Check OWN_KEY in .env"]
