"""Offline tests for domain.py (the thin wrappers over propose)."""
from __future__ import annotations

import json
import unittest

from personal_agent import domain, habits
from personal_agent.query import QueryError

from test_proposals import COMS, HABITS, INTS, LOGS, ORGS, PEOPLE, QUEUE, FakeWS


def queued(ws):
    return [json.loads(p["properties"]["Payload"]["rich_text"][0]["plain_text"]) for p in ws.pages_of(QUEUE)]


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.ws = FakeWS()
        self.anna = self.ws.seed(PEOPLE, Name="Anna Rossi")
        self.org = self.ws.seed(ORGS, Name="Bosch", Category="COMPANY")
        self.ws.seed(COMS, Name="Send the draft", Status="OPEN")
        self.ws.seed(INTS, Name="Kickoff call", Type="CALL")
        self.check = self.ws.seed(HABITS, Name="Learn Mandarin", Status="ACTIVE", Measure="CHECK")
        self.count = self.ws.seed(HABITS, Name="Read papers", Status="ACTIVE", Measure="COUNT")

    def test_interaction_with_commitments_is_one_linked_batch(self):
        out = domain.log_interaction(self.ws, "Call with Anna", date="2026-10-26", type="CALL", people="Anna Rossi",
                                     commitments=[{"name": "Email the slides", "due": "2026-10-30"}])
        rows = queued(self.ws)
        self.assertEqual(len(rows), 2)
        self.assertIn("Origin", out)
        self.assertIn("Anna Rossi", out)

    def test_commitment_unknown_field_and_missing_name(self):
        with self.assertRaises(QueryError):
            domain.log_interaction(self.ws, "x", commitments=[{"name": "a", "colour": "red"}], dry_run=True)
        with self.assertRaises(QueryError):
            domain.log_interaction(self.ws, "x", commitments=[{"due": "2026-10-30"}], dry_run=True)

    def test_add_commitment_defaults_open_and_links_origin(self):
        out = domain.add_commitment(self.ws, "Review the draft", due="2026-10-31", origin="INT-1", dry_run=True)
        self.assertIn("OPEN", out)
        self.assertIn("Origin", out)

    def test_complete_commitment(self):
        out = domain.complete_commitment(self.ws, "Send the draft", done_via="Kickoff call", dry_run=True)
        self.assertIn("DONE", out)
        self.assertIn("Done via", out)
        with self.assertRaises(QueryError):
            domain.complete_commitment(self.ws, "Send the draft", status="MAYBE", dry_run=True)

    def test_update_item_reviewed_sets_today(self):
        out = domain.update_item(self.ws, "Habits", "Learn Mandarin", reviewed=True, dry_run=True)
        self.assertIn("Last Reviewed", out)
        with self.assertRaises(QueryError):
            domain.update_item(self.ws, "Habits", "Learn Mandarin", dry_run=True)
        with self.assertRaises(QueryError):
            domain.update_item(self.ws, "Organizations", "Bosch", reviewed=True, dry_run=True)

    def test_set_inactive(self):
        out = domain.set_inactive(self.ws, "Habits", "Learn Mandarin", dry_run=True)
        self.assertIn("ARCHIVED", out)

    def test_add_person_blocks_lookalikes(self):
        for name in ("Anna Rossi", "anna rossi", "Anna Rosi", "Anna"):
            with self.assertRaises(QueryError, msg=name):
                domain.add_person(self.ws, name, dry_run=True)
        out = domain.add_person(self.ws, "Marco Bianchi", organization="Bosch", title="Lead", dry_run=True)
        self.assertIn("Marco Bianchi", out)
        domain.add_person(self.ws, "Anna Rosso", allow_duplicate=True, dry_run=True)

    def test_add_organization(self):
        with self.assertRaises(QueryError):
            domain.add_organization(self.ws, "Bosch", dry_run=True)
        out = domain.add_organization(self.ws, "ACME Robotics", category="STARTUP", dry_run=True)
        self.assertIn("ACME Robotics", out)

    def test_habit_duplicate_warning_only_for_check(self):
        for hid in (self.check, self.count):
            self.ws.seed(LOGS, Name="x", Habit=[{"id": hid}], Date={"start": "2026-10-26"}, Value=1)
        warn = habits.log_habit(self.ws, "Learn Mandarin", date="2026-10-26", dry_run=True)
        self.assertIn("already logged", warn)
        quiet = habits.log_habit(self.ws, "Read papers", date="2026-10-26", dry_run=True)
        self.assertNotIn("already logged", quiet)


if __name__ == "__main__":
    unittest.main()
