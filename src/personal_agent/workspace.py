"""Shared state for tools: settings, the API client and the cached registry."""
from __future__ import annotations

import time
from functools import cached_property

from .config import CACHE_DIR, Settings, load_settings
from .names import Names
from .notion_api import NotionAPI
from .registry import REGISTRY_VERSION, Registry, build_registry

REGISTRY_TTL_SECONDS = 15 * 60


class Workspace:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or load_settings()
        self._registry: Registry | None = None

    @cached_property
    def api(self) -> NotionAPI:
        return NotionAPI(self.settings.notion_token)

    @cached_property
    def names(self) -> Names:
        return Names(self.api)

    @property
    def cache_file(self):
        return CACHE_DIR / f"registry-{self.settings.root_page_id}.json"

    def registry(self, refresh: bool = False) -> Registry:
        """Return the workspace map, rebuilding it when stale or asked to."""
        if not refresh and self._registry and time.time() - self._registry.built_at < REGISTRY_TTL_SECONDS:
            return self._registry
        if not refresh and self.cache_file.exists():
            try:
                cached = Registry.load(self.cache_file)
            except (TypeError, KeyError, ValueError):   # cache from another code version
                cached = None
            if cached and cached.version == REGISTRY_VERSION and time.time() - cached.built_at < REGISTRY_TTL_SECONDS:
                self._registry = cached
                return cached
        self._registry = build_registry(self.api, self.settings.root_page_id)
        self._registry.save(self.cache_file)
        return self._registry
