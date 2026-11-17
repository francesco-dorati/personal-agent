"""Page bodies in proposals, and the user's edits in the queue row (offline, fake in-memory Notion).

    uv run python -m unittest discover -s tests -v
"""
from __future__ import annotations

import unittest
import uuid

from personal_agent import bodies, proposals
from personal_agent.registry import Registry

from test_proposals import (GOALS, HABITS, PREFIX, QUEUE, REGISTRY, TYPES, FakeWS, database, log_change, prop)  # noqa: E402

AREAS, ALOGS = "ab" * 16, "cd" * 16
EXTRA = [
    database("Areas", ["Content"], AREAS, [
        prop("Name", "title"), prop("ID", "unique_id", prefix="AREA"), prop("Summary", "rich_text"),
        prop("Status", "select", ["ACTIVE", "PAUSED", "CLOSED"])]),
    database("Area Logs", ["Content", "Records"], ALOGS, [
        prop("Name", "title"), prop("ID", "unique_id", prefix="ALOG"), prop("Areas", "relation", relation_to=AREAS),
        prop("Period", "date"), prop("Type", "select", ["WEEKLY", "MILESTONE", "EVENT"]), prop("Summary", "rich_text"),
        prop("Skills", "multi_select", ["VLA", "G1"]), prop("Visibility", "select", ["private", "CV-ok", "public"]),
        prop("Source", "select", ["me", "assistant", "import"])]),
]
for d in EXTRA:                                   # the fake API looks column types up by data source id
    TYPES[d.data_source_id] = {p.name: p.type for p in d.properties}
    PREFIX[d.data_source_id] = {p.name: p.prefix for p in d.properties if p.type == "unique_id"}
MY_REGISTRY = Registry("root", "Test", 9e12, [], [*REGISTRY.databases, *EXTRA])   # a copy: other tests keep theirs


class WS(FakeWS):
    def registry(self, refresh=False):
        return MY_REGISTRY


BODY = "## Did\n- Mapped the joint temperature limits\n  - on the **G1** left arm\n\n## Results\nPeak was 71 °C after 40 min."


def para(text):
    return {"id": uuid.uuid4().hex, "type": "paragraph", "has_children": False,
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}, "plain_text": text}]}}


def texts(blocks):
    return ["".join(p["plain_text"] for p in b[b["type"]].get("rich_text", [])) for b in blocks]


class MarkdownTests(unittest.TestCase):
    def test_structure_and_inline_formatting(self):
        blocks = bodies.markdown_to_blocks(
            "# Title\n\nSome **bold** and *italic* and `code` and [a link](https://example.com).\n\n"
            "- one\n  - nested\n- [x] done\n1. first\n\n> quoted\n\n---\n```python\nprint(1)\n```")
        kinds = [b["type"] for b in blocks]
        self.assertEqual(kinds, ["heading_1", "paragraph", "bulleted_list_item", "to_do", "numbered_list_item",
                                 "quote", "divider", "code"])
        para_parts = blocks[1]["paragraph"]["rich_text"]
        self.assertTrue(any(p.get("annotations", {}).get("bold") for p in para_parts))
        self.assertTrue(any(p["text"].get("link") for p in para_parts))
        self.assertEqual(blocks[2]["bulleted_list_item"]["children"][0]["type"], "bulleted_list_item")
        self.assertTrue(blocks[3]["to_do"]["checked"])
        self.assertEqual(blocks[7]["code"]["language"], "python")

    def test_long_text_is_split_below_the_notion_limit(self):
        parts = bodies.rich_text("x" * 5000)
        self.assertTrue(all(len(p["text"]["content"]) <= bodies.TEXT_CHUNK for p in parts))
        self.assertEqual(sum(len(p["text"]["content"]) for p in parts), 5000)

    def test_the_row_page_uses_no_icons_or_callouts_which_notion_may_refuse(self):
        blocks = bodies.row_blocks({"Name": "x"}, bodies.markdown_to_blocks("text"))
        self.assertNotIn("callout", [b["type"] for b in blocks])
        self.assertNotIn("icon", repr(blocks))

    def test_code_languages_are_limited_to_ones_notion_accepts(self):
        self.assertEqual(bodies.language("py"), "python")
        self.assertEqual(bodies.language("js"), "javascript")
        self.assertEqual(bodies.language("klingon"), "plain text")
        self.assertEqual(bodies.language(""), "plain text")
        self.assertEqual(bodies.markdown_to_blocks("```weird\nx\n```")[0]["code"]["language"], "plain text")

    def test_blocks_survive_a_round_trip_through_notion(self):
        ws = WS()
        blocks = bodies.markdown_to_blocks(BODY)
        page = ws.api.create_page(ALOGS, {}, children=blocks)
        read = ws.api.block_children(page["id"])
        skipped: list[str] = []
        again = bodies.convert_blocks(ws.api, read, skipped)
        self.assertEqual(skipped, [])
        self.assertEqual(bodies.plain(again), bodies.plain(blocks))

    def test_unsupported_blocks_are_reported_not_dropped_silently(self):
        ws = WS()
        read = [{"id": "x", "type": "image", "image": {}, "has_children": False}, para("kept")]
        skipped: list[str] = []
        out = bodies.convert_blocks(ws.api, read, skipped)
        self.assertEqual(skipped, ["image"])
        self.assertEqual(len(out), 1)


