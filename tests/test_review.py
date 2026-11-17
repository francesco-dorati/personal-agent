"""Offline tests for the weekly review (review.py) and log_conversation (domain.py).

    uv run python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

import test_proposals as tp
from personal_agent import domain, review
from personal_agent.query import QueryError
from personal_agent.registry import Registry
from test_proposals import COMS, GOALS, HABITS, LOGS, PEOPLE, QUEUE, CHECKIN, FakeWS, database, prop

AREAS, QUESTIONS, OPPS, CONVS = ("b" * 32, "c" * 32, "d" * 32, "e" * 32)
TODAY = "2026-11-02"                                  # a Monday

EXTRA = [
    database("Areas", ["Content"], AREAS, [
        prop("Name", "title"), prop("ID", "unique_id", prefix="AREA"),
        prop("Status", "select", ["ACTIVE", "PAUSED", "CLOSED"]), prop("Last Reviewed", "date"),
        prop("Review Period", "select", ["WEEKLY", "BI-WEEKLY", "MONTHLY"])]),
    database("Open Questions", ["Content"], QUESTIONS, [
        prop("Name", "title"), prop("ID", "unique_id", prefix="Q"), prop("Decide By", "date"),
        prop("Status", "select", ["OPEN", "LEANING", "RESOLVED", "PARKED"]), prop("Current Leaning", "rich_text")]),
    database("Opportunities", ["Content", "Collections"], OPPS, [
        prop("Name", "title"), prop("ID", "unique_id", prefix="OPP"), prop("Deadline", "date"),
        prop("Status", "status", ["WATCHIN", "APPLIED", "REJECTED"])]),
    database("Conversations", ["Content", "Records"], CONVS, [
        prop("Name", "title"), prop("ID", "unique_id", prefix="CONV"), prop("Date", "date"),
        prop("Summary", "rich_text"), prop("Conclusions", "rich_text"),
        prop("Outcome", "select", ["CHANGED", "NO-CHANGE", "OPEN"]), prop("Link", "url"),
        prop("Source", "select", ["ME", "ASSISTANT", "IMPORT"]),
        prop("Areas", "relation", relation_to=AREAS), prop("Open Questions", "relation", relation_to=QUESTIONS),
        prop("People", "relation", relation_to=PEOPLE), prop("Commitments", "relation", relation_to=COMS)]),
]
# Goals and People get the review's columns too.
GOALS_DB = database("Goals", ["Content"], GOALS, [
    prop("Name", "title"), prop("ID", "unique_id", prefix="GOAL"),
    prop("Status", "select", ["ACTIVE", "ACHIEVED", "ABANDONED"]), prop("Target Date", "date"),
    prop("Progress", "select", ["ON-TRACK", "AT-RISK", "OFF-TRACK"]), prop("Last Reviewed", "date"),
    prop("Review Frequency", "select", ["weekly", "monthly"])])
PEOPLE_DB = database("People", ["Content", "Collections"], PEOPLE, [
    prop("Name", "title"), prop("ID", "unique_id", prefix="PER"), prop("Last Contact", "formula"),
    prop("Relationship", "select", ["Peer", "Mentor"])])
REGISTRY = Registry("root", "Test", 9e12, [], [
    *(d for d in tp.REGISTRY.databases if d.name not in ("Goals", "People")), GOALS_DB, PEOPLE_DB, *EXTRA])
TYPES = {d.data_source_id: {p.name: p.type for p in d.properties} for d in REGISTRY.databases}
PREFIX = {d.data_source_id: {p.name: p.prefix for p in d.properties if p.type == "unique_id"} for d in REGISTRY.databases}


class ReviewWS(FakeWS):
    def registry(self, refresh=False):
        return REGISTRY


class Base(unittest.TestCase):
    def setUp(self):
        patches = [mock.patch.dict(tp.TYPES, TYPES, clear=True), mock.patch.dict(tp.PREFIX, PREFIX, clear=True),
                   mock.patch("personal_agent.habits._day", lambda ws, text: __import__("datetime").date.fromisoformat(
                       TODAY if text in ("today", "now", "") else text[:10]))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.ws = ReviewWS()


class ReviewTests(Base):
    def test_everything_that_needs_attention_shows_up(self):
        s = self.ws.seed
        s(COMS, Name="Send the draft", Status="OPEN", Due={"start": "2026-10-30"})
        s(COMS, Name="Book the exam", Status="OPEN", Due={"start": "2026-11-05"})
        s(COMS, Name="Get reply from HR", Status="WAITING")
        s(COMS, Name="Old thing", Status="DONE", Due={"start": "2026-10-01"})
        s(QUESTIONS, Name="Stay in Germany?", Status="LEANING", **{"Decide By": {"start": "2026-10-31"},
                                                                   "Current Leaning": "yes"})
        s(QUESTIONS, Name="Parked one", Status="PARKED", **{"Decide By": {"start": "2026-10-01"}})
        s(GOALS, Name="Paper", Status="ACTIVE", Progress="AT-RISK", **{"Target Date": {"start": "2026-10-15"}})
        s(GOALS, Name="Fine goal", Status="ACTIVE", **{"Last Reviewed": {"start": "2026-11-01"},
                                                       "Review Frequency": "monthly"})
        s(AREAS, Name="Health", Status="ACTIVE", **{"Last Reviewed": {"start": "2026-10-01"}, "Review Period": "WEEKLY"})
        s(AREAS, Name="Paused area", Status="PAUSED")
        s(OPPS, Name="RA post", Status="WATCHIN", Deadline={"start": "2026-11-06"})
        s(PEOPLE, Name="Old friend", Relationship="Peer",
          **{"Last Contact": {"type": "date", "date": {"start": "2026-07-01"}}})
        s(PEOPLE, Name="Recent", **{"Last Contact": {"type": "date", "date": {"start": "2026-10-30"}}})
        s(CONVS, Name="Low energy", Outcome="OPEN", Date={"start": "2026-10-31"})
        s(CHECKIN, Name="2026-11-01", Date={"start": "2026-11-01"}, **{"Morning Energy": 40, "Sleep hours": 6})
        s(CHECKIN, Name="2026-10-24", Date={"start": "2026-10-24"}, **{"Morning Energy": 70, "Sleep hours": 7.5})
        out = review.review(self.ws, TODAY)
        for text in ("Send the draft · due 2026-10-30 (3d late)", "Book the exam", "Get reply from HR · waiting",
                     "Stay in Germany? · decide by 2026-10-31 (2d past) · leaning: yes",
                     "Paper · target 2026-10-15 passed · AT-RISK · never reviewed",
                     "Health · last reviewed 2026-10-01 (32d ago, every 7d)", "RA post · deadline Fri 06 Nov",
                     "Old friend (Peer) · last contact 2026-07-01", "Low energy · 2026-10-31",
                     "logged 1/7 days (previous week 1/7)", "morning energy: 40 (-30)  vs 70"):
            self.assertIn(text, out)
        for text in ("Old thing", "Parked one", "Fine goal", "Paused area", "Recent"):
            self.assertNotIn(text, out)

    def test_sections_filter_and_unknown_section(self):
        self.ws.seed(COMS, Name="Send the draft", Status="OPEN", Due={"start": "2026-10-30"})
        out = review.review(self.ws, TODAY, sections=["commitments"])
        self.assertIn("Send the draft", out)
        self.assertNotIn("Check-ins", out)
        with self.assertRaises(QueryError):
            review.review(self.ws, TODAY, sections=["nope"])

    def test_lapsed_habits_are_included(self):
        gym = self.ws.seed(HABITS, Name="Exercise", Status="ACTIVE", Target=3, Measure="CHECK",
                           **{"Target per": "WEEK", "Type": "POSITIVE"})
        self.ws.seed(LOGS, Name="x", Habit=[{"id": gym}], Date={"start": "2026-09-20"}, Value=1)
        out = review.review(self.ws, TODAY, sections=["habits"])
        self.assertIn("Habits lapsed or slipping", out)
        self.assertIn("Exercise", out)

    def test_pending_proposals_are_counted(self):
        domain.add_commitment(self.ws, "Call the bank", source="me")
        self.assertIn("Proposals waiting for approval: 1", review.review(self.ws, TODAY, sections=["queue"]))


class ConversationTests(Base):
    def payloads(self):
        return [json.loads(p["properties"]["Payload"]["rich_text"][0]["plain_text"]) for p in self.ws.pages_of(QUEUE)]

    def test_record_with_follow_up_links_both(self):
        self.ws.seed(AREAS, Name="Health", Status="ACTIVE")
        out = domain.log_conversation(self.ws, "Low energy lately", "Explored sleep and workload.", date=TODAY,
                                      outcome="open", areas="Health",
                                      follow_ups=[{"name": "Book a blood test", "due": "2026-11-10"}])
        self.assertIn("Proposed 2 change(s)", out)
        commitment, conv = self.payloads()
        self.assertEqual(commitment["props"]["Name"], "Book a blood test")
        self.assertEqual(conv["props"]["Commitments"], ["$ref:1"])
        self.assertEqual(conv["props"]["Outcome"], "OPEN")
        self.assertEqual(conv["props"]["Source"], "ASSISTANT")
        self.assertEqual(self.ws.pages_of(CONVS), [])          # only proposed

    def test_needs_summary_and_valid_outcome(self):
        with self.assertRaises(QueryError):
            domain.log_conversation(self.ws, "x", "  ", dry_run=True)
        with self.assertRaises(QueryError):
            domain.log_conversation(self.ws, "x", "y", outcome="MAYBE", dry_run=True)


if __name__ == "__main__":
    unittest.main()
