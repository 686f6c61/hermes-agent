"""``prepare_model`` on a following session must keep the rename map a dict (#142488).

The ``follows_profile`` block reused the name ``moved`` for the route-bound keys it drops, and the
secret-path rewrite further down reads ``moved`` as the dict ``_freeze_selected_provider`` returns.
So a following session whose receipt carries *any* frozen config secret outside the followed
sections crashed on every model switch with ``AttributeError: 'tuple' object has no attribute
'get'``: the desktop showed ``Model switch failed: internal error`` and the switch never landed.

The secret that fires it cannot be the model route's own key: ``recover_config_secrets`` skips
``FOLLOW_SECTIONS`` for a following session, so an inline ``custom_providers[i].api_key`` alone
recovers ``{}`` and the rewrite never sees a non-empty map (``test_a_following_session_skips_the
_route_key`` pins that). What survives the skip is a private secret of any *other* section -- an
``mcp_servers.<name>.env`` token, a bot token, a terminal docker env -- which
``_extract_config_secrets`` records because ``env``/``headers`` are containers.
"""
from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from gateway.session_policy import build_policy, bind_launch_key
from gateway.session_policy_credentials import recover_config_secrets
from tests.gateway.test_session_mutation_model_provider_replacement import peers, pick


def _profile(old_url, new_url=None):
    """A following-capable profile whose private secret lives OUTSIDE the followed sections."""
    url = new_url or old_url
    return {'model': {'provider': 'custom', 'base_url': url, 'default': 'original'},
            'custom_providers': [{'name': 'review', 'base_url': url,
                                  'api_key': 'stored-review-key',
                                  'models': {'original': {}, 'switched': {}}}],
            'mcp_servers': {'files': {'env': {'FILES_TOKEN': 'stored-mcp-token'}}}}


@pytest.mark.asyncio
async def test_a_following_pick_rewrites_the_stored_secrets(tmp_path, monkeypatch):
    with peers() as (_old_peer, old_url, _new_peer, new_url):
        _config, runtime = await pick(tmp_path, monkeypatch, _profile(old_url), _profile(old_url, new_url),
                                      'custom:review', request={'follow_profile_config': True})
        assert runtime['base_url'].rstrip('/') == new_url


def test_a_following_session_recovers_off_route_secrets_only(tmp_path, monkeypatch):
    """The discriminator the report corrected: the route key is skipped, an MCP env token is not."""
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    route_only = {'model': {'provider': 'custom', 'base_url': 'http://127.0.0.1:9', 'default': 'original'},
                  'custom_providers': [{'name': 'review', 'base_url': 'http://127.0.0.1:9',
                                        'api_key': 'stored-review-key'}]}
    off_route = {**_profile('http://127.0.0.1:9')}

    recovered = {}
    for label, before in (('route key only', route_only), ('plus an mcp env token', off_route)):
        private = {}
        policy = build_policy({'cwd': str(tmp_path), 'model': 'original',
                               'follow_profile_config': True},
                              deepcopy(before), private_secrets=private)
        (tmp_path / 'config.yaml').write_text(json.dumps(before))
        from hermes_state import SessionDB
        with SessionDB(tmp_path / 'state.db') as db:
            authority = SimpleNamespace(instance_id='review', epoch=1, profile_id='review', db=db)
            policy = bind_launch_key(authority, 'sid', policy, None, config_secrets=private)
            assert policy.follows_profile is True
            recovered[label] = recover_config_secrets(authority, policy)

    assert recovered['route key only'] == {}
    # `_extract_config_secrets` keeps a container key whole: the path stops at `env`.
    assert list(recovered['plus an mcp env token']) == [('mcp_servers', 'files', 'env')]
