"""Tests for provider-aware replay-field accounting in tail-budget walks (#73624, #80246).

Generic thinking fields (``reasoning`` / ``reasoning_content`` + the
``reasoning_details`` text charge) are replayed for at most the NEWEST
assistant turn on Anthropic (strips all-but-newest at convert time) and
Bedrock (never replays thinking). Charging them on every message spent
19-24% of the tail budget on bytes that never reach the wire (#73624).

DeepSeek and Kimi thinking-mode chat endpoints echo every historical
``reasoning_content`` block. Skipping those bytes undercounts the tail,
compaction fires late, and the session hits an upstream 400 (#80246).

Codex sidecar fields (``codex_reasoning_items`` / ``codex_message_items``)
ARE wire-replayed on every retained turn and stay charged unconditionally
(#55572) — including native compaction checkpoints (#81747).
"""

from agent.context_compressor import (
    _ALWAYS_REPLAYED_BUDGET_KEYS,
    _NEWEST_TURN_ONLY_BUDGET_KEYS,
    _REPLAY_BUDGET_KEYS,
    _estimate_msg_budget_tokens,
    _last_assistant_index,
    _stale_thinking_reaches_the_wire,
)


BIG_THINKING = "deliberation " * 400  # ~1.3K tokens of stale thinking text
BIG_BLOB = [{"type": "reasoning", "encrypted_content": "x" * 4000}]


def _assistant(thinking=False, codex=False):
    msg = {"role": "assistant", "content": "done"}
    if thinking:
        msg["reasoning"] = BIG_THINKING
        msg["reasoning_content"] = BIG_THINKING
    if codex:
        msg["codex_reasoning_items"] = BIG_BLOB
    return msg


class TestChargeStaleThinking:
    def test_stale_turn_thinking_not_charged(self):
        msg = _assistant(thinking=True)
        full = _estimate_msg_budget_tokens(msg, charge_stale_thinking=True)
        stale = _estimate_msg_budget_tokens(msg, charge_stale_thinking=False)
        assert stale < full
        # The delta is the thinking text — a substantial chunk, not noise.
        assert full - stale > 300

    def test_codex_sidecar_always_charged(self):
        """Wire-replayed Codex blobs (incl. native compaction checkpoints)
        must stay in the budget even for stale turns — #55572's invariant."""
        msg = _assistant(codex=True)
        full = _estimate_msg_budget_tokens(msg, charge_stale_thinking=True)
        stale = _estimate_msg_budget_tokens(msg, charge_stale_thinking=False)
        assert stale == full  # nothing thinking-only to drop
        bare = _estimate_msg_budget_tokens(
            {"role": "assistant", "content": "done"}, charge_stale_thinking=False
        )
        assert stale > bare + 500  # blob still charged on the stale path

    def test_default_is_conservative_full_charge(self):
        msg = _assistant(thinking=True)
        assert _estimate_msg_budget_tokens(msg) == _estimate_msg_budget_tokens(
            msg, charge_stale_thinking=True
        )

    def test_reasoning_details_text_skipped_on_stale_path(self):
        msg = {
            "role": "assistant",
            "content": "done",
            "reasoning_details": [
                {"type": "reasoning.text", "text": "long plan " * 300}
            ],
        }
        full = _estimate_msg_budget_tokens(msg, charge_stale_thinking=True)
        stale = _estimate_msg_budget_tokens(msg, charge_stale_thinking=False)
        assert stale < full


class TestKeyPartition:
    def test_partition_covers_replay_budget_keys_exactly(self):
        """Invariant: the two accounting classes partition _REPLAY_BUDGET_KEYS.
        A future key added to the replay budget must be classified."""
        assert set(_ALWAYS_REPLAYED_BUDGET_KEYS) | set(
            _NEWEST_TURN_ONLY_BUDGET_KEYS
        ) == set(_REPLAY_BUDGET_KEYS)
        assert not set(_ALWAYS_REPLAYED_BUDGET_KEYS) & set(
            _NEWEST_TURN_ONLY_BUDGET_KEYS
        )

    def test_codex_fields_are_always_replayed_class(self):
        assert "codex_reasoning_items" in _ALWAYS_REPLAYED_BUDGET_KEYS
        assert "codex_message_items" in _ALWAYS_REPLAYED_BUDGET_KEYS


