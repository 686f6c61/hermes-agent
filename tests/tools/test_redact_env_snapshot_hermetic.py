"""The hermetic test environment must undo a shell-level redaction opt-out.

Repro: `security.redact_secrets: false` is bridged to
``HERMES_REDACT_SECRETS=false`` in the environment of every ``hermes chat``,
kanban worker and terminal subprocess of such a profile — pytest included.
``agent/redact.py`` snapshots that variable into ``_REDACT_ENABLED`` at import
time, and the test modules import ``agent.redact`` during collection, i.e.
*before* ``tests/conftest.py::_hermetic_environment`` blanks it. The scrub
therefore could not reach the snapshot, redaction stayed off for the whole
run, and four tests that never pin the flag failed locally while CI (where the
variable is unset) stayed green.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# The four tests that do not pin `agent.redact._REDACT_ENABLED` themselves.
AFFECTED = (
    "tests/tools/test_file_tools.py::TestSecretFileReadRedaction",
    "tests/tools/test_approval.py::TestApprovalPromptRedaction",
)


def test_pytest_run_survives_a_shell_level_redaction_opt_out():
    """Launching pytest with HERMES_REDACT_SECRETS=false must not fail tests.

    A real subprocess: the snapshot happens at import, so it cannot be
    simulated in-process.
    """
    env = dict(os.environ)
    env["HERMES_REDACT_SECRETS"] = "false"
    env.pop("PYTEST_ADDOPTS", None)

    result = subprocess.run(
        [sys.executable, "-m", "pytest", *AFFECTED, "-q", "-p", "no:cacheprovider"],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=600,
        check=False,
    )

    assert result.returncode == 0, (
        "pytest still inherits the shell's redaction opt-out:\n"
        + result.stdout[-4000:]
        + result.stderr[-2000:]
    )
