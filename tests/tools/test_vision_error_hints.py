"""The aux vision failure explanation names a routing answer when the call timed out.

A locally hosted vision model (LM Studio, Unsloth, vLLM, llama.cpp behind its own server) is
reached through the auxiliary vision call only when Hermes cannot prove the main model reads
images, and a high-reasoning model can spend more time producing the description than the
120 s aux budget allows. The tool result then carried a bare ``Request timed out.``, which
sends the reader after the model's speed instead of the routing (#142676).
"""

import asyncio
import json

import pytest

from tools import vision_tools as vt


class _DebugStub:
    """``_run_analysis`` records every call; the recorder must not touch the real debug dir."""

    def log_call(self, *args, **kwargs):
        pass

    def save(self):
        pass


@pytest.fixture(autouse=True)
def _no_debug(monkeypatch):
    monkeypatch.setattr(vt, "_debug", _DebugStub())


def _run_image(stage):
    return asyncio.run(
        vt._run_analysis("image", "shot.png", "describe it", "qwen/qwen3-vl-27b", stage))


def test_timeout_names_the_override_that_skips_the_aux_call():
    async def stage(prompt, debug, temps):
        raise TimeoutError("Request timed out.")

    result = json.loads(_run_image(stage))

    assert result["success"] is False
    assert "Request timed out." in result["error"]
    analysis = result["analysis"]
    assert "timed out" in analysis
    # The answer is the routing, not the model's speed: name the override and the knob.
    assert "model.supports_vision: true" in analysis
    assert "auxiliary.vision.timeout" in analysis
    assert "LM Studio" in analysis


def test_a_capability_rejection_keeps_its_own_explanation():
    async def stage(prompt, debug, temps):
        raise ValueError("This model does not support image input")

    analysis = json.loads(_run_image(stage))["analysis"]

    assert "does not support vision" in analysis
    assert "model.supports_vision" not in analysis


def test_an_unclassified_failure_keeps_the_generic_explanation():
    async def stage(prompt, debug, temps):
        raise RuntimeError("connection reset by peer")

    analysis = json.loads(_run_image(stage))["analysis"]

    assert analysis.startswith("There was a problem with the request")
    assert "model.supports_vision" not in analysis


def test_the_happy_path_is_unchanged():
    async def stage(prompt, debug, temps):
        return "A red square on black.", None

    result = json.loads(_run_image(stage))

    assert result == {"success": True, "analysis": "A red square on black."}
