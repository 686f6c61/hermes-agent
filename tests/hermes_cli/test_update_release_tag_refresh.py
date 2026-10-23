"""``hermes update`` refreshes the release tag that names the build (#143361).

Every update fetch is ``--no-tags``, and a checkout already on the release commit fetches no tree
at all, so the checkout could hold the release while ``refs/tags/v*`` never arrived: the tree was
current and ``hermes --version`` named the previous release plus its distance. The update now
refreshes release tags itself; a failed refresh never fails an update that already moved the tree.
"""
import argparse
from copy import deepcopy
import subprocess
from types import SimpleNamespace

import pytest

from hermes_cli import main, source_releases, update_cmd, version_info
from hermes_cli.subcommands.update import build_update_parser


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                          text=True, stdin=subprocess.DEVNULL).stdout.strip()


@pytest.fixture
def source(tmp_path, monkeypatch):
    """An install cloned with ``--no-tags``: the release commit is an object, its tag is not a ref."""
    home, origin, checkout = (tmp_path / name for name in ("home", "origin", "checkout"))
    home.mkdir()
    origin.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_INSTALL_ROOT", str(checkout))
    monkeypatch.delenv("HERMES_MANAGED", raising=False)
    git(origin, "init", "-b", "main")
    git(origin, "config", "user.name", "Tag Fixture")
    git(origin, "config", "user.email", "fixture@example.invalid")
    git(origin, "config", "commit.gpgsign", "false")
    (origin / "notes.txt").write_text("previous release\n")
    git(origin, "add", ".")
    git(origin, "commit", "-m", "previous release")
    previous = git(origin, "rev-parse", "HEAD")
    git(origin, "tag", "v1.0.0")
    (origin / "notes.txt").write_text("current release\n")
    git(origin, "commit", "-am", "current release")
    release = git(origin, "rev-parse", "HEAD")
    git(origin, "tag", "v1.2.3")
    git(tmp_path, "clone", "-q", "--no-tags", str(origin), str(checkout))
    monkeypatch.setattr(main, "PROJECT_ROOT", checkout)
    monkeypatch.setattr("hermes_cli.config.get_project_root", lambda: checkout)
    monkeypatch.setattr("hermes_cli.backup._sibling_profile_homes", lambda h: [])
    monkeypatch.setattr(update_cmd._commit, "preflight_refusal", lambda *a, **k: None)
    parser = argparse.ArgumentParser()
    build_update_parser(parser.add_subparsers(), cmd_update=main.cmd_update)
    opts = update_cmd._UpdateOptions(pre_update_version=None, gw_input_fn=None,
        assume_yes=True, keep_stash=False, switch_branch=False, discard_local_changes=False)
    monkeypatch.setattr(update_cmd, "_resolve_update_options", lambda *_: opts)
    monkeypatch.setattr(update_cmd, "_begin_update_receipt_and_plan", lambda *_: None)
    monkeypatch.setattr(main, "_run_pre_update_backup", lambda *_: None)
    monkeypatch.setattr(main, "_pause_windows_gateways_for_update", lambda: None)
    monkeypatch.setattr(update_cmd, "_prepare_git_command", lambda **_: (False, ["git"], False))
    completed = []
    monkeypatch.setattr(update_cmd, "_complete_source_update",
                        lambda request: completed.append(deepcopy(request)))
    assert git(checkout, "tag", "--list", "v1.2.3") == ""  # the clone carried no tag at all
    return SimpleNamespace(home=home, root=checkout, previous=previous, release=release,
                           parser=parser, completed=completed)


def _stable_publishes(monkeypatch, commit, version="1.2.3"):
    monkeypatch.setattr("hermes_cli.update_channel.default_channel", lambda *_a, **_k: "stable")
    monkeypatch.setattr(source_releases, "_resolve_stable",
                        lambda repository, *_: source_releases.SourceTarget(
                            "stable", "stable", repository, commit=commit, version=version))


def test_a_checkout_already_on_the_release_gains_the_tag_that_names_it(source, monkeypatch):
    """The reported shape: HEAD *is* the release commit, so the update fetches no tree at all."""
    _stable_publishes(monkeypatch, source.release)

    update_cmd._cmd_update_impl(source.parser.parse_args(["update", "--yes"]), False)

    assert git(source.root, "rev-parse", "HEAD") == source.release
    assert git(source.root, "tag", "--list", "v1.2.3") == "v1.2.3"
    assert version_info._git_version_info(source.root).base_version == "1.2.3"


def test_a_release_move_also_carries_the_tag_of_the_release_it_moved_to(source, monkeypatch):
    git(source.root, "checkout", "-q", "--detach", source.previous)
    _stable_publishes(monkeypatch, source.release)

    update_cmd._cmd_update_impl(source.parser.parse_args(["update", "--yes"]), False)

    assert git(source.root, "rev-parse", "HEAD") == source.release
    assert git(source.root, "tag", "--list", "v1.2.3") == "v1.2.3"
    assert version_info._git_version_info(source.root).base_version == "1.2.3"
