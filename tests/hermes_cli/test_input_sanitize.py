"""Tests for shared user prompt input sanitization."""

from hermes_cli.input_sanitize import (
    collapse_repeated_input_artifacts,
    sanitize_user_prompt_text,
    strip_leaked_bracketed_paste_wrappers,
)


class TestStripLeakedBracketedPasteWrappers:
    def test_plain_text_unchanged(self):
        assert strip_leaked_bracketed_paste_wrappers("hello world") == "hello world"



    def test_does_not_strip_non_wrapper_bracket_forms_in_normal_text(self):
        text = "literal[200~tag and literal[201~tag should stay"
        assert strip_leaked_bracketed_paste_wrappers(text) == text

    def test_keeps_clock_time_ranges_intact(self):
        """A time range is user text, not a degraded marker (#143444)."""
        for text in ("12:00~12:15", "08:00~09:30", "9:00~9:30", "12:01~ 12:15"):
            assert strip_leaked_bracketed_paste_wrappers(text) == text

    def test_keeps_a_time_range_inside_a_sentence(self):
        text = "Schedule lunch 12:00~12:15."
        assert strip_leaked_bracketed_paste_wrappers(text) == text

    def test_keeps_a_range_with_several_spaces(self):
        """Any run of spaces may separate the two times (live check on #143444)."""
        text = "12:01~  12:15"
        assert strip_leaked_bracketed_paste_wrappers(text) == text

    def test_keeps_a_marker_embedded_before_a_range(self):
        """The `01~` in `id01~12:00~12:15` is mid-string in the original, so it is not a boundary marker."""
        text = "id01~12:00~12:15"
        assert strip_leaked_bracketed_paste_wrappers(text) == text

    def test_keeps_a_marker_embedded_after_a_range(self):
        """The `[200~` in `12:00~12:15[200~tag` follows the range, not the start of the string."""
        text = "12:00~12:15[200~tag"
        assert strip_leaked_bracketed_paste_wrappers(text) == text

    def test_still_strips_a_degraded_wrapper_beside_a_time_range(self):
        assert strip_leaked_bracketed_paste_wrappers("00~12:00~12:15 and 00~x01~") == "12:00~12:15 and x"


class TestCollapseRepeatedInputArtifacts:
    def test_issue_62557_corruption_tail(self):
        prefix = "需要时随时叫我。"
        tail = "[e~[[e" + "~[[e" * 20
        assert collapse_repeated_input_artifacts(prefix + tail) == prefix


    def test_trailing_punctuation_preserved(self):
        assert collapse_repeated_input_artifacts("wait....") == "wait...."


class TestSanitizeUserPromptText:
    def test_combines_wrapper_strip_and_tail_collapse(self):
        prefix = "hello["
        corrupted = prefix + "~[[e" * 8
        assert sanitize_user_prompt_text(corrupted) == "hello"
