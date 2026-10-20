"""A manual fire from a Kanban-fenced caller lineage must say so (#141873).

``hermes cron run`` and ``cronjob(action="run")`` execute the job in the *caller's* process,
and the child env keeps ``HERMES_DELEGATED_CHILD_CONTEXT`` on purpose so a fenced caller cannot
launder Kanban mutation rights through the cron path. A job that touches the board therefore
dies mid-script with ``kanban: delegate_task child contexts cannot mutate Kanban tasks via the
CLI`` while the very same job succeeds on its scheduled tick — and nothing on the attempt row
said the fence came from the lineage, so the failure read as a script bug (it was misdiagnosed
as gateway contamination).

The fence itself is correct and is not relaxed here: the direct attempt row and the manual-fire
response now carry ``fence_inherited`` so the refusal is self-explaining. Fires are still
delivered — a fenced caller can legitimately run a job that never touches the board.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

_JOB = {"id": "job-fenced-1", "name": "board probe", "prompt": "touch the board",
        "schedule": {"kind": "cron", "expr": "0 9 * * *"}}


@pytest.fixture()
def execution_store(tmp_path, monkeypatch):
    """Isolate the executions ledger: ``create_execution`` writes a real sqlite row."""
    from cron import executions

    monkeypatch.setattr(executions, "EXECUTIONS_FILE", tmp_path / "cron" / "executions.db")
    return executions


def _fenced(monkeypatch, root):
    monkeypatch.setenv("HERMES_DELEGATED_CHILD_CONTEXT", str(root))


def test_direct_fire_row_records_the_inherited_fence(execution_store, tmp_path, monkeypatch):
    _fenced(monkeypatch, tmp_path)

    row = execution_store.create_execution("job-fenced-1", source="direct")

    assert row["source"] == "direct"
    assert row["fence_inherited"] == 1, row


def test_scheduled_tick_row_is_not_marked(execution_store, tmp_path, monkeypatch):
    """The gateway tick is its own lineage; the marker in a caller's env must not mark it."""
    _fenced(monkeypatch, tmp_path)

    row = execution_store.create_execution("job-fenced-1", source="builtin")

    assert row["fence_inherited"] == 0, row


def test_clean_caller_direct_fire_is_not_marked(execution_store, monkeypatch):
    monkeypatch.delenv("HERMES_DELEGATED_CHILD_CONTEXT", raising=False)

    row = execution_store.create_execution("job-fenced-1", source="direct")

    assert row["fence_inherited"] == 0, row


def test_run_response_names_the_fence_and_the_failure_cause(tmp_path, monkeypatch):
    """A failing manual fire reports the lineage, not just the script's stderr."""
    from tools.cronjob_tools import cronjob

    _fenced(monkeypatch, tmp_path)
    refused = {
        "id": "job-fenced-1",
        "last_status": "error",
        "last_error": "Script exited with code 1: kanban: delegate_task child contexts "
                      "cannot mutate Kanban tasks via the CLI",
    }
    claimed = {**_JOB, "fire_claim": {"by": "manual-owner"}}
    with patch("tools.cronjob_tools.resolve_job_ref", return_value=dict(_JOB)), \
         patch("tools.cronjob_tools.claim_job_for_fire", return_value=claimed), \
         patch("cron.scheduler.run_one_job", return_value=True), \
         patch("tools.cronjob_tools.get_job", return_value=refused):
        out = json.loads(cronjob(action="run", job_id="job-fenced-1"))

    assert out["job"]["execution_success"] is False
    assert out["fence_inherited"] is True
    assert "kanban-worker" in out["fence_notice"]
    assert "scheduled tick is not fenced" in out["job"]["execution_error"]
    # The script's own error stays in front: the cause is appended, never replaced.
    assert out["job"]["execution_error"].startswith("Script exited with code 1")


def test_clean_caller_run_response_stays_unchanged(monkeypatch):
    from tools.cronjob_tools import cronjob

    monkeypatch.delenv("HERMES_DELEGATED_CHILD_CONTEXT", raising=False)
    ran = {"id": "job-fenced-1", "last_status": "ok", "last_error": None}
    claimed = {**_JOB, "fire_claim": {"by": "manual-owner"}}
    with patch("tools.cronjob_tools.resolve_job_ref", return_value=dict(_JOB)), \
         patch("tools.cronjob_tools.claim_job_for_fire", return_value=claimed), \
         patch("cron.scheduler.run_one_job", return_value=True), \
         patch("tools.cronjob_tools.get_job", return_value=ran):
        out = json.loads(cronjob(action="run", job_id="job-fenced-1"))

    assert out["job"]["execution_success"] is True
    assert "fence_inherited" not in out
    assert "execution_error" not in out["job"]
