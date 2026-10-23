"""The aiohttp access-log filter that keeps webhook credentials out of the log file.

A shared-listener ingress forwards a served profile's webhook to the default profile's
listener, so the vendor's callback URL (query string included) is written by the *default*
listener's access logger. An adapter that passes ``access_log=None`` is bypassed on that path,
which is how a BlueBubbles server password ended up in ``agent.log`` (#143550).
"""
import logging

import pytest

import hermes_logging


@pytest.fixture()
def access_records():
    """Capture ``aiohttp.access`` records after installing the redactor, then restore the logger."""
    access_logger = logging.getLogger("aiohttp.access")
    previous_level = access_logger.level
    previous_propagate = access_logger.propagate
    added = []

    class _Capture(logging.Handler):
        def __init__(self):
            super().__init__()
            self.messages: list[str] = []

        def emit(self, record):
            self.messages.append(record.getMessage())

    handler = _Capture()
    before = list(access_logger.filters)
    hermes_logging.redact_access_log_secrets()
    access_logger.addHandler(handler)
    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False
    added = [f for f in access_logger.filters if f not in before]
    try:
        yield handler.messages
    finally:
        access_logger.removeHandler(handler)
        for f in added:
            access_logger.removeFilter(f)
        access_logger.setLevel(previous_level)
        access_logger.propagate = previous_propagate


def test_access_log_masks_a_credential_query_parameter(access_records):
    logging.getLogger("aiohttp.access").info(
        '%s "%s" %s',
        "127.0.0.1:54321",
        "POST /p/work/bluebubbles-webhook?password=s3cr3tP4ss HTTP/1.1",
        200,
    )
    assert access_records
    line = access_records[-1]
    assert "s3cr3tP4ss" not in line
    assert "password=***" in line
    # The request target stays readable: only the value is masked.
    assert "/p/work/bluebubbles-webhook" in line


def test_access_log_keeps_public_query_parameters(access_records):
    logging.getLogger("aiohttp.access").info(
        'GET /api/status?since=10&limit=5 HTTP/1.1 200'
    )
    assert access_records[-1] == "GET /api/status?since=10&limit=5 HTTP/1.1 200"


def test_redact_access_log_secrets_is_idempotent():
    access_logger = logging.getLogger("aiohttp.access")
    hermes_logging.redact_access_log_secrets()
    hermes_logging.redact_access_log_secrets()
    try:
        installed = [f for f in access_logger.filters
                     if isinstance(f, hermes_logging._AccessLogQueryRedactor)]
        assert len(installed) == 1
    finally:
        for f in list(access_logger.filters):
            if isinstance(f, hermes_logging._AccessLogQueryRedactor):
                access_logger.removeFilter(f)
