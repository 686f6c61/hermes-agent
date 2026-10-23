"""Pipeline shapes that decide WHICH program `osascript` reads, and which the reader got wrong.

Every row was reported with bytes: the reporter ran the producer half under `/bin/sh`, asserted its
stdout, then passed the same spelling to `detect_dangerous_command()`. Each destructive row was
judged inert on `36bedee743`, and the carrier row published the wrong approval key rather than the
unreadable-pipeline one its payload deserved.

The reason matters as much as the verdict: smart mode stores a session approval under the
description, so a carrier that reports the generic unsaved-close key for a pipeline the detector
could not reconstruct lets a later direct close ride on that approval.
"""

import pytest

from tools.approval import detect_dangerous_command

UNSAVED_CLOSE = "AppleScript closes or quits a document without saving"
UNREADABLE_PIPE = "osascript reads its program from a pipeline this detector cannot reconstruct"


@pytest.mark.parametrize(
    "command,description",
    [
        # A heredoc body behind a rewriting stage: `tr z t` turns `quiz` into `quit`, so the body
        # this reader sees is not the program the binary receives. The heredoc branch returned its
        # body before applying the rewrite state the walk had already set.
        pytest.param(
            "cat <<'EOF' | tr z t | osascript\ntell application \"Keynote\" to quiz without saving\nEOF",
            UNREADABLE_PIPE,
            id="heredoc-behind-tr",
        ),
        # Same seam for a literal-printing stage: `awk` emits the program, `tr` renames the verb.
        pytest.param(
            'awk \'BEGIN{print "tell application \\"Keynote\\" to quiz without saving"}\' | tr z t | osascript',
            UNREADABLE_PIPE,
            id="awk-print-behind-tr",
        ),
        # `<<EOF` inside a single-quoted printf argument is data the shell never parses as a marker.
        # Matching it started a here-document with no body and the producer's real payload was
        # never read.
        pytest.param(
            'printf \'set marker to "<<EOF"\\ntell application "Keynote" to quit without saving\' | osascript',
            UNSAVED_CLOSE,
            id="heredoc-marker-inside-quotes",
        ),
        # awk decodes escapes when it lexes the literal, so printf writes the close on its own line.
        pytest.param(
            'awk \'BEGIN{printf "tell application \\"Keynote\\"\\nclose front document saving no\\nend tell\\n"}\' | osascript',
            UNSAVED_CLOSE,
            id="awk-printf-decodes-newlines",
        ),
        # The same decoding on `print`, whose operand is also lexed.
        pytest.param(
            'awk \'BEGIN{print "tell application \\"Keynote\\"\\nquit without saving"}\' | osascript',
            UNSAVED_CLOSE,
            id="awk-print-decodes-newlines",
        ),
        # A carrier must publish the reason its payload produced, not collapse it to the generic one.
        pytest.param(
            'sh -c "printf \'tell application \\"Keynote\\" to quiz without saving\' | tr z t | osascript"',
            UNREADABLE_PIPE,
            id="carrier-keeps-nested-reason",
        ),
    ],
)
def test_pipeline_program_is_read_through_the_stage_that_decides_it(command, description):
    dangerous, key, reason = detect_dangerous_command(command)

    assert dangerous, command
    assert key == description
    assert reason == description


@pytest.mark.parametrize(
    "command",
    [
        # Activates the app and closes nothing.
        'printf \'tell application "Keynote" to activate\' | osascript',
        'awk \'BEGIN{print "tell application \\"Keynote\\" to activate"}\' | osascript',
        # A marker that only exists as data, with no program behind it.
        'printf \'set marker to "<<EOF"\' | osascript',
        # A heredoc body that quits nothing.
        "cat <<'EOF' | osascript\nbeep\nEOF",
    ],
)
def test_non_destructive_producer_shapes_stay_inert(command):
    assert detect_dangerous_command(command)[0] is False
