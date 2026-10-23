"""Sanitize user prompt text leaked from terminal / paste control sequences."""

from __future__ import annotations

import re

# Degraded visible bracketed-paste forms, matched only at boundaries so embedded literals stay intact.
_BOUNDARY_SUBS = (
    (re.compile(r"(^|[\s\n>:\]\)])\[200~"), r"\1"),
    (re.compile(r"\[201~(?=$|[\s\n<\[\(\):;.,!?])"), ""),
    (re.compile(r"(^|[\s\n>:\]\)])00~"), r"\1"),
    (re.compile(r"01~(?=$|[\s\n<\[\(\):;.,!?])"), ""),
)

# A clock-time range (``12:00~12:15``) reuses the shape of the degraded ``00~`` / ``01~`` markers, so its
# span is held back from the boundary substitutions and passed through verbatim. Any run of spaces or tabs
# may separate the two times.
_CLOCK_TIME_RANGE = re.compile(r"\d{1,2}:\d{2}~[ \t]*\d{1,2}:\d{2}")

# Corruption signature from desktop bracketed-paste leaks (#62557).
_DESKTOP_PASTE_ARTIFACT = "~[[e"


def _strip_boundary_wrappers(text: str) -> str:
    for wrapper in ("\x1b[200~", "\x1b[201~", "^[[200~", "^[[201~"):
        text = text.replace(wrapper, "")
    for pattern, repl in _BOUNDARY_SUBS:
        text = pattern.sub(repl, text)
    return text


def _restore_ranges(stripped: str, source: str, spans: list[tuple[int, int]], placeholder: str) -> str:
    """Put the held-back range spans back in the order their placeholders appear."""
    restored: list[str] = []
    pending = list(spans)
    index = 0
    while index < len(stripped):
        if stripped[index] != placeholder:
            restored.append(stripped[index])
            index += 1
            continue
        run_end = index
        while run_end < len(stripped) and stripped[run_end] == placeholder:
            run_end += 1
        remaining = run_end - index
        while remaining and pending:
            start, stop = pending[0]
            length = stop - start
            if length > remaining:
                break
            restored.append(source[start:stop])
            pending.pop(0)
            remaining -= length
        index = run_end
    return "".join(restored)


def strip_leaked_bracketed_paste_wrappers(text: str) -> str:
    """Strip leaked bracketed-paste wrapper markers: canonical wrappers unconditionally, degraded visible forms
    (``[200~`` / ``[201~`` and ``00~`` / ``01~``) only at boundaries so ``literal[200~tag`` stays intact.

    A clock-time range is user text, not a wrapper: ``12:00~12:15`` reaches the model unchanged.
    """
    if not text:
        return text
    spans = [match.span() for match in _CLOCK_TIME_RANGE.finditer(text)]
    if not spans:
        return _strip_boundary_wrappers(text)
    # Hold each range back with a same-length placeholder instead of cutting the text into fragments: the
    # boundary patterns anchor on the neighbouring character, so a fragment that starts or ends where a range
    # does gains an artificial string boundary and eats a marker that is embedded in the original text
    # (``id01~12:00~12:15`` keeps its ``01~``, ``12:00~12:15[200~tag`` keeps its ``[200~``).
    placeholder = "\x00" if "\x00" not in text else "\x01"
    masked_pieces: list[str] = []
    cursor = 0
    for start, stop in spans:
        masked_pieces.append(text[cursor:start])
        masked_pieces.append(placeholder * (stop - start))
        cursor = stop
    masked_pieces.append(text[cursor:])
    stripped = _strip_boundary_wrappers("".join(masked_pieces))
    return _restore_ranges(stripped, text, spans, placeholder)


def collapse_repeated_input_artifacts(text: str, min_repeats: int = 4) -> str:
    """Drop a trailing run of the desktop ~[[e corruption signature (#62557)."""
    if not text:
        return text
    marker = _DESKTOP_PASTE_ARTIFACT
    index = len(text)
    repeat_count = 0
    while index >= len(marker) and text[index - len(marker) : index] == marker:
        repeat_count += 1
        index -= len(marker)
    if repeat_count < min_repeats:
        return text
    if index >= 2 and text[index - 2 : index] == "[e":
        index -= 2
    elif index >= 1 and text[index - 1] == "[":
        index -= 1
    return text[:index]


def sanitize_user_prompt_text(text: str) -> str:
    """Normalize user-authored prompt text before persistence or model input."""
    if not isinstance(text, str) or not text:
        return text
    return collapse_repeated_input_artifacts(strip_leaked_bracketed_paste_wrappers(text))
