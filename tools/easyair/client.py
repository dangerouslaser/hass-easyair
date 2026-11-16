"""Minimal client for the Bosch EasyAir (IDS) cloud API.

Recovered from the Bosch EasyAir Android app (com.idsmobileapp 4.2.0):
  * Auth: AWS Cognito user pool us-east-1_TFlzavFpZ, Hosted UI at
    auth.smart-climate-ids.com, federated to SingleKey ID via the
    "IDS-TTNA" identity provider. Public client (no secret), PKCE.
  * API:  https://api.smart-climate-ids.com, raw "Bearer <Cognito access token>" in the
    Authorization header.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

AUTH_DOMAIN = "https://auth.smart-climate-ids.com"
CLIENT_ID = "7q2puec5cov7ls93041mb38p6v"
REDIRECT_URI = "idsmobileapp://"
IDENTITY_PROVIDER = "IDS-TTNA"
SCOPES = "phone email openid profile aws.cognito.signin.user.admin"
API_BASE = "https://api.smart-climate-ids.com"
USER_AGENT = "hass-easyair/0.1"


class EasyAirError(Exception):
    pass


class AuthError(EasyAirError):
    """Tokens are missing/expired and a new browser login is required."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def new_login() -> dict:
    """Create a PKCE login request. Returns {url, verifier, state}."""
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    state = _b64url(secrets.token_bytes(16))
    q = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "identity_provider": IDENTITY_PROVIDER,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return {"url": f"{AUTH_DOMAIN}/oauth2/authorize?{q}", "verifier": verifier, "state": state}


def extract_code(redirect: str) -> str:
    """Accept the full idsmobileapp://?code=... URL or a bare code."""
    redirect = redirect.strip()
    if "code=" not in redirect:
        return redirect
    query = redirect.split("?", 1)[1] if "?" in redirect else redirect
    params = urllib.parse.parse_qs(query.split("#", 1)[0])
    if "error" in params:
        raise AuthError(f"Login failed: {params.get('error_description', params['error'])}")
    return params["code"][0]


def _post_form(url: str, data: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise AuthError(f"Token endpoint returned {e.code}: {body}") from None


def _with_expiry(tok: dict, previous: dict | None = None) -> dict:
    out = dict(previous or {})
    out.update(tok)
    out["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
    return out


def exchange_code(redirect_or_code: str, verifier: str) -> dict:
    tok = _post_form(f"{AUTH_DOMAIN}/oauth2/token", {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "code": extract_code(redirect_or_code),
        "code_verifier": verifier,
    })
    return _with_expiry(tok)


def refresh(tokens: dict) -> dict:
    if not tokens.get("refresh_token"):
        raise AuthError("No refresh token; log in again")
    tok = _post_form(f"{AUTH_DOMAIN}/oauth2/token", {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": tokens["refresh_token"],
    })
    return _with_expiry(tok, tokens)  # Cognito does not return a new refresh_token


class EasyAirClient:
    def __init__(self, tokens: dict, on_tokens=None):
        self.tokens = tokens
        self._on_tokens = on_tokens  # callback(tokens) to persist refreshed tokens

    def _access_token(self) -> str:
        if time.time() >= self.tokens.get("expires_at", 0):
            self.tokens = refresh(self.tokens)
            if self._on_tokens:
                self._on_tokens(self.tokens)
        return self.tokens["access_token"]

    def get(self, path: str, _retry: bool = True):
        req = urllib.request.Request(
            API_BASE + path,
            headers={
                "Authorization": "Bearer " + self._access_token(),
                "Accept": "application/json",
                "Cache-Control": "no-cache, no-store",
                "Language-Tag": "en",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            if e.code in (401, 403) and _retry:
                self.tokens["expires_at"] = 0  # force refresh once
                return self.get(path, _retry=False)
            raise EasyAirError(f"GET {path} -> {e.code}: {e.read().decode(errors='replace')[:500]}") from None
        try:
            return json.loads(raw)
        except ValueError:
            return raw.decode(errors="replace")

    # Endpoints used by the homeowner screens of the app
    def device_list(self):
        return self.get("/homeowner/devicelist")

    def device_details(self, gateway_id: str):
        return self.get("/homeowner/devicedetails/" + urllib.parse.quote(gateway_id))

    def energy_usage(self, gateway_id: str):
        return self.get("/energyusage/" + urllib.parse.quote(gateway_id))
