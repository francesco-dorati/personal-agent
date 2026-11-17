"""The HTTP transport must refuse every request that lacks the bearer token."""
from __future__ import annotations

import unittest

from starlette.testclient import TestClient

from personal_agent.server import build_http_app

TOKEN = "t" * 32
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}}
HEADERS = {"content-type": "application/json", "accept": "application/json, text/event-stream"}


class BearerTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(build_http_app("127.0.0.1", "/mcp", TOKEN), base_url="http://127.0.0.1:8765")

    def test_no_token_is_refused(self):
        r = self.client.post("/mcp", json=INIT, headers=HEADERS)
        self.assertEqual(r.status_code, 401)

    def test_wrong_token_is_refused(self):
        r = self.client.post("/mcp", json=INIT, headers={**HEADERS, "authorization": "Bearer nope"})
        self.assertEqual(r.status_code, 401)

    def test_other_scheme_is_refused(self):
        r = self.client.post("/mcp", json=INIT, headers={**HEADERS, "authorization": f"Basic {TOKEN}"})
        self.assertEqual(r.status_code, 401)

    def test_right_token_reaches_the_server(self):
        with self.client as c:
            r = c.post("/mcp", json=INIT, headers={**HEADERS, "authorization": f"Bearer {TOKEN}"})
        self.assertNotEqual(r.status_code, 401)
        self.assertLess(r.status_code, 500)


if __name__ == "__main__":
    unittest.main()
