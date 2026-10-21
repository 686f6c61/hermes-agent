"""Bounded cancellation of the discord.py client task.

``Client.start()`` runs discord.py's own reconnect loop, so a cancelled task can stay alive
while the loop sits inside a starved or closing transport (#142670). ``disconnect()`` for an
adapter that never made it onto ``runner.adapters`` runs on the gateway's platform reconnect
watcher, which also owns every other primary platform's retries: awaiting that task unbounded
wedges the watcher, the platform is never reinstalled, and the orphaned client keeps delivering
inbound messages that fail with ``RuntimeStoreError: not_found``.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

logger = logging.getLogger(__name__)

# How long disposal waits for a cancelled ``client.start()`` task before abandoning it.
DEFAULT_CANCEL_TIMEOUT = 5.0


def _drain(task: asyncio.Future) -> None:
    """Retrieve a late result so an abandoned task doesn't warn when it is collected."""
    with suppress(asyncio.CancelledError, Exception):
        task.exception()


async def cancel_client_task(owner: Any) -> None:
    """Cancel ``owner._bot_task`` and wait for it, bounded by the owner's cancel timeout.

    The task is dropped from the owner either way: a client that ignores cancellation must not
    keep the caller's disposal (and the reconnect watcher behind it) blocked, and
    ``_handle_bot_task_done`` already tolerates a stale task when it ends later.
    """
    task = getattr(owner, "_bot_task", None)
    if task is not None and not task.done() and isinstance(task, asyncio.Future):
        task.cancel()
        timeout = getattr(owner, "_bot_task_cancel_timeout", DEFAULT_CANCEL_TIMEOUT)
        _done, pending = await asyncio.wait({task}, timeout=timeout)
        if pending:
            logger.warning(
                "[%s] client.start() still running %.1fs after cancel(); abandoning it so "
                "disposal can finish", owner.name, timeout,
            )
            task.add_done_callback(_drain)
    owner._bot_task = None
