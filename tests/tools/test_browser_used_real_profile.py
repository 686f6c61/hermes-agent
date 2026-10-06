"""``used_real_profile`` must audit the endpoint that served the navigation.

The flag used to be copied from the session record (launch intent), so a stale
session bound to a throwaway temp-dir browser still answered with
``used_real_profile: true`` while the user's profile was never in play. The
response must verify the endpoint against the managed copy's DevToolsActivePort
(the same check the launch path uses before reuse) and downgrade explicitly
when it does not match.
"""
import json
from unittest.mock import Mock, patch

import pytest

from tools import browser_tool as bt
from tools import browser_tool_real_profile as bt_real_profile
from tools import browser_tool_session as bt_session

NAV_URL = "https://example.com"


def _rp_session(cdp_url):
    """A session record as the real-profile attach creates it."""
    return {"session_name": "rp_test000001", "bb_session_id": None,
            "cdp_url": cdp_url, "features": {"local": True, "real_profile": True},
            "_first_nav": False}


def _run_navigation(session_info, tmp_path, *, cdp_http_ready=True, copy_dir_value="set"):
    """Drive browser_navigate with a fixed pipeline; port matching stays real."""
    if copy_dir_value == "set":
        (tmp_path / "DevToolsActivePort").write_text("41000\n/devtools/browser/x\n")
        copy_dir_value = str(tmp_path)
    with patch.object(bt, "_secret_url_error_normalized", return_value=(NAV_URL, None)), \
         patch.object(bt, "_url_policy_error", return_value=None), \
         patch.object(bt, "_is_camofox_mode", return_value=False), \
         patch.object(bt, "_is_local_sidecar_key", return_value=False), \
         patch.object(bt, "_post_redirect_block", return_value=None), \
         patch.object(bt, "_attach_auto_snapshot"), \
         patch.object(bt_session, "_get_session_info", return_value=session_info), \
         patch.object(bt_session, "_run_browser_command",
                      return_value={"success": True, "data": {"title": "OK", "url": NAV_URL}}), \
         patch("hermes_cli.browser_connect.detect_default_chromium", return_value="chrome"), \
         patch("hermes_cli.browser_connect.real_profile_copy_dir", return_value=copy_dir_value), \
         patch.object(bt_real_profile, "_cdp_http_ready", return_value=cdp_http_ready):
        return json.loads(bt.browser_navigate(NAV_URL))


class TestUsedRealProfileProvenance:

    def setup_method(self):
        bt._last_active_session_key.clear()
        bt._real_profile_cdp_cache.clear()

    def teardown_method(self):
        bt._last_active_session_key.clear()
        bt._real_profile_cdp_cache.clear()

    def test_endpoint_on_copy_dir_reports_true(self, tmp_path):
        """The endpoint's port matches the copy's DevToolsActivePort: flag stays true."""
        response = _run_navigation(_rp_session("http://127.0.0.1:41000"), tmp_path)
        assert response["success"] is True
        assert response["used_real_profile"] is True
        assert "real_profile_warning" not in response

    def test_throwaway_endpoint_downgrades_with_warning(self, tmp_path):
        """A live endpoint on another port (a throwaway temp-dir browser) must not
        inherit the audit flag: the response downgrades and names the mismatch."""
        response = _run_navigation(_rp_session("http://127.0.0.1:51510"), tmp_path)
        assert response["success"] is True
        assert response["used_real_profile"] is False
        assert "throwaway" in response["real_profile_warning"]

    def test_dead_endpoint_downgrades_with_warning(self, tmp_path):
        """The port file matches but the endpoint is gone: fail closed."""
        response = _run_navigation(_rp_session("http://127.0.0.1:41000"), tmp_path,
                                   cdp_http_ready=False)
        assert response["success"] is True
        assert response["used_real_profile"] is False
        assert "real_profile_warning" in response

    def test_unresolvable_copy_dir_fails_closed(self, tmp_path):
        """No managed copy dir (unknown browser): provenance cannot be verified."""
        response = _run_navigation(_rp_session("http://127.0.0.1:41000"), tmp_path,
                                   copy_dir_value=None)
        assert response["success"] is True
        assert response["used_real_profile"] is False
        assert "real_profile_warning" in response

    def test_plain_local_session_is_untouched(self, tmp_path):
        """Sessions without the real-profile feature keep the old shape: no flag,
        no warning, and the verification never runs."""
        probe = Mock(side_effect=AssertionError("verification must not run"))
        info = {"session_name": "h_test000002", "bb_session_id": None, "cdp_url": None,
                "features": {"local": True}, "_first_nav": False}
        with patch("hermes_cli.browser_connect.detect_default_chromium", probe), \
             patch("hermes_cli.browser_connect.real_profile_copy_dir", probe), \
             patch.object(bt, "_secret_url_error_normalized", return_value=(NAV_URL, None)), \
             patch.object(bt, "_url_policy_error", return_value=None), \
             patch.object(bt, "_is_camofox_mode", return_value=False), \
             patch.object(bt, "_is_local_sidecar_key", return_value=False), \
             patch.object(bt, "_post_redirect_block", return_value=None), \
             patch.object(bt, "_attach_auto_snapshot"), \
             patch.object(bt_session, "_get_session_info", return_value=info), \
             patch.object(bt_session, "_run_browser_command",
                          return_value={"success": True, "data": {"title": "OK", "url": NAV_URL}}):
            response = json.loads(bt.browser_navigate(NAV_URL))
        assert response["success"] is True
        assert "used_real_profile" not in response
        assert "real_profile_warning" not in response
