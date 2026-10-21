"""The producer and comment shapes a changed-head acceptance run measured (#141346).

Each row is one command whose verdict was wrong on `422f6ea92e`: either a destructive program read
as inert (the miss) or a program the shell never executes read as destructive (the false positive).
The echo rows depend on which shell PARSES the pipeline, so they pin the process `$SHELL` — an
inline `SHELL=` word is the child's environment and decides nothing.
"""

import pytest

from tools.approval import detect_dangerous_command

PROGRAM = r"tell application \"Keynote\"\nclose front document saving no\nend tell"


def _dangerous(command: str) -> bool:
    return detect_dangerous_command(command)[0]


@pytest.mark.parametrize(
    "shell,command",
    [
        # zsh parses: its echo writes the escapes as bytes, so the close reaches osascript on its own
        # line. Reading the inline `SHELL=/bin/bash` as the decoder missed it.
        ("/bin/zsh", f"SHELL=/bin/bash echo '{PROGRAM}' | osascript"),
        # dash parses: XSI echo decodes with no flag; a bare sh that is dash also decodes.
        ("/bin/dash", f"echo '{PROGRAM}' | osascript"),
        # tee copies stdin to stdout, so the program behind it is the producer's, not `/dev/null`.
        ("/bin/bash", f"printf '{PROGRAM}' | tee /dev/null | osascript"),
    ],
    ids=["zsh-parses-inline-bash-assignment", "dash-echo-escape", "tee-passthrough"],
)
def test_destructive_producer_shapes(shell, command, monkeypatch):
    monkeypatch.setenv("SHELL", shell)
    assert _dangerous(command)


@pytest.mark.parametrize(
    "shell,command",
    [
        # bash parses: its builtin prints the escapes as text, so this is one line holding `\nclose`
        # and no operation. Reading the inline `SHELL=/bin/dash` as the decoder flagged it.
        ("/bin/bash", f"SHELL=/bin/dash echo '{PROGRAM}' | osascript"),
        # A switch after the first operand is text, not a switch: bash prints `… -e`.
        ("/bin/bash", f"echo '{PROGRAM}' -e | osascript"),
        # The call is inside a JS string literal: printing it closes nothing.
        (
            "/bin/bash",
            'osascript -l JavaScript -e \'console.log(".close({saving: \\"no\\"})")\'',
        ),
        # `$"…"` is locale translation and decodes nothing; the `$'done'` further along the line is
        # what made the whole command read as ANSI-C quoted.
        (
            "/bin/bash",
            'osascript -e $"tell application \\"Keynote\\"\\nclose front document saving no\\nend tell"; echo $\'done\'',
        ),
        # A block comment spanning lines is prose: the close spelled between `(*` and `*)` is
        # commented out, and a heredoc body is judged whole, so this false-positived where the argv
        # spelling passed.
        (
            "/bin/bash",
            "osascript <<'EOF'\n(*\ntell application \"Keynote\" to close front document saving no\n*)\ntell application \"Keynote\" to get name of front document\nEOF",
        ),
        (
            "/bin/bash",
            "osascript -l JavaScript <<'EOF'\n/*\nApplication('Keynote').documents[0].close({saving: \"no\"})\n*/\nApplication('Keynote').documents[0].name()\nEOF",
        ),
    ],
    ids=[
        "bash-parses-inline-dash-assignment",
        "flag-after-operand-is-text",
        "jxa-call-inside-string-literal",
        "locale-quoting-beside-ansi-c-word",
        "applescript-multiline-block-comment-heredoc",
        "jxa-multiline-block-comment-heredoc",
    ],
)
def test_inert_producer_and_comment_shapes(shell, command, monkeypatch):
    monkeypatch.setenv("SHELL", shell)
    assert not _dangerous(command)
