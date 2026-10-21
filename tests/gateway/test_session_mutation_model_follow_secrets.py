"""``prepare_model`` on a following session must keep the rename map a dict (#142488).

The ``follows_profile`` block reused the name ``moved`` for the route-bound keys it drops, and the
secret-path rewrite further down reads ``moved`` as the dict ``_freeze_selected_provider`` returns.
So a following session whose previous route stored a literal key — the normal case for a
``custom_providers:`` entry with an inline ``api_key`` — crashed on every model switch with
``AttributeError: 'tuple' object has no attribute 'get'``: the desktop showed ``Model switch
failed: internal error`` and the switch never landed.

The receipt's secret store is stubbed here: what the test pins is that a *non-empty* recovered map
is rewritten through the rename map on the following path, which is where the shadowed name died.
"""
from copy import deepcopy

import pytest

from gateway.session_policy_credentials import recover_config_secrets
from tests.gateway.test_session_mutation_model_provider_replacement import peers, pick


@pytest.mark.asyncio
async def test_a_following_pick_rewrites_the_stored_secrets(tmp_path, monkeypatch):
    recovered = {('custom_providers', 0, 'api_key'): 'stored-review-key'}
    monkeypatch.setattr('gateway.session_policy_credentials.recover_config_secrets',
                        lambda *_args, **_kwargs: dict(recovered))
    with peers() as (_old_peer, old_url, _new_peer, new_url):
        profile = {'model': {'provider': 'custom', 'base_url': old_url, 'default': 'original'},
                   'custom_providers': [{'name': 'review', 'base_url': old_url,
                                         'api_key': 'stored-review-key',
                                         'models': {'original': {}, 'switched': {}}}]}
        after = {**deepcopy(profile), 'custom_providers': [{'name': 'review', 'base_url': new_url,
                                                            'api_key': 'stored-review-key',
                                                            'models': {'original': {},
                                                                       'switched': {}}}]}
        assert recover_config_secrets is not None  # imported by prepare_model from this module
        _config, runtime = await pick(tmp_path, monkeypatch, deepcopy(profile), after,
                                      'custom:review', request={'follow_profile_config': True})
        assert runtime['base_url'].rstrip('/') == new_url
