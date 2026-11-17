"""The workspace map must never make a caller wait when an older copy exists."""
from __future__ import annotations

import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from personal_agent import workspace as W
from personal_agent.registry import REGISTRY_VERSION, Registry


def registry(age):
    return Registry("root", "Test", time.time() - age, [], [])


class CacheTests(unittest.TestCase):
    def make(self):
        ws = W.Workspace(types.SimpleNamespace(root_page_id="r", notion_token="x", timezone="UTC"))
        ws.__dict__["api"] = object()
        return ws

    def test_stale_map_is_served_at_once_and_refreshed_behind(self):
        ws = self.make()
        ws._registry = registry(3600)                         # an hour old: past the 15 minute TTL
        done = threading.Event()

        def slow_build(api, root):
            time.sleep(0.3)
            done.set()
            return registry(0)

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(W, "build_registry", slow_build), \
                mock.patch.object(W.Workspace, "cache_file", Path(tmp) / "r.json"):
            started = time.time()
            got = ws.registry()
            self.assertLess(time.time() - started, 0.2)       # did not wait for the rebuild
            self.assertGreater(time.time() - got.built_at, 3000)
            self.assertTrue(done.wait(2))
            time.sleep(0.1)
            self.assertLess(time.time() - ws.registry().built_at, 5)   # next call sees the new map

    def test_week_old_map_is_rebuilt_while_waiting(self):
        ws = self.make()
        ws._registry = registry(8 * 24 * 3600)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(W, "build_registry", lambda api, root: registry(0)), \
                mock.patch.object(W.Workspace, "cache_file", Path(tmp) / "r.json"):
            self.assertLess(time.time() - ws.registry().built_at, 5)

    def test_refresh_flag_rebuilds(self):
        ws = self.make()
        ws._registry = registry(10)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(W, "build_registry", lambda api, root: registry(0)), \
                mock.patch.object(W.Workspace, "cache_file", Path(tmp) / "r.json"):
            self.assertLess(time.time() - ws.registry(refresh=True).built_at, 5)


if __name__ == "__main__":
    unittest.main()
