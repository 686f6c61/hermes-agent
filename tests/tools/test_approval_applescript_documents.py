"""AppleScript that closes or quits a document without saving (#141346).

An `osascript` payload closed the operator's own unsaved deck with `saving no`; the document and
its AutoRecovery were discarded and the only export was deleted afterwards. Two things are tested
here, because either alone leaves the hole open: the pattern must match the spellings AppleScript
and JXA accept, and smart mode must not let the auxiliary guardian approve this class — the model's
APPROVE is not the consent of the person whose work is at stake.
"""

import pytest

from tools import approval as approval_module
from tools import approval_context, approval_smart
from tools.approval import check_all_command_guards, detect_dangerous_command

DESCRIPTION = "AppleScript closes or quits a document without saving"


class TestDetection:
    @pytest.mark.parametrize("command", [
        # The reported command: one -e payload, statements on their own lines.
        'osascript -e \'tell application "Microsoft PowerPoint"\n'
        '  open POSIX file "/tmp/traz.pptx"\n'
        '  save active presentation in POSIX file "/tmp/traz.pdf" as save as PDF\n'
        '  close active presentation saving no\n'
        'end tell\'',
        'osascript -e \'tell application "Keynote" to close front document saving no\'',
        'osascript -e \'tell application "Pages" to quit without saving\'',
        'osascript -e \'Application("Keynote").documents[0].close({saving: false})\'',
    ])
    def test_closing_without_saving_requires_approval(self, command):
        dangerous, key, desc = detect_dangerous_command(command)
        assert dangerous is True, command
        assert key == DESCRIPTION
        assert desc == DESCRIPTION

    @pytest.mark.parametrize("command", [
        # Executable identity: the absolute path and the wrappers that hide the command name.
        '/usr/bin/osascript -e \'tell application "Keynote" to close front document saving no\'',
        'command osascript -e \'tell application "Keynote" to quit without saving\'',
        'nice -n 5 /usr/bin/osascript -e \'tell application "Keynote" to close front document saving: false\'',
        # A carrier hands the same payload to a second layer of shell.
        'sh -c "/usr/bin/osascript -e \'tell application \\"Keynote\\" to quit without saving\'"',
        'eval "osascript -e \'tell application \\"Keynote\\" to quit without saving\'"',
        'env -S "/usr/bin/osascript -e \'tell application \\"Keynote\\" to quit without saving\'"',
        # Script source that is not an -e argument: a heredoc body and a pipe into stdin.
        'osascript <<\'EOF\'\ntell application "Keynote"\n  close front document saving no\nend tell\nEOF',
        'printf \'%s\' \'tell application "Keynote" to quit without saving\' | osascript',
        # JXA spells "do not save" as the string enum, not a boolean.
        'osascript -l JavaScript -e \'Application("Keynote").documents[0].close({saving: "no"})\'',
        # Source shapes the same payload arrives in when it is not a bare `-e` argument: an
        # apostrophe in the document expression beside a `-- don't` comment, `-s` consuming the
        # output-style token, a wrapper after the pipe, a heredoc on the producer side of the pipe,
        # a here-string, and `eval`'s whole tail.
        'osascript <<\'EOF\'\n'
        'tell application "Keynote" to close (first document whose name is front document\'s name) '
        'saving no -- don\'t keep\nEOF',
        'printf \'%s\' \'tell application "Keynote" to quit without saving\' | osascript -s o',
        'printf \'%s\' \'tell application "Keynote" to quit without saving\' | nice osascript',
        'cat <<\'EOF\' | osascript\ntell application "Keynote" to quit without saving\nEOF',
        'osascript <<< \'tell application "Keynote" to quit without saving\'',
        'eval osascript -e "\'tell application \\"Keynote\\" to close front document saving no\'"',
        # `¬` continues the statement: `saving ¬` and `no` are one operation.
        'osascript -e \'tell application "Keynote" to close front document saving ¬\nno\'',
        # `¬` also continues across a CR line ending, and CR alone ends an AppleScript statement.
        'osascript -e \'tell application "Keynote" to close front document saving ¬\rno\'',
        # A pass-through stage (`cat` with no arguments) does not consume the pipe's payload.
        'printf \'%s\' \'tell application "Keynote" to quit without saving\' | cat | osascript',
        # An AppleScript comment containing `let` is not JXA, so its apostrophes stay punctuation.
        'osascript <<\'EOF\'\ntell application "Keynote" to close (first document whose name is '
        'front document\'s name) saving no -- don\'t let it keep\nEOF',
        # A quoted JS property key is the same option; raw four-character codes compile to the
        # same Standard Suite command and parameter.
        'osascript -l JavaScript -e \'Application("Keynote").documents[0].close({"saving": "no"})\'',
        'osascript -e \'tell application "Keynote" to «event coreclos» front document '
        'given «class savo»:no\'',
        # A heredoc delimiter is a shell word (`APPLESCRIPT-END`), and a plain `<<` body ends only
        # on the delimiter itself, so an indented ` EOF` line is still part of the program.
        'osascript <<\'APPLESCRIPT-END\'\ntell application "Keynote" to quit without saving\n'
        'APPLESCRIPT-END',
        'osascript <<\'EOF\'\nset x to 1\n EOF\ntell application "Keynote" to quit without saving\nEOF',
    ])
    def test_every_carrier_of_the_same_payload_requires_approval(self, command):
        """The first fix matched only a bare `osascript … saving no` at command position."""
        dangerous, key, desc = detect_dangerous_command(command)
        assert dangerous is True, command
        assert key == DESCRIPTION
        assert desc == DESCRIPTION

    @pytest.mark.parametrize("command", [
        # The question, not the operation: the phrase lives inside a dialog's string literal.
        'osascript -e \'display dialog "Quit without saving?" buttons {"Cancel", "Quit"}\'',
        # The phrase as another command's argument, beside a read-only script.
        'osascript -e \'tell application "Keynote" to get name of front document\'; '
        'echo "closed without saving"',
        'echo "closed without saving"',
        # JXA prose inside a single-quoted JS string is data too, while AppleScript's apostrophes
        # (`front document's name`) are punctuation and must not shield the operation.
        'osascript -l JavaScript -e "var m = \'Quit without saving?\'; '
        'Application(\'Keynote\').documents.length"',
        # `-l JavaScript` on a script with no operation at all: the phrase is a JS string, and a
        # commented-out JXA call is a comment.
        'osascript -l JavaScript -e "console.log(\'quit without saving\')"',
        'osascript -e \'tell application "Keynote" to get name of front document -- quit without saving\'',
        'osascript -l JavaScript -e \'Application("Keynote").documents.length // .close({saving: "no"})\'',
    ])
    def test_inert_text_is_not_flagged(self, command):
        assert detect_dangerous_command(command) == (False, None, None), command

    @pytest.mark.parametrize("command", [
        # Reading state, and the reported command's saving half: both leave the document alone.
        'osascript -e \'tell application "Finder" to get the name of every disk\'',
        'osascript -e \'tell application "Microsoft PowerPoint" to save active presentation '
        'in POSIX file "/tmp/traz.pdf" as save as PDF\'',
        'osascript -e \'tell application "Keynote" to close front document saving yes\'',
        # Command position: the phrase as another command's argument is data.
        'git commit -m "osascript closed the deck with saving no"',
    ])
    def test_benign_osascript_is_not_flagged(self, command):
        assert detect_dangerous_command(command) == (False, None, None), command