class TestLastAssistantIndex:
    def test_finds_newest_assistant(self):
        msgs = [
            {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
            {"role": "tool", "content": "t"},
        ]
        assert _last_assistant_index(msgs) == 3

    def test_no_assistant_returns_minus_one(self):
        assert _last_assistant_index([{"role": "user", "content": "u"}]) == -1
        assert _last_assistant_index([]) == -1


class TestTailCutBehavior:
    """The tail cut must protect MORE real transcript when stale turns carry
    heavy thinking — the #73624 symptom was the cut landing early."""

    def _compressor(self):
        from agent.context_compressor import ContextCompressor

        cc = ContextCompressor(
            model="claude-opus-5",
            quiet_mode=True,
            config_context_length=200_000,
        )
        return cc

    def test_stale_thinking_does_not_shrink_tail(self):
        cc = self._compressor()
        # Build a transcript where every assistant turn drags huge stale
        # thinking. Under the old accounting these bloat the walk and the
        # cut lands early; with newest-turn-only accounting the same budget
        # protects more messages.
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(30):
            msgs.append({"role": "user", "content": f"question {i}"})
            msgs.append(
                {
                    "role": "assistant",
                    "content": f"answer {i}",
                    "reasoning": BIG_THINKING,
                    "reasoning_content": BIG_THINKING,
                }
            )
        budget = 3_000
        cut = cc._find_tail_cut_by_tokens(msgs, 1, token_budget=budget)

        # Compute what the OLD accounting (charge everything) would protect.
        old_accumulated = 0
        old_cut = len(msgs)
        soft = int(budget * 1.5)
        for i in range(len(msgs) - 1, 0, -1):
            t = _estimate_msg_budget_tokens(msgs[i], charge_stale_thinking=True)
            if old_accumulated + t > soft and (len(msgs) - i) >= 3:
                break
            old_accumulated += t
            old_cut = i

        # New accounting must protect at least as much transcript (lower cut
        # index = more messages in the tail), and strictly more here because
        # the stale thinking dominates each message's old-cost.
        assert cut < old_cut

    def test_deepseek_charges_stale_thinking_so_tail_is_smaller_than_skip_stale(self):
        """DeepSeek echoes historical reasoning_content; skip-stale undercounts (#80246).

        Do not reimplement the compressor's min_tail / fallback / align
        walk here — those steps move the cut independently of thinking
        charge. Compare two compressors on the same transcript instead.
        """
        from agent.context_compressor import ContextCompressor

        msgs = [{"role": "system", "content": "sys"}]
        for i in range(30):
            msgs.append({"role": "user", "content": f"question {i}"})
            msgs.append(
                {
                    "role": "assistant",
                    "content": f"answer {i}",
                    "reasoning": BIG_THINKING,
                    "reasoning_content": BIG_THINKING,
                }
            )
        budget = 3_000
        skip_stale = ContextCompressor(
            model="claude-opus-5",
            provider="anthropic",
            quiet_mode=True,
            config_context_length=200_000,
        )
        charge_stale = ContextCompressor(
            model="deepseek-v4-flash",
            provider="deepseek",
            quiet_mode=True,
            config_context_length=200_000,
        )
        skip_cut = skip_stale._find_tail_cut_by_tokens(msgs, 1, token_budget=budget)
        charge_cut = charge_stale._find_tail_cut_by_tokens(msgs, 1, token_budget=budget)
        # Higher cut index = fewer messages kept verbatim. Charging the
        # echoed thinking spends the budget faster so compaction fires
        # before the wire request exceeds the model limit.
        assert charge_cut > skip_cut

    def test_kimi_matches_deepseek_stale_thinking_charge(self):
        """Kimi thinking mode has the same historical-echo requirement as DeepSeek."""
        from agent.context_compressor import ContextCompressor

        msgs = [{"role": "system", "content": "sys"}]
        for i in range(30):
            msgs.append({"role": "user", "content": f"question {i}"})
            msgs.append(
                {
                    "role": "assistant",
                    "content": f"answer {i}",
                    "reasoning": BIG_THINKING,
                    "reasoning_content": BIG_THINKING,
                }
            )
        budget = 3_000
        deepseek = ContextCompressor(
            model="deepseek-v4-flash",
            provider="deepseek",
            quiet_mode=True,
            config_context_length=200_000,
        )
        kimi = ContextCompressor(
            model="kimi-k2.5",
            provider="moonshot",
            quiet_mode=True,
            config_context_length=200_000,
        )
        assert deepseek._find_tail_cut_by_tokens(msgs, 1, token_budget=budget) == kimi._find_tail_cut_by_tokens(
            msgs, 1, token_budget=budget
        )


class TestStaleThinkingWireReplay:
    def test_deepseek_and_kimi_replay_stale_thinking(self):
        assert _stale_thinking_reaches_the_wire("deepseek-v4-flash", "deepseek")
        assert _stale_thinking_reaches_the_wire("kimi-k2.5", "")
        assert _stale_thinking_reaches_the_wire("moonshot-v1", "moonshot")
        # Custom-provider DeepSeek still matches on the model id.
        assert _stale_thinking_reaches_the_wire("deepseek-v4-flash", "custom")
        assert not _stale_thinking_reaches_the_wire("claude-opus-5", "anthropic")
        assert not _stale_thinking_reaches_the_wire("gpt-5", "openai")
        assert not _stale_thinking_reaches_the_wire("", "")
