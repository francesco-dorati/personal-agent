"""Thin Notion REST client: auth, pagination, rate limiting, retries.

Knows nothing about the personal-agent data model; see `registry.py` for that.
Uses the 2025-09-03 API, where a database holds one or more data sources.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Iterator

import httpx

API_URL = "https://api.notion.com/v1"
API_VERSION = "2025-09-03"

logging.getLogger("httpx").setLevel(logging.WARNING)   # one log line per request is noise


class NotionError(RuntimeError):
    def __init__(self, status: int, code: str, message: str, path: str):
        super().__init__(f"Notion {status} {code} on {path}: {message}")
        self.status, self.code = status, code


class NotionAPI:
    def __init__(self, token: str, *, requests_per_second: float = 3.0, timeout: float = 30.0):
        self._client = httpx.Client(
            base_url=API_URL,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": API_VERSION,
                "Content-Type": "application/json",
            },
        )
        self._min_interval = 1.0 / requests_per_second
        self._last_request = 0.0
        self.request_count = 0

    # -- core -------------------------------------------------------------
    def request(self, method: str, path: str, *, json: dict | None = None,
                params: dict | None = None, retries: int = 4) -> dict:
        for attempt in range(retries + 1):
            wait = self._min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            self.request_count += 1
            resp = self._client.request(method, path, json=json, params=params)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < retries:
                    time.sleep(float(resp.headers.get("Retry-After", 2 ** attempt)))
                    continue
            if resp.status_code >= 400:
                body = resp.json() if resp.content else {}
                raise NotionError(resp.status_code, body.get("code", ""), body.get("message", resp.text), path)
            return resp.json()
        raise AssertionError("unreachable")

    def paginate(self, method: str, path: str, *, json: dict | None = None,
                 params: dict | None = None, limit: int | None = None) -> Iterator[dict]:
        """Yield results across pages, stopping after `limit` items if given."""
        cursor, seen = None, 0
        while True:
            page_params = dict(params or {})
            page_body = dict(json or {}) if method == "POST" else None
            size = min(100, limit - seen) if limit else 100
            if method == "POST":
                page_body["page_size"] = size
                if cursor:
                    page_body["start_cursor"] = cursor
            else:
                page_params["page_size"] = size
                if cursor:
                    page_params["start_cursor"] = cursor
            data = self.request(method, path, json=page_body, params=page_params)
            for item in data.get("results", []):
                yield item
                seen += 1
                if limit and seen >= limit:
                    return
            if not data.get("has_more"):
                return
            cursor = data.get("next_cursor")

    # -- endpoints ----------------------------------------------------------
    def block_children(self, block_id: str) -> list[dict]:
        return list(self.paginate("GET", f"/blocks/{block_id}/children"))

    def page(self, page_id: str) -> dict:
        return self.request("GET", f"/pages/{page_id}")

    def database(self, database_id: str) -> dict:
        return self.request("GET", f"/databases/{database_id}")

    def data_source(self, data_source_id: str) -> dict:
        return self.request("GET", f"/data_sources/{data_source_id}")

    def query(self, data_source_id: str, *, filter: dict | None = None,
              sorts: list | None = None, limit: int | None = None) -> list[dict]:
        body: dict[str, Any] = {}
        if filter:
            body["filter"] = filter
        if sorts:
            body["sorts"] = sorts
        return list(self.paginate("POST", f"/data_sources/{data_source_id}/query", json=body, limit=limit))


def plain_text(rich: list[dict] | None) -> str:
    """Concatenate a Notion rich-text array into plain text."""
    return "".join(part.get("plain_text", "") for part in rich or []).strip()
