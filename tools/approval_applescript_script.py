"""Which script text closes or quits a document without saving (#141346).

Topical sibling of :mod:`tools.approval_detection` (`<stem>_<topic>.py`): the carrier machinery
that finds an `osascript` program stays there, while the judgement of the program itself — the
language readings, the raw four-character codes, JXA comments — lives here.

`osascript` reaches an application the agent never opened, and the document it names belongs to
the operator: closing or quitting with "do not save" discards that unsaved work and the app's
AutoRecovery with it, so the class is manual-only.
"""

import re

_OSASCRIPT_CLOSE_VERB_RE = re.compile(r"\b(?:close|quit|shut\s+down)\b", re.IGNORECASE)
_OSASCRIPT_NO_SAVE_RE = re.compile(r"\bwithout\s+saving\b|\bsaving\s*(?::\s*)?(?:no|false)\b", re.IGNORECASE)
# AppleScript string literals: an operation verb and the "without saving" text inside a quoted
# string is prose (a dialog asking the question), not the operation.
#
# Only double quotes delimit an AppleScript literal. A single quote is an apostrophe in prose
# (`(first document whose name is front document's name)`), and reading it as a literal delimiter
# paired the possessive with the apostrophe of a later `-- don't` comment, swallowing the
# `saving no` between them and letting the destructive statement read as inert. JavaScript (JXA)
# does use both, so the single-quoted form is stripped only for a source that looks like JXA.
_SCRIPT_STRING_LITERAL_RE = re.compile(r'"(?:[^"\\]|\\.)*"')
_SCRIPT_SINGLE_QUOTED_LITERAL_RE = re.compile(r"'(?:[^'\\]|\\.)*'")
_JS_SCRIPT_HINT_RE = re.compile(r"Application\s*\(|ObjC\.|\.close\s*\(|\b(?:var|let|const)\s")
# AppleScript's line-continuation character; the statement continues after it, and CR is a line
# ending the language accepts as well as LF.
_APPLESCRIPT_CONTINUATION_RE = re.compile(r"¬[ \t]*(?:\r\n|\r|\n)[ \t]*")
# Comments are prose in both languages, and an operation that only appears inside one is not the
# operation: `get name of front document -- quit without saving` reads the document, and
# `documents.length // .close({saving: "no"})` is commented-out JXA.
_APPLESCRIPT_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_APPLESCRIPT_BLOCK_COMMENT_RE = re.compile(r"\(\*.*?\*\)", re.DOTALL)
_JS_LINE_COMMENT_RE = re.compile(r"(?<!:)//[^\n]*")
_JS_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
# JXA's close option is the string enum "yes" | "no" | "ask" (`saving: false` also appears in the
# wild); only the two that discard the document count — `saving: "ask"` prompts by itself. The key
# is a JS property name, so it may be quoted. The object is any ARGUMENT of the call, not just the
# first: `close(k.documents[0], {saving: "no"})` names the document as the direct parameter and the
# options second (Apple's JXA release notes), and a local `var o = {saving: "no"}` handed to
# `close(o)` is the same object one binding away.
_JXA_CALL_RE = re.compile(r"\.(?:close|quit)\s*\(", re.IGNORECASE)
_JXA_NO_SAVE_OBJECT_RE = re.compile(
    r"\{[^{}]*[\"']?saving[\"']?\s*:\s*(?:[\"'](?:no|false)[\"']|false)[^{}]*\}",
    re.IGNORECASE,
)
_JXA_OBJECT_BINDING_RE = re.compile(r"\b(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*(\{[^{}]*\})")
# AppleScript can address a command by its four-character code: `«event coreclos»` is `close` and
# `«class savo»` is the `saving` parameter, which is the same Standard Suite operation.
_APPLESCRIPT_RAW_CODE_RE = re.compile(r"«(?:event|class)\s+([A-Za-z0-9]+)»")
_APPLESCRIPT_RAW_CODE_NAMES = {"coreclos": "close", "aevtquit": "quit", "savo": "saving"}


def strip_js_comments(statement: str) -> str:
    """Drop JXA comments that sit outside a string literal.

    A plain regex cannot tell `//` in `var s = "//"` from the start of a comment, and cutting there
    deleted the `.close({saving: "no"})` that followed on the same line, so the real call read as
    inert (reported on #141346).
    """
    out: list[str] = []
    index, quote, length = 0, "", len(statement)
    while index < length:
        char = statement[index]
        if quote:
            out.append(char)
            if char == "\\" and index + 1 < length:
                out.append(statement[index + 1])
                index += 2
                continue
            if char == quote:
                quote = ""
        elif char in "\"'`":
            quote = char
            out.append(char)
        elif statement.startswith("//", index):
            break
        elif statement.startswith("/*", index):
            end = statement.find("*/", index + 2)
            if end < 0:
                break
            index = end + 2
            continue
        else:
            out.append(char)
        index += 1
    return "".join(out)


