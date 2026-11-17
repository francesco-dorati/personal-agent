"""Single-owner OAuth 2.1 for the HTTP transport.

Hosted assistants (the Claude app, ChatGPT, ...) cannot send a static `Authorization` header. They
discover this server's OAuth endpoints, register themselves (RFC 7591), send the owner to `/login`,
and then use short-lived access tokens. This module is the authorization server behind that flow.

Only one person can ever log in: the owner, with `PERSONAL_AGENT_OWNER_PASSWORD`. Anyone else who
finds the public URL can register a client, but never obtains a token.

Tokens are random, stored only as SHA-256 hashes in `<state dir>/oauth.json` (mode 0600), so a
restart does not force a new login and a leaked state file does not leak usable tokens.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import json
import os
import secrets
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

SCOPE = "mcp"
ACCESS_TTL = 60 * 60                 # 1 hour
REFRESH_TTL = 30 * 24 * 60 * 60      # 30 days, rotated on every use
CODE_TTL = 5 * 60
PENDING_TTL = 10 * 60
MAX_CLIENTS = 100
MAX_FAILURES = 5                     # wrong passwords ...
FAILURE_WINDOW = 15 * 60             # ... within this many seconds lock the login page
MIN_PASSWORD_LENGTH = 12


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class OwnerOAuthProvider:
    """`OAuthAuthorizationServerProvider` for one owner, persisted to a small JSON file."""

    def __init__(self, issuer_url: str, owner_password: str, state_file: Path,
                 *, access_ttl: int = ACCESS_TTL, refresh_ttl: int = REFRESH_TTL) -> None:
        if len(owner_password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"The owner password must have at least {MIN_PASSWORD_LENGTH} characters.")
        self.issuer_url = issuer_url.rstrip("/")
        self._password = owner_password.encode()
        self._state_file = Path(state_file)
        self._access_ttl = access_ttl
        self._refresh_ttl = refresh_ttl
        self._clients: dict[str, dict] = {}
        self._tokens: dict[str, dict] = {}        # sha256(token) -> record
        self._codes: dict[str, AuthorizationCode] = {}
        self._pending: dict[str, tuple[OAuthClientInformationFull, AuthorizationParams, float]] = {}
        self._failures: list[float] = []
        self._load()

    # ---- persistence ---------------------------------------------------------------------------

    def _load(self) -> None:
        try:
            data = json.loads(self._state_file.read_text())
        except (FileNotFoundError, ValueError):
            return
        self._clients = data.get("clients", {})
        self._tokens = data.get("tokens", {})
        self._prune()

    def _save(self) -> None:
        self._prune()
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._state_file.parent, prefix=".oauth-")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump({"clients": self._clients, "tokens": self._tokens}, fh)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self._state_file)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _prune(self) -> None:
        now = time.time()
        self._tokens = {h: t for h, t in self._tokens.items() if t["expires_at"] > now}
        self._codes = {c: a for c, a in self._codes.items() if a.expires_at > now}
        self._pending = {r: p for r, p in self._pending.items() if p[2] > now}

    # ---- clients (dynamic registration) --------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        raw = self._clients.get(client_id)
        return OAuthClientInformationFull.model_validate(raw) if raw else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if client_info.client_id is None:
            raise ValueError("client_id is required")
        self._clients[client_info.client_id] = client_info.model_dump(mode="json", exclude_none=True)
        while len(self._clients) > MAX_CLIENTS:      # oldest registrations go first
            self._clients.pop(next(iter(self._clients)))
        self._save()

    # ---- authorization -------------------------------------------------------------------------

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        self._prune()
        req_id = secrets.token_urlsafe(24)
        self._pending[req_id] = (client, params, time.time() + PENDING_TTL)
        return f"{self.issuer_url}/login?req={req_id}"

    def pending(self, req_id: str) -> tuple[OAuthClientInformationFull, AuthorizationParams] | None:
        self._prune()
        entry = self._pending.get(req_id)
        return (entry[0], entry[1]) if entry else None

    def locked_out(self) -> bool:
        now = time.time()
        self._failures = [t for t in self._failures if now - t < FAILURE_WINDOW]
        return len(self._failures) >= MAX_FAILURES

    def check_password(self, supplied: str) -> bool:
        ok = hmac.compare_digest(supplied.encode(), self._password)
        if not ok:
            self._failures.append(time.time())
        return ok

    def approve(self, req_id: str) -> str:
        """The owner logged in: issue the authorization code and return the client's redirect URL."""
        client, params, _ = self._pending.pop(req_id)
        code = secrets.token_urlsafe(32)
        self._codes[code] = AuthorizationCode(
            code=code,
            scopes=params.scopes or [SCOPE],
            expires_at=time.time() + CODE_TTL,
            client_id=client.client_id or "",
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
            subject="owner",
        )
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    async def load_authorization_code(self, client: OAuthClientInformationFull,
                                      authorization_code: str) -> AuthorizationCode | None:
        self._prune()
        code = self._codes.get(authorization_code)
        return code if code and code.client_id == client.client_id else None

    async def exchange_authorization_code(self, client: OAuthClientInformationFull,
                                          authorization_code: AuthorizationCode) -> OAuthToken:
        if self._codes.pop(authorization_code.code, None) is None:      # single use
            raise TokenError("invalid_grant", "authorization code already used or expired")
        return self._issue(client.client_id or "", authorization_code.scopes, authorization_code.resource)

    # ---- tokens --------------------------------------------------------------------------------

    def _issue(self, client_id: str, scopes: list[str], resource: str | None) -> OAuthToken:
        family = secrets.token_hex(8)
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = time.time()
        base = {"client_id": client_id, "scopes": scopes, "resource": resource, "family": family}
        self._tokens[_hash(access)] = {**base, "kind": "access", "expires_at": int(now + self._access_ttl)}
        self._tokens[_hash(refresh)] = {**base, "kind": "refresh", "expires_at": int(now + self._refresh_ttl)}
        self._save()
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=self._access_ttl,
                          scope=" ".join(scopes), refresh_token=refresh)

    def _lookup(self, token: str, kind: str) -> dict | None:
        record = self._tokens.get(_hash(token))
        if record is None or record["kind"] != kind or record["expires_at"] <= time.time():
            return None
        return record

    async def load_access_token(self, token: str) -> AccessToken | None:
        record = self._lookup(token, "access")
        if record is None:
            return None
        return AccessToken(token=token, client_id=record["client_id"], scopes=record["scopes"],
                           expires_at=record["expires_at"], resource=record.get("resource"), subject="owner")

    async def load_refresh_token(self, client: OAuthClientInformationFull,
                                 refresh_token: str) -> RefreshToken | None:
        record = self._lookup(refresh_token, "refresh")
        if record is None or record["client_id"] != client.client_id:
            return None
        return RefreshToken(token=refresh_token, client_id=record["client_id"], scopes=record["scopes"],
                            expires_at=record["expires_at"], resource=record.get("resource"), subject="owner")

    async def exchange_refresh_token(self, client: OAuthClientInformationFull,
                                     refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        record = self._lookup(refresh_token.token, "refresh")
        if record is None:
            raise TokenError("invalid_grant", "refresh token expired or revoked")
        granted = [s for s in scopes if s in refresh_token.scopes] or refresh_token.scopes
        self._revoke_family(record["family"])           # rotate: the old pair stops working
        return self._issue(refresh_token.client_id, granted, refresh_token.resource)

    def _revoke_family(self, family: str) -> None:
        self._tokens = {h: t for h, t in self._tokens.items() if t["family"] != family}

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        record = self._tokens.get(_hash(token.token))
        if record is not None:
            self._revoke_family(record["family"])
            self._save()

    # ---- the login page ------------------------------------------------------------------------

    def login_routes(self) -> list[Route]:
        return [Route("/login", endpoint=self._login, methods=["GET", "POST"])]

    def _page(self, req_id: str, client: OAuthClientInformationFull, error: str = "", status: int = 200) -> Response:
        name = html.escape(client.client_name or "An application")
        target = html.escape(urlparse(str((client.redirect_uris or [""])[0])).netloc or "unknown")
        err = f'<p class="err">{html.escape(error)}</p>' if error else ""
        body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Personal Agent</title>
<style>body{{font:16px system-ui,sans-serif;max-width:26rem;margin:12vh auto;padding:0 1rem;color:#222}}
input,button{{font:inherit;width:100%;padding:.6rem;margin:.4rem 0;box-sizing:border-box}}
button{{cursor:pointer}}.err{{color:#b00020}}small{{color:#666}}
@media(prefers-color-scheme:dark){{body{{background:#111;color:#eee}}small{{color:#aaa}}}}</style></head>
<body><h2>Personal Agent</h2>
<p><b>{name}</b> wants to read and propose changes to your personal workspace.<br>
<small>It will be sent back to {target}.</small></p>{err}
<form method="post" action="/login?req={html.escape(req_id)}">
<input type="password" name="password" placeholder="Owner password" autocomplete="current-password" autofocus required>
<button type="submit">Allow</button></form>
<small>Only continue if you started this connection yourself.</small></body></html>"""
        return self._secure(HTMLResponse(body, status_code=status))

    @staticmethod
    def _secure(response: Response) -> Response:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"
        return response

    async def _login(self, request: Request) -> Response:
        req_id = request.query_params.get("req", "")
        entry = self.pending(req_id)
        if entry is None:
            return self._secure(HTMLResponse(
                "<!doctype html><title>Personal Agent</title><p>This login link expired. "
                "Start the connection again from your assistant.</p>", status_code=400))
        client, _ = entry
        if request.method == "GET":
            return self._page(req_id, client)
        if self.locked_out():
            return self._page(req_id, client, "Too many wrong passwords. Try again in 15 minutes.", 429)
        raw = await request.body()
        if len(raw) > 4096:
            return self._page(req_id, client, "Request too large.", 413)
        password = parse_qs(raw.decode("utf-8", "replace")).get("password", [""])[0]
        if not self.check_password(password):
            await asyncio.sleep(1)           # slow down guessing
            return self._page(req_id, client, "Wrong password.", 401)
        return self._secure(RedirectResponse(self.approve(req_id), status_code=303))
