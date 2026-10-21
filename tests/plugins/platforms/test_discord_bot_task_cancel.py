"""Regression tests for the bounded dispose of the discord.py client task (#142670).

``_cancel_bot_task`` used to await the cancelled ``client.start()`` task with no bound. That task
runs discord.py's own reconnect loop, and on a starved event loop it can survive cancellation; the
await then never returns, so ``_dispose_unused_adapter`` → ``disconnect()`` on the gateway's
platform reconnect watcher hangs for good. Because the watcher is shared, no primary platform is
ever retried, Discord is never reinstalled, and the orphaned client keeps delivering inbound
messages that fail with ``RuntimeStoreError: not_found`` until the gateway is restarted.

The assertions are on elapsed time, not just on the resulting state: the pre-fix code did clear
``_bot_task`` — after the caller's patience ran out (here, an outer ``wait_for`` whose cancellation
it swallowed) — so only the bound distinguishes the two. The stand-in client blocks on an Event
the test releases at teardown, so nothing here waits on the clock.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from gateway.config import PlatformConfig
from plugins.platforms.discord.adapter import DiscordAdapter


def _adapter(cancel_timeout: float = 0.05) -> DiscordAdapter:
    adapter = DiscordAdapter(PlatformConfig(enabled=True, token="test-token"))
    adapter._bot_task_cancel_timeout = cancel_timeout
    return adapter


async def _stubborn_start(gate: asyncio.Event) -> None:
    """Stand-in for ``Client.start()``: swallows cancellation until the test releases it."""
    while not gate.is_set():
        try:
            await gate.wait()
        except asyncio.CancelledError:
            continue


async def _release(gate: asyncio.Event, task: asyncio.Task) -> None:
    """Let a stand-in client finish so the loop teardown has no live task."""
    gate.set()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancel_bot_task_returns_when_the_client_ignores_cancel():
    """Disposing an adapter must be bounded even when the client task survives cancel()."""
    adapter = _adapter()
    gate = asyncio.Event()
    adapter._bot_task = asyncio.create_task(_stubborn_start(gate))
    await asyncio.sleep(0)  # let the task reach its first await
    survivor = adapter._bot_task
    loop = asyncio.get_running_loop()

    started = loop.time()
    # The outer wait_for only keeps the suite from hanging if the bound ever regresses.
    await asyncio.wait_for(adapter._cancel_bot_task(), timeout=2)
    elapsed = loop.time() - started

    assert elapsed < 1.0, f"disposal waited {elapsed:.2f}s on a client that ignores cancel()"
    assert adapter._bot_task is None, "an abandoned client task must be dropped from the adapter"
    await _release(gate, survivor)


@pytest.mark.asyncio
async def test_disconnect_returns_when_the_client_ignores_cancel():
    """The watcher path is ``disconnect()``; it must finish instead of hanging on the client."""
    adapter = _adapter()
    gate = asyncio.Event()
    adapter._bot_task = asyncio.create_task(_stubborn_start(gate))
    client = AsyncMock()
    adapter._client = client
    adapter._post_connect_task = None
    adapter._voice_clients = {}
    adapter._running = True
    adapter._ready_event = asyncio.Event()
    await asyncio.sleep(0)
    survivor = adapter._bot_task
    loop = asyncio.get_running_loop()

    started = loop.time()
    await asyncio.wait_for(adapter.disconnect(), timeout=5)
    elapsed = loop.time() - started

    assert elapsed < 1.0, f"disconnect() waited {elapsed:.2f}s on a client that ignores cancel()"
    assert adapter._bot_task is None
    client.close.assert_awaited()
    await _release(gate, survivor)


@pytest.mark.asyncio
async def test_cancel_bot_task_still_awaits_a_cooperative_client():
    """A client task that honours cancellation is still awaited to completion."""
    adapter = _adapter()
    gate = asyncio.Event()
    adapter._bot_task = asyncio.create_task(gate.wait())
    stopped = adapter._bot_task
    await asyncio.sleep(0)

    await adapter._cancel_bot_task()

    assert stopped.done() and stopped.cancelled()
    assert adapter._bot_task is None


@pytest.mark.asyncio
async def test_cancel_bot_task_is_a_noop_without_a_task():
    """Adapters that never started a client keep working (dispose on a half-built adapter)."""
    adapter = _adapter()

    await adapter._cancel_bot_task()

    assert adapter._bot_task is None
