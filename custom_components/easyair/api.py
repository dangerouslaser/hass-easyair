"""Async client for the Bosch EasyAir cloud API."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qs, quote, urlencode

import aiohttp

from .const import (
    API_BASE,
    AUTH_DOMAIN,
    CLIENT_ID,
    IDENTITY_PROVIDER,
    REDIRECT_URI,
    SCOPES,
)

TIMEOUT = aiohttp.ClientTimeout(total=30)


class EasyAirError(Exception):
    """Generic API error."""


class EasyAirAuthError(EasyAirError):
    """Authentication failed; a new browser login is required."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def new_login() -> dict[str, str]:
    """Create a PKCE authorization request. Returns url and verifier."""
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    query = urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "identity_provider": IDENTITY_PROVIDER,
            "scope": SCOPES,
            "state": _b64url(secrets.token_bytes(16)),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return {"url": f"{AUTH_DOMAIN}/oauth2/authorize?{query}", "verifier": verifier}


def extract_code(redirect: str) -> str:
    """Return the auth code from an idsmobileapp://?code=... URL (or a bare code)."""
    redirect = redirect.strip().strip("'\"")
    if "=" not in redirect:
        return redirect
    query = redirect.split("?", 1)[-1].split("#", 1)[0]
    params = parse_qs(query)
    if "error" in params:
        raise EasyAirAuthError(params.get("error_description", params["error"])[0])
    if "code" not in params:
        raise EasyAirAuthError("No code found in the pasted URL")
    return params["code"][0]


def token_claims(token: str) -> dict[str, Any]:
    """Decode (without verifying) a JWT payload."""
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


async def _token_request(session: aiohttp.ClientSession, data: dict) -> dict:
    try:
        async with session.post(
            f"{AUTH_DOMAIN}/oauth2/token", data=data, timeout=TIMEOUT
        ) as resp:
            body = await resp.json(content_type=None)
            if resp.status >= 400:
                raise EasyAirAuthError(
                    f"{body.get('error', resp.status)}: {body.get('error_description', '')}"
                )
            return body
    except aiohttp.ClientError as err:
        raise EasyAirError(f"Token request failed: {err}") from err


def _with_expiry(tok: dict, previous: dict | None = None) -> dict:
    out = dict(previous or {})
    out.update(tok)
    out["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 120
    return out


async def exchange_code(
    session: aiohttp.ClientSession, redirect_or_code: str, verifier: str
) -> dict:
    """Exchange an authorization code for tokens."""
    tok = await _token_request(
        session,
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "code": extract_code(redirect_or_code),
            "code_verifier": verifier,
        },
    )
    return _with_expiry(tok)


class EasyAirApi:
    """Authenticated API client. Refreshes the access token as needed."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tokens: dict,
        on_tokens: Callable[[dict], Awaitable[None] | None] | None = None,
    ) -> None:
        self._session = session
        self.tokens = tokens
        self._on_tokens = on_tokens

    async def _refresh(self) -> None:
        if not self.tokens.get("refresh_token"):
            raise EasyAirAuthError("No refresh token")
        tok = await _token_request(
            self._session,
            {
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": self.tokens["refresh_token"],
            },
        )
        # Cognito keeps the original refresh token; merge so we retain it.
        self.tokens = _with_expiry(tok, self.tokens)
        if self._on_tokens:
            result = self._on_tokens(self.tokens)
            if result is not None:
                await result

    async def _get(self, path: str, retry: bool = True) -> Any:
        if time.time() >= self.tokens.get("expires_at", 0):
            await self._refresh()
        headers = {
            "Authorization": f"Bearer {self.tokens['access_token']}",
            "Accept": "application/json",
            "Cache-Control": "no-cache, no-store",
            "Language-Tag": "en",
        }
        try:
            async with self._session.get(
                API_BASE + path, headers=headers, timeout=TIMEOUT
            ) as resp:
                if resp.status in (401, 403) and retry:
                    self.tokens["expires_at"] = 0
                    return await self._get(path, retry=False)
                if resp.status in (401, 403):
                    raise EasyAirAuthError(f"GET {path} unauthorized")
                if resp.status >= 400:
                    text = await resp.text()
                    raise EasyAirError(f"GET {path} -> {resp.status}: {text[:300]}")
                return await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise EasyAirError(f"GET {path} failed: {err}") from err

    async def device_list(self) -> list[dict]:
        """Return the homeowner's units."""
        body = await self._get("/homeowner/devicelist")
        return (body.get("data") or {}).get("deviceList") or []

    async def energy_usage(self, gateway_id: str) -> dict:
        """Return {'communicatingFlag', 'data': [{year, months{0-11}, weekly{1-53}}]} in kWh."""
        body = await self._get("/energyusage/" + quote(gateway_id, safe=""))
        return body.get("data") or {}
