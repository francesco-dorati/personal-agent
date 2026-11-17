"""Create the Conversations database (Records): assistant conversations worth remembering.

    uv run python scripts/add_conversations_db.py           # dry run: prints what it would create
    uv run python scripts/add_conversations_db.py --apply   # creates it (skips if it already exists)

It is created as a page "Conversations" holding the database, appended at the end of the
root page, which is under the Records heading when Records is the last section (move it
there in Notion otherwise). Relations are two-way: Areas, Goals, Open Questions, People and
Commitments each get a "Conversations" column. Afterwards run `agent server refresh`.
"""
from __future__ import annotations

import sys

from personal_agent.notion_api import NotionError
from personal_agent.workspace import Workspace

NAME = "Conversations"
DESCRIPTION = ("Assistant conversations worth remembering: what was explored and concluded, "
               "even when nothing else changed. A short summary and the chat link, never the transcript.")
OUTCOMES = [
    ("CHANGED", "green", "Led to changes in the workspace; they are linked."),
    ("NO-CHANGE", "gray", "Explored or concluded something; nothing else changed."),
    ("OPEN", "yellow", "Unresolved: pick it up again (shown in the weekly review)."),
]
SOURCES = [("ME", "blue", "Written by the user."), ("ASSISTANT", "purple", "Summarised by an assistant, to be read as its reading of the chat."),
           ("IMPORT", "gray", "Taken from a document or another tool.")]
LINKS = ["Areas", "Goals", "Open Questions", "People", "Commitments"]


def rt(text: str) -> list[dict]:
    return [{"type": "text", "text": {"content": text}}]


def options(spec, with_descriptions: bool) -> list[dict]:
    return [{"name": n, "color": c, **({"description": d} if with_descriptions else {})} for n, c, d in spec]


def schema(reg, with_descriptions: bool) -> dict:
    props: dict = {
        "Name": {"title": {}},
        "ID": {"unique_id": {"prefix": "CONV"}},
        "Date": {"date": {}},
        "Summary": {"rich_text": {}},
        "Conclusions": {"rich_text": {}},
        "Outcome": {"select": {"options": options(OUTCOMES, with_descriptions)}},
        "Link": {"url": {}},
        "Source": {"select": {"options": options(SOURCES, with_descriptions)}},
    }
    for target in LINKS:
        db = reg.find_database(target)
        if db is None:
            print(f"  (no {target} database: no relation to it)")
            continue
        props[target] = {"relation": {"data_source_id": db.data_source_id, "type": "dual_property",
                                      "dual_property": {"synced_property_name": NAME}}}
    return props


def main() -> None:
    apply = "--apply" in sys.argv
    ws = Workspace()
    reg = ws.registry(refresh=True)
    if reg.find_database(NAME):
        print(f"{NAME} already exists: nothing to do.")
        return
    props = schema(reg, with_descriptions=True)
    print(f"{'Creating' if apply else 'DRY RUN, would create'} '{NAME}' at the end of the root page with columns:")
    for name, spec in props.items():
        kind = next(iter(spec))
        extra = ", ".join(o["name"] for o in spec[kind].get("options", [])) if kind == "select" else ""
        print(f"  - {name}: {kind}{' (' + extra + ')' if extra else ''}{' ↔ ' + name + '.' + NAME if kind == 'relation' else ''}")
    if not apply:
        print("\nRun again with --apply to create it.")
        return

    holder = ws.api.request("POST", "/pages", json={
        "parent": {"type": "page_id", "page_id": ws.settings.root_page_id},
        "properties": {"title": {"title": rt(NAME)}}}, retry_server_errors=False)
    body = {"parent": {"type": "page_id", "page_id": holder["id"]}, "title": rt(NAME), "description": rt(DESCRIPTION),
            "is_inline": True, "initial_data_source": {"properties": props}}
    try:
        db = ws.api.request("POST", "/databases", json=body, retry_server_errors=False)
    except NotionError as err:                      # older API without option descriptions: retry without them
        if err.status != 400:
            raise
        print(f"  Notion refused option descriptions ({err}); creating without them.")
        body["initial_data_source"]["properties"] = schema(reg, with_descriptions=False)
        db = ws.api.request("POST", "/databases", json=body, retry_server_errors=False)
        print("  Add these option descriptions by hand (the agent reads them):")
        for n, _, d in OUTCOMES + SOURCES:
            print(f"    {n}: {d}")
    print(f"\nCreated {NAME}: {db.get('url', db['id'])}")
    print("Move the 'Conversations' page under the Records heading if it is not there, then: agent server refresh")


if __name__ == "__main__":
    main()
