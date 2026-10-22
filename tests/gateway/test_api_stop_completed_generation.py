"""A Stop that names a run whose turn already finished never reaches the next turn's agent.

``POST /v1/runs/{run_id}/stop`` for a run that has just completed is a normal client pattern:
a UI aborts the stream it was reading and posts the next message in the same breath. The
admission still reads ``started`` until its settlement is published, so the Stop passes the
generation check — but that generation owns no agent any more, and the route's live agent
already belongs to the turn that replaced it.
"""
from types import SimpleNamespace

import pytest

from hermes_state_runtime import claim_session_input
from tests.gateway.test_api_unknown_resolution import _AUTH_HEADERS, _runs_client


async def _claimed_run(api, owner, key):
    """A run whose admission the drain has claimed: ``started``, with a generation."""
    client = _runs_client(api)
    await client.start_server()
    owner._schedule = lambda ref: None
    accepted = await client.post(
        '/v1/runs',
        json={'input': 'HEAD', 'session_id': 'api-session'},
        headers={**_AUTH_HEADERS, 'Idempotency-Key': key},
    )
    assert accepted.status == 202, await accepted.text()
    run_id = (await accepted.json())['run_id']
    row = claim_session_input(owner.db, epoch=owner.epoch, session_id='api-session')
    assert row is not None and row['status'] == 'started'
    return client, run_id, row


def _route_agent(owner, agent):
    """Put *agent* in the route's running slot, as a turn that created its agent would."""
    live = owner.sessions['api-session']
    owner.runner._cached_agent_for = lambda route: agent
    owner.runner._running_agents = {live.route: agent}


@pytest.mark.asyncio
async def test_stop_of_a_finished_run_does_not_interrupt_the_next_turns_agent(api, owner):
    client, run_id, row = await _claimed_run(api, owner, 'finished-run')
    interrupted = []
    next_agent = SimpleNamespace(interrupt=lambda *a: interrupted.append(True))
    _route_agent(owner, next_agent)
    # The run's execution returned and its settlement is in flight: committed, not yet published,
    # so the admission still reads ``started`` while the next turn's agent holds the route.
    owner.sessions['api-session'].settling[row['admission_id']] = row
    try:
        stopped = await client.post(f'/v1/runs/{run_id}/stop', headers=_AUTH_HEADERS)
        assert stopped.status == 200, await stopped.text()
        assert interrupted == []
        # Nor does the Stop latch onto the next turn: adopt_agent consumes a latch only for the
        # generation that set it, so a stray latch would sit there forever.
        assert owner.pending_stops.get('api-session') is None
    finally:
        for task in list(api._active_run_tasks.values()):
            task.cancel()
        await client.close()


@pytest.mark.asyncio
async def test_stop_of_the_running_generation_still_reaches_the_route_agent(api, owner):
    """The control: while that generation is the executing one, Stop reaches its agent."""
    client, run_id, row = await _claimed_run(api, owner, 'running-run')
    interrupted = []
    running_agent = SimpleNamespace(interrupt=lambda *a: interrupted.append(True))
    _route_agent(owner, running_agent)
    owner.executing['api-session'] = row['generation']
    try:
        stopped = await client.post(f'/v1/runs/{run_id}/stop', headers=_AUTH_HEADERS)
        assert stopped.status == 200, await stopped.text()
        assert interrupted == [True]
    finally:
        for task in list(api._active_run_tasks.values()):
            task.cancel()
        await client.close()
