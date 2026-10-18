"""#141209: agent-browser can answer with valid JSON that is not an object.

``back`` on a tab with no history prints ``null``, and a bare scalar is equally legal JSON
from the CLI's ``--json`` mode. Both used to come back out of
``_interpret_browser_command_output`` unchanged, so ``_run_browser_command`` read ``.get`` on
``None`` and the tool surface got a raw ``AttributeError`` traceback instead of a result.

The parsers are driven directly with fake stdout: no agent-browser or Chromium is spawned.
"""

from tools import browser_tool_session as bt_session


def test_null_output_is_normalised_to_an_error_result():
    result = bt_session._interpret_browser_command_output("back", "null\n", "", 0)

    assert isinstance(result, dict)
    assert result["success"] is False
    assert "non-object JSON" in result["error"]
    assert result["returncode"] == 0


def test_scalar_output_is_normalised_to_an_error_result():
    result = bt_session._interpret_browser_command_output("back", "42", "", 0)

    assert isinstance(result, dict)
    assert result["success"] is False


def test_run_browser_command_survives_a_null_back_result(monkeypatch):
    session_info = {"session_name": "null-back", "cdp_url": None, "bb_session_id": None, "features": {}}
    monkeypatch.setattr(bt_session, "_browser_command_preflight", lambda: {"browser_cmd": "agent-browser"})
    monkeypatch.setattr(bt_session, "_get_session_info", lambda task_id: session_info)
    monkeypatch.setattr(
        bt_session,
        "_dispatch_browser_command",
        lambda *a, **k: ("auto", bt_session._interpret_browser_command_output("back", "null", "", 0)),
    )

    result = bt_session._run_browser_command("null-back", "back")

    assert isinstance(result, dict)
    assert result["success"] is False
    assert "non-object JSON" in result["error"]
