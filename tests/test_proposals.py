"""Offline tests for the write path (proposals.py), against a fake in-memory Notion.

    uv run python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import re
import types
import unittest
import uuid
from unittest import mock

from personal_agent import proposals
from personal_agent.names import Names
from personal_agent.notion_api import NotionError
from personal_agent.query import QueryError
from personal_agent.registry import Database, Option, Property, Registry

QUEUE, HABITS, LOGS, CHECKIN, GOALS, PREFS, PEOPLE, ORGS, INTS, COMS = (c * 32 for c in "123456789a")


def prop(name, kind, options=(), relation_to="", prefix=""):
    return Property(name, kind, "", [Option(o) for o in options], relation_to, prefix)


def database(name, path, ds, props):
    return Database(name=name, path=path, database_id=ds, data_source_id=ds, properties=props)


def text_props(*names):
    return [prop(n, "rich_text") for n in names]


REGISTRY = Registry("root", "Test", 9e12, [], [
    database("Assistant Queue", ["Content", "Records"], QUEUE, [
        prop("Name", "title"), prop("ID", "unique_id"),
        prop("Status", "status", proposals.STATUSES), prop("Operation", "select", proposals.OPERATIONS),
        *text_props("Target Database ID", "Target Item ID", "Payload", "Before", "Preview",
                    "Reason / Evidence", "Proposed By", "Batch ID")]),
    database("Habits", ["Content", "Collections"], HABITS, [
        prop("Name", "title"), prop("ID", "unique_id", prefix="HAB"), prop("Target", "number"),
        prop("Status", "select", ["ACTIVE", "PAUSED", "ARCHIVED"]), prop("Type", "select", ["POSITIVE", "NEGATIVE"]),
        prop("Measure", "select", ["CHECK", "COUNT"]), prop("Last Reviewed", "date"), prop("Started", "date"), prop("Target per", "select", ["DAY", "WEEK"])]),
    database("Habits Log", ["Content", "Records"], LOGS, [
        prop("Name", "title"), prop("ID", "unique_id", prefix="HLOG"), prop("Date", "date"),
        prop("Habit", "relation", relation_to=HABITS), prop("Value", "number"), prop("Notes", "rich_text"),
        prop("Source", "select", ["me", "assistant", "import"])]),
    database("Daily Check-In", ["Content", "Records"], CHECKIN, [
        prop("Name", "title"), prop("Date", "date"), prop("Sleep hours", "number"),
        prop("Morning Energy", "number"), prop("Evening Energy", "number"), prop("Satisfaction", "number"),
        prop("Wake-up time", "number"), prop("Log Complete", "checkbox"), prop("Note", "rich_text")]),
    database("People", ["Content", "Collections"], PEOPLE, [
        prop("Name", "title"), prop("ID", "unique_id", prefix="PER"), prop("Organization", "relation", relation_to=ORGS),
        prop("Title", "rich_text"), prop("Relationship", "select", ["Peer", "Mentor"]),
        prop("Interactions", "relation", relation_to=INTS)]),
    database("Organizations", ["Content", "Collections"], ORGS, [
        prop("Name", "title"), prop("ID", "unique_id", prefix="ORG"),
        prop("Category", "select", ["STARTUP", "COMPANY"])]),
    database("Interactions", ["Content", "Records"], INTS, [
        prop("Name", "title"), prop("ID", "unique_id", prefix="INT"), prop("Date", "date"),
        prop("Type", "select", ["CALL", "MEETING"]), prop("Description", "rich_text"),
        prop("People", "relation", relation_to=PEOPLE)]),
    database("Commitments", ["Content", "Records"], COMS, [
        prop("Name", "title"), prop("ID", "unique_id", prefix="COM"), prop("Due", "date"),
        prop("Status", "status", ["WAITING", "OPEN", "DROPPED", "DONE"]), prop("Importance", "select", ["LOW", "NORMAL", "HIGH"]),
        prop("People", "relation", relation_to=PEOPLE), prop("Origin", "relation", relation_to=INTS),
        prop("Done via", "relation", relation_to=INTS)]),
    database("Goals", ["Content"], GOALS, [
        prop("Name", "title"), prop("ID", "unique_id", prefix="GOAL"),
        prop("Status", "select", ["ACTIVE", "ACHIEVED", "ABANDONED"]), prop("Target Date", "date")]),
    database("Preferences", ["Context"], PREFS, [
        prop("Name", "title"), prop("ID", "unique_id", prefix="PREF"), prop("Status", "select", ["active", "inactive"])]),
])
TYPES = {d.data_source_id: {p.name: p.type for p in d.properties} for d in REGISTRY.databases}
PREFIX = {d.data_source_id: {p.name: p.prefix for p in d.properties if p.type == "unique_id"} for d in REGISTRY.databases}


def to_read(kind, value):
    if kind in ("title", "rich_text"):
        return {"type": kind, kind: [{"plain_text": "".join(c["text"]["content"] for c in value)}]}
    if kind in ("select", "status"):
        return {"type": kind, kind: value}
    if kind == "multi_select":
        return {"type": kind, kind: value}
    return {"type": kind, kind: value}


class FakeAPI:
    def __init__(self):
        self.pages: dict[str, dict] = {}
        self.blocks: dict[str, list[dict]] = {}      # parent id → child blocks, as Notion returns them
        self.counters: dict[str, int] = {}
        self.clock = 0
        self.request_count = 0

    def _stamp(self):
        self.clock += 1
        return f"2026-10-26T20:{self.clock // 60:02d}:{self.clock % 60:02d}.000Z"

    def _store(self, children):
        out = []
        for child in children:
            kind = child["type"]
            data = {k: v for k, v in (child.get(kind) or {}).items() if k != "children"}
            if "rich_text" in data:
                data["rich_text"] = [{**part, "plain_text": part["text"]["content"]} for part in data["rich_text"]]
            read = {"id": uuid.uuid4().hex, "type": kind, kind: data, "has_children": bool((child.get(kind) or {}).get("children"))}
            if read["has_children"]:
                self.blocks[read["id"]] = self._store(child[kind]["children"])
            out.append(read)
        return out

    def block_children(self, block_id):
        return list(self.blocks.get(block_id, []))

    def append_blocks(self, block_id, children):
        self.blocks.setdefault(block_id, []).extend(self._store(children))

    def create_page(self, ds, properties, children=None):
        pid = uuid.uuid4().hex
        self.counters[ds] = self.counters.get(ds, 0) + 1
        page = {"id": pid, "parent": {"data_source_id": ds}, "properties": {}, "created_time": self._stamp(),
                "last_edited_time": self._stamp()}
        for name, kind in TYPES[ds].items():
            if kind == "unique_id":
                page["properties"][name] = {"type": "unique_id", "unique_id": {"prefix": PREFIX[ds][name] or None,
                                                                              "number": self.counters[ds]}}
            else:
                page["properties"][name] = to_read(kind, None if kind not in ("title", "rich_text") else [])
                if kind in ("title", "rich_text"):
                    page["properties"][name] = {"type": kind, kind: []}
        self.pages[pid] = page
        self.update_page(pid, properties)
        if children:
            self.blocks[pid] = self._store(children)
        return self.pages[pid]

    def update_page(self, pid, properties):
        page = self.pages[pid]
        ds = page["parent"]["data_source_id"]
        for name, value in properties.items():
            kind = TYPES[ds][name]
            if kind in ("title", "rich_text"):
                page["properties"][name] = {"type": kind, kind: [{"plain_text": "".join(c["text"]["content"] for c in value[kind])}]}
            else:
                page["properties"][name] = {"type": kind, kind: value[kind]}
        page["last_edited_time"] = self._stamp()
        return page

    def page(self, pid):
        if pid not in self.pages:
            raise NotionError(404, "object_not_found", "no such page", pid)
        return self.pages[pid]

    @staticmethod
    def _match(page, flt):
        if not flt:
            return True
        if "and" in flt:
            return all(FakeAPI._match(page, f) for f in flt["and"])
        if "or" in flt:
            return any(FakeAPI._match(page, f) for f in flt["or"])
        value = page["properties"].get(flt["property"])
        if "status" in flt:
            return (value["status"] or {}).get("name") == flt["status"]["equals"]
        if "rich_text" in flt:
            return "".join(t["plain_text"] for t in value["rich_text"]) == flt["rich_text"]["equals"]
        if "unique_id" in flt:
            return value["unique_id"]["number"] == flt["unique_id"]["equals"]
        if "relation" in flt:
            return flt["relation"]["contains"] in [r["id"] for r in value["relation"] or []]
        if "date" in flt:
            start = ((value["date"] or {}).get("start") or "")[:10]
            cond = flt["date"]
            return bool(start) and start >= cond.get("on_or_after", "") and start <= cond.get("on_or_before", "9999")
        return True

    def query(self, ds, *, filter=None, sorts=None, limit=None):
        rows = [p for p in self.pages.values() if p["parent"]["data_source_id"] == ds and self._match(p, filter)]
        rows.sort(key=lambda p: p["created_time"])
        return rows[:limit] if limit else rows


class FakeWS:
    def __init__(self):
        self.settings = types.SimpleNamespace(timezone="Europe/Berlin")
        self.api = FakeAPI()
        self.names = Names(self.api)

    def registry(self, refresh=False):
        return REGISTRY

    def seed(self, ds, **props):
        wire = {}
        for name, value in props.items():
            kind = TYPES[ds][name]
            if kind == "title":
                wire[name] = {"title": [{"text": {"content": value}}]}
            elif kind == "rich_text":
                wire[name] = {"rich_text": [{"text": {"content": value}}]}
            elif kind in ("select", "status"):
                wire[name] = {kind: {"name": value}}
            else:
                wire[name] = {kind: value}
        page = self.api.create_page(ds, wire)
        self.names._by_source.clear()
        return page["id"]

    def pages_of(self, ds):
        return self.api.query(ds)


def numbers(text):
    return [int(n) for n in re.findall(r"^#(\d+) ·", text, re.M)]


def log_change(**props):
    return {"operation": "CREATE", "database": "Habits Log", "properties": {"Habit": "Learn Mandarin", **props}}


class WriteTests(unittest.TestCase):
    def setUp(self):
        self.ws = FakeWS()
        self.mandarin = self.ws.seed(HABITS, Name="Learn Mandarin", Status="ACTIVE", Target=7)
        self.ws.seed(HABITS, Name="Read papers", Status="ACTIVE", Target=2)
        self.goal = self.ws.seed(GOALS, Name="HSK in April", Status="ACTIVE", **{"Target Date": {"start": "2027-04-01"}})
        self.pref = self.ws.seed(PREFS, Name="Big cities", Status="active")
        self.pref2 = self.ws.seed(PREFS, Name="Warm weather", Status="active")

    def propose(self, changes, **kw):
        return proposals.propose(self.ws, changes, kw.pop("reason", "user said so"), **kw)

    def queue_rows(self):
        return self.ws.pages_of(QUEUE)

    # -- proposing ------------------------------------------------------------------
    def test_dry_run_writes_nothing_and_names_the_log_after_the_habit(self):
        out = self.propose([log_change(Date="2026-10-26 21:34", Value=1)], dry_run=True)
        self.assertIn("DRY RUN", out)
        self.assertIn("Habits Log · Learn Mandarin", out)
        self.assertIn("Date: 2026-10-26 21:34", out)
        self.assertEqual(self.queue_rows(), [])

    def test_propose_only_touches_the_queue(self):
        out = self.propose([log_change(Date="today", Value=1)])
        self.assertEqual(len(self.queue_rows()), 1)
        self.assertEqual(self.ws.pages_of(LOGS), [])
        row = proposals._read_row(self.queue_rows()[0])
        self.assertEqual((row["status"], row["op"], row["by"]), ("PENDING", "CREATE", "claude"))
        self.assertEqual(row["payload"]["props"]["Source"], "assistant")
        self.assertIn("Nothing in your data has changed", out)

    def test_invalid_change_in_a_batch_writes_nothing(self):
        with self.assertRaisesRegex(QueryError, "Change 2"):
            self.propose([log_change(), {"operation": "CREATE", "database": "Habits Log", "properties": {"Nope": 1}}])
        self.assertEqual(self.queue_rows(), [])

    def test_unknown_option_lists_the_real_ones_and_creates_none(self):
        with self.assertRaisesRegex(QueryError, "Options: ACTIVE, PAUSED, ARCHIVED"):
            self.propose([{"operation": "UPDATE", "database": "Habits", "item": "HAB-1", "properties": {"Status": "Busy"}}])

    def test_no_delete_and_no_queue_edits(self):
        with self.assertRaisesRegex(QueryError, "no delete"):
            self.propose([{"operation": "DELETE", "database": "Habits", "item": "HAB-1"}])
        with self.assertRaisesRegex(QueryError, "cannot be changed"):
            self.propose([{"operation": "CREATE", "database": "Assistant Queue", "properties": {"Name": "x"}}])

    def test_times_are_stored_in_the_users_time_zone_with_their_offset(self):
        self.propose([log_change(Date="2026-10-26 21:34"), log_change(Date="2026-07-01 08:00")])
        starts = sorted(proposals._read_row(r)["payload"]["props"]["Date"]["start"] for r in self.queue_rows())
        self.assertEqual(starts, ["2026-07-01T08:00+02:00", "2026-10-26T21:34+01:00"])   # summer and winter time

    def test_reason_is_required(self):
        with self.assertRaisesRegex(QueryError, "reason"):
            proposals.propose(self.ws, [log_change()], " ")

    def test_duplicate_title_in_a_collection_is_blocked_unless_allowed(self):
        change = {"operation": "CREATE", "database": "Habits", "properties": {"Name": "learn mandarin"}}
        with self.assertRaisesRegex(QueryError, "already has"):
            self.propose([change])
        self.propose([{**change, "allow_duplicate": True}], dry_run=True)

    def test_one_check_in_per_day(self):
        self.ws.seed(CHECKIN, Name="2026-10-26", Date={"start": "2026-10-26"})
        with self.assertRaisesRegex(QueryError, "already has a row for 2026-10-26"):
            self.propose([{"operation": "CREATE", "database": "Daily Check-In",
                           "properties": {"Name": "x", "Date": "2026-10-26", "Sleep hours": 7}}])

    def test_a_check_in_is_named_after_its_day(self):
        out = self.propose([{"operation": "CREATE", "database": "Daily Check-In",
                             "properties": {"Date": "2026-10-27", "Sleep hours": 7.5}}], dry_run=True)
        self.assertIn("Daily Check-In · 2026-10-27", out)

    def test_double_logging_a_habit_is_a_warning_not_an_error(self):
        self.ws.seed(LOGS, Name="Learn Mandarin", Date={"start": "2026-10-26"}, Habit=[{"id": self.mandarin}])
        out = self.propose([log_change(Date="2026-10-26")], dry_run=True)
        self.assertIn("already logged on 2026-10-26", out)

    # -- approving and applying -----------------------------------------------------------
    def test_apply_does_nothing_until_approved(self):
        (n,) = numbers(self.propose([log_change(Date="today")]))
        out = proposals.apply(self.ws, ids=[n])
        self.assertIn("Nothing approved", out)
        self.assertEqual(self.ws.pages_of(LOGS), [])

    def test_approve_then_apply_creates_the_item_and_marks_the_row(self):
        (n,) = numbers(self.propose([log_change(Date="2026-10-26", Value=1, Notes="app lesson")]))
        proposals.approve(self.ws, ids=[n], approved_by="yes, log it")
        out = proposals.apply(self.ws)                          # no ids: everything approved
        self.assertIn("applied", out)
        (log,) = self.ws.pages_of(LOGS)
        self.assertEqual(log["properties"]["Name"]["title"][0]["plain_text"], "Learn Mandarin")
        self.assertEqual(log["properties"]["Habit"]["relation"], [{"id": self.mandarin}])
        row = proposals._read_row(self.queue_rows()[0])
        self.assertEqual(row["status"], "APPLIED")
        self.assertIn("HLOG-1", row["item"])
        self.assertIn("approved in conversation: yes, log it", row["reason"])
        self.assertIn("Nothing approved", proposals.apply(self.ws, ids=[n]))   # applying twice does nothing

    def test_approve_needs_the_users_words(self):
        (n,) = numbers(self.propose([log_change()]))
        with self.assertRaisesRegex(QueryError, "approved_by"):
            proposals.approve(self.ws, ids=[n], approved_by="")

    def test_rejected_rows_are_never_applied(self):
        (n,) = numbers(self.propose([log_change()]))
        proposals.reject(self.ws, ids=[n], reason="not today")
        proposals.apply(self.ws, ids=[n])
        self.assertEqual(self.ws.pages_of(LOGS), [])

    def test_update_applies_and_revert_proposes_the_inverse(self):
        (n,) = numbers(self.propose([{"operation": "UPDATE", "database": "Habits", "item": "HAB-1",
                                      "properties": {"Target": 5}}]))
        proposals.approve(self.ws, ids=[n], approved_by="yes, ok")
        proposals.apply(self.ws, ids=[n])
        self.assertEqual(self.ws.api.pages[self.mandarin]["properties"]["Target"]["number"], 5)
        out = proposals.revert(self.ws, n)
        self.assertIn("Target: 5 → 7", out)
        (m,) = numbers(out)
        proposals.approve(self.ws, ids=[m], approved_by="undo")
        proposals.apply(self.ws, ids=[m])
        self.assertEqual(self.ws.api.pages[self.mandarin]["properties"]["Target"]["number"], 7)

    def test_update_fails_if_the_value_changed_after_the_proposal(self):
        (n,) = numbers(self.propose([{"operation": "UPDATE", "database": "Habits", "item": "HAB-1",
                                      "properties": {"Target": 5}}]))
        proposals.approve(self.ws, ids=[n], approved_by="yes, ok")
        self.ws.api.update_page(self.mandarin, {"Target": {"number": 9}})       # the user edits it meanwhile
        out = proposals.apply(self.ws, ids=[n])
        self.assertIn("changed since the proposal", out)
        self.assertEqual(self.ws.api.pages[self.mandarin]["properties"]["Target"]["number"], 9)
        self.assertEqual(proposals._read_row(self.queue_rows()[0])["status"], "FAILED")

    def test_unrelated_edits_do_not_block_an_update(self):
        (n,) = numbers(self.propose([{"operation": "UPDATE", "database": "Habits", "item": "HAB-1",
                                      "properties": {"Target": 5}}]))
        proposals.approve(self.ws, ids=[n], approved_by="yes, ok")
        self.ws.api.update_page(self.mandarin, {"Type": {"select": {"name": "POSITIVE"}}})
        self.assertIn("applied", proposals.apply(self.ws, ids=[n]))

    def test_new_items_can_be_referenced_inside_a_batch(self):
        out = self.propose([
            {"operation": "CREATE", "database": "Habits", "properties": {"Name": "Stretch", "Status": "ACTIVE"}},
            {"operation": "CREATE", "database": "Habits Log",
             "properties": {"Name": "Stretch, first time", "Habit": "$1", "Date": "2026-10-26"}}])
        first, second = numbers(out)
        proposals.approve(self.ws, ids=[first, second], approved_by="yes, ok")
        proposals.apply(self.ws, ids=[first, second])
        (stretch,) = [p for p in self.ws.pages_of(HABITS) if p["properties"]["Name"]["title"][0]["plain_text"] == "Stretch"]
        (log,) = self.ws.pages_of(LOGS)
        self.assertEqual(log["properties"]["Habit"]["relation"], [{"id": stretch["id"]}])

    def test_a_change_that_depends_on_an_unapplied_one_fails_cleanly(self):
        out = self.propose([
            {"operation": "CREATE", "database": "Habits", "properties": {"Name": "Stretch"}},
            {"operation": "CREATE", "database": "Habits Log", "properties": {"Name": "x", "Habit": "$1", "Date": "today"}}])
        _, second = numbers(out)
        proposals.approve(self.ws, ids=[second], approved_by="yes, ok")
        self.assertIn("depends on change 1", proposals.apply(self.ws, ids=[second]))
        self.assertEqual(self.ws.pages_of(LOGS), [])

    def test_set_inactive_uses_the_databases_own_word(self):
        out = self.propose([{"operation": "SET-INACTIVE", "database": "Habits", "item": "Read papers"}], dry_run=True)
        self.assertIn("Status: ACTIVE → ARCHIVED", out)

    # -- guardrails --------------------------------------------------------------------------
    def test_closing_a_goal_needs_explicit_confirmation(self):
        (n,) = numbers(self.propose([{"operation": "UPDATE", "database": "Goals", "item": "GOAL-1",
                                      "properties": {"Status": "ACHIEVED"}}]))
        self.assertIn("NOT approved", proposals.approve(self.ws, ids=[n], approved_by="maybe"))
        self.assertEqual(proposals._read_row(self.queue_rows()[0])["status"], "PENDING")
        self.assertIn("approved", proposals.approve(self.ws, ids=[n], approved_by="yes, I got HSK 3", confirmed=True))
        self.assertEqual(proposals._read_row(self.queue_rows()[0])["status"], "APPROVED")

    def test_moving_a_goals_target_date_is_guarded_too(self):
        out = self.propose([{"operation": "UPDATE", "database": "Goals", "item": "GOAL-1",
                             "properties": {"Target Date": "2027-05-01"}}], dry_run=True)
        self.assertIn("needs the user's explicit confirmation", out)

    def test_context_changes_go_one_at_a_time(self):
        out = self.propose([{"operation": "SET-INACTIVE", "database": "Preferences", "item": "PREF-1"},
                            {"operation": "SET-INACTIVE", "database": "Preferences", "item": "PREF-2"}])
        a, b = numbers(out)
        with self.assertRaisesRegex(QueryError, "one at a time"):
            proposals.approve(self.ws, ids=[a, b], approved_by="yes, ok")
        proposals.approve(self.ws, ids=[a], approved_by="yes, ok")
        proposals.approve(self.ws, ids=[b], approved_by="yes, ok")
        bulk = proposals.apply(self.ws)                          # a bulk apply leaves context rows alone
        self.assertIn("left approved", bulk)
        with self.assertRaisesRegex(QueryError, "one at a time"):
            proposals.apply(self.ws, ids=[a, b])
        self.assertIn("applied", proposals.apply(self.ws, ids=[a]))
        self.assertEqual(self.ws.api.pages[self.pref]["properties"]["Status"]["select"]["name"], "inactive")
        self.assertEqual(self.ws.api.pages[self.pref2]["properties"]["Status"]["select"]["name"], "active")

    def test_a_worker_may_propose_but_never_approve_or_apply(self):
        with mock.patch.dict(os.environ, {"AGENT_MODE": "worker"}):
            out = self.propose([log_change(Date="today")])
            (n,) = numbers(out)
            self.assertEqual(proposals._read_row(self.queue_rows()[0])["by"], "worker")
            with self.assertRaisesRegex(QueryError, "worker mode"):
                proposals.approve(self.ws, ids=[n], approved_by="yes, ok")
            with self.assertRaisesRegex(QueryError, "worker mode"):
                proposals.apply(self.ws)

    def test_queue_lists_pending_with_previews(self):
        self.propose([log_change(Date="2026-10-26")])
        out = proposals.queue(self.ws)
        self.assertIn("PENDING", out)
        self.assertIn("Habit: Learn Mandarin", out)
        self.assertEqual(proposals.queue(self.ws, status="APPLIED"), "Assistant Queue: nothing APPLIED.")


if __name__ == "__main__":
    unittest.main()
