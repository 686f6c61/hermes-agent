"""Regression for #136694: a missing recorded dependency lock must fail the update's
dependency-sync follow-up with an actionable ``InstallError`` naming the path, not the
raw ``FileNotFoundError`` from ``lock_and_sync``'s blind seed copy — that crash left the
desktop build owed and the update in a retry loop with no remediation hint."""

from pathlib import Path

import pytest

from pm.package import InstallError
from pm.packages import Venv


def test_missing_recorded_seed_raises_actionable_error(tmp_path):
    seed = tmp_path / "gone-generation" / "workspace" / "uv.lock"

    with pytest.raises(InstallError) as err:
        Venv(tmp_path)._seed_lock({"resolved_lock": str(seed)}, ["member"], tmp_path)

    assert str(seed) in err.value.cause
    assert err.value.remedy


def test_existing_recorded_seed_is_used(tmp_path):
    seed = tmp_path / "gen" / "workspace" / "uv.lock"
    seed.parent.mkdir(parents=True)
    seed.write_text("lock", encoding="utf-8")

    assert Venv(tmp_path)._seed_lock({"resolved_lock": str(seed)}, ["member"], tmp_path) == seed


def test_without_members_or_prior_seeds_the_project_lock(tmp_path):
    project = tmp_path / "uv.lock"

    assert Venv(tmp_path)._seed_lock({}, [], tmp_path) == project
    assert Venv(tmp_path)._seed_lock({"resolved_lock": "/nonexistent"}, [], tmp_path) == project
