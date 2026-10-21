"""The text a shell pipeline hands a program on stdin, read out of the command line.

`osascript`, `python -`, `sh` and friends take their program from stdin, so the payload is only
visible in the producer stage's own argv (`printf '…'`), in a heredoc body it reads, or in the
literal a filter prints (`awk 'BEGIN{print "…"}'`). This module owns that reading for the approval
detector: which stages produce text, how each one spells the escapes it decodes on the way out, and
where a here-document ends.

Kept out of `tools/approval_detection.py` because the detector is a facade at its file-size cap;
nothing here imports it back, so the two stay acyclic.
"""

import os
import re

# A heredoc delimiter is a shell word, not an identifier: `<<'APPLESCRIPT-END'` is valid, a quoted
# delimiter may hold spaces (`<<'END SCRIPT'`), and `<<-` (tabs stripped) is not the same body rule
# as a plain `<<` (delimiter alone on the line).
_HEREDOC_MARKER_RE = re.compile(
    r"<<(?P<dash>-?)[ \t]*(?:(?P<quote>['\"])(?P<quoted>[^'\"]+)(?P=quote)"
    r"|(?P<delimiter>[A-Za-z0-9_][A-Za-z0-9_.-]*))"
)


def _heredoc_delimiter(marker) -> str:
    """The delimiter of a heredoc marker: the quoted word when quoted, else the bare one."""
    return marker.group("quoted") or marker.group("delimiter")


# Producers that decode backslash escapes on their way to stdout: `printf 'a\nb'` hands osascript
# two lines, not one line holding `\n` — and on that single line `\nclose` is not the word `close`.
# `printf` decodes in every sh-family shell; `echo` only where the shell interprets them itself.
_ESCAPE_DECODING_PRODUCERS = frozenset({"printf", "echo"})
# The shells whose `echo` writes those escapes out as bytes rather than printing them: zsh
# interprets them with no flag, and so does dash's builtin (XSI behaviour, measured on #141346:
# `/bin/dash` emitted `41 0a 42 0a` for `echo 'A\nB'`), which makes `dash`, `ksh` and `mksh`
# decoders too. `bash` and a bare `sh` are the literal ones — `/bin/sh` is bash on macOS and dash
# on Debian, so the ambiguous spelling keeps the literal reading and `SHELL=/bin/dash` on the
# command line is what names the decoder (`terminal` spawns the user's `$SHELL`).
_ECHO_LITERAL_SHELLS = frozenset({"bash", "sh"})
_SHELL_ESCAPE_RE = re.compile(
    r"\\(?:x(?P<hex>[0-9A-Fa-f]{1,2})|(?P<octal>[0-7]{1,3})|(?P<code>[nrt]))"
)
_SHELL_ESCAPE_CODES = {"n": "\n", "r": "\r", "t": "\t"}
# `echo`'s own switches: `-e` forces the escape decoding, `-E` turns it off. They can be spelled
# together (`-ne`, `-nE`) and they are not part of the text the binary reads.
_ECHO_FLAG_RE = re.compile(r"^-[neE]+$")


def _decode_shell_escapes(text: str) -> str:
    """Spell out the escapes a decoding producer writes as bytes, `\\xHH` and `\\NNN` included."""
    def replace(match) -> str:
        if match.group("hex"):
            return chr(int(match.group("hex"), 16))
        if match.group("octal"):
            return chr(int(match.group("octal"), 8))
        return _SHELL_ESCAPE_CODES[match.group("code")]

    return _SHELL_ESCAPE_RE.sub(replace, text)


def _echo_decodes_escapes(shell: str | None = None) -> bool:
    """Whether this host's `echo` hands the escapes over as bytes (`zsh`) or prints them as text.

    The detector runs in the process that spawns the command, so `$SHELL` is the shell the pipeline
    will reach the binary from — unless the command itself pins it (`SHELL=/bin/dash echo …`), which
    *shell* names. An unset `$SHELL` keeps the decoding reading: it is the one that catches the
    destructive program instead of printing it (reported on #141346).
    """
    name = shell if shell is not None else os.environ.get("SHELL", "")
    return os.path.basename(name).lower() not in _ECHO_LITERAL_SHELLS