class Base(unittest.TestCase):
    def setUp(self):
        self.ws = WS()
        self.area = self.ws.seed(AREAS, Name="Bosch Internship", Status="ACTIVE", Summary="old summary")

    def log(self, **extra):
        change = {"operation": "CREATE", "database": "Area Logs", "body": BODY, "properties": {
            "Name": "2026-W45", "Areas": "Bosch Internship", "Type": "WEEKLY", "Summary": "Thermal limits mapped",
            "Period": {"start": "2026-11-02", "end": "2026-11-08"}}}
        change.update(extra)
        return change

    def propose(self, changes, **kw):
        return proposals.propose(self.ws, changes, "user said so", **kw)

    def row(self, n=0):
        return self.ws.pages_of(QUEUE)[n]

    def edit_line(self, name, text, n=0):
        """What the user does in Notion: change a 'Name: value' line, or add a new one above the Body heading."""
        blocks = self.ws.api.blocks[self.row(n)["id"]]
        for b in blocks:
            if b["type"] == "paragraph" and "".join(p["plain_text"] for p in b["paragraph"]["rich_text"]).startswith(name + ":"):
                b["paragraph"]["rich_text"] = para(f"{name}: {text}")["paragraph"]["rich_text"]
                return
        at = next(i for i, b in enumerate(blocks) if b["type"] == "heading_2" and b["heading_2"]["rich_text"][0]["plain_text"] == "Body")
        blocks.insert(at, para(f"{name}: {text}"))

    def edit_body(self, text, n=0):
        blocks = self.ws.api.blocks[self.row(n)["id"]]
        at = next(i for i, b in enumerate(blocks) if b["type"] == "heading_2" and b["heading_2"]["rich_text"][0]["plain_text"] == "Body")
        blocks[at + 1:] = [para(text)]

    def approve_apply(self, num=1):
        out = [proposals.approve(self.ws, [num], approved_by="yes, go ahead")]
        out.append(proposals.apply(self.ws, [num]))
        return "\n".join(out)

    def created(self):
        return self.ws.pages_of(ALOGS)


