"""Tests for scripts/fetch_highergov_api.py — fetch_resource helper."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.fetch_highergov_api import RESOURCES, fetch_resource


# ---------------------------------------------------------------------------
# fetch_resource — mocked HTTP
# ---------------------------------------------------------------------------

def _mock_response(status_code=200, json_data=None, raise_exc=None):
    resp = MagicMock()
    resp.status_code = status_code
    if raise_exc:
        resp.raise_for_status.side_effect = raise_exc
    else:
        resp.raise_for_status.return_value = None
    resp.json.return_value = json_data or {}
    return resp


class TestFetchResource:
    def test_successful_results_list_returns_dataframe(self):
        json_data = {"results": [{"vendor": "Acme PR", "amount": 500000}]}
        resp = _mock_response(json_data=json_data)
        with patch("scripts.fetch_highergov_api.requests.get", return_value=resp):
            result = fetch_resource("contract", "fake-key", {"page_size": 100})
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1
        assert "vendor" in result.columns

    def test_list_response_returned_as_dataframe(self):
        json_data = [{"vendor": "Corp A", "amount": 200000}, {"vendor": "Corp B", "amount": 100000}]
        resp = _mock_response(json_data=json_data)
        with patch("scripts.fetch_highergov_api.requests.get", return_value=resp):
            result = fetch_resource("contract", "fake-key", {})
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2

    def test_data_key_also_accepted(self):
        json_data = {"data": [{"name": "Entity X"}]}
        resp = _mock_response(json_data=json_data)
        with patch("scripts.fetch_highergov_api.requests.get", return_value=resp):
            result = fetch_resource("opportunity", "fake-key", {})
        assert result is not None
        assert len(result) == 1

    def test_http_error_returns_none(self):
        resp = _mock_response(raise_exc=requests.HTTPError("404"))
        with patch("scripts.fetch_highergov_api.requests.get", return_value=resp):
            result = fetch_resource("contract", "fake-key", {})
        assert result is None

    def test_connection_error_returns_none(self):
        with patch("scripts.fetch_highergov_api.requests.get",
                   side_effect=requests.ConnectionError("down")):
            result = fetch_resource("contract", "fake-key", {})
        assert result is None

    def test_empty_results_returns_none(self):
        resp = _mock_response(json_data={"results": []})
        with patch("scripts.fetch_highergov_api.requests.get", return_value=resp):
            result = fetch_resource("idv", "fake-key", {})
        assert result is None

    def test_non_json_response_returns_none(self):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.side_effect = ValueError("No JSON")
        with patch("scripts.fetch_highergov_api.requests.get", return_value=resp):
            result = fetch_resource("contract", "fake-key", {})
        assert result is None

    def test_no_list_data_in_response_returns_none(self):
        resp = _mock_response(json_data={"error": "Not found", "code": 404})
        with patch("scripts.fetch_highergov_api.requests.get", return_value=resp):
            result = fetch_resource("contract", "fake-key", {})
        assert result is None

    def test_api_key_included_in_request(self):
        resp = _mock_response(json_data={"results": [{"name": "X"}]})
        with patch("scripts.fetch_highergov_api.requests.get", return_value=resp) as mock_get:
            fetch_resource("contract", "my-secret-key", {"page_size": 100})
        call_kwargs = mock_get.call_args
        params = call_kwargs[1].get("params") or call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {}
        if not params:
            params = call_kwargs.kwargs.get("params", {})
        assert "api_key" in params
        assert params["api_key"] == "my-secret-key"

    def test_timeout_returns_none(self):
        with patch("scripts.fetch_highergov_api.requests.get",
                   side_effect=requests.Timeout("timeout")):
            result = fetch_resource("contract", "fake-key", {})
        assert result is None


# ---------------------------------------------------------------------------
# RESOURCES constant
# ---------------------------------------------------------------------------

class TestResources:
    def test_has_expected_resource_types(self):
        assert "contract" in RESOURCES
        assert "idv" in RESOURCES
        assert "opportunity" in RESOURCES

    def test_all_values_are_tuples(self):
        for k, v in RESOURCES.items():
            assert isinstance(v, tuple), f"{k} should be a tuple"

    def test_output_filenames_are_csv(self):
        for k, (out_name, _) in RESOURCES.items():
            assert out_name.endswith(".csv"), f"{k}: {out_name} not a CSV"

    def test_params_are_dicts(self):
        for k, (_, params) in RESOURCES.items():
            assert isinstance(params, dict), f"{k} params should be dict"
