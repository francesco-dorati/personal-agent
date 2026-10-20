"""Page ID ↔ name lookups, so relations read as names, not IDs."""
from __future__ import annotations

import difflib
import time
from dataclasses import dataclass

from .notion_api import NotionAPI
from .registry import Database
from .values import decode, norm_id

TTL_SECONDS = 5 * 60


@dataclass
class Item:
    page_id: str
    title: str
    label: str           # e.g. "PER-33", or "" if the database has no ID property
    database: str


class Names:
    def __init__(self, api: NotionAPI):
        self.api = api
        self._by_source: dict[str, tuple[float, dict[str, Item]]] = {}

    def items(self, db: Database) -> dict[str, Item]:
        """All items of a database, by page ID (cached)."""
        cached = self._by_source.get(db.data_source_id)
        if cached and time.time() - cached[0] < TTL_SECONDS:
            return cached[1]
        items: dict[str, Item] = {}
        for row in self.api.query(db.data_source_id, limit=2000):
            title, label = "", ""
            for prop in row["properties"].values():
                if prop["type"] == "title":
                    title = decode(prop) or "Untitled"
                elif prop["type"] == "unique_id":
                    label = decode(prop) or ""
            pid = norm_id(row["id"])
            items[pid] = Item(pid, title or "Untitled", label, db.name)
        self._by_source[db.data_source_id] = (time.time(), items)
        return items

    def remember(self, db: Database, item: Item) -> None:
        cached = self._by_source.get(db.data_source_id)
        if cached:
            cached[1][item.page_id] = item

    def name_of(self, db: Database | None, page_id: str) -> str:
        if db is None:
            return page_id
        item = self.items(db).get(norm_id(page_id))
        return item.title if item else f"(unknown {page_id[:8]})"

    def match(self, db: Database, query: str, cutoff: float = 0.6) -> list[tuple[Item, float]]:
        """Items whose title or ID best matches `query`, best first."""
        q = query.strip().lower()
        scored = []
        for item in self.items(db).values():
            title = item.title.lower()
            if q == title or q == item.label.lower():
                score = 1.0
            elif q in title:
                score = 0.9
            else:
                # Whole title, or any single word of it (a surname, a typo of one).
                score = max(difflib.SequenceMatcher(None, q, title).ratio(),
                            max((difflib.SequenceMatcher(None, q, w).ratio() for w in title.split()), default=0) * 0.95)
            if score >= cutoff:
                scored.append((item, round(score, 2)))
        return sorted(scored, key=lambda s: -s[1])
