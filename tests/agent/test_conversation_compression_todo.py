"""The stale todo-snapshot strip is scoped to the block, not to the rest of the row (#137652).

Compaction folds the todo snapshot into the trailing user turn. The pre-call repair
(``agent_runtime_helpers._merge_consecutive_users``) can then join the next user turn onto that same
row, leaving the new human text *after* the header. The next boundary used to cut from the header down
and delete that text: the model never saw the message again. These tests pin the block scope — the
snapshot goes, everything around it stays — and the boundary-level repro end to end.
"""

from __future__ import annotations

from types import SimpleNamespace

from agent.agent_runtime_helpers import _merge_consecutive_users
from agent.conversation_compression import (
    _PRUNED_SKILL_RELOAD_NOTICE_HEADER,
    _fold_todo_snapshot,
    _strip_stale_todo_snapshot,
)
from tools.todo_tool import TODO_INJECTION_HEADER, TodoStore


def _snapshot(*lines: str) -> str:
    return "\n".join([TODO_INJECTION_HEADER, *lines])


TASK_LINE = "- [>] 1. ship the release (in_progress)"
STALE_LINE = "- [ ] t0. old finished task (pending)"


class TestStrippedScope:
    """Only the block is removed; text before, between and after it survives."""

    def test_merged_user_turn_after_the_snapshot_survives(self):
        content = f"first request\n\n{_snapshot(TASK_LINE)}\n\nSECOND MESSAGE: please also update the docs"
        assert (
            _strip_stale_todo_snapshot(content)
            == "first request\n\nSECOND MESSAGE: please also update the docs"
        )

    def test_snapshot_at_the_end_still_strips_to_the_remaining_text(self):
        content = f"please fix the login bug\n\n{_snapshot(STALE_LINE)}"
        assert _strip_stale_todo_snapshot(content) == "please fix the login bug"

    def test_a_row_that_is_only_the_snapshot_strips_to_nothing(self):
        assert _strip_stale_todo_snapshot(_snapshot(STALE_LINE)) == ""

    def test_text_after_a_bare_snapshot_survives(self):
        content = f"{_snapshot(STALE_LINE)}\n\nSECOND MESSAGE"
        assert _strip_stale_todo_snapshot(content) == "SECOND MESSAGE"

    def test_no_snapshot_returns_the_content_untouched(self):
        assert _strip_stale_todo_snapshot("just a turn") == "just a turn"

    def test_repeated_blocks_do_not_accumulate(self):
        content = (
            f"keep me\n\n{_snapshot(STALE_LINE)}\n\nkeep me too\n\n{_snapshot('- [ ] t1. stale (pending)')}"
        )
        assert _strip_stale_todo_snapshot(content) == "keep me\n\nkeep me too"

    def test_the_reload_notice_rides_with_the_block(self):
        """The notice belongs to the block, so text after it is still a later turn, not the block."""
        content = (
            f"real user words\n\n{_snapshot(STALE_LINE)}\n\n{_PRUNED_SKILL_RELOAD_NOTICE_HEADER}\n"
            "reload skill_view(name='old-skill') first.\n\nSECOND MESSAGE"
        )
        stripped = _strip_stale_todo_snapshot(content)
        assert stripped == "real user words\n\nSECOND MESSAGE"
        assert _PRUNED_SKILL_RELOAD_NOTICE_HEADER not in stripped

    def test_list_content_keeps_the_later_text_and_non_text_parts(self):
        content = [
            {"type": "text", "text": f"real user words\n\n{_snapshot(STALE_LINE)}\n\nSECOND MESSAGE"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
        ]
        assert _strip_stale_todo_snapshot(content) == [
            {"type": "text", "text": "real user words\n\nSECOND MESSAGE"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
        ]

    def test_list_part_that_was_only_the_block_is_dropped(self):
        content = [
            {"type": "text", "text": _snapshot(STALE_LINE)},
            {"type": "text", "text": "hello"},
        ]
        assert _strip_stale_todo_snapshot(content) == [{"type": "text", "text": "hello"}]


class TestBoundaryAfterTheMerge:
    """The issue's repro: fold, then merge the next user turn, then fold again."""

    @staticmethod
    def _agent() -> SimpleNamespace:
        store = TodoStore()
        store.write([{"id": "1", "content": "ship the release", "status": "in_progress"}])
        return SimpleNamespace(_todo_store=store, _repair_message_sequence=lambda rows: None)

    def test_second_message_survives_the_next_boundary(self):
        agent = self._agent()
        rows = [{"role": "user", "content": "first request"}]
        _fold_todo_snapshot(agent, rows)
        assert TODO_INJECTION_HEADER in rows[-1]["content"]

        rows.append({"role": "user", "content": "SECOND MESSAGE: please also update the docs"})
        rows, _repairs = _merge_consecutive_users(rows)
        assert len(rows) == 1

        _fold_todo_snapshot(agent, rows)
        assert "SECOND MESSAGE: please also update the docs" in rows[-1]["content"]
        assert "first request" in rows[-1]["content"]
        assert rows[-1]["content"].count(TODO_INJECTION_HEADER) == 1

    def test_the_merged_row_keeps_one_fresh_snapshot(self):
        """The strip still refreshes the list instead of stacking a second snapshot."""
        agent = self._agent()
        rows = [{"role": "user", "content": "first request"}]
        _fold_todo_snapshot(agent, rows)
        rows.append({"role": "user", "content": "SECOND MESSAGE"})
        rows, _repairs = _merge_consecutive_users(rows)
        _fold_todo_snapshot(agent, rows)
        tail = rows[-1]["content"]
        assert tail.count("- [>] 1. ship the release (in_progress)") == 1
        assert tail.index("first request") < tail.index(TODO_INJECTION_HEADER)
        assert tail.index("SECOND MESSAGE") < tail.index(TODO_INJECTION_HEADER)