def _echo_payload(tokens, shell: str | None = None) -> tuple:
    """The text `echo` prints, and whether it decodes escapes, out of *tokens* (its own argv).

    The shell decides the default — zsh decodes, bash/sh print — but `echo`'s own flags override
    it in both directions: `-e` asks for the decoding anywhere, `-E` turns it off where the shell
    would have decoded. A flag is not part of the text, so it leaves the payload. Reading only
    `$SHELL` judged `SHELL=/bin/bash; echo -e '…\\nclose …'` as one literal line and the close
    went unseen (reported on #141346).
    """
    decodes = _echo_decodes_escapes(shell)
    text: list[str] = []
    for token in tokens:
        if _ECHO_FLAG_RE.match(token):
            for flag in token[1:]:
                if flag == "e":
                    decodes = True
                elif flag == "E":
                    decodes = False
            continue
        text.append(token)
    return decodes, " ".join(text)


def _printed_literals(raw_stage: str) -> str | None:
    """Text a filter-`print` stage emits from its own literals, or None when it only transforms.

    `awk 'BEGIN{print "tell … to quit without saving"}'` produces the program on its own, so the
    payload behind the pipe is its argv. `grep -v 'quit without saving'` only filters, and reading
    its pattern as the script flagged a harmless pipeline (reported on #141346) — hence the two
    conditions: a print verb AND a quoted literal. Anything else stays a pass-through stage.
    """
    if not re.search(r"\bprint(?:f)?\b", raw_stage):
        return None
    literals = re.findall(r'"((?:\\.|[^"\\])*)"', raw_stage)
    if not literals:
        return None
    return " ".join(literal.replace('\\"', '"') for literal in literals)


def _strip_output_redirections(tokens: list[str]) -> list[str]:
    """*tokens* without output redirections, which are wiring rather than script operands.

    The tokenizer splits `2>&1` into `2`, `>`, `&1` (`punctuation_chars="<>"`), so a bare digit is
    the descriptor the operator applies to when an operator follows it. Input redirections are
    KEPT: a program that arrives from a file is a source this detector cannot read, and dropping
    it would turn an unreadable source into "no source".
    """
    cleaned: list[str] = []
    position = 0
    while position < len(tokens):
        token = tokens[position]
        following = tokens[position + 1] if position + 1 < len(tokens) else None
        if following in (">", ">>", ">&") and (token.isdigit() or token in ("&", "<", "<<")):
            position += 1  # the descriptor the operator applies to
            continue
        if token in (">", ">>", ">&"):
            position += 2 if following is not None and not following.startswith("<") else 1
            continue
        cleaned.append(token)
        position += 1
    return cleaned


def _heredoc_body(command: str, marker_end: int, delimiter: str, strip_tabs: bool = False) -> str:
    """Body of the heredoc whose delimiter starts after *marker_end*.

    A plain `<<` body ends only on the delimiter alone on its line, so an indented ` EOF` is part
    of the program; `<<-` strips leading tabs from each line before the comparison (and only tabs).
    """
    newline = command.find("\n", marker_end)
    if newline < 0:
        return ""
    body: list[str] = []
    # Physical lines only: the shell ends a heredoc on an LF-terminated line, so a CR or a vertical
    # tab inside a body line is data. `splitlines()` splits on those too, which turned
    # `beep<CR>tell … to quit without saving` into a `beep` delimiter line and dropped the
    # destructive statement that the shell keeps in the body (reported on #141346).
    for line in command[newline + 1:].split("\n"):
        candidate = line.lstrip("\t") if strip_tabs else line
        if candidate == delimiter:
            return "\n".join(body)
        body.append(line)
    # An unterminated heredoc is not "no heredoc": bash warns about the missing delimiter and then
    # feeds everything it read, so `osascript <<'EOF'\ntell … to quit without saving` executes the
    # program while the reader saw nothing to judge (reported on #141346). A body that is empty
    # still returns "" so the caller keeps the "source is unreachable" answer rather than inventing
    # a payload.
    return "\n".join(body)