class TestSmartModeAsksTheOperator:
    def test_smart_mode_never_consults_the_guardian(self, monkeypatch):
        """The reported failure: smart approval auto-approved the close."""
        command = 'osascript -e \'tell application "Keynote" to close front document saving no\''
        session_key = "test-141346-manual-only"
        prompts = []
        monkeypatch.setenv("HERMES_SESSION_KEY", session_key)
        monkeypatch.setenv("HERMES_INTERACTIVE", "1")
        monkeypatch.setenv("HERMES_EXEC_ASK", "1")
        monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)
        monkeypatch.setattr(approval_context, "_get_approval_config", lambda: {"mode": "smart"})
        monkeypatch.setattr(approval_module, "_YOLO_MODE_FROZEN", False)

        def guardian_must_not_decide(*_args, **_kwargs):
            raise AssertionError("smart approval auto-decided a close that discards the operator's work")

        monkeypatch.setattr(approval_smart, "_smart_approve", guardian_must_not_decide)
        approval_module.clear_session(session_key)
        approval_module._permanent_approved.clear()

        def deny(*args, **kwargs):
            prompts.append((args, kwargs))
            return "deny"

        result = check_all_command_guards(command, "local", approval_callback=deny)

        assert len(prompts) == 1
        assert result["approved"] is False
        assert not result.get("smart_approved")
