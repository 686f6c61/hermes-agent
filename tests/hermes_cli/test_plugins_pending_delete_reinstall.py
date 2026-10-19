"""A reinstall after a remove that could not delete a held tree is not a conflict (#141539).

``_discard_tree`` strips the manifests of a tree another process holds and parks its path under
``cache/plugin-pending-delete``; the sweep that finishes the job runs only at gateway start-up. Until
then the remnant is not an installed plugin — the install record is gone, the manifests are gone,
``plugins list`` is clean — so ``hermes plugins install`` must finish the removal instead of refusing
with "already exists" and a ``plugins update`` remedy that needs the deleted record.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cli import plugins_cmd_install, plugins_cmd_remove


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("hermes_constants.get_hermes_home", lambda: tmp_path)
    return tmp_path


def _park(home: Path, tree: Path) -> Path:
    """Write the note ``_discard_tree`` leaves when the held directory cannot even be renamed."""
    root = home / "cache" / "plugin-pending-delete"
    root.mkdir(parents=True, exist_ok=True)
    note = root / f"{tree.parent.name}-{tree.name}.path"
    note.write_text(str(tree), encoding="utf-8")
    return note


def test_parked_delete_note_finds_the_tree_a_remove_parked(home: Path) -> None:
    tree = home / "plugins" / "rea"
    tree.mkdir(parents=True)
    assert plugins_cmd_remove.parked_delete_note(tree) is None
    note = _park(home, tree)
    assert plugins_cmd_remove.parked_delete_note(tree) == note


def test_parked_delete_note_ignores_another_trees_note(home: Path) -> None:
    tree = home / "plugins" / "rea"
    other = home / "plugins" / "other"
    tree.mkdir(parents=True)
    other.mkdir()
    _park(home, other)
    assert plugins_cmd_remove.parked_delete_note(tree) is None


def test_reinstall_finishes_the_parked_removal(home: Path) -> None:
    tree = home / "plugins" / "rea"
    tree.mkdir(parents=True)
    _park(home, tree)

    plugins_cmd_install._clear_parked_remnant("rea", tree)  # nothing left to conflict with

    assert not tree.exists()
    assert plugins_cmd_remove.parked_delete_note(tree) is None


def test_reinstall_names_the_hold_when_the_tree_survives(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tree = home / "plugins" / "rea"
    tree.mkdir(parents=True)
    _park(home, tree)
    # A live process still owns the directory: the sweep cannot delete it.
    monkeypatch.setattr(plugins_cmd_remove._pc(), "rmtree_readonly", lambda *_a, **_k: None)

    with pytest.raises(plugins_cmd_install._pc().PluginOperationError) as exc:
        plugins_cmd_install._clear_parked_remnant("rea", tree)

    assert "still held by another process" in str(exc.value)
    assert str(tree) in str(exc.value)
    assert "plugins update" not in str(exc.value)


def test_reinstall_of_an_installed_plugin_keeps_the_existing_refusal(home: Path) -> None:
    tree = home / "plugins" / "rea"
    tree.mkdir(parents=True)
    (tree / "plugin.yaml").write_text("name: rea\n", encoding="utf-8")

    with pytest.raises(plugins_cmd_install._pc().PluginOperationError) as exc:
        plugins_cmd_install._clear_parked_remnant("rea", tree)

    assert "already exists" in str(exc.value)
    assert tree.exists()
