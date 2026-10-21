"""An `npm audit` that did not complete must not be reported as a clean tree (#142635).

`_audit_one` used to collapse three different outcomes — a timeout, a non-zero
exit outside npm's own `0 = clean / 1 = findings` pair, and an unparseable
payload — into `counts == {}` and therefore into
`check_ok("(no known vulnerabilities)")`. On a tree that really had a `high`
finding this printed a green row whenever the audit did not finish, which is
how the reporter saw the same install alternate between `✓ … (no known
vulnerabilities)` and `⚠ … 1 high` between two runs a moment apart.

Findings unknown is its own outcome: it warns, and it lands in `manual_issues`
so the summary cannot drop it.
"""

import json
import subprocess
from unittest.mock import patch

import pytest

from hermes_cli import doctor_tools


def _audit_json(critical=0, high=0, moderate=0):
    return json.dumps({
        "metadata": {"vulnerabilities": {
            "critical": critical, "high": high, "moderate": moderate,
            "low": 0, "info": 0, "total": critical + high + moderate,
        }},
    })


def _run_one(capsys, *, returncode=0, stdout="", side_effect=None):
    issues: list[str] = []
    completed = subprocess.CompletedProcess(["npm", "audit"], returncode, stdout=stdout, stderr="")
    kwargs = {"side_effect": side_effect} if side_effect is not None else {"return_value": completed}
    with patch.object(doctor_tools.subprocess, "run", **kwargs):
        doctor_tools._audit_one("npm", "/fake/web", "web workspace", ["--workspace", "web"], issues)
    return capsys.readouterr().out, issues


def test_nonzero_exit_without_payload_is_not_reported_clean(capsys):
    """A registry/arborist error exits outside 0/1 with no JSON: unknown, not clean."""
    out, issues = _run_one(capsys, returncode=2, stdout="")
    assert "no known vulnerabilities" not in out
    assert "audit did not complete" in out
    assert len(issues) == 1
    assert "web workspace npm audit did not complete" in issues[0]


def test_timeout_is_not_reported_clean(capsys):
    """The 30 s cap is crossed on slow trees; the row must say so instead of going silent."""
    timeout = subprocess.TimeoutExpired(cmd=["npm", "audit"], timeout=30)
    out, issues = _run_one(capsys, side_effect=timeout)
    assert "no known vulnerabilities" not in out
    assert "audit timed out" in out
    assert len(issues) == 1


@pytest.mark.parametrize("stdout", ["npm ERR! code EREGISTRY\n", "{\"metadata\": ", "[]"])
def test_unparseable_payload_is_not_reported_clean(capsys, stdout):
    out, issues = _run_one(capsys, returncode=0, stdout=stdout)
    assert "no known vulnerabilities" not in out
    assert "audit did not complete" in out
    assert len(issues) == 1


def test_clean_payload_still_reports_no_known_vulnerabilities(capsys):
    """Control: a completed audit with zero findings keeps the green row and stays out of manual_issues."""
    out, issues = _run_one(capsys, returncode=0, stdout=_audit_json())
    assert "no known vulnerabilities" in out
    assert "audit did not complete" not in out
    assert issues == []


def test_findings_under_exit_code_one_still_report_counts(capsys):
    """Control: npm exits 1 when it *did* find something, so findings must keep flowing through."""
    out, issues = _run_one(capsys, returncode=1, stdout=_audit_json(high=1, moderate=1))
    assert "1 high" in out
    assert "audit did not complete" not in out
    assert len(issues) == 1
    assert issues[0].startswith("web workspace has 2 npm vulnerabilities")