class BodyTests(Base):
    def test_a_proposal_carries_its_body_and_shows_it(self):
        out = self.propose([self.log()])
        self.assertIn("Body: 6 line(s)", out)
        self.assertIn("| ## Did", out)
        self.assertEqual(self.created(), [])                   # nothing written yet
        blocks = self.ws.api.blocks[self.row()["id"]]
        lines = texts(blocks)
        self.assertIn("Properties", lines)
        self.assertIn("Body", lines)
        self.assertIn("Summary: Thermal limits mapped", lines)
        self.assertIn("Areas: Bosch Internship", lines)
        self.assertIn("Period: 2026-11-02 → 2026-11-08", lines)

    def test_the_body_is_written_to_the_new_page_when_applied(self):
        self.propose([self.log()])
        out = self.approve_apply()
        self.assertIn("applied", out)
        self.assertNotIn("edits", out)
        (page,) = self.created()
        self.assertEqual(bodies.plain(bodies.convert_blocks(self.ws.api, self.ws.api.block_children(page["id"]), [])),
                         bodies.plain(bodies.markdown_to_blocks(BODY)))

    def test_a_long_body_is_appended_in_chunks(self):
        body = "\n\n".join(f"paragraph {i}" for i in range(230))
        self.propose([self.log(body=body)])
        self.approve_apply()
        (page,) = self.created()
        self.assertEqual(len(self.ws.api.block_children(page["id"])), 230)

    def test_update_can_append_a_body_without_properties(self):
        out = self.propose([{"operation": "UPDATE", "database": "Areas", "item": "Bosch Internship", "body": "## Week 45\nMore."}])
        self.assertIn("added at the end of the page", out)
        self.approve_apply()
        texts_now = texts(self.ws.api.block_children(self.area))
        self.assertEqual(texts_now, ["Week 45", "More."])

    def test_body_and_properties_are_both_optional_for_update_but_one_is_needed(self):
        with self.assertRaises(proposals.QueryError):
            self.propose([{"operation": "UPDATE", "database": "Areas", "item": "Bosch Internship"}])

    def test_a_set_inactive_has_no_body(self):
        with self.assertRaises(proposals.QueryError):
            self.propose([{"operation": "SET-INACTIVE", "database": "Areas", "item": "Bosch Internship", "body": "x"}])

    def test_a_habit_log_with_a_body_is_not_written_directly(self):
        self.ws.seed(HABITS, Name="Learn Mandarin", Status="ACTIVE", Target=7)
        out = proposals.record(self.ws, [{**log_change(Date="today", Value=1), "body": "notes"}], "user said so", source="me")
        self.assertIn("Proposed for approval", out)
        self.assertIn("page body", out)


