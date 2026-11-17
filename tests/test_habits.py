"""Offline tests for habits.py (log_habit, log_checkin, habits_status).

    uv run python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import unittest

from personal_agent import habits
from personal_agent.query import QueryError

from test_proposals import CHECKIN, HABITS, LOGS, QUEUE, FakeWS

TODAY = "2026-10-28"        # a Wednesday; the rolling week is 10-22 .. 10-28


def payloads(ws):
    return [json.loads(p["properties"]["Payload"]["rich_text"][0]["plain_text"]) for p in ws.pages_of(QUEUE)]


class HabitTests(unittest.TestCase):
    def setUp(self):
        self.ws = FakeWS()
        s = self.ws.seed
        self.mandarin = s(HABITS, Name="Learn Mandarin", Status="ACTIVE", Target=1, Measure="CHECK",
                          **{"Target per": "DAY", "Type": "POSITIVE"})
        self.papers = s(HABITS, Name="Read papers", Status="ACTIVE", Target=2, Measure="COUNT",
                        **{"Target per": "WEEK", "Type": "POSITIVE"})
        self.alcohol = s(HABITS, Name="Alcohol", Status="ACTIVE", Target=2, Measure="COUNT",
                         **{"Target per": "WEEK", "Type": "NEGATIVE"})
        self.old = s(HABITS, Name="Cold showers", Status="PAUSED", Target=1, Measure="CHECK", **{"Target per": "DAY"})
        self.free = s(HABITS, Name="Meditate", Status="ACTIVE")

    def log(self, habit, day, value=1):
        self.ws.seed(LOGS, Name="x", Habit=[{"id": habit}], Date={"start": day}, Value=value)

    # -- log_habit ------------------------------------------------------------------
    def test_log_habit_dry_run_names_the_habit(self):
        out = habits.log_habit(self.ws, "Learn Mandarin", date="2026-10-28", dry_run=True)
        self.assertIn("DRY RUN", out)
        self.assertIn("Learn Mandarin", out)
        self.assertEqual(payloads(self.ws), [])

    def test_log_habit_batch_creates_one_row_each(self):
        habits.log_habit(self.ws, ["Learn Mandarin", "Read papers"], date="2026-10-28", value=2)
        rows = payloads(self.ws)
        self.assertEqual(len(rows), 2)

    def test_log_habit_warns_when_paused(self):
        out = habits.log_habit(self.ws, "Cold showers", date="2026-10-28", dry_run=True)
        self.assertIn("PAUSED", out)

    def test_log_habit_unknown_habit(self):
        with self.assertRaises(QueryError):
            habits.log_habit(self.ws, "Zzzzzz nothing", dry_run=True)

    # -- log_checkin ----------------------------------------------------------------
    def test_checkin_creates_then_updates(self):
        habits.log_checkin(self.ws, date=TODAY, sleep_hours=7.5, wakeup_time="07:45")
        item = payloads(self.ws)[0]
        self.assertEqual(item["props"]["Wake-up time"], 7.75)
        self.assertEqual(item["props"]["Name"], TODAY)
        self.ws.seed(CHECKIN, Name=TODAY, Date={"start": TODAY})
        out = habits.log_checkin(self.ws, date=TODAY, morning_energy=70, dry_run=True)
        self.assertIn("UPDATE", out.upper())

    def test_checkin_validation(self):
        with self.assertRaises(QueryError):
            habits.log_checkin(self.ws, date=TODAY, morning_energy=120, dry_run=True)
        with self.assertRaises(QueryError):
            habits.log_checkin(self.ws, date=TODAY, sleep_hours=30, dry_run=True)
        with self.assertRaises(QueryError):
            habits.log_checkin(self.ws, date=TODAY, dry_run=True)

    # -- habits_status --------------------------------------------------------------
    def test_status(self):
        for d in ("2026-10-26", "2026-10-27", "2026-10-28"):
            self.log(self.mandarin, d)
        self.log(self.papers, "2026-10-20", 1)
        self.log(self.papers, "2026-10-22", 1)
        self.log(self.papers, "2026-10-27", 1)
        for d in ("2026-10-26", "2026-10-27", "2026-10-28"):
            self.log(self.alcohol, d)
        self.log(self.old, "2026-10-28")
        self.log(self.mandarin, "2026-10-30")             # in the future: ignored
        out = habits.habits_status(self.ws, TODAY)
        self.assertIn("Learn Mandarin: 1/1 today ✓", out)
        self.assertIn("streak 3d", out)
        self.assertIn("Read papers: 2/2 in the last 7 days ✓", out)
        self.assertIn("Alcohol: 3/2 in the last 7 days (limit) · OVER the limit", out)
        self.assertIn("Meditate: no target set", out)
        self.assertNotIn("Cold showers", out)
        self.assertIn("1 paused", out)
        self.assertIn(f"Check-in {TODAY}: not logged yet", out)

    def test_status_week_streak(self):
        self.log(self.papers, "2026-10-20", 1)
        self.log(self.papers, "2026-10-21", 1)
        self.log(self.papers, "2026-10-27", 2)
        out = habits.habits_status(self.ws, TODAY)
        self.assertIn("Read papers: 2/2 in the last 7 days ✓", out)

    def test_a_long_gap_outranks_a_single_miss(self):
        s = self.ws.seed
        gym = s(HABITS, Name="Exercise", Status="ACTIVE", Target=3, Measure="CHECK", **{"Target per": "WEEK", "Type": "POSITIVE"})
        self.log(gym, "2026-09-20")                               # last session 38 days ago, usually every ~2 days
        for d in range(1, 28):                                    # Mandarin nearly every day, misses only today
            self.log(self.mandarin, f"2026-10-{d:02d}") if d != 28 else None
        out = habits.habits_status(self.ws, TODAY)
        lapsed, due = out.index("Lapsed"), out.index("Due:")
        self.assertLess(lapsed, out.index("Exercise"))
        self.assertLess(out.index("Exercise"), due)
        self.assertGreater(out.index("Learn Mandarin"), due)
        self.assertIn("quiet for 38d", out)
        self.assertIn("28d 0%", out.split("Exercise")[1].splitlines()[0])
        self.assertIn("84d", out)

    def test_new_habit_is_not_called_lapsed(self):
        s = self.ws.seed
        s(HABITS, Name="Brand new", Status="ACTIVE", Target=1, Measure="CHECK", Started={"start": "2026-10-27"},
          **{"Target per": "DAY", "Type": "POSITIVE"})
        out = habits.habits_status(self.ws, TODAY)
        self.assertNotIn("Brand new", out.split("Due:")[0])

    def test_status_checkin_present(self):
        self.ws.seed(CHECKIN, Name=TODAY, Date={"start": TODAY}, **{"Log Complete": True})
        out = habits.habits_status(self.ws, TODAY)
        self.assertIn("exists, Log Complete: yes", out)


if __name__ == "__main__":
    unittest.main()
