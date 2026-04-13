"""Tests for CharmmGuiClient and TokenInfo."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from aiida_charmm_gui.client import (
    CharmmGuiAuthError,
    CharmmGuiClient,
    CharmmGuiConfigError,
    TokenInfo,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _future_ts(days: float = 2) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _past_ts(seconds: float = 120) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _client(tmp_path: Path, email: str = "user@example.com", password: str = "secret") -> CharmmGuiClient:
    return CharmmGuiClient(email=email, password=password, token_file=tmp_path / "token.json")


# ---------------------------------------------------------------------------
# TokenInfo.is_valid
# ---------------------------------------------------------------------------


def test_token_is_valid_future():
    token = TokenInfo(token="tok", expires_at=_future_ts())
    assert token.is_valid()


def test_token_is_expired():
    token = TokenInfo(token="tok", expires_at=_past_ts())
    assert not token.is_valid()


def test_token_within_margin_counts_as_invalid():
    # expires in 30 s, default margin is 60 s → should be invalid
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    token = TokenInfo(token="tok", expires_at=expires_at)
    assert not token.is_valid()


def test_token_z_suffix_parsed():
    # Z suffix must be handled without raising
    expires_at = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    token = TokenInfo(token="tok", expires_at=expires_at)
    assert token.is_valid()


# ---------------------------------------------------------------------------
# read_cached_token / write_cached_token
# ---------------------------------------------------------------------------


def test_read_cached_token_missing_file(tmp_path):
    client = _client(tmp_path)
    assert client.read_cached_token() is None


def test_write_then_read_cached_token(tmp_path):
    client = _client(tmp_path)
    info = TokenInfo(token="abc123", expires_at=_future_ts())
    client.write_cached_token(info)
    result = client.read_cached_token()
    assert result is not None
    assert result.token == "abc123"


def test_read_cached_token_invalid_json(tmp_path):
    client = _client(tmp_path)
    client.token_file.write_text("not json")
    assert client.read_cached_token() is None


def test_read_cached_token_missing_fields(tmp_path):
    client = _client(tmp_path)
    client.token_file.write_text(json.dumps({"token": "abc"}))  # no expires_at
    assert client.read_cached_token() is None


# ---------------------------------------------------------------------------
# get_cached_token
# ---------------------------------------------------------------------------


def test_get_cached_token_valid(tmp_path):
    client = _client(tmp_path)
    client.write_cached_token(TokenInfo(token="valid", expires_at=_future_ts()))
    result = client.get_cached_token()
    assert result is not None
    assert result.token == "valid"


def test_get_cached_token_expired(tmp_path):
    client = _client(tmp_path)
    client.write_cached_token(TokenInfo(token="old", expires_at=_past_ts()))
    assert client.get_cached_token() is None


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


def test_login_missing_credentials(tmp_path):
    client = CharmmGuiClient(token_file=tmp_path / "token.json")
    with pytest.raises(CharmmGuiConfigError):
        client.login()


def test_login_success(tmp_path):
    client = _client(tmp_path)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"token": "newtoken"}

    with patch("aiida_charmm_gui.client.requests.post", return_value=mock_response):
        info = client.login()

    assert info.token == "newtoken"
    # token should be persisted
    cached = client.read_cached_token()
    assert cached is not None
    assert cached.token == "newtoken"


def test_login_http_error(tmp_path):
    client = _client(tmp_path)
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"

    with patch("aiida_charmm_gui.client.requests.post", return_value=mock_response):
        with pytest.raises(CharmmGuiAuthError, match="401"):
            client.login()


def test_login_missing_token_in_response(tmp_path):
    client = _client(tmp_path)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {}  # no "token" key

    with patch("aiida_charmm_gui.client.requests.post", return_value=mock_response):
        with pytest.raises(CharmmGuiAuthError, match="did not contain a token"):
            client.login()


# ---------------------------------------------------------------------------
# get_token
# ---------------------------------------------------------------------------


def test_get_token_uses_cache(tmp_path):
    client = _client(tmp_path)
    client.write_cached_token(TokenInfo(token="cached", expires_at=_future_ts()))

    with patch("aiida_charmm_gui.client.requests.post") as mock_post:
        token = client.get_token()

    mock_post.assert_not_called()
    assert token == "cached"


def test_get_token_force_refresh(tmp_path):
    client = _client(tmp_path)
    client.write_cached_token(TokenInfo(token="cached", expires_at=_future_ts()))

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"token": "fresh"}

    with patch("aiida_charmm_gui.client.requests.post", return_value=mock_response):
        token = client.get_token(force_refresh=True)

    assert token == "fresh"


def test_get_token_falls_back_to_login_when_expired(tmp_path):
    client = _client(tmp_path)
    client.write_cached_token(TokenInfo(token="old", expires_at=_past_ts()))

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"token": "refreshed"}

    with patch("aiida_charmm_gui.client.requests.post", return_value=mock_response):
        token = client.get_token()

    assert token == "refreshed"


# ---------------------------------------------------------------------------
# get_auth_headers
# ---------------------------------------------------------------------------


def test_get_auth_headers(tmp_path):
    client = _client(tmp_path)
    client.write_cached_token(TokenInfo(token="mytoken", expires_at=_future_ts()))
    headers = client.get_auth_headers()
    assert headers == {"Authorization": "Bearer mytoken"}
