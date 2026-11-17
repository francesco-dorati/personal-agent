"""Shared state for tools: settings, the API client and the cached registry."""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import cached_property

from .config import CACHE_DIR, Settings, load_settings
from .names import Names
from .notion_api import NotionAPI
from .registry import REGISTRY_VERSION, Registry, build_registry

REGISTRY_TTL_SECONDS = 15 * 60                # older than this: serve it, refresh in the background
REGISTRY_MAX_STALE_SECONDS = 7 * 24 * 3600    # older than this: rebuild before answering


class Workspace:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or load_settings()
        self._registry: Registry | None = None
        self._build_lock = threading.Lock()
        self._refreshing = threading.Lock()

    @cached_property
    def api(self) -> NotionAPI:
        return NotionAPI(self.settings.notion_token)

    @cached_property
    def names(self) -> Names:
        return Names(self.api, CACHE_DIR / f"names-{self.settings.root_page_id}.json")

    @property
    def cache_file(self):
        return CACHE_DIR / f"registry-{self.settings.root_page_id}.json"

    def _load_cached(self) -> Registry | None:
        if not self.cache_file.exists():
            return None
        try:
            cached = Registry.load(self.cache_file)
        except (TypeError, KeyError, ValueError):       # cache from another code version
            return None
        return cached if cached.version == REGISTRY_VERSION else None

    def _rebuild(self) -> Registry:
        with self._build_lock:                           # one rebuild at a time; later callers reuse its result
            fresh = self._registry
            if fresh and time.time() - fresh.built_at < REGISTRY_TTL_SECONDS:
                return fresh
            self._registry = build_registry(self.api, self.settings.root_page_id)
            self._registry.save(self.cache_file)
            return self._registry

    def _refresh_in_background(self) -> None:
        if self._refreshing.acquire(blocking=False):
            def run():
                try:
                    self._rebuild()
                except Exception:                        # noqa: BLE001  (a failed refresh keeps the old map)
                    pass
                finally:
                    self._refreshing.release()
            threading.Thread(target=run, daemon=True).start()

    def registry(self, refresh: bool = False) -> Registry:
        """The workspace map. Building it takes ~120 Notion requests (over a minute), longer than a
        chat client waits for a tool, so an older map is served at once and refreshed in the background.
        Only a missing, incompatible or week-old map (or refresh=True) is rebuilt while the caller waits."""
        if refresh:
            self._registry = None
            return self._rebuild()
        current = self._registry
        if current is None or time.time() - current.built_at > REGISTRY_TTL_SECONDS:
            disk = self._load_cached()                   # another process (agent refresh) may have rebuilt it
            if disk and (current is None or disk.built_at > current.built_at):
                current = disk
        if current is None or time.time() - current.built_at > REGISTRY_MAX_STALE_SECONDS:
            self._registry = None
            return self._rebuild()
        self._registry = current
        if time.time() - current.built_at > REGISTRY_TTL_SECONDS:
            self._refresh_in_background()
        return current

    def refresh_all(self) -> tuple[int, int]:
        """Rebuild the map and reload every database's names now. Returns (databases, items)."""
        reg = self.registry(refresh=True)
        dbs = [d for d in reg.databases if d.data_source_id]
        with ThreadPoolExecutor(max_workers=3) as pool:
            counts = list(pool.map(lambda d: len(self.names.items(d, fresh=True)) if self._expire(d) else 0, dbs))
        return len(dbs), sum(counts)

    def _expire(self, db) -> bool:
        self.names._by_source.pop(db.data_source_id, None)
        return True

    def warm(self) -> None:
        """Load the workspace map and every database's names ahead of the first request."""
        reg = self.registry()
        self.names.warm([d for d in reg.databases if d.data_source_id])
