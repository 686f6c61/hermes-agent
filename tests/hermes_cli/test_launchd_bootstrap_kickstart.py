"""A job launchd registers without starting it must be kickstarted, not bootstrapped again (#142741).

``launchctl bootstrap`` exits 0 for a job launchd loads but does not start (an on-demand plist with no
``RunAtLoad``/``KeepAlive``, or a per-user ``gui/<uid>`` domain), and exits 5/EIO when the label is already
loaded. Neither starts anything, so a bootstrap-only retry burns the whole reload budget and reports the
gateway as down while one ``kickstart`` would have started it.
"""
import subprocess
import time

from hermes_cli import gateway as gw


def _launchd(monkeypatch, *, kickstart_starts: bool):
    """Wire the launchd primitives the retry loop calls; returns the call counters."""
    calls = {"bootstrap": 0, "kickstart": []}
    state: dict[str, int | None] = {"pid": None}

    def bootstrap(domain, plist_path, label, *, timeout=30):
        calls["bootstrap"] += 1

    def kickstart_registered(domain, label, *, timeout=30):
        calls["kickstart"].append(f"{domain}/{label}")
        if kickstart_starts:
            state["pid"] = 4242
        return state["pid"] is not None

    monkeypatch.setattr(gw, "_launchctl_bootstrap", bootstrap)
    monkeypatch.setattr(gw, "_launchctl_kickstart_registered", kickstart_registered)
    monkeypatch.setattr(gw, "_launchctl_label_supervising_process", lambda label: state["pid"] is not None)
    monkeypatch.setattr(gw, "_append_launchd_reload_log", lambda msg: None)

    return calls


def test_a_registered_job_with_no_process_is_kickstarted(monkeypatch):
    calls = _launchd(monkeypatch, kickstart_starts=True)

    assert gw._retry_launchctl_bootstrap_until_registered(
        "gui/501", "/tmp/com.hermes.plist", "com.hermes.agent", deadline=time.monotonic() + 30,
    ) is True
    # One bootstrap, one kickstart of the label launchd already registered — no second bootstrap.
    assert calls == {"bootstrap": 1, "kickstart": ["gui/501/com.hermes.agent"]}


def test_a_job_that_never_starts_still_fails_bounded(monkeypatch):
    calls = _launchd(monkeypatch, kickstart_starts=False)

    assert gw._retry_launchctl_bootstrap_until_registered(
        "gui/501", "/tmp/com.hermes.plist", "com.hermes.agent", deadline=time.monotonic() - 1,
    ) is False
    # The attempt is counted lost after the kickstart fails, and the deadline is what ends the loop.
    assert calls["bootstrap"] == 1
    assert calls["kickstart"] == ["gui/501/com.hermes.agent"]


def test_a_bootstrap_failure_is_not_kickstarted(monkeypatch):
    """A failed bootstrap (drain, unmanageable domain) must keep the old retry-only behaviour."""
    calls = _launchd(monkeypatch, kickstart_starts=True)

    def failing_bootstrap(domain, plist_path, label, *, timeout=30):
        calls["bootstrap"] += 1
        raise subprocess.CalledProcessError(5, "launchctl bootstrap")

    monkeypatch.setattr(gw, "_launchctl_bootstrap", failing_bootstrap)

    assert gw._retry_launchctl_bootstrap_until_registered(
        "gui/501", "/tmp/com.hermes.plist", "com.hermes.agent", deadline=time.monotonic() - 1,
    ) is False
    assert calls["bootstrap"] == 1
    assert calls["kickstart"] == []
