"""A 403 written by a WAF/CDN in front of the provider is not an API-key rejection (#53099, #70566).

A relay that blocks the SDK User-Agent answers ``403 Your request was blocked.``; Cloudflare's
browser challenge answers 403 HTML. Both used to classify as ``auth`` and print key guidance.
"""
import pytest

from agent.error_classifier import FailoverReason, classify_api_error


class _APIError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.parametrize("body", [
    "Error code: 403 - Your request was blocked.",
    "<!doctype html><html><body>Enable JavaScript and cookies to continue</body></html>",
    "<!doctype html><html><script src='/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page'></script></html>",
])
def test_403_waf_block_is_upstream_blocked_not_auth(body):
    result = classify_api_error(_APIError(body, 403), provider="openai-api")
    assert result.reason == FailoverReason.upstream_blocked
    assert result.retryable is False and result.should_fallback is True
    assert result.should_rotate_credential is False and result.is_auth is False


@pytest.mark.parametrize("body, status, reason", [
    ("<html><title>Forbidden</title><body>Access denied</body></html>", 403, FailoverReason.auth),
    ("<html>Enable JavaScript and cookies to continue</html>", 401, FailoverReason.auth),
])
def test_generic_403_and_all_401_keep_auth(body, status, reason):
    assert classify_api_error(_APIError(body, status), provider="openai-api").reason == reason


# Cloudflare's "Unable to load site" page: the edge could not or would not reach the origin. It
# carries neither ``cf-error-details`` nor the challenge markers — only the title and the Ray ID
# footer — so it used to fall through to ``auth`` and made a Codex OAuth session refresh its pool
# entry (single-use refresh token, rotation-family revocation risk) over a network block (#141080).
_CLOUDFLARE_UNABLE_TO_LOAD_SITE = """<!DOCTYPE html><html lang="en-US"><head>
<title>Unable to load site</title></head><body>
<h1>Unable to load site</h1><p>Please try again later.</p>
<div class="cf-error-footer"><span>Cloudflare Ray ID:
<strong>8d3f21c9be0a7d15</strong></span> &bull; Your IP: 203.0.113.7</div>
</body></html>"""


@pytest.mark.parametrize("body", [
    _CLOUDFLARE_UNABLE_TO_LOAD_SITE,
    # The Ray ID footer alone, with the title localized away.
    "<!DOCTYPE html><html><body><p>Cloudflare Ray ID: <strong>8d3f21c9be0a7d15</strong></p></body></html>",
])
def test_cloudflare_unable_to_load_site_is_upstream_blocked_not_auth(body):
    result = classify_api_error(
        _APIError("Error code: 403 - " + body, 403), provider="openai-codex", model="gpt-6.1-sol"
    )
    assert result.reason == FailoverReason.upstream_blocked
    assert result.is_auth is False and result.should_rotate_credential is False
    assert result.should_fallback is True and result.retryable is False
