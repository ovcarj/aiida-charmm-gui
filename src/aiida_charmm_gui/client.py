"""Client utilities for interacting with the CHARMM-GUI API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

LOGIN_URL = "https://charmm-gui.org/api/login"
CHECK_STATUS_URL = "https://charmm-gui.org/api/check_status"
DOWNLOAD_URL = "https://charmm-gui.org/api/download"
DEFAULT_TOKEN_FILE = Path.home() / ".cache" / "aiida-charmm-gui" / "token.json"


class CharmmGuiAuthError(RuntimeError):
    """Raised when authentication fails."""


class CharmmGuiConfigError(RuntimeError):
    """Raised when local configuration is missing or invalid."""


@dataclass
class TokenInfo:
    token: str
    expires_at: str  # ISO format UTC timestamp

    def is_valid(self, margin_seconds: int = 60) -> bool:
        """Return True if token is still valid with a small safety margin."""
        expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return now + timedelta(seconds=margin_seconds) < expires


class CharmmGuiClient:
    """Small client for auth and authenticated HTTP requests."""

    def __init__(
        self,
        email: str | None = None,
        password: str | None = None,
        token_file: Path | None = None,
        timeout: int = 30,
    ) -> None:
        self.email = email
        self.password = password
        self.token_file = token_file or DEFAULT_TOKEN_FILE
        self.timeout = timeout

    def has_credentials(self) -> bool:
        return bool(self.email and self.password)

    def read_cached_token(self) -> TokenInfo | None:
        """Read token from local cache if present."""
        if not self.token_file.exists():
            return None

        try:
            data = json.loads(self.token_file.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        token = data.get("token")
        expires_at = data.get("expires_at")
        if not token or not expires_at:
            return None

        return TokenInfo(token=token, expires_at=expires_at)

    def write_cached_token(self, token_info: TokenInfo) -> None:
        """Write token to local cache."""
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(
            json.dumps(
                {
                    "token": token_info.token,
                    "expires_at": token_info.expires_at,
                },
                indent=2,
            )
        )

    def login(self) -> TokenInfo:
        """Authenticate and cache a new token."""
        if not self.has_credentials():
            raise CharmmGuiConfigError("Missing CHARMM-GUI credentials. Provide username and password.")

        response = requests.post(
            LOGIN_URL,
            json={"email": self.email, "password": self.password},
            timeout=self.timeout,
        )

        if response.status_code != 200:
            raise CharmmGuiAuthError(f"Login failed with status {response.status_code}: {response.text}")

        payload: dict[str, Any] = response.json()
        token = payload.get("token")
        if not token:
            raise CharmmGuiAuthError("Login response did not contain a token.")

        expires_at = (datetime.now(timezone.utc) + timedelta(hours=36)).isoformat()

        token_info = TokenInfo(token=token, expires_at=expires_at)
        self.write_cached_token(token_info)
        return token_info

    def get_cached_token(self) -> TokenInfo | None:
        """Return the cached token if it exists and is still valid, otherwise None."""
        cached = self.read_cached_token()
        return cached if (cached and cached.is_valid()) else None

    def get_token(self, force_refresh: bool = False) -> str:
        """Return a valid token, using cache when possible."""
        if not force_refresh:
            cached = self.get_cached_token()
            if cached:
                return cached.token

        return self.login().token

    def get_auth_headers(self) -> dict[str, str]:
        """Return headers for authenticated requests."""
        return {"Authorization": f"Bearer {self.get_token()}"}

    def submit(self, url: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Submit a job to a module endpoint and return the parsed response."""
        response = requests.post(url, data=parameters, headers=self.get_auth_headers(), timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def check_status(self, jobid: str) -> dict[str, Any]:
        """Return the current status payload for a job."""
        response = requests.get(
            CHECK_STATUS_URL, params={"jobid": jobid}, headers=self.get_auth_headers(), timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def download(self, jobid: str) -> bytes:
        """Download and return the raw .tgz archive for a completed job."""
        response = requests.get(DOWNLOAD_URL, params={"jobid": jobid}, headers=self.get_auth_headers(), timeout=120)
        response.raise_for_status()
        return response.content
