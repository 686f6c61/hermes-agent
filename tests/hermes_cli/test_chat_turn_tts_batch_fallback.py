"""Batch-TTS fallback for providers that stream no text deltas (#141313).

Streaming TTS is armed from ``check_tts_requirements()`` alone, so an
external-process provider (``claude-subscription-directsdk``, …) that never calls
``stream_callback`` leaves the speaker with only the end-of-text sentinel: the
reply prints and nothing is spoken. Before the fix the batch path was skipped
whenever streaming TTS was armed, so the whole reply stayed silent.

Contracts here: an armed turn whose speaker was never fed falls back to batch
TTS; an armed turn that did feed it must not speak the reply twice; an unarmed
turn keeps the old behaviour.

Behavior contracts, no real audio, no config on disk.
"""

import os
import queue
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from cli import HermesCLI, _ChatTurn
from hermes_cli.cli_chat_turn_mixin import _needs_batch_tts


def _cli(voice_tts=True):
    """A CLI instance with the rendering phases stubbed out."""
    cli = HermesCLI.__new__(HermesCLI)
    cli._voice_tts = voice_tts
    cli._voice_continuous = False
    cli.agent = SimpleNamespace(max_iterations=10, provider="", model="")
    cli.provider = ""
    cli.model = ""
    cli._pending_input = queue.Queue()
    cli.spoken = []
    cli._voice_speak_response_async = lambda text: cli.spoken.append(text)
    cli._chat_resolve_interrupt = lambda turn, thread, msg, response: (None, False)
    cli._chat_print_reasoning_box = lambda turn: None
    cli._chat_print_response_panel = lambda turn, response: None
    cli._emit_focus_recovery_line = lambda: None
    cli._ring_bell = lambda **kwargs: None
    return cli


def _turn(response="hola", streaming=True, fed=False):
    turn = _ChatTurn()
    turn.result = {"final_response": response, "completed": True}
    turn.use_streaming_tts = streaming
    turn.tts_fed = fed
    return turn


def test_armed_speaker_never_fed_falls_back_to_batch_tts():
    """The reported case: armed streaming TTS, provider streams nothing."""
    cli = _cli()
    turn = _turn()
    assert cli._chat_render_turn(turn, None, None) == "hola"
    assert cli.spoken == ["hola"], "a reply nobody streamed must still be spoken"


def test_armed_speaker_fed_does_not_speak_the_reply_twice():
    cli = _cli()
    turn = _turn(fed=True)
    cli._chat_render_turn(turn, None, None)
    assert cli.spoken == [], "streaming already spoke it"


def test_unarmed_turn_keeps_batch_tts():
    cli = _cli()
    turn = _turn(streaming=False)
    cli._chat_render_turn(turn, None, None)
    assert cli.spoken == ["hola"]


def test_no_batch_tts_without_voice_tts_or_response():
    cli = _cli(voice_tts=False)
    cli._chat_render_turn(_turn(), None, None)
    assert cli.spoken == []

    cli = _cli()
    cli._chat_render_turn(_turn(response=""), None, None)
    assert cli.spoken == [], "nothing to speak"


def test_needs_batch_tts_truth_table():
    armed_unfed = _turn()
    armed_fed = _turn(fed=True)
    unarmed = _turn(streaming=False)
    assert _needs_batch_tts(True, "hola", armed_unfed) is True
    assert _needs_batch_tts(True, "hola", armed_fed) is False
    assert _needs_batch_tts(True, "hola", unarmed) is True
    assert _needs_batch_tts(False, "hola", armed_unfed) is False
    assert _needs_batch_tts(True, "", armed_unfed) is False


def test_stream_callback_marks_the_speaker_fed_only_on_text(monkeypatch):
    """The flag is set by the delta callback, not by the arm itself."""
    from tools import tts_tool
    import tools.tts_tool_speaker as speaker_mod

    monkeypatch.setattr(tts_tool, "check_tts_requirements", lambda: True)
    monkeypatch.setattr(speaker_mod, "stream_tts_to_speaker",
                        lambda text_queue, stop_event, done_event, *a, **k: None)

    cli = _cli()
    cli._voice_mode = False
    cli._voice_continuous = False
    cli._voice_tts_done = threading.Event()
    cli._voice_last_tts_text = ""
    cli.show_timestamps = False
    cli.streaming_enabled = True
    cli.timestamp_format = "%H:%M"

    turn = _ChatTurn()
    cli._chat_setup_turn_audio(turn, "hello", False)
    try:
        assert turn.use_streaming_tts is True
        assert turn.tts_fed is False, "arming alone does not feed the speaker"
        turn.stream_callback("")
        assert turn.tts_fed is False, "an empty delta is not speech"
        turn.stream_callback("hola")
        assert turn.tts_fed is True
        assert turn.text_queue.get_nowait() == ""
        assert turn.text_queue.get_nowait() == "hola"
    finally:
        turn.text_queue.put(None)
