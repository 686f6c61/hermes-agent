"""A skill slash-command submitted with composer images must carry those images."""
import queue

from cli import HermesCLI


def test_skill_slash_command_keeps_images_attached_on_the_same_enter():
    cli = HermesCLI.__new__(HermesCLI)
    cli._pending_input = queue.Queue()
    cli._pending_agent_seed = None
    cli._pending_resume_sessions = []
    cli._should_exit = False
    cli._status_bar_suppressed_after_resize = False
    cli._agent_running = False
    cli._interactive_turn = False
    cli._app = type("App", (), {"invalidate": lambda self: None, "is_running": False, "exit": lambda self: None})()

    def process_command(text):
        assert text == "/crypto-trading-expert analyze this screenshot"
        cli._queue_skill_message("SKILL BODY analyze this screenshot")
        return True

    cli.process_command = process_command
    cli._typed_voice_stop = lambda text: False
    cli.handle_bang_shell = lambda text: False
    cli._turn_summary_begin = lambda: None
    cli._tui_after_turn = lambda: None
    cli._print_user_message_preview = lambda text: None
    seen = []
    cli.chat = lambda text, images=None, voice_input=False: seen.append((text, images))

    cli._tui_process_one_input(("/crypto-trading-expert analyze this screenshot", ["/tmp/shot.png"]))

    queued = cli._pending_input.get_nowait()
    cli._tui_process_one_input(queued)

    assert seen == [("SKILL BODY analyze this screenshot", ["/tmp/shot.png"])]
    assert cli._pending_input.empty()