class EditTests(Base):
    def test_untouched_rows_apply_exactly_as_proposed(self):
        self.propose([self.log()])
        out = self.approve_apply()
        self.assertNotIn("your edits", out)

    def test_an_edited_value_is_what_gets_written(self):
        self.propose([self.log()])
        self.edit_line("Summary", "Found the thermal limit of the left elbow")
        out = self.approve_apply()
        self.assertIn("with your edits: Summary", out)
        (page,) = self.created()
        self.assertEqual("".join(p["plain_text"] for p in page["properties"]["Summary"]["rich_text"]),
                         "Found the thermal limit of the left elbow")

    def test_the_user_can_add_a_property_the_agent_did_not_propose(self):
        self.propose([self.log()])
        self.edit_line("Visibility", "CV-ok")                  # a state the agent left out
        self.edit_line("Skills", "VLA; G1")
        out = self.approve_apply()
        self.assertIn("Visibility", out)
        (page,) = self.created()
        self.assertEqual(page["properties"]["Visibility"]["select"], {"name": "CV-ok"})
        self.assertEqual(page["properties"]["Skills"]["multi_select"], [{"name": "VLA"}, {"name": "G1"}])

    def test_dates_and_relations_can_be_edited_as_text(self):
        self.propose([self.log()])
        self.edit_line("Period", "2026-11-09 → 2026-11-15")
        other = self.ws.seed(AREAS, Name="MSc thesis", Status="ACTIVE")
        self.edit_line("Areas", "MSc thesis")
        self.approve_apply()
        (page,) = self.created()
        self.assertEqual(page["properties"]["Period"]["date"], {"start": "2026-11-09", "end": "2026-11-15"})
        self.assertEqual([r["id"] for r in page["properties"]["Areas"]["relation"]], [other])

    def test_the_body_can_be_edited(self):
        self.propose([self.log()])
        self.edit_body("Rewritten by me.")
        out = self.approve_apply()
        self.assertIn("with your edits: body", out)
        (page,) = self.created()
        self.assertEqual(texts(self.ws.api.block_children(page["id"])), ["Rewritten by me."])

    def test_the_user_can_write_a_body_the_agent_did_not_propose(self):
        self.propose([self.log(body=None)])
        self.edit_body("Typed by me.")
        self.approve_apply()
        (page,) = self.created()
        self.assertEqual(texts(self.ws.api.block_children(page["id"])), ["Typed by me."])

    def test_an_emptied_value_clears_the_property(self):
        self.propose([self.log()])
        self.edit_line("Summary", "")
        self.approve_apply()
        (page,) = self.created()
        self.assertEqual(page["properties"]["Summary"]["rich_text"], [{"plain_text": ""}])

    def test_queue_shows_the_edited_version(self):
        self.propose([self.log()])
        self.edit_line("Type", "MILESTONE")
        out = proposals.queue(self.ws)
        self.assertIn("Type: MILESTONE   ✎ edited by you", out)
        self.assertNotIn("Type: WEEKLY", out)

    def test_approve_reports_the_final_values_for_the_agent_to_show(self):
        self.propose([self.log()])
        self.edit_line("Summary", "Edited")
        out = proposals.approve(self.ws, [1], approved_by="yes")
        self.assertIn("approved", out)
        self.assertIn("with your edits: Summary", out)
        self.assertIn("Summary: Edited", out)
        self.assertIn("Summary: Edited", "".join(p["plain_text"] for p in self.row()["properties"]["Preview"]["rich_text"]))

    def test_an_invalid_edit_blocks_approval(self):
        self.propose([self.log()])
        self.edit_line("Type", "NOT-A-TYPE")
        out = proposals.approve(self.ws, [1], approved_by="yes")
        self.assertIn("NOT approved", out)
        self.assertIn("Type", out)
        self.assertEqual(proposals._read_row(self.row())["status"], "PENDING")

    def test_a_line_that_is_not_a_property_blocks_approval(self):
        self.propose([self.log()])
        self.edit_line("Colour", "red")
        self.assertIn("NOT approved", proposals.approve(self.ws, [1], approved_by="yes"))

    def test_an_invalid_edit_found_at_apply_sends_the_row_back_and_writes_nothing(self):
        self.propose([self.log()])
        self.ws.api.update_page(self.row()["id"], {"Status": {"status": {"name": "APPROVED"}}})   # Approve pressed in Notion
        self.edit_line("Type", "NOT-A-TYPE")
        out = proposals.apply(self.ws, [1])
        self.assertIn("sent back to PENDING", out)
        self.assertEqual(self.created(), [])
        self.assertEqual(proposals._read_row(self.row())["status"], "PENDING")

    def test_a_title_cannot_be_cleared(self):
        self.propose([self.log()])
        self.edit_line("Name", "")
        self.assertIn("NOT approved", proposals.approve(self.ws, [1], approved_by="yes"))

    def test_editing_a_value_into_a_closing_state_needs_explicit_confirmation(self):
        self.ws.seed(GOALS, Name="HSK in April", Status="ABANDONED")
        self.propose([{"operation": "UPDATE", "database": "Goals", "item": "HSK in April", "properties": {"Status": "ACTIVE"}}])
        self.edit_line("Status", "ACHIEVED")                    # the user turns "reopen" into "done"
        out = proposals.approve(self.ws, [1], approved_by="yes")
        self.assertIn("NOT approved", out)
        self.assertIn("closes it", out)
        out = proposals.approve(self.ws, [1], approved_by="yes, it is done", confirmed=True)
        self.assertNotIn("NOT approved", out)
        self.assertIn("approved", out)

    def test_update_edits_are_applied_and_revert_restores_added_properties(self):
        self.propose([{"operation": "UPDATE", "database": "Areas", "item": "Bosch Internship", "properties": {"Summary": "new"}}])
        self.edit_line("Status", "PAUSED")                      # the user also pauses it
        out = self.approve_apply()
        self.assertIn("with your edits: Status", out)
        page = self.ws.api.page(self.area)
        self.assertEqual(page["properties"]["Status"]["select"], {"name": "PAUSED"})
        self.assertEqual(proposals._read_row(self.row())["before"]["values"]["Status"], "ACTIVE")
        proposals.revert(self.ws, 1)
        proposals.approve(self.ws, [2], approved_by="yes")
        proposals.apply(self.ws, [2])
        page = self.ws.api.page(self.area)
        self.assertEqual(page["properties"]["Status"]["select"], {"name": "ACTIVE"})

    def test_rows_from_before_this_feature_still_apply(self):
        self.propose([self.log(body=None)])
        row = self.row()
        payload = proposals._read_row(row)["payload"]
        for key in ("shown", "body", "total"):
            payload.pop(key, None)
        self.ws.api.update_page(row["id"], {"Payload": {"rich_text": proposals._rt(__import__("json").dumps(payload))}})
        self.ws.api.blocks.pop(row["id"], None)
        self.assertIn("applied", self.approve_apply())
        self.assertEqual(len(self.created()), 1)


if __name__ == "__main__":
    unittest.main()