def script_closes_without_saving(source: str, language: str | None = None) -> bool:
    """Whether *source*, as script text in *language*, closes or quits a document without saving.

    *language* is the `-l` value when the invocation names one. With no ``-l`` the binary reads the
    program as AppleScript, so that reading is the rule; the JXA one is kept as a second reading
    because nothing stops a caller from piping JavaScript to a bare `osascript` and the union only
    adds manual-only answers. Reading exactly one guess was wrong in both directions: an
    AppleScript comment holding the word `let` flipped a document close into the JXA reading (where
    the apostrophe of `front document's name` pairs with the one in `-- don't`, swallowing the
    `saving no` between them), and `set var to 1` did the same by its `var`.
    """
    # Four-character codes are the same command and parameter spelled raw.
    source = _APPLESCRIPT_RAW_CODE_RE.sub(
        lambda match: _APPLESCRIPT_RAW_CODE_NAMES.get(match.group(1).lower(), match.group(0)),
        source,
    )
    # `¬` continues an AppleScript statement on the next physical line, so `saving ¬\nno` is the
    # same operation as `saving no`; splitting first would strand each half on its own line.
    source = _APPLESCRIPT_CONTINUATION_RE.sub(" ", source)
    if language:
        readings = (language,)
    else:
        # A bare `osascript` reads AppleScript, so that reading is always taken; the JXA one is
        # added when the code (not a comment or a string literal) looks like JavaScript, because
        # piping JavaScript into a bare `osascript` is a shape callers write too. Reading only the
        # hint was wrong in both directions: `set var to 1` flipped an AppleScript close into the
        # JXA reading, where the apostrophe of `front document's name` pairs with the one in
        # `-- don't` and swallows the `saving no` between them.
        code_only = _SCRIPT_STRING_LITERAL_RE.sub(
            '""', _APPLESCRIPT_BLOCK_COMMENT_RE.sub("", _APPLESCRIPT_LINE_COMMENT_RE.sub("", source))
        )
        readings = ("applescript", "javascript") if _JS_SCRIPT_HINT_RE.search(code_only) else ("applescript",)
    return any(_reading_closes_without_saving(source, reading == "javascript") for reading in readings)


def _call_arguments(source: str, open_paren: int) -> str | None:
    """Text between the `(` that ends at *open_paren* and its matching `)`, string literals intact.

    Balanced rather than greedy: `close(k.documents[0], {saving: "no"})` has a nested call and an
    index, and a regex that stopped at the first `)` would read `{saving: …}` as outside the call.
    """
    depth, index, quote, start = 0, open_paren - 1, "", open_paren
    while index < len(source):
        char = source[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = ""
        elif char in "\"'`":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return source[start:index]
        index += 1
    return None


def _jxa_closes_without_saving(source: str) -> bool:
    """Whether a JXA close/quit call carries a no-save options object.

    The object may be any argument (JXA's direct parameter comes first, the named-parameter object
    second) or a local binding handed to the call (`var o = {saving: "no"}; …close(o)`).
    """
    bindings = {
        match.group(1)
        for match in _JXA_OBJECT_BINDING_RE.finditer(source)
        if _JXA_NO_SAVE_OBJECT_RE.search(match.group(2))
    }
    for match in _JXA_CALL_RE.finditer(source):
        arguments = _call_arguments(source, match.end())
        if arguments is None:
            continue
        if _JXA_NO_SAVE_OBJECT_RE.search(arguments):
            return True
        for name in bindings:
            if re.search(rf"(?<![\w$.]){re.escape(name)}(?![\w$])", arguments):
                return True
    return False


def _reading_closes_without_saving(source: str, javascript: bool) -> bool:
    """One language's reading of *source*: does it close or quit a document without saving?"""
    if javascript:
        # JXA is not line-structured: `doc.close({\n saving: "no"\n })` is one call across three
        # lines, so the joined program is read as well. Comments are dropped per line first, which
        # keeps `//` inside a string literal as data.
        joined = " ".join(strip_js_comments(line) for line in source.splitlines() or (source,))
        if _jxa_closes_without_saving(joined):
            return True
    for statement in source.splitlines() or (source,):
        if javascript:
            # A commented-out call is not the call: `documents.length // .close({saving: "no"})`,
            # while `//` inside a string is data and keeps the call beside it.
            statement = strip_js_comments(statement)
        # AppleScript string literals are DATA here: the dialog that ASKS "Quit without saving?"
        # must not read as the operation, while `close document "Untitled" saving no` still does.
        literal_free = _SCRIPT_STRING_LITERAL_RE.sub('""', statement)
        if javascript:
            literal_free = _SCRIPT_SINGLE_QUOTED_LITERAL_RE.sub('""', literal_free)
        else:
            # An AppleScript comment is prose too: `get name of front document -- quit without saving`.
            literal_free = _APPLESCRIPT_LINE_COMMENT_RE.sub(
                "", _APPLESCRIPT_BLOCK_COMMENT_RE.sub("", literal_free)
            )
        # A continuation character that survived on one line (`saving ¬ no`) is whitespace here.
        literal_free = literal_free.replace("¬", " ")
        if _OSASCRIPT_CLOSE_VERB_RE.search(literal_free) and _OSASCRIPT_NO_SAVE_RE.search(literal_free):
            return True
    return False
