"""Page ID ↔ name lookups, so relations read as names, not IDs."""
from __future__ import annotations

import difflib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from .notion_api import NotionAPI
from .registry import Database
from .values import decode, norm_id

TTL_SECONDS = 5 * 60            # older: still served for reads, but refreshed in the background
FRESH_SECONDS = 30              # what a write needs (duplicate checks, resolving a name to link)
MAX_STALE_SECONDS = 24 * 3600   # older than this on disk: fetch before answering


@dataclass
class Item:
    page_id: str
    title: str
    label: str           # e.g. "PER-33", or "" if the database has no ID property
    database: str


class Names:
    def __init__(self, api: NotionAPI, cache_file: Path | None = None):
        self.api = api
        self.cache_file = cache_file
        self._by_source: dict[str, tuple[float, dict[str, Item]]] = {}
        self._lock = threading.Lock()
        self._refreshing: set[str] = set()
        self._loaded = False

    # -- disk cache: titles and IDs are small, and a new process should not re-read every database
    def _load_disk(self) -> None:
        self._loaded = True
        if not self.cache_file or not Path(self.cache_file).exists():
            return
        try:
            data = json.loads(Path(self.cache_file).read_text())
            for ds, (built, rows) in data.items():
                if time.time() - built < MAX_STALE_SECONDS and ds not in self._by_source:
                    self._by_source[ds] = (built, {r["page_id"]: Item(**r) for r in rows})
        except (OSError, ValueError, TypeError, KeyError):
            pass

    def _save_disk(self) -> None:
        if not self.cache_file:
            return
        try:
            payload = {ds: [built, [asdict(i) for i in items.values()]] for ds, (built, items) in self._by_source.items()}
            tmp = Path(str(self.cache_file) + ".tmp")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload))
            tmp.replace(self.cache_file)
        except OSError:
            pass

    def _adopt_newer_disk(self, db: Database) -> None:
        if not self.cache_file or not Path(self.cache_file).exists():
            return
        try:
            built, rows = json.loads(Path(self.cache_file).read_text())[db.data_source_id]
            if built > self._by_source[db.data_source_id][0]:
                self._by_source[db.data_source_id] = (built, {r["page_id"]: Item(**r) for r in rows})
        except (OSError, ValueError, TypeError, KeyError):
            pass

    def _fetch(self, db: Database) -> dict[str, Item]:
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
        with self._lock:
            self._by_source[db.data_source_id] = (time.time(), items)
            self._save_disk()
        return items

    def _refresh_later(self, db: Database) -> None:
        with self._lock:
            if db.data_source_id in self._refreshing:
                return
            self._refreshing.add(db.data_source_id)

        def run():
            try:
                self._fetch(db)
            except Exception:                            # noqa: BLE001  (keep serving the old list)
                pass
            finally:
                with self._lock:
                    self._refreshing.discard(db.data_source_id)
        threading.Thread(target=run, daemon=True).start()

    def items(self, db: Database, fresh: bool = False) -> dict[str, Item]:
        """All items of a database, by page ID. Reads may be a few minutes old (and are refreshed in the
        background); `fresh=True`, for anything that writes, needs a copy under 30 seconds old."""
        if not self._loaded:
            self._load_disk()
        cached = self._by_source.get(db.data_source_id)
        if cached:
            age = time.time() - cached[0]
            if age < (FRESH_SECONDS if fresh else TTL_SECONDS):
                return cached[1]
            if not fresh:
                self._adopt_newer_disk(db)               # `agent refresh` in another process may have updated it
                cached = self._by_source[db.data_source_id]
                if time.time() - cached[0] >= TTL_SECONDS:
                    self._refresh_later(db)
                return cached[1]
        return self._fetch(db)

    def warm(self, dbs: list[Database], workers: int = 3) -> None:
        """Load every database's names ahead of time (a few requests each, a few at a time)."""
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda d: self.items(d), dbs))

    def remember(self, db: Database, item: Item) -> None:
        cached = self._by_source.get(db.data_source_id)
        if cached:
            cached[1][item.page_id] = item

    def name_of(self, db: Database | None, page_id: str) -> str:
        if db is None:
            return page_id
        item = self.items(db).get(norm_id(page_id))
        return item.title if item else f"(unknown {page_id[:8]})"

    def match(self, db: Database, query: str, cutoff: float = 0.6, fresh: bool = False) -> list[tuple[Item, float]]:
        """Items whose title or ID best matches `query`, best first."""
        q = query.strip().lower()
        scored = []
        for item in self.items(db, fresh=fresh).values():
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
