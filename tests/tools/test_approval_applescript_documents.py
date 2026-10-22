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
        # An AppleScript string holding `let` is data, not a JXA declaration: the language hint has
        # to be read on code only, or the apostrophe of `document's name` pairs with the one in
        # `-- don't` and the `saving no` between them disappears.
        'osascript <<\'EOF\'\ndisplay dialog "let it go"\n'
        'tell application "Keynote" to close (first document whose name is front document\'s name) '
        'saving no -- don\'t keep\nEOF',
        # `//` inside a JS string is data: cutting the comment there deleted the call beside it.
        'osascript -l JavaScript -e \'var s = "//"; '
        'Application("Keynote").documents[0].close({saving: "no"})\'',
        # A shell joins the producer\'s argv with one space, so `echo` hands stdin a single line.
        'echo tell application \\"Keynote\\" to quit without saving | osascript',
        # osascript builds one program from repeated `-e` options, a line each.
        'osascript -e \'tell application "Keynote" to close front document saving ¬\' -e \'no\'',
        # `aevtquit` is the `quit` event and `savo` the `saving` parameter of the same suite.
        'osascript -e \'tell application "Keynote" to «event aevtquit» given «class savo»:no\'',
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
        # The two shapes the fixes above must not overreach on: a JS string that merely contains
        # the comment marker, and a piped read whose argv is space-joined but closes nothing.
        'osascript -l JavaScript -e \'var s = "// close"; Application("Keynote").documents.length\'',
        'echo tell application \\"Keynote\\" to get name of front document | osascript',
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

    @pytest.mark.parametrize("command", [
        # JXA's direct parameter comes first and the named-parameter object second (Apple's JXA
        # release notes), so the options object is not the first argument.
        'osascript -l JavaScript -e \'const k = Application("Keynote"); '
        'k.close(k.documents[0], {saving: "no"})\'',
        # The same object one binding away: a local literal handed to the call.
        'osascript -l JavaScript -e \'var o = {saving: "no"}; '
        'Application("Keynote").documents[0].close(o)\'',
        # zsh's `echo` decodes backslash escapes with no flag, so the binary reads two physical
        # lines; judging the spelling left `\nclose` with no word boundary before the verb.
        'echo \'tell application "Keynote"\\nclose front document saving no\\nend tell\' | osascript',
        # `$'…'` is ANSI-C quoting: the shell decodes it before the word becomes the `-e` argument.
        'osascript -e $\'tell application "Keynote"\\nclose front document saving no\\nend tell\'',
        # A heredoc body ends on an LF-terminated line, so a CR inside one is data: `splitlines()`
        # read the text before the CR as the delimiter and dropped the statement after it.
        'cat <<beep | osascript\nbeep\rtell application "Keynote" to quit without saving\nbeep\n',
        # A vertical tab is data the same way (`splitlines()` splits on it too).
        'cat <<EOF | osascript\n\x0bEOF\ntell application "Keynote" to quit without saving\nEOF\n',
    ])
    def test_the_live_matrix_rows_require_approval(self, command, monkeypatch):
        """Six rows a verifier's executable matrix drove through the head of this branch."""
        # The echo row is measured under the shell that decodes the escapes; the bash reading of
        # the same command is pinned in `test_echo_follows_the_shell_that_will_run_the_pipeline`.
        monkeypatch.setenv("SHELL", "/bin/zsh")
        dangerous, key, desc = detect_dangerous_command(command)
        assert dangerous is True, command
        assert key == DESCRIPTION
        assert desc == DESCRIPTION

    def test_the_ansi_c_hex_escape_reaches_the_verb(self):
        """`osascript -e $'…\\x63lose …'`: ANSI-C quoting hands the binary the word `close`."""
        command = (
            'osascript -e $\'tell application "Keynote"\\n\\x63lose front document saving no\\n'
            "end tell'"
        )
        dangerous, key, desc = detect_dangerous_command(command)
        assert dangerous is True, command
        assert key == DESCRIPTION
        assert desc == DESCRIPTION

    @pytest.mark.parametrize("command", [
        # The same two JXA shapes with a saving option that keeps the document.
        'osascript -l JavaScript -e \'const k = Application("Keynote"); '
        'k.close(k.documents[0], {saving: "yes"})\'',
        'osascript -l JavaScript -e \'var o = {saving: "yes"}; '
        'Application("Keynote").documents[0].close(o)\'',
        # A decoded echo of a read-only program stays inert.
        'echo \'tell application "Keynote"\\nget name of front document\\nend tell\' | osascript',
        # JXA's `ask` prompts by itself; a heredoc whose CR line is not the delimiter still closes.
        'cat <<beep | osascript\nbeep\rquit\nbeep\n',
    ])
    def test_the_matrix_controls_stay_inert(self, command, monkeypatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        assert detect_dangerous_command(command) == (False, None, None), command

    @pytest.mark.parametrize("command", [
        # Bound twice: the latest literal before the call is the effective options, so the
        # document is kept and the earlier `saving: "no"` is dead code.
        'osascript -l JavaScript -e \'var o = {saving: "no"}; o = {saving: "yes"}; '
        'Application("Keynote").documents[0].close(o)\'',
        # A filter's argv is its pattern, not the program: only `activate` reaches the binary.
        'printf \'tell application "Keynote" to activate\\n\' | grep -v \'quit without saving\' '
        '| osascript',
        # `$"…"` is locale translation, not ANSI-C quoting: no sh-family shell decodes escapes
        # inside it, so the binary reads one line holding `\\n`, which closes nothing.
        'osascript -e $"tell application \\"Keynote\\"\\nclose front document saving no\\nend tell"',
    ])
    def test_the_acceptance_file_controls_stay_inert(self, command):
        """Rows from the acceptance file a verifier drove through this head (#141346)."""
        assert detect_dangerous_command(command) == (False, None, None), command

    def test_echo_follows_the_shell_that_will_run_the_pipeline(self, monkeypatch):
        """`echo` hands the escapes over as bytes under zsh and prints them under bash.

        The terminal tool spawns the pipeline in the user's `$SHELL`
        (`tools/environments/local.py::_find_shell`), so the detector reads the same value: decoding
        under bash flagged a producer that in fact passes one literal line (#141346).
        """
        command = ('echo \'tell application "Keynote"\\nclose front document saving no\\n'
                   "end tell' | osascript")
        monkeypatch.setenv("SHELL", "/bin/zsh")
        assert detect_dangerous_command(command)[0] is True
        monkeypatch.setenv("SHELL", "/bin/bash")
        assert detect_dangerous_command(command) == (False, None, None)


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


class TestCarriersTheReportLeft:
    """The five carriers a live matrix still drove through head `e8810eecb7` (#141346)."""

    @pytest.mark.parametrize("command", [
        # 1. The payload rides on the switch: `-e'…'` with no space is accepted by the binary.
        'osascript -e\'tell application "Keynote" to close front document saving no\'',
        # 2. No `-l` means AppleScript, whatever identifiers the prose holds: `set var to 1`
        #    used to flip this into the JXA reading, whose apostrophe pairing ate `saving no`.
        'osascript <<\'EOF\'\n'
        'set var to 1\n'
        'tell application "Keynote" to close (first document whose name is front document\'s name) '
        'saving no -- don\'t\n'
        'EOF',
        # 3. JXA is not line-structured: the options object sits on its own lines.
        'osascript -l JavaScript <<\'EOF\'\n'
        'const doc = Application("Keynote").documents[0];\n'
        'doc.close({\n'
        '  saving: "no"\n'
        '});\n'
        'EOF',
        # 4. `printf` decodes `\n` before osascript reads stdin; with the escapes spelled out the
        #    close verb lost its word boundary (`"Keynote"\nclose` → `"Keynote"nclose`).
        'printf \'tell application "Keynote"\\nclose front document saving no\\nend tell\\n\' | osascript',
        # 5. A quoted heredoc delimiter is a shell word and may hold spaces.
        'osascript <<\'END SCRIPT\'\n'
        'tell application "Keynote" to quit without saving\n'
        'END SCRIPT',
    ])
    def test_the_carrier_is_judged(self, command):
        assert detect_dangerous_command(command) == (True, DESCRIPTION, DESCRIPTION), command

    @pytest.mark.parametrize("command", [
        # The same five carriers holding a read instead of the operation.
        'osascript -e\'tell application "Keynote" to get name of front document\'',
        'osascript <<\'EOF\'\n'
        'set var to 1\n'
        'tell application "Keynote" to get name of front document\n'
        'EOF',
        'osascript -l JavaScript <<\'EOF\'\n'
        'const doc = Application("Keynote").documents[0];\n'
        'doc.close({\n'
        '  saving: "yes"\n'
        '});\n'
        'EOF',
        'printf \'tell application "Keynote"\\nactivate\\nend tell\\n\' | osascript',
        'osascript <<\'END SCRIPT\'\n'
        'tell application "Keynote" to get name of front document\n'
        'END SCRIPT',
    ])
    def test_the_same_carrier_reading_is_inert(self, command):
        assert detect_dangerous_command(command) == (False, None, None), command


class TestTheVerifiersSecondRound:
    """Three diagnostics a verifier drove through head `2b8520e9f0` (#141346)."""

    def test_echo_dash_e_decodes_under_a_bash_shell(self, monkeypatch):
        """`echo -e` asks for the decoding wherever the shell defaults to printing.

        The shell decides the default (zsh decodes, bash prints), but `-e` overrides it in both
        directions, so `SHELL=/bin/bash; echo -e '…\\nclose …'` hands the binary two lines and the
        close is real. Reading only `$SHELL` judged it inert (#141346).
        """
        command = ('echo -e \'tell application "Keynote"\\\\nclose front document saving no\\\\n'
                   "end tell' | osascript")
        monkeypatch.setenv("SHELL", "/bin/bash")
        dangerous, key, desc = detect_dangerous_command(command)
        assert dangerous is True, command
        assert key == DESCRIPTION
        assert desc == DESCRIPTION

    @pytest.mark.parametrize("command", [
        # `-E` turns the decoding off under the shell that would have done it, so the same payload
        # reaches the binary as one literal line holding `\\n` — a `-e`-style flag pair, read both
        # ways.
        'echo -E \'tell application "Keynote"\\\\nclose front document saving no\\\\n'
        "end tell' | osascript",
        # The flag can ride with another one (`-n`, no trailing newline).
        'echo -nE \'tell application "Keynote"\\\\nclose front document saving no\\\\n'
        "end tell' | osascript",
    ])
    def test_echo_dash_capital_e_prints_them_literally(self, command, monkeypatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        assert detect_dangerous_command(command) == (False, None, None), command

    def test_the_raw_projection_stays_out_of_the_flat_patterns(self):
        """A commit message that merely mentions a destructive command is prose, not a command.

        The raw line is fed to the AppleScript reader because it is the only projection that keeps
        the escapes a `printf`-style producer decodes; the flat patterns judge the de-obfuscated
        variants, and reading the raw line there matched `disk copy` inside the message body
        (#141346).
        """
        command = 'git commit -m "notes\ndd if=/dev/zero of=/dev/sda explained"'
        assert detect_dangerous_command(command) == (False, None, None), command

    def test_the_flat_patterns_still_read_the_command_itself(self):
        """The control for the row above: the same text as an actual command is still caught."""
        dangerous, key, _desc = detect_dangerous_command("dd if=/dev/zero of=/dev/sda")
        assert dangerous is True
        assert key == "disk copy"

    def test_a_name_inside_a_string_literal_is_not_the_binding(self):
        """`close("o")` passes the one-character string `o`, not a bound options object.

        Resolving the identifier out of the quote read a binding the call never uses, so a close
        that keeps the document came back manual-only (#141346).
        """
        command = ('osascript -l JavaScript -e \'var o = {saving: "no"}; '
                   'Application("Keynote").documents[0].close("o")\'')
        assert detect_dangerous_command(command) == (False, None, None), command

    def test_the_same_name_passed_bare_is_the_binding(self):
        """The control: the identifier outside the quotes is the object it was bound to."""
        command = ('osascript -l JavaScript -e \'var o = {saving: "no"}; '
                   'Application("Keynote").documents[0].close(o)\'')
        dangerous, key, desc = detect_dangerous_command(command)
        assert dangerous is True, command
        assert key == DESCRIPTION
        assert desc == DESCRIPTION


class TestTheVerifiersThirdRound:
    """The rows the verifier drove on `111e21817c` (#141346).

    Two of them are one defect: the block-comment scan picked its closing marker off the second
    character of the opener, which is `*` for BOTH `(*` and `/*`, so every `/* … */` went looking
    for a `*)` a JavaScript program never holds, ran to the end of the source and deleted the live
    call that followed a closed comment. The rest are the same trust boundary one level down: a
    marker written inside a line comment, a template expression that is code beside data, and the
    POSIX spelling of an octal byte.
    """

    @pytest.mark.parametrize("command", [
        # A CLOSED comment in front of the operation.
        'osascript -l JavaScript -e \'/* closed */ '
        'Application("Keynote").documents[0].close({saving: "no"})\'',
        # A comment MARKER inside a line comment is prose, in both languages.
        'osascript -e \'-- (* open\ntell application "Keynote" to close front document saving no\'',
        'osascript -l JavaScript -e \'// /* open\n'
        'Application("Keynote").documents[0].close({saving: "no"})\'',
        # A template expression is an expression even though the template's text is data.
        'osascript -l JavaScript -e \'`${Application("Keynote").documents[0].close({saving: "no"})}`\'',
        # `\\0NNN` is POSIX octal: `\\0157` is `o`, so the payload reads `saving no`.
        'printf \'close front document saving n\\0157\' | osascript',
        'echo \'\\0161uit without saving\' | osascript',
    ])
    def test_the_closed_comment_and_the_octal_byte_reach_the_verb(self, command):
        dangerous, key, desc = detect_dangerous_command(command)
        assert dangerous is True, command
        assert key == DESCRIPTION
        assert desc == DESCRIPTION

    @pytest.mark.parametrize("command", [
        # Template TEXT prints the words and closes nothing; only `${…}` is code.
        'osascript -l JavaScript -e \'console.log(`.close({saving: "no"})`)\'',
        # `--` is also JavaScript's decrement, so it does not open a comment there.
        'osascript -l JavaScript -e \'var i = 3; i--; i--; console.log(i)\'',
        # A closed comment leaves the program standing, and a read is still a read.
        'osascript -e \'(* note *) get name of front document\'',
    ])
    def test_the_comment_and_template_controls_stay_inert(self, command):
        assert detect_dangerous_command(command) == (False, None, None), command

    def test_dash_prints_the_switch_and_still_decodes(self, monkeypatch):
        """`-E` is not POSIX: dash's `echo` prints the word and writes the escapes anyway.

        On this host `/bin/dash` emits `-E A`, `0a`, `B` for `echo -E 'A\\nB'`, so the same
        pipeline that bash hands over as one literal line is TWO lines under dash and the close is
        real. Reading `-E` as a switch there turned the decoding off (#141346).
        """
        command = ('echo -E \'tell application "Keynote"\\nclose front document saving no\\n'
                   "end tell' | osascript")
        monkeypatch.setenv("SHELL", "/bin/dash")
        dangerous, key, desc = detect_dangerous_command(command)
        assert dangerous is True, command
        assert key == DESCRIPTION
        assert desc == DESCRIPTION

    def test_dash_reads_are_still_reads(self, monkeypatch):
        """The control: the same producer under dash, with nothing destructive to decode."""
        command = ('echo -E \'tell application "Keynote"\\nget name of front document\\n'
                   "end tell' | osascript")
        monkeypatch.setenv("SHELL", "/bin/dash")
        assert detect_dangerous_command(command) == (False, None, None), command
