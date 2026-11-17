"""Names: reads are served from a cache that survives restarts; writes insist on fresh data."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from personal_agent import names as N
from personal_agent.names import Names
from test_proposals import HABITS, REGISTRY, FakeAPI

HAB = REGISTRY.database_by_id(HABITS)


class Counting(FakeAPI):
    def __init__(self):
        super().__init__()
        self.queries = 0

    def query(self, ds, **kw):
        self.queries += 1
        return super().query(ds, **kw)


def seeded():
    api = Counting()
    api.create_page(HABITS, {"Name": {"title": [{"text": {"content": "Learn Mandarin"}}]}})
    return api


class NamesCacheTests(unittest.TestCase):
    def test_second_process_reads_the_disk_copy(self):
        api = seeded()
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "names.json"
            Names(api, f).items(HAB)
            before = api.queries
            again = Names(api, f).items(HAB)                  # a new process: no query needed
            self.assertEqual(api.queries, before)
            self.assertEqual([i.title for i in again.values()], ["Learn Mandarin"])

    def test_stale_read_is_instant_and_refreshes_behind(self):
        api = seeded()
        n = Names(api)
        n.items(HAB)
        n._by_source[HAB.data_source_id] = (time.time() - N.TTL_SECONDS - 5, n._by_source[HAB.data_source_id][1])
        api.create_page(HABITS, {"Name": {"title": [{"text": {"content": "New one"}}]}})
        self.assertEqual(len(n.items(HAB)), 1)               # old list at once
        time.sleep(0.3)
        self.assertEqual(len(n.items(HAB)), 2)               # refreshed in the background

    def test_a_write_never_uses_a_stale_list(self):
        api = seeded()
        n = Names(api)
        n.items(HAB)
        n._by_source[HAB.data_source_id] = (time.time() - 60, n._by_source[HAB.data_source_id][1])
        api.create_page(HABITS, {"Name": {"title": [{"text": {"content": "New one"}}]}})
        self.assertEqual(len(n.items(HAB, fresh=True)), 2)


if __name__ == "__main__":
    unittest.main()
