"""The OAuth flow for hosted assistants: only the owner can log in, tokens work, static token still works."""
from __future__ import annotations

import base64
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, quote_plus, urlparse

from starlette.testclient import TestClient

from personal_agent import oauth as oauth_mod
from personal_agent.oauth import OwnerOAuthProvider
from personal_agent.server import build_http_app

PUBLIC = "https://jetson.example.ts.net"
STATIC = "s" * 32
PASSWORD = "correct horse battery staple"
REDIRECT = "https://assistant.example/callback"
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}}
HEADERS = {"content-type": "application/json", "accept": "application/json, text/event-stream"}


def pkce():
    verifier = "v" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "oauth.json"
        self.provider = OwnerOAuthProvider(PUBLIC, PASSWORD, self.state)
        self.app = build_http_app("127.0.0.1", "/mcp", STATIC, ("jetson.example.ts.net",), self.provider, PUBLIC)
        self.client = TestClient(self.app, base_url=PUBLIC, follow_redirects=False)
        self.client.__enter__()      # runs the app's lifespan once for the whole test
        self.addCleanup(self.client.__exit__, None, None, None)
        patcher = mock.patch.object(oauth_mod.asyncio, "sleep", _instant)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    # -- helpers

    def register(self):
        r = self.client.post("/register", json={
            "client_name": "Test Assistant", "redirect_uris": [REDIRECT], "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"], "scope": "mcp"})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["client_id"]

    def start(self, client_id, challenge):
        r = self.client.get("/authorize", params={
            "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "scope": "mcp",
            "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz"})
        self.assertEqual(r.status_code, 302, r.text)
        return r.headers["location"]

    def login(self, login_url, password):
        return self.client.post(login_url, content=f"password={quote_plus(password)}",
                                headers={"content-type": "application/x-www-form-urlencoded"})

    def tokens(self):
        client_id = self.register()
        verifier, challenge = pkce()
        login_url = self.start(client_id, challenge)
        r = self.login(login_url, PASSWORD)
        self.assertEqual(r.status_code, 303, r.text)
        query = parse_qs(urlparse(r.headers["location"]).query)
        self.assertEqual(query["state"], ["xyz"])
        r = self.client.post("/token", data={
            "grant_type": "authorization_code", "code": query["code"][0], "redirect_uri": REDIRECT,
            "client_id": client_id, "code_verifier": verifier})
        self.assertEqual(r.status_code, 200, r.text)
        return client_id, r.json()

    def mcp(self, token):
        return self.client.post("/mcp", json=INIT, headers={**HEADERS, "authorization": f"Bearer {token}"})

    # -- tests

    def test_discovery_is_public_and_points_at_the_issuer(self):
        meta = self.client.get("/.well-known/oauth-authorization-server")
        self.assertEqual(meta.status_code, 200)
        self.assertEqual(meta.json()["issuer"], PUBLIC)
        self.assertEqual(meta.json()["registration_endpoint"], f"{PUBLIC}/register")
        resource = self.client.get("/.well-known/oauth-protected-resource/mcp")
        self.assertEqual(resource.status_code, 200)
        self.assertEqual(resource.json()["authorization_servers"], [PUBLIC])

    def test_unauthenticated_mcp_call_says_where_to_log_in(self):
        r = self.client.post("/mcp", json=INIT, headers=HEADERS)
        self.assertEqual(r.status_code, 401)
        self.assertIn("resource_metadata=", r.headers["www-authenticate"])
        self.assertIn("/.well-known/oauth-protected-resource/mcp", r.headers["www-authenticate"])

    def test_full_flow_gives_a_working_token(self):
        _, tokens = self.tokens()
        self.assertEqual(tokens["token_type"], "Bearer")
        r = self.mcp(tokens["access_token"])
        self.assertNotEqual(r.status_code, 401)
        self.assertLess(r.status_code, 500)

    def test_static_token_still_works_next_to_oauth(self):
        r = self.mcp(STATIC)
        self.assertNotEqual(r.status_code, 401)

    def test_random_token_is_refused(self):
        self.assertEqual(self.mcp("not-a-token").status_code, 401)

    def test_wrong_password_gets_no_code(self):
        client_id = self.register()
        _, challenge = pkce()
        login_url = self.start(client_id, challenge)
        r = self.login(login_url, "wrong-password-123")
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("location", r.headers)

    def test_login_locks_after_repeated_failures(self):
        client_id = self.register()
        _, challenge = pkce()
        login_url = self.start(client_id, challenge)
        for _ in range(oauth_mod.MAX_FAILURES):
            self.assertEqual(self.login(login_url, "wrong-password-123").status_code, 401)
        locked = self.login(login_url, PASSWORD)      # even the right password is refused now
        self.assertEqual(locked.status_code, 429)

    def test_unknown_login_request_is_rejected(self):
        self.assertEqual(self.client.get("/login?req=nope").status_code, 400)
        self.assertEqual(self.login("/login?req=nope", "whatever-123456").status_code, 400)

    def test_login_page_names_the_client_and_escapes_it(self):
        r = self.client.post("/register", json={
            "client_name": "<script>alert(1)</script>", "redirect_uris": [REDIRECT],
            "token_endpoint_auth_method": "none"})
        _, challenge = pkce()
        login_url = self.start(r.json()["client_id"], challenge)
        page = self.client.get(login_url)
        self.assertEqual(page.status_code, 200)
        self.assertNotIn("<script>alert(1)", page.text)
        self.assertIn("&lt;script&gt;", page.text)
        self.assertEqual(page.headers["x-frame-options"], "DENY")

    def test_code_is_single_use_and_bound_to_pkce(self):
        client_id = self.register()
        verifier, challenge = pkce()
        r = self.login(self.start(client_id, challenge), PASSWORD)
        code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
        body = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, "client_id": client_id}
        self.assertEqual(self.client.post("/token", data={**body, "code_verifier": "x" * 64}).status_code, 400)
        ok = self.client.post("/token", data={**body, "code_verifier": verifier})
        again = self.client.post("/token", data={**body, "code_verifier": verifier})
        self.assertIn(ok.status_code, (200, 400))      # a failed verifier attempt may already have burnt the code
        self.assertEqual(again.status_code, 400)

    def test_refresh_rotates_tokens(self):
        client_id, tokens = self.tokens()
        r = self.client.post("/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                                             "client_id": client_id})
        self.assertEqual(r.status_code, 200, r.text)
        new = r.json()
        self.assertNotEqual(new["access_token"], tokens["access_token"])
        self.assertEqual(self.mcp(tokens["access_token"]).status_code, 401)      # old pair is gone
        self.assertNotEqual(self.mcp(new["access_token"]).status_code, 401)
        reuse = self.client.post("/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                                                 "client_id": client_id})
        self.assertEqual(reuse.status_code, 400)

    def test_revoke_kills_the_token(self):
        client_id, tokens = self.tokens()
        r = self.client.post("/revoke", data={"token": tokens["access_token"], "client_id": client_id,
                                                "client_secret": ""})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.mcp(tokens["access_token"]).status_code, 401)

    def test_tokens_survive_a_restart_and_are_stored_hashed(self):
        _, tokens = self.tokens()
        stored = self.state.read_text()
        self.assertNotIn(tokens["access_token"], stored)
        self.assertNotIn(tokens["refresh_token"], stored)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)
        restarted = OwnerOAuthProvider(PUBLIC, PASSWORD, self.state)
        import asyncio
        self.assertIsNotNone(asyncio.run(restarted.load_access_token(tokens["access_token"])))

    def test_weak_owner_password_is_refused(self):
        with self.assertRaises(ValueError):
            OwnerOAuthProvider(PUBLIC, "short", self.state)

    def test_oauth_off_keeps_endpoints_closed(self):
        app = build_http_app("127.0.0.1", "/mcp", STATIC)
        client = TestClient(app, base_url="http://127.0.0.1:8765")
        self.assertEqual(client.get("/.well-known/oauth-authorization-server").status_code, 401)
        self.assertEqual(client.post("/register", json={}).status_code, 401)


async def _instant(_seconds):
    return None


if __name__ == "__main__":
    unittest.main()
