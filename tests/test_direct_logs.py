"""Offline tests for direct logs (proposals.record): habit logs and check-ins skip approval.

    uv run python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from personal_agent import habits, proposals
from personal_agent.values import decode

from test_proposals import CHECKIN, HABITS, LOGS, QUEUE, FakeWS

TODAY = "2026-10-28"


def statuses(ws):
    return [decode(p["properties"]["Status"]) for p in ws.pages_of(QUEUE)]


class DirectLogTests(unittest.TestCase):
    def setUp(self):
        self.ws = FakeWS()
        self.ws.seed(HABITS, Name="Learn Mandarin", Status="ACTIVE", Target=1, Measure="CHECK",
                     **{"Target per": "DAY", "Type": "POSITIVE"})

    def test_user_reported_habit_is_written_at_once(self):
        out = habits.log_habit(self.ws, "Learn Mandarin", date=TODAY)
        self.assertIn("Written directly", out)
        self.assertEqual(len(self.ws.pages_of(LOGS)), 1)
        self.assertEqual(statuses(self.ws), ["APPLIED"])

    def test_inferred_habit_waits_for_approval(self):
        out = habits.log_habit(self.ws, "Learn Mandarin", date=TODAY, source="assistant")
        self.assertIn("Proposed for approval", out)
        self.assertEqual(self.ws.pages_of(LOGS), [])
        self.assertEqual(statuses(self.ws), ["PENDING"])

    def test_worker_mode_only_proposes(self):
        with mock.patch.dict(os.environ, {"AGENT_MODE": "worker"}):
            out = habits.log_habit(self.ws, "Learn Mandarin", date=TODAY)
        self.assertIn("worker mode", out)
        self.assertEqual(self.ws.pages_of(LOGS), [])

    def test_switch_off_with_env(self):
        with mock.patch.dict(os.environ, {"AGENT_DIRECT_LOGS": "0"}):
            habits.log_checkin(self.ws, date=TODAY, morning_energy=40)
        self.assertEqual(self.ws.pages_of(CHECKIN), [])
        self.assertEqual(statuses(self.ws), ["PENDING"])

    def test_checkin_created_then_updated_directly(self):
        habits.log_checkin(self.ws, date=TODAY, sleep_hours=6, morning_energy=40)
        out = habits.log_checkin(self.ws, date=TODAY, evening_energy=30)
        rows = self.ws.pages_of(CHECKIN)
        self.assertEqual(len(rows), 1)
        self.assertEqual(decode(rows[0]["properties"]["Evening Energy"]), 30)
        self.assertEqual(decode(rows[0]["properties"]["Morning Energy"]), 40)
        self.assertIn("revert", out)
        self.assertEqual(statuses(self.ws), ["APPLIED", "APPLIED"])

    def test_dry_run_says_direct_and_writes_nothing(self):
        out = habits.log_habit(self.ws, "Learn Mandarin", date=TODAY, dry_run=True)
        self.assertIn("written directly", out)
        self.assertEqual(self.ws.pages_of(QUEUE), [])

    def test_other_databases_never_go_direct(self):
        out = proposals.record(self.ws, [{"operation": "CREATE", "database": "Habits",
                                          "properties": {"Name": "Run", "Status": "ACTIVE"}}], "test")
        self.assertIn("always needs approval", out)
        self.assertEqual(statuses(self.ws), ["PENDING"])


if __name__ == "__main__":
    unittest.main()
