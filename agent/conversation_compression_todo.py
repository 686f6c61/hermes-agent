"""Scope of the stale todo-snapshot strip at the compaction boundary.

Compaction appends the todo snapshot (``TODO_INJECTION_HEADER`` +
``TodoStore.format_for_injection``) to the end of the trailing user turn; every later boundary strips
that block before folding in a fresh one, so the list refreshes instead of accumulating (#26981).

The strip is scoped to the block. The pre-call repair in
``agent_runtime_helpers._merge_consecutive_users`` can join a later user turn onto the very row that
already carries a snapshot — a boundary folds the snapshot into the trailing user row, the turn ends
without an assistant row (an API error or /stop), the user sends the next message — so the new human
text sits *after* the header. Cutting everything from the header down deleted that turn at the next
boundary: the model never saw the message again (#137652).

Block shape — what is removed, and what survives::

    <real turn text>
    <blank>
    [Your active task list was preserved across context compression]
    - [>] 1. ship the release (in_progress)
    <blank>                                    # only when this boundary pruned skill bodies
    [Skills pruned during compression — reload before acting on these tasks]
    <notice body>
    <blank>
    <a later user turn merged onto this row>    # kept
"""

from __future__ import annotations

from typing import Any


def _block_end(text: str, start: int, notice_header: str) -> int:
    """Index of the newline that closes the snapshot block whose header begins at *start*.

    The block is the header line plus its task lines, and the reload notice rides after one blank line
    as part of it, so only a blank line followed by anything else ends the block. ``len(text)`` when the
    block runs to the end of the content."""
    end = start
    while True:
        brk = text.find("\n\n", end)
        if brk == -1:
            return len(text)
        if notice_header and text.startswith(notice_header, brk + 2):
            end = brk + 2
            continue
        return brk


def _strip_text(text: str, header: str, notice_header: str) -> str:
    """Remove every snapshot block from *text*, keeping the text before, between and after them."""
    while (start := text.find(header)) != -1:
        head = text[:start].rstrip()
        tail = text[_block_end(text, start, notice_header):].lstrip("\n")
        text = f"{head}\n\n{tail}" if head and tail else (head or tail)
    return text


def strip_todo_snapshot_block(content: Any, notice_header: str = "") -> Any:
    """Strip the stale todo-snapshot block from message content, keeping any text around it.

    Strings are stripped in place. In list content each ``text`` part is stripped on its own and a part
    that held nothing but the block is dropped, while non-text parts (image, audio, …) always survive —
    they are never snapshot scaffolding. *notice_header* is the reload notice that belongs to the block;
    omitted, the notice is left in place like any other text."""
    from tools.todo_tool import TODO_INJECTION_HEADER
    if isinstance(content, str):
        return _strip_text(content, TODO_INJECTION_HEADER, notice_header)
    if isinstance(content, list):
        cleaned = []
        for part in content:
            text = str(part.get("text") or "") if isinstance(part, dict) and part.get("type") == "text" else ""
            if not text or TODO_INJECTION_HEADER not in text:
                cleaned.append(part)
            elif stripped := _strip_text(text, TODO_INJECTION_HEADER, notice_header):
                cleaned.append({**part, "text": stripped})
        return cleaned
    return content
