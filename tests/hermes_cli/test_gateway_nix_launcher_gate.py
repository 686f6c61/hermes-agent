"""A Nix install must not publish its launchers inside the read-only store.

`hermes gateway restart` reached `ensure_install_launchers` on a Nix host
because the publication gate only asked whether `$HERMES_HOME/tools` holds a
managed Python. A Python left there by an earlier install-script install
answers yes, so `.hermes/bin` was created under `/nix/store/...` and the
restart raised `OSError: [Errno 30] Read-only file system` before systemd was
called (#141442). The install method decides: a Nix-owned tree publishes
nothing.
"""

from pathlib import Path

import pytest

import hermes_cli.gateway as gw
from hermes_cli import _launchers
from hermes_cli import config as hermes_config


@pytest.fixture
def host(tmp_path, monkeypatch):
    home = tmp_path / "home" / ".hermes"
    store = home / "tools"
    interpreter = store / "python-3.14.7" / "bin" / "python3"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text("", encoding="utf-8")
    (store / "facts.json").write_text(
        '{"schema": 1, "packages": {"python": {"entry": "python-3.14.7"}}}',
        encoding="utf-8",
    )
    package_root = tmp_path / "nix-store" / "hermes-agent-env" / "site-packages"
    package_root.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("HERMES_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(gw, "PROJECT_ROOT", package_root)
    monkeypatch.setattr(gw, "get_hermes_home", lambda: home)
    published = []

    def record(root, out_dir):
        published.append((Path(root), Path(out_dir)))
        return [str(Path(out_dir) / name) for name in _launchers.ENTRY_POINTS]

    monkeypatch.setattr(_launchers, "ensure_install_launchers", record)
    return package_root, published


@pytest.mark.parametrize("method", ["nix", "nixos", "home-manager"])
def test_nix_install_does_not_publish_into_the_store(host, monkeypatch, method):
    package_root, published = host
    # The gate this test guards: a managed Python in the home is what used to
    # let the Nix install through.
    assert _launchers.resolve_store_python(package_root, publication=True) is not None
    monkeypatch.setattr(hermes_config, "detect_install_method", lambda root=None: method)

    gw._prepare_service_launcher()

    assert published == []


def test_source_install_still_publishes(host, monkeypatch):
    package_root, published = host
    monkeypatch.setattr(hermes_config, "detect_install_method", lambda root=None: "git")

    gw._prepare_service_launcher()

    assert published == [(package_root, package_root / ".hermes" / "bin")]
