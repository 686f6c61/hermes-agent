"""#143466: a non-default ``HERMES_HOME`` gets its own browser-harness root.

browser-harness resolves its home from the account ``HOME``, so every Hermes root that is not a
served profile used to share one ``~/.config/browser-harness`` daemon: a second gateway met the
first one's live browser, and a home sandboxed to its own folders could not start a daemon at all.
"""
import hashlib
from pathlib import Path

import pytest

from tools import browser_use_cli as bu_cli


@pytest.fixture
def homes(tmp_path, monkeypatch):
    """A fake platform default plus a second, unrelated Hermes home."""
    default, other = tmp_path / "default-home", tmp_path / "other-home"
    default.mkdir()
    other.mkdir()
    monkeypatch.setattr(bu_cli, "account_default_hermes_home", lambda: default, raising=False)
    for key in ("BH_HOME", "BROWSER_HARNESS_HOME", "BH_RUNTIME_DIR", "BH_RUNTIME_DIR_SHARED"):
        monkeypatch.delenv(key, raising=False)
    return default, other


def _env_for(monkeypatch, home: Path) -> dict:
    monkeypatch.setenv("HERMES_HOME", str(home))
    return bu_cli._base_subprocess_env()


def test_a_non_default_home_gets_a_harness_root_under_itself(homes, monkeypatch):
    """Two roots must not share one daemon: the root follows HERMES_HOME, not the account HOME."""
    _default, other = homes
    env = _env_for(monkeypatch, other)
    root = other / "cache" / "browser-harness"
    assert env["BH_HOME"] == str(root)
    # The daemon (and the socket it binds) lives under the runtime dir, so it stays inside that root
    # unless the path is too long for a sun_path -- then the short ``hbh-`` fallback owns it.
    runtime = Path(env["BH_RUNTIME_DIR"])
    assert runtime == root / "runtime" or runtime.name.startswith("hbh-")
    assert env["BH_RUNTIME_DIR_SHARED"] == "1"


def test_the_plain_install_keeps_the_legacy_location(homes, monkeypatch):
    """The default home is byte-identical to before: nothing moves for an ordinary install."""
    default, _other = homes
    env = _env_for(monkeypatch, default)
    assert "BH_HOME" not in env
    assert "BH_RUNTIME_DIR" not in env


def test_an_explicit_harness_home_wins(homes, monkeypatch):
    """A user who sets BH_HOME keeps it."""
    _default, other = homes
    monkeypatch.setenv("HERMES_HOME", str(other))
    monkeypatch.setenv("BH_HOME", str(other / "custom-harness"))
    env = bu_cli._base_subprocess_env()
    assert env["BH_HOME"] == str(other / "custom-harness")


def test_an_unresolvable_default_home_leaves_the_env_alone(homes, monkeypatch):
    """A comparator that raises must not break the browser: the legacy location stays."""
    _default, other = homes

    def boom():
        raise RuntimeError("no account home")

    monkeypatch.setattr(bu_cli, "account_default_hermes_home", boom)
    env = _env_for(monkeypatch, other)
    assert "BH_HOME" not in env


def test_the_served_profile_scope_still_owns_its_own_keys(homes, monkeypatch):
    """A multiplexed turn keeps the per-profile keying it already had (no double scoping)."""
    _default, other = homes
    monkeypatch.setenv("HERMES_HOME", str(other))
    monkeypatch.setattr(bu_cli, "_served_profile_tag", lambda: "profile-key")
    env = bu_cli._base_subprocess_env()
    leaf = "p-" + hashlib.sha256(b"profile-key").hexdigest()[:12]
    assert "BH_HOME" not in env
    assert leaf in Path(env["BH_RUNTIME_DIR"]).parts


def test_the_helper_is_a_no_op_once_a_root_is_set():
    """Idempotent: an env that already names a harness root is left untouched."""
    env = {"BH_HOME": "/tmp/explicit-harness"}
    bu_cli._home_scoped_harness_env(env)
    assert env == {"BH_HOME": "/tmp/explicit-harness"}
