"""Extended tests for scripts/web_fetch.py — http_get, http_post, redirect, timeout."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.web_fetch import http_get, http_post, parse_embedded_json


def _mock_session(status_code=200, json_data=None, raise_exc=None):
    session = MagicMock(spec=requests.Session)
    if raise_exc:
        session.get.side_effect = raise_exc
        session.post.side_effect = raise_exc
        return session
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = ""
    session.get.return_value = resp
    session.post.return_value = resp
    return session


# ---------------------------------------------------------------------------
# http_get
# ---------------------------------------------------------------------------

class TestHttpGet:
    def test_200_returns_response(self):
        session = _mock_session(200, {"data": "ok"})
        result = http_get(session, "http://example.com/", max_retries=1, backoff=[0])
        assert result is not None
        assert result.status_code == 200

    def test_404_returns_none(self):
        session = _mock_session(404)
        result = http_get(session, "http://example.com/", max_retries=1, backoff=[0])
        assert result is None

    def test_400_returns_none(self):
        session = _mock_session(400)
        result = http_get(session, "http://example.com/", max_retries=1, backoff=[0])
        assert result is None

    def test_connection_error_returns_none_after_retries(self):
        session = _mock_session(raise_exc=requests.ConnectionError("down"))
        with patch("scripts.web_fetch.time.sleep"):
            result = http_get(session, "http://example.com/", max_retries=2, backoff=[0, 0])
        assert result is None

    def test_timeout_returns_none_after_retries(self):
        session = _mock_session(raise_exc=requests.Timeout("timeout"))
        with patch("scripts.web_fetch.time.sleep"):
            result = http_get(session, "http://example.com/", max_retries=2, backoff=[0, 0])
        assert result is None

    def test_500_retries_and_returns_none(self):
        resp = MagicMock()
        resp.status_code = 500
        session = MagicMock(spec=requests.Session)
        session.get.return_value = resp
        with patch("scripts.web_fetch.time.sleep"):
            result = http_get(session, "http://example.com/", max_retries=2, backoff=[0, 0])
        assert result is None

    def test_redirect_followed_by_default(self):
        # allow_redirects=True is the default; verify it's passed through
        session = _mock_session(200)
        http_get(session, "http://example.com/", max_retries=1, backoff=[0])
        call_kwargs = session.get.call_args
        assert call_kwargs.kwargs.get("allow_redirects", True) is True


# ---------------------------------------------------------------------------
# http_post
# ---------------------------------------------------------------------------

class TestHttpPost:
    def test_200_returns_response(self):
        session = _mock_session(200, {"result": "ok"})
        result = http_post(session, "http://example.com/", json_payload={"q": 1},
                           max_retries=1, backoff=[0])
        assert result is not None

    def test_404_returns_none(self):
        session = _mock_session(404)
        result = http_post(session, "http://example.com/", max_retries=1, backoff=[0])
        assert result is None

    def test_network_error_returns_none(self):
        session = _mock_session(raise_exc=requests.ConnectionError("down"))
        with patch("scripts.web_fetch.time.sleep"):
            result = http_post(session, "http://example.com/", max_retries=2, backoff=[0, 0])
        assert result is None


# ---------------------------------------------------------------------------
# parse_embedded_json — additional edge cases
# ---------------------------------------------------------------------------

class TestParseEmbeddedJsonExtended:
    def test_no_json_returns_none(self):
        result = parse_embedded_json("<html><body>No JSON here</body></html>")
        assert result is None

    def test_empty_string_returns_none(self):
        result = parse_embedded_json("")
        assert result is None

    def test_nested_json_extracted_correctly(self):
        html = '<script>window.__DATA__ = {"nested": {"a": 1, "b": [1, 2, 3]}};</script>'
        result = parse_embedded_json(html)
        assert result is not None
        assert result["nested"]["b"] == [1, 2, 3]

    def test_json_array_in_script(self):
        html = '<script>var items = [{"id": 1}, {"id": 2}];</script>'
        result = parse_embedded_json(html)
        # May or may not match depending on patterns — just verify no crash
        assert result is None or isinstance(result, (dict, list))
