"""Probes from the verifier's sealed review of b18bbea025 (2026-10-21T19:14Z)."""

import pytest

from tools.approval import detect_dangerous_command

PRODUCERS = [
    pytest.param(
        "SHELL=/bin/dash echo 'tell application \"Keynote\"\\nclose front document saving no\\nend tell' | osascript",
        id="dash-echo-escape",
    ),
    pytest.param(
        "printf '%s' 'tell application \"Keynote\" to quit without saving' | osascript 2>&1",
        id="redirection-not-an-operand",
    ),
    pytest.param(
        "osascript <<'EOF'\ntell application \"Keynote\" to quit without saving\n",
        id="unterminated-heredoc",
    ),
    pytest.param(
        "awk 'BEGIN{print \"tell application \\\"Keynote\\\" to quit without saving\"}' | osascript",
        id="awk-producer",
    ),
]

INERT = [
    pytest.param(
        "awk '{print $1}' | osascript",
        id="awk-field-projection-is-not-a-payload",
    ),
    pytest.param(
        "(*\ntell application \"Keynote\" to close front document saving no\n*)\n"
        "tell application \"Keynote\" to get name of front document",
        id="applescript-block-comment",
    ),
    pytest.param(
        "/*\nApplication(\"Keynote\").documents[0].close({saving: \"no\"})\n*/\n"
        "Application(\"Keynote\").documents.length",
        id="javascript-block-comment",
    ),
]


@pytest.mark.parametrize("command", PRODUCERS)
def test_a_producer_stage_reaches_osascript_as_stdin(command):
    dangerous, key, desc = detect_dangerous_command(command)
    assert dangerous is True, (command, dangerous, key, desc)


@pytest.mark.parametrize("command", INERT)
def test_an_inert_block_comment_is_not_a_document_close(command):
    assert detect_dangerous_command(command) == (False, None, None), command
