"""The iteration-limit failure copy must name the config key that actually works (#132073).

``max_iterations`` is not a recognised user-facing config key for the main agent loop
(``hermes config set max_iterations`` even warns about it); the knob is ``agent.max_turns``.
"""

from agent.turn_failure_copy import site_copy


def test_max_iterations_no_summary_names_agent_max_turns():
    copy = site_copy("max_iterations_no_summary", limit=7)

    assert "agent.max_turns" in copy
    assert "max_iterations" not in copy


def test_max_iterations_no_summary_interpolates_the_limit():
    copy = site_copy("max_iterations_no_summary", limit=7)

    assert "(7 tool calls)" in copy
