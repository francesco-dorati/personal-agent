"""Write path: every change goes through the Assistant Queue.

    propose  →  the user approves (Approve button in Notion, or `approve` after
                their OK in the conversation)  →  apply

`propose` checks a change against the workspace schema and writes it as a
PENDING row in the Assistant Queue; nothing else is touched. `apply` performs
only rows whose Status is APPROVED, re-checks that the target did not change
since the proposal, and records the outcome on the row. There is no delete:
removing something means SET-INACTIVE.

Queue columns used: Name, Operation, Status, Target Database ID, Target Item ID,
Payload, Before, Preview, Reason / Evidence, Proposed By, Batch ID, ID.
Optional extra columns "Result" (text) and "Applied At" (date) are used when
they exist; otherwise the outcome is appended to Reason / Evidence.
"""
from __future__ import annotations

import json
import os
import re
import secrets
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from . import bodies
from .names import Item
from .notion_api import NotionError
from .query import QueryError, parse_date, resolve_database, resolve_property
from .registry import Database, Property, Registry
from .values import decode, format_value, norm_id
from .workspace import Workspace

QUEUE_NAME = "Assistant Queue"
OPERATIONS = ("CREATE", "UPDATE", "SET-INACTIVE")
SOURCES = ("me", "assistant", "import")
STATUSES = ("PENDING", "APPROVED", "REJECTED", "APPLIED", "FAILED", "EXPIRED")
REQUIRED_FIELDS = ("Name", "Operation", "Status", "Target Database ID", "Target Item ID", "Payload",
                   "Before", "Preview", "Reason / Evidence", "Proposed By", "Batch ID")

WRITABLE = {"title", "rich_text", "number", "checkbox", "select", "status", "multi_select",
            "date", "relation", "url", "email", "phone_number"}
INACTIVE_ORDER = ("inactive", "archived", "dropped", "closed", "abandoned", "cancelled", "canceled", "declined")

# Goals and questions are the user's to close or re-date: such changes need `confirmed=True`.
GUARDED_DATABASES = {"goals", "open questions"}
CLOSING = {"achieved", "resolved", "done", "completed", "closed", "abandoned", "dropped", "inactive"}
GUARDED_PROPERTIES = re.compile(r"target|success|criteria|deadline|decide|due", re.I)

UNIQUE_PER_DAY = {"daily check-in"}          # databases with one row per day
DIRECT_DATABASES = {"habits log", "daily check-in"}   # user-reported logs written without approval (record())
MAX_CHANGES = 25
TEXT_CHUNK = 1900                            # Notion allows 2000 characters per rich-text part
HEX_RE = re.compile(r"[0-9a-f]{32}")
MAX_BODY_CHARS = 60000                       # Markdown in one proposal's `body`


class EditError(QueryError):
    """The user's edit in a queue row cannot be applied (unknown property, invalid value…)."""


# -- modes and levels -------------------------------------------------------------
def worker_mode() -> bool:
    """A background worker (AGENT_MODE=worker) may propose, never approve or apply."""
    return os.environ.get("AGENT_MODE", "").strip().lower() == "worker"


def _no_worker(action: str) -> None:
    if worker_mode():
        raise QueryError(f"`{action}` is disabled in worker mode (AGENT_MODE=worker): a worker may only propose.")


def approval_level(db: Database) -> str:
    """How a change to this database must be approved (from the guide, section 6)."""
    parts = [p.lower() for p in db.path]
    if "context" in parts:
        return "context"          # explicit, one change at a time
    if "records" in parts:
        return "record"           # batch approval is fine
    if "collections" in parts:
        return "collection"       # explicit, batch allowed
    return "explicit"             # areas, goals, open questions


# -- small helpers -----------------------------------------------------------------
def _rt(text: str) -> list[dict]:
    text = text or ""
    return [{"type": "text", "text": {"content": text[i:i + TEXT_CHUNK]}} for i in range(0, len(text), TEXT_CHUNK)]


def _now(ws: Workspace) -> str:
    return datetime.now(ZoneInfo(ws.settings.timezone)).isoformat(timespec="minutes")


def _batch_id(ws: Workspace) -> str:
    return f"B-{datetime.now(ZoneInfo(ws.settings.timezone)):%Y%m%d-%H%M}-{secrets.token_hex(2)}"


def _queue_db(ws: Workspace) -> Database:
    reg = ws.registry()
    db = reg.find_database(QUEUE_NAME)
    if db is None:
        db = ws.registry(refresh=True).find_database(QUEUE_NAME)
    if db is None:
        raise QueryError(f"There is no '{QUEUE_NAME}' database under the root page, so nothing can be proposed. "
                         "Create it in Notion (see the README) and run overview with refresh=true.")
    have = {p.name for p in db.properties}
    missing = [f for f in REQUIRED_FIELDS if f not in have]
    if missing:
        raise QueryError(f"The {QUEUE_NAME} lacks these columns: {', '.join(missing)}.")
    return db


def _id_property(qdb: Database) -> str:
    prop = next((p.name for p in qdb.properties if p.type == "unique_id"), None)
    if prop is None:
        raise QueryError(f"The {QUEUE_NAME} needs an ID (auto-increment) column.")
    return prop


# -- value handling ------------------------------------------------------------------
def _date_one(ws: Workspace, value: Any) -> str | None:
    if value in (None, ""):
        return None
    text, low = str(value).strip(), str(value).strip().lower()
    tz = ZoneInfo(ws.settings.timezone)
    if low == "now":
        return datetime.now(tz).isoformat(timespec="minutes")
    if low in ("today", "yesterday", "tomorrow") or re.fullmatch(r"[+-]\d+d", low):
        return parse_date(text, ws.settings.timezone)
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{1,2}):(\d{2})(?::\d{2})?(Z|[+-]\d{2}:?\d{2})?)?", text)
    if not m:
        raise QueryError(f"Not a date: '{value}'. Use YYYY-MM-DD, 'YYYY-MM-DD HH:MM', now, today, yesterday or +3d.")
    day, hh, mm, offset = m.groups()
    try:
        date.fromisoformat(day)
    except ValueError:
        raise QueryError(f"Not a calendar date: '{value}'.") from None
    if hh is None:
        return day
    stamp = f"{day}T{int(hh):02d}:{mm}"
    if offset:
        offset = "+00:00" if offset == "Z" else (offset if ":" in offset else offset[:3] + ":" + offset[3:])
        return stamp + offset
    return datetime.fromisoformat(stamp).replace(tzinfo=tz).isoformat(timespec="minutes")


def _canon_date(ws: Workspace, value: Any) -> dict | None:
    start, end = (value.get("start"), value.get("end")) if isinstance(value, dict) else (value, None)
    start = _date_one(ws, start)
    if start is None:
        return None
    return {"start": start, "end": _date_one(ws, end)}


def _option(db: Database, prop: Property, value: Any) -> str:
    wanted = str(value).strip().lower()
    for option in prop.options:
        if option.name.lower() == wanted:
            return option.name
    raise QueryError(f"'{value}' is not an option of {db.name} › {prop.name}. Options: "
                     f"{', '.join(o.name for o in prop.options)}. New options are never created: ask the user to add it.")


def _resolve_item(ws: Workspace, target: Database, ref: str) -> tuple[str, str]:
    """(page id, title) of the item `ref` names: a page ID, a label like HAB-1, or a title."""
    ref = ref.strip()
    items = ws.names.items(target, fresh=True)
    pid = norm_id(ref).lower()
    if HEX_RE.fullmatch(pid):
        if pid in items:
            return pid, items[pid].title
        try:                                       # created a moment ago, not in the cache yet
            page = ws.api.page(pid)
        except NotionError:
            page = None
        if page and norm_id(page.get("parent", {}).get("data_source_id", "")) == target.data_source_id:
            title = next((decode(p) for p in page["properties"].values() if p["type"] == "title"), None)
            return pid, title or "Untitled"
        raise QueryError(f"Page {ref} is not an item of {target.name}.")
    for item in items.values():
        if item.label and item.label.upper() == ref.upper():
            return item.page_id, item.title
    matches = ws.names.match(target, ref, cutoff=0.75, fresh=True)
    if not matches:
        raise QueryError(f"No {target.name} item matches '{ref}'. Use search or find, or CREATE it in the same batch "
                         "and refer to it as $1, $2…")
    top = matches[0][1]
    rival = matches[1][1] if len(matches) > 1 else 0.0
    if (top >= 0.99 and rival < 0.99) or (top >= 0.85 and rival < top - 0.1):
        return matches[0][0].page_id, matches[0][0].title
    options = ", ".join(f"{i.label + ' · ' if i.label else ''}{i.title}" for i, _ in matches[:5])
    raise QueryError(f"'{ref}' could be several {target.name} items: {options}. Use the ID.")


def _canon(ws: Workspace, reg: Registry, db: Database, prop: Property, raw: Any, total: int) -> Any:
    """The plain value stored in the proposal: select names as written in Notion, dates as ISO strings,
    relations as page IDs (or '$ref:N' for the Nth change of the batch)."""
    kind = prop.type
    if kind not in WRITABLE:
        raise QueryError(f"{db.name} › {prop.name} ({kind}) is automatic or read-only and cannot be written.")
    if raw is None:
        if kind in ("title", "status"):
            raise QueryError(f"{db.name} › {prop.name} cannot be cleared.")
        return [] if kind in ("relation", "multi_select") else None
    if kind in ("title", "rich_text", "url", "email", "phone_number"):
        text = str(raw).strip()
        if kind == "title" and not text:
            raise QueryError(f"{db.name} › {prop.name} cannot be empty.")
        return text
    if kind == "number":
        if isinstance(raw, bool):
            raise QueryError(f"{db.name} › {prop.name} expects a number, got {raw!r}.")
        try:
            number = float(raw)
        except (TypeError, ValueError):
            raise QueryError(f"{db.name} › {prop.name} expects a number, got {raw!r}.") from None
        return int(number) if number.is_integer() else number
    if kind == "checkbox":
        if isinstance(raw, bool):
            return raw
        if str(raw).strip().lower() in ("true", "yes", "1", "__yes__"):
            return True
        if str(raw).strip().lower() in ("false", "no", "0", "__no__"):
            return False
        raise QueryError(f"{db.name} › {prop.name} expects true or false, got {raw!r}.")
    if kind in ("select", "status"):
        return _option(db, prop, raw)
    if kind == "multi_select":
        values = raw if isinstance(raw, list) else str(raw).split(",")
        return [_option(db, prop, v) for v in values if str(v).strip()]
    if kind == "date":
        return _canon_date(ws, raw)
    target = reg.database_by_id(prop.relation_to)          # relation
    if target is None:
        raise QueryError(f"{db.name} › {prop.name} points to a database outside the workspace map.")
    out = []
    for ref in raw if isinstance(raw, list) else [raw]:
        text = str(ref).strip()
        m = re.fullmatch(r"\$(\d+)", text)
        if m:
            if not 1 <= int(m.group(1)) <= total:
                raise QueryError(f"{text} refers to a change outside this batch of {total}.")
            out.append(f"$ref:{m.group(1)}")
        else:
            out.append(_resolve_item(ws, target, text)[0])
    return out


def _show(ws: Workspace, reg: Registry, prop: Property, value: Any) -> str:
    if value in (None, [], ""):
        return "(empty)"
    if prop.type == "relation":
        target = reg.database_by_id(prop.relation_to)
        return ", ".join(f"new item #{v[5:]} of this batch" if str(v).startswith("$ref:")
                         else ws.names.name_of(target, v) for v in value)
    return format_value(value) or "(empty)"


def _to_notion(prop: Property, value: Any, refmap: dict, batch: str) -> dict:
    kind = prop.type
    if kind == "title":
        return {"title": _rt(value)}
    if kind == "rich_text":
        return {"rich_text": _rt(value or "")}
    if kind in ("url", "email", "phone_number", "number"):
        return {kind: value}
    if kind == "checkbox":
        return {"checkbox": bool(value)}
    if kind == "select":
        return {"select": {"name": value} if value else None}
    if kind == "status":
        return {"status": {"name": value}}
    if kind == "multi_select":
        return {"multi_select": [{"name": v} for v in value or []]}
    if kind == "date":
        if not value:
            return {"date": None}
        return {"date": {"start": value["start"], **({"end": value["end"]} if value.get("end") else {})}}
    ids = []
    for v in value or []:                                   # relation
        if str(v).startswith("$ref:"):
            k = int(v[5:])
            if (batch, k) not in refmap:
                raise QueryError(f"depends on change {k} of its batch, which has not been applied: approve and apply it first")
            ids.append({"id": refmap[(batch, k)]})
        else:
            ids.append({"id": v})
    return {"relation": ids}


def _inactive_option(db: Database) -> tuple[Property, str]:
    for prop in db.properties:
        if prop.type in ("select", "status") and prop.name.lower() == "status":
            names = {o.name.lower(): o.name for o in prop.options}
            for candidate in INACTIVE_ORDER:
                if candidate in names:
                    return prop, names[candidate]
    raise QueryError(f"{db.name} has no Status option meaning inactive (inactive, archived, dropped, closed…). "
                     "Use UPDATE with the status the user chooses.")


# -- the user's edits in a queue row -------------------------------------------------------------
# Each queue row is a page. It holds one "Name: value" line per property and the page body, as
# editable text. Whatever the user leaves there when the row is approved or applied is what is written.
def _norm(text: Any) -> str:
    return " ".join(str(text or "").split())


def _fit(name: str, text: str) -> str:
    """A property line short enough to be written to the row and read back unchanged."""
    room = bodies.TEXT_CHUNK - len(name) - 2
    return text if len(text) <= room else text[:room - 1] + "…"


def _edit_text(ws: Workspace, reg: Registry, prop: Property, value: Any) -> str:
    """A value as the user sees and edits it in the row (parsed back by `_parse_edit`)."""
    if value in (None, [], ""):
        return ""
    if prop.type == "relation":
        target = reg.database_by_id(prop.relation_to)
        return "; ".join(f"${str(v)[5:]}" if str(v).startswith("$ref:") else ws.names.name_of(target, v) for v in value)
    if prop.type == "multi_select":
        return "; ".join(value)
    return format_value(value)


def _parse_edit(prop: Property, text: str) -> Any:
    """What the user typed after 'Name:' as input for `_canon`. Empty clears the value."""
    text = text.strip()
    if not text:
        return None
    if prop.type == "relation":
        return [t.strip() for t in text.split(";") if t.strip()]
    if prop.type == "multi_select":
        return [t.strip() for t in re.split(r"[;,]", text) if t.strip()]
    if prop.type == "date":
        parts = re.split(r"\s*(?:→|->|\bto\b)\s*", text, maxsplit=1)
        return {"start": parts[0].strip(), "end": parts[1].strip() if len(parts) > 1 and parts[1].strip() else None}
    return text


def _guard(db: Database, props: dict) -> list[str]:
    """Reasons a change needs the user's explicit confirmation (closing a goal, moving a target date…)."""
    guard: list[str] = []
    if db.name.lower() in GUARDED_DATABASES:
        for name, value in props.items():
            kind = resolve_property(db, name).type
            if kind in ("select", "status") and str(value).lower() in CLOSING:
                guard.append(f"{name} → {value} (closes it)")
            elif GUARDED_PROPERTIES.search(name):
                guard.append(f"changes {name}")
    return guard


def _preview_lines(ws: Workspace, reg: Registry, db: Database, op: str, props: dict, before: dict, guard: list[str],
                   conflicts: list[str], body: str = "", edited: Any = (), body_edited: bool = False) -> list[str]:
    lines = []
    for name, value in props.items():
        prop = resolve_property(db, name)
        new = _show(ws, reg, prop, value)
        mark = "   ✎ edited by you" if name in edited else ""
        lines.append(f"  {name}: {_show(ws, reg, prop, before.get(name)) + ' → ' if op != 'CREATE' else ''}{new}{mark}")
    if body:
        rows = body.splitlines()
        where = "" if op == "CREATE" else " (added at the end of the page)"
        lines.append(f"  Body: {len(rows)} line(s){where}{'   ✎ edited by you' if body_edited else ''}")
        lines += [f"    | {line}" for line in rows[:6]]
        if len(rows) > 6:
            lines.append(f"    | … (+{len(rows) - 6} more lines)")
    if guard:
        lines.append("  ⚠ needs the user's explicit confirmation: " + "; ".join(guard))
    lines += [f"  ⚠ {c}" for c in conflicts]
    return lines


def _create_with_blocks(api: Any, data_source_id: str, properties: dict, blocks: list[dict] | None) -> dict:
    """Create a row with its content (the first 100 blocks go with the page, the rest are appended)."""
    page = api.create_page(data_source_id, properties, children=(blocks or [])[:100])
    if blocks and len(blocks) > 100:
        api.append_blocks(page["id"], blocks[100:])
    return page


def _effective(ws: Workspace, reg: Registry, r: dict) -> dict:
    """The queue row as it will be applied: the proposal plus whatever the user edited in the row's page.

    {props, edited (names), body (blocks or None), body_edited, skipped (block kinds not copied)}.
    Raises EditError when an edit cannot be applied, so nothing is written from a half-understood row."""
    payload = r["payload"]
    out: dict[str, Any] = {"props": dict(payload.get("props") or {}), "edited": [], "body": None,
                           "body_edited": False, "skipped": []}
    db = reg.database_by_id(r["ds"])
    if db is None or "shown" not in payload or payload.get("direct"):
        return out                                          # rows from before this existed, and direct logs
    shown = payload["shown"]
    lines, raw_body = bodies.split_row(ws.api.block_children(r["page_id"]))
    seen: dict[str, str] = {}
    for name, text in lines:
        try:
            seen[resolve_property(db, name).name] = text
        except QueryError as err:
            raise EditError(f"the line '{name}: …' in the row is not a property. {err}") from err
    total = int(payload.get("total") or 1)
    for name, text in seen.items():
        if name in shown and _norm(text) == _norm(shown[name]):
            continue                                        # untouched: keep the exact proposed value
        if name not in shown and not text.strip():
            continue
        prop = resolve_property(db, name)
        try:
            value = _canon(ws, reg, db, prop, _parse_edit(prop, text), total)
        except QueryError as err:
            raise EditError(f"{name}: {err}") from err
        if not _same(out["props"].get(name), value):
            out["props"][name] = value
            out["edited"].append(name)
    original = payload.get("body") or ""
    if raw_body is None:                                    # the Body heading was deleted: use the proposed body
        blocks = bodies.markdown_to_blocks(original)
    else:
        blocks = bodies.strip_blank(bodies.convert_blocks(ws.api, raw_body, out["skipped"]))
    if bodies.count_blocks(blocks) > bodies.MAX_BLOCKS:
        raise EditError(f"the body has more than {bodies.MAX_BLOCKS} blocks: shorten it")
    out["body"] = blocks
    out["body_edited"] = _norm(bodies.plain(blocks)) != _norm(bodies.plain(bodies.markdown_to_blocks(original)))
    return out


def _edit_note(eff: dict) -> str:
    names = list(eff["edited"]) + (["body"] if eff["body_edited"] else [])
    return f" (with your edits: {', '.join(names)})" if names else ""


def _effective_lines(ws: Workspace, reg: Registry, db: Database, r: dict, eff: dict) -> list[str]:
    before = (r["before"] or {}).get("values") or {}
    text = bodies.plain(eff["body"]) if eff["body"] else ""
    return _preview_lines(ws, reg, db, r["op"], eff["props"], before, _guard(db, eff["props"]), [], text,
                          eff["edited"], eff["body_edited"])


def _sync_preview(ws: Workspace, reg: Registry, db: Database, r: dict, eff: dict) -> None:
    """Keep the Preview column in line with what will be written, so the table shows the edited version."""
    head = r["preview"].splitlines()[0] if r["preview"] else r["name"]
    try:
        ws.api.update_page(r["page_id"], {"Preview": {"rich_text": _rt(head + "\n" + "\n".join(_effective_lines(ws, reg, db, r, eff)))}})
    except NotionError:
        pass                                                # cosmetic: never block a decision on it


# -- proposing -------------------------------------------------------------------------
def _page_values(page: dict, names: list[str]) -> dict:
    return {n: decode(page["properties"][n]) for n in names if n in page["properties"]}


def _day_window(prop: str, day: str) -> list[dict]:
    return [{"property": prop, "date": {"on_or_after": day}}, {"property": prop, "date": {"on_or_before": day}}]


def _conflicts(ws: Workspace, reg: Registry, db: Database, level: str, props: dict, title: str,
               allow_duplicate: bool) -> tuple[list[str], list[str]]:
    """(blocking problems, warnings) for creating a new item."""
    hard: list[str] = []
    soft: list[str] = []
    if level != "record":                                   # records repeat by nature; things must not
        items = ws.names.items(db, fresh=True).values()
        same = [i for i in items if i.title.strip().lower() == title.strip().lower()]
        if same and not allow_duplicate:
            hard.append(f"{db.name} already has '{same[0].title}'{' (' + same[0].label + ')' if same[0].label else ''}: "
                        "update that one, or set allow_duplicate if it really is a second item.")
        elif not same:
            close = [(i, s) for i, s in ws.names.match(db, title, cutoff=0.85, fresh=True)]
            if close:
                soft.append(f"similar existing item: {close[0][0].title}"
                            f"{' (' + close[0][0].label + ')' if close[0][0].label else ''}")
        return hard, soft
    date_prop = next((p.name for p in db.properties if p.type == "date" and p.name.lower() == "date"), None)
    value = props.get(date_prop) if date_prop else None
    if not value:
        return hard, soft
    day = value["start"][:10]
    if db.name.lower() in UNIQUE_PER_DAY:
        rows = ws.api.query(db.data_source_id, filter={"and": _day_window(date_prop, day)}, limit=1)
        if rows:
            hard.append(f"{db.name} already has a row for {day}: update it instead of creating another.")
    habit_prop = next((p for p in db.properties if p.type == "relation" and p.name.lower() == "habit"), None)
    habits = [h for h in props.get(habit_prop.name, []) if not str(h).startswith("$ref:")] if habit_prop else []
    if habits:
        rows = ws.api.query(db.data_source_id, limit=1, filter={"and": [
            *_day_window(date_prop, day), {"property": habit_prop.name, "relation": {"contains": habits[0]}}]})
        measure = next((p.name for p in reg.database_by_id(habit_prop.relation_to).properties if p.name.lower() == "measure"), None)
        counts = False                                          # COUNT habits legitimately repeat within a day
        if measure:
            counts = str(decode(ws.api.page(habits[0])["properties"].get(measure, {"type": "select", "select": None})) or "").upper() == "COUNT"
        if rows and not counts:
            soft.append(f"this habit is already logged on {day}")
    return hard, soft


def _prepare(ws: Workspace, reg: Registry, n: int, change: Any, source: str, total: int) -> dict:
    where = f"Change {n}: "
    try:
        if not isinstance(change, dict):
            raise QueryError("expected an object with operation, database and properties.")
        op = str(change.get("operation", "")).strip().upper().replace("_", "-")
        if op not in OPERATIONS:
            raise QueryError(f"operation must be CREATE, UPDATE or SET-INACTIVE (got '{change.get('operation')}'). "
                             "There is no delete: use SET-INACTIVE.")
        db = resolve_database(reg, str(change.get("database", "")))
        if db.name.lower() == QUEUE_NAME.lower():
            raise QueryError(f"the {QUEUE_NAME} cannot be changed through proposals.")
        level = approval_level(db)
        raw = change.get("properties") or {}
        if not isinstance(raw, dict):
            raise QueryError("`properties` must be an object {property: value}.")
        props = {}
        for key, value in raw.items():
            prop = resolve_property(db, key)
            props[prop.name] = _canon(ws, reg, db, prop, value, total)
        body = change.get("body")
        if body is not None and not isinstance(body, str):
            raise QueryError("`body` must be a Markdown string.")
        body = (body or "").strip()
        if body and op == "SET-INACTIVE":
            raise QueryError("SET-INACTIVE takes no body.")
        if len(body) > MAX_BODY_CHARS:
            raise QueryError(f"`body` is {len(body)} characters; at most {MAX_BODY_CHARS}.")
        body_blocks = bodies.markdown_to_blocks(body) if body else []
        if bodies.count_blocks(body_blocks) > bodies.MAX_BLOCKS:
            raise QueryError(f"`body` has more than {bodies.MAX_BLOCKS} blocks: split it or shorten it.")
        title_prop = next(p for p in db.properties if p.type == "title")
        before: dict[str, Any] = {}
        edited = ""
        item_ref = ""
        conflicts: list[str] = []

        if op == "CREATE":
            if change.get("item"):
                raise QueryError("CREATE takes no `item`; use UPDATE to change an existing one.")
            title = props.get(title_prop.name)
            if not title and level == "record":     # a log row is named after what it logs (no typos, no drift)
                linked = [p for p in db.properties if p.type == "relation" and props.get(p.name)
                          and not str(props[p.name][0]).startswith("$ref:")]
                linked.sort(key=lambda p: p.name.lower() != "habit")
                if linked:
                    title = ws.names.name_of(reg.database_by_id(linked[0].relation_to), props[linked[0].name][0])
                else:                                # a day record (check-in) is named after its day
                    day = next((v["start"][:10] for v in props.values() if isinstance(v, dict) and v.get("start")), "")
                    title = day
                if title:
                    props[title_prop.name] = title
            if not title:
                raise QueryError(f"a new {db.name} item needs a {title_prop.name}.")
            source_prop = next((p for p in db.properties if p.name.lower() == "source" and p.type in ("select", "status")), None)
            if source_prop and source_prop.name not in props:
                try:
                    props[source_prop.name] = _option(db, source_prop, source)
                except QueryError:
                    pass                                # the database has no such option: leave Source empty
            hard, conflicts = _conflicts(ws, reg, db, level, props, title, bool(change.get("allow_duplicate")))
            if hard:
                raise QueryError(" ".join(hard))
        else:
            if not change.get("item"):
                raise QueryError(f"{op} needs `item`: an ID like HAB-1, a page ID or a title.")
            pid, title = _resolve_item(ws, db, str(change["item"]))
            if op == "SET-INACTIVE":
                if props:
                    raise QueryError("SET-INACTIVE takes no properties.")
                prop, option = _inactive_option(db)
                props = {prop.name: option}
            if not props and not body:
                raise QueryError("nothing to change: give `properties` or a `body`.")
            page = ws.api.page(pid)
            before = _page_values(page, list(props))
            edited = page.get("last_edited_time", "")
            label = next((i.label for i in ws.names.items(db).values() if i.page_id == pid), "")
            item_ref = f"{label} {pid}".strip()

        guard = _guard(db, props)
        shown = {name: _fit(name, _edit_text(ws, reg, resolve_property(db, name), value)) for name, value in props.items()}
        lines = _preview_lines(ws, reg, db, op, props, before, guard, conflicts, body)
        return {"n": n, "op": op, "db": db, "level": level, "title": title, "props": props, "before": before,
                "edited": edited, "item": item_ref, "guard": guard, "preview": "\n".join(lines),
                "body": body, "body_blocks": body_blocks, "shown": shown}
    except QueryError as err:
        raise QueryError(where + str(err)) from err


def _validate(ws: Workspace, changes: list[dict], reason: str, source: str) -> list[dict]:
    """Check every change against the schema (all or nothing) and return them prepared."""
    if not isinstance(changes, list) or not changes:
        raise QueryError("`changes` must be a non-empty list.")
    if len(changes) > MAX_CHANGES:
        raise QueryError(f"At most {MAX_CHANGES} changes per proposal; got {len(changes)}.")
    if not (reason or "").strip():
        raise QueryError("`reason` is required: say why, and quote the evidence (the user's words, the email).")
    if source not in SOURCES:
        raise QueryError(f"`source` must be one of: {', '.join(SOURCES)}.")
    reg = ws.registry()
    return [_prepare(ws, reg, n, c, source, len(changes)) for n, c in enumerate(changes, 1)]


def _dry_run(prepared: list[dict], verb: str) -> str:
    out = [f"DRY RUN: nothing written, no queue rows created. {len(prepared)} change(s) would be {verb}:", ""]
    for p in prepared:
        out.append(f"{p['op']} · {p['db'].name} · {p['title']}  [{p['level']}]")
        out.append(p["preview"])
    return "\n".join(out)


def _enqueue(ws: Workspace, prepared: list[dict], reason: str, source: str, proposed_by: str | None,
             status: str = "PENDING", direct: bool = False) -> tuple[str, list[tuple[int, dict]]]:
    """Write one queue row per prepared change, all in a new batch, with the given status."""
    qdb = _queue_db(ws)
    batch = _batch_id(ws)
    actor = proposed_by or ("worker" if worker_mode() else "claude")
    created: list[tuple[int, dict]] = []
    for p in prepared:
        name = f"{p['op'].title()} {p['db'].name}: {p['title']}"
        payload: dict[str, Any] = {"n": p["n"], "props": p["props"], "guard": p["guard"], "total": len(prepared)}
        if direct:
            payload["direct"] = True                        # written at once: no editing, no row content
        else:
            payload["shown"], payload["body"] = p["shown"], p["body"]
        before = {"edited": p["edited"], "values": p["before"]} if p["before"] or p["edited"] else {}
        preview = f"{p['op']} · {p['db'].name} · {p['title']}\n{p['preview']}"
        row = {
            "Name": {"title": _rt(name[:200])},
            "Status": {"status": {"name": status}},
            "Operation": {"select": {"name": p["op"]}},
            "Target Database ID": {"rich_text": _rt(p["db"].data_source_id)},
            "Target Item ID": {"rich_text": _rt(p["item"])},
            "Payload": {"rich_text": _rt(json.dumps(payload, ensure_ascii=False))},
            "Before": {"rich_text": _rt(json.dumps(before, ensure_ascii=False) if before else "")},
            "Preview": {"rich_text": _rt(preview)},
            "Reason / Evidence": {"rich_text": _rt(f"{reason.strip()}\n[source: {source}]")},
            "Proposed By": {"rich_text": _rt(actor)},
            "Batch ID": {"rich_text": _rt(batch)},
        }
        try:
            page = _create_with_blocks(ws.api, qdb.data_source_id, row,
                                       None if direct else bodies.row_blocks(p["shown"], p["body_blocks"]))
        except NotionError as err:
            done = ", ".join(f"#{num}" for num, _ in created) or "none"
            raise QueryError(f"Could not write change {p['n']} to the queue ({err}). Already queued: {done}. "
                             f"Reject them with reject(batch='{batch}') or approve them as they are.") from err
        num = _read_row(page)["num"]
        created.append((num, p))
    return batch, created


def propose(ws: Workspace, changes: list[dict], reason: str, source: str = "assistant",
            proposed_by: str | None = None, dry_run: bool = False) -> str:
    """Validate changes and put them in the Assistant Queue as PENDING. Changes nothing else."""
    prepared = _validate(ws, changes, reason, source)
    if dry_run:
        return _dry_run(prepared, "proposed")
    batch, created = _enqueue(ws, prepared, reason, source, proposed_by)
    out = [f"Proposed {len(created)} change(s) in batch {batch}. Nothing in your data has changed yet.", ""]
    for num, p in created:
        flag = "  ⚠ needs explicit confirmation" if p["guard"] else ""
        out.append(f"#{num} · {p['op']} · {p['db'].name} · {p['title']}  [{p['level']}]{flag}")
        out.append(p["preview"])
    ids = ", ".join(str(num) for num, _ in created)
    out += ["", f"Show this to the user. If they agree in the conversation: approve(ids=[{ids}], approved_by=<their words>), "
                f"then apply(ids=[{ids}]). Or they press Approve in the Assistant Queue and you call apply() later.",
            "The user can change any value, add a 'Property: value' line or edit the body in the queue row's page "
            "before approving: approve and apply use their edited version (queue marks it ✎). Never write the "
            "original values back."]
    return "\n".join(out)



# -- direct logs ------------------------------------------------------------------------
def direct_logs_enabled() -> bool:
    """Habit logs and check-ins skip approval unless AGENT_DIRECT_LOGS=0."""
    return os.environ.get("AGENT_DIRECT_LOGS", "1").strip().lower() not in ("0", "false", "no", "off")


def record(ws: Workspace, changes: list[dict], reason: str, source: str = "me",
           proposed_by: str | None = None, dry_run: bool = False) -> str:
    """Write low-stakes logs the user reported (Habits Log, Daily Check-In) at once.

    The change still goes through the queue, created as APPROVED and applied in the same
    call: the queue row is the history, and `revert` can undo it. Falls back to a normal
    proposal when the source is not the user, in worker mode, when AGENT_DIRECT_LOGS=0,
    or when a change touches any other database."""
    prepared = _validate(ws, changes, reason, source)
    outside = sorted({p["db"].name for p in prepared if p["db"].name.lower() not in DIRECT_DATABASES})
    why_not = ("the source is not the user" if source != "me" else
               "worker mode" if worker_mode() else
               "AGENT_DIRECT_LOGS=0" if not direct_logs_enabled() else
               f"{', '.join(outside)} always needs approval" if outside else
               "a page body needs approval" if any(p["body"] for p in prepared) else
               "a change needs explicit confirmation" if any(p["guard"] for p in prepared) else "")
    if dry_run:
        return _dry_run(prepared, "proposed for approval" if why_not else "written directly (no approval needed)")
    if why_not:
        batch, created = _enqueue(ws, prepared, reason, source, proposed_by)
        ids = ", ".join(str(num) for num, _ in created)
        lines = [f"#{num} · {p['op']} · {p['db'].name} · {p['title']}\n{p['preview']}" for num, p in created]
        return "\n".join([f"Proposed for approval ({why_not}). Nothing in your data has changed yet.", "", *lines, "",
                          f"Show this to the user; after their OK: approve(ids=[{ids}], approved_by=<their words>), "
                          f"then apply(ids=[{ids}])."])
    batch, created = _enqueue(ws, prepared, reason + "\n[auto-approved: direct log reported by the user]",
                              source, proposed_by, status="APPROVED", direct=True)
    result = apply(ws, batch=batch)
    updates = [str(num) for num, p in created if p["op"] == "UPDATE"]
    undo = ["To undo: a new log row has no inactive state, so the user deletes it in Notion."]
    if updates:
        undo.append(f"An update is undone with revert(id) (#{', #'.join(updates)}).")
    return "\n".join(["Written directly (habit logs and check-ins the user reported need no approval).",
                      result, "", *undo])

# -- reading queue rows -----------------------------------------------------------------
def _read_row(page: dict) -> dict:
    values = {name: decode(prop) for name, prop in page["properties"].items()}

    def js(key: str) -> dict:
        try:
            return json.loads(values.get(key) or "") or {}
        except ValueError:
            return {}

    ident = next((decode(p) for p in page["properties"].values() if p["type"] == "unique_id"), None)
    digits = re.sub(r"\D", "", str(ident or ""))
    return {"page_id": norm_id(page["id"]), "num": int(digits) if digits else 0, "name": values.get("Name") or "",
            "op": values.get("Operation"), "status": values.get("Status"), "ds": norm_id(values.get("Target Database ID") or ""),
            "item": values.get("Target Item ID") or "", "payload": js("Payload"), "before": js("Before"),
            "preview": values.get("Preview") or "", "reason": values.get("Reason / Evidence") or "",
            "by": values.get("Proposed By") or "", "batch": values.get("Batch ID") or "", "created": page.get("created_time", "")}


def _split_refs(ids: list | None, batch: str | None) -> tuple[list[int], list[str], list[str]]:
    numbers: list[int] = []
    pages: list[str] = []
    batches = [batch] if batch else []
    for ref in ids or []:
        text = str(ref).strip().lstrip("#")
        if text.upper().startswith("B-"):
            batches.append(text)
        elif re.fullmatch(r"(?:Q-)?\d+", text, re.I):
            numbers.append(int(re.sub(r"\D", "", text)))
        elif HEX_RE.fullmatch(norm_id(text).lower()):
            pages.append(norm_id(text).lower())
        else:
            raise QueryError(f"'{ref}' is not a queue ID. Use the number shown by queue (like 12), or a batch ID (B-…).")
    return numbers, pages, batches


def _fetch_rows(ws: Workspace, qdb: Database, ids: list | None = None, batch: str | None = None,
                status: str | None = None, limit: int = 100) -> list[dict]:
    numbers, pages, batches = _split_refs(ids, batch)
    id_prop = _id_property(qdb)
    found: dict[str, dict] = {}
    for num in numbers:
        rows = ws.api.query(qdb.data_source_id, filter={"property": id_prop, "unique_id": {"equals": num}}, limit=1)
        if not rows:
            raise QueryError(f"No queue item #{num}.")
        found[norm_id(rows[0]["id"])] = _read_row(rows[0])
    for pid in pages:
        found[pid] = _read_row(ws.api.page(pid))
    for b in batches:
        rows = ws.api.query(qdb.data_source_id, filter={"property": "Batch ID", "rich_text": {"equals": b}}, limit=limit)
        if not rows:
            raise QueryError(f"No queue items in batch {b}.")
        for row in rows:
            found[norm_id(row["id"])] = _read_row(row)
    if not (numbers or pages or batches):
        flt = {"property": "Status", "status": {"equals": status}} if status and status != "ALL" else None
        for row in ws.api.query(qdb.data_source_id, filter=flt, limit=limit):
            found[norm_id(row["id"])] = _read_row(row)
    return sorted(found.values(), key=lambda r: (r["batch"], r["payload"].get("n", 0), r["num"]))


def _line(reg: Registry, r: dict) -> str:
    db = reg.database_by_id(r["ds"])
    level = approval_level(db) if db else "no target"
    return f"#{r['num']} · {r['status']} · {r['name'] or '(untitled)'}  [{level}; batch {r['batch'] or '-'}; by {r['by'] or '?'}]"


def queue(ws: Workspace, status: str = "PENDING", batch: str | None = None, limit: int = 30) -> str:
    """Rows of the Assistant Queue with their previews."""
    status = (status or "PENDING").upper()
    if status != "ALL" and status not in STATUSES:
        raise QueryError(f"`status` must be one of: {', '.join(STATUSES)}, ALL.")
    reg = ws.registry()
    qdb = _queue_db(ws)
    rows = _fetch_rows(ws, qdb, batch=batch, status=status, limit=max(1, min(limit, 100)))
    if batch and status != "ALL":
        rows = [r for r in rows if r["status"] == status]
    if not rows:
        scope = "" if status == "ALL" else f" {status}"
        return f"Assistant Queue: nothing{scope}{' in batch ' + batch if batch else ''}."
    out = [f"Assistant Queue: {len(rows)} item(s){'' if status == 'ALL' else ' ' + status}", ""]
    for r in rows:
        out.append(_line(reg, r))
        preview = r["preview"].splitlines()[1:]
        db = reg.database_by_id(r["ds"])
        if db is not None and r["status"] in ("PENDING", "APPROVED"):
            try:
                eff = _effective(ws, reg, r)
                if eff["edited"] or eff["body_edited"]:
                    preview = _effective_lines(ws, reg, db, r, eff)
            except EditError as err:
                preview += [f"  ⚠ the user's edit in the row cannot be applied: {err}"]
            except NotionError:
                pass
        out += [f"    {line}" for line in preview]
        if r["status"] in ("FAILED", "APPLIED"):
            tail = r["reason"].splitlines()[-1] if r["reason"] else ""
            out.append(f"    ↳ {tail}")
        out.append("")
    return "\n".join(out).rstrip()


# -- deciding ----------------------------------------------------------------------------
def _note(ws: Workspace, qdb: Database, r: dict, text: str, **extra: Any) -> None:
    stamp = _now(ws)
    props: dict[str, Any] = {"Reason / Evidence": {"rich_text": _rt((r["reason"] + f"\n[{stamp}] {text}").strip())}}
    props.update(extra)
    ws.api.update_page(r["page_id"], props)


def approve(ws: Workspace, ids: list | None = None, batch: str | None = None, approved_by: str = "",
            confirmed: bool = False) -> str:
    """PENDING → APPROVED, after the user has agreed in the conversation."""
    _no_worker("approve")
    if not (ids or batch):
        raise QueryError("Give `ids` (numbers from queue) or a `batch`. Approving everything pending is not offered.")
    if len((approved_by or "").strip()) < 3:
        raise QueryError("`approved_by` is required: the user's own words agreeing to this (it is stored on the row).")
    reg = ws.registry()
    qdb = _queue_db(ws)
    rows = _fetch_rows(ws, qdb, ids, batch)
    contexts = [r for r in rows if (reg.database_by_id(r["ds"]) and approval_level(reg.database_by_id(r["ds"])) == "context")]
    if contexts and len(rows) > 1:
        raise QueryError("Context changes are approved one at a time, on their own. Approve "
                         + ", ".join(f"#{r['num']}" for r in contexts) + " separately.")
    out = []
    for r in rows:
        if r["status"] != "PENDING":
            out.append(f"#{r['num']} left as it is: status is {r['status']}, not PENDING.")
            continue
        db = reg.database_by_id(r["ds"])
        try:
            eff = _effective(ws, reg, r)
        except EditError as err:
            out.append(f"#{r['num']} NOT approved: {err} Fix it in the row (or reject it), then approve again.")
            continue
        guard = _guard(db, eff["props"]) if db else (r["payload"].get("guard") or [])
        if guard and not confirmed:
            out.append(f"#{r['num']} NOT approved: {'; '.join(guard)}. Ask the user to confirm this explicitly, "
                       "then approve with confirmed=true.")
            continue
        ws.api.update_page(r["page_id"], {"Status": {"status": {"name": "APPROVED"}}})
        _note(ws, qdb, r, f"approved in conversation: {approved_by.strip()}{_edit_note(eff)}")
        out.append(f"#{r['num']} approved · {r['name']}{_edit_note(eff)}")
        if db is not None and (eff["edited"] or eff["body_edited"]):
            lines = _effective_lines(ws, reg, db, r, eff)
            out += [f"    {line}" for line in lines]
            _sync_preview(ws, reg, db, r, eff)
    return "\n".join(out) + "\n\nApply with apply(ids=[…])."


def reject(ws: Workspace, ids: list | None = None, batch: str | None = None, reason: str = "") -> str:
    """PENDING or APPROVED → REJECTED (nothing was applied)."""
    if not (ids or batch):
        raise QueryError("Give `ids` or a `batch`.")
    qdb = _queue_db(ws)
    out = []
    for r in _fetch_rows(ws, qdb, ids, batch):
        if r["status"] not in ("PENDING", "APPROVED"):
            out.append(f"#{r['num']} left as it is: status is {r['status']}.")
            continue
        ws.api.update_page(r["page_id"], {"Status": {"status": {"name": "REJECTED"}}})
        _note(ws, qdb, r, f"rejected{': ' + reason.strip() if reason.strip() else ''}")
        out.append(f"#{r['num']} rejected · {r['name']}")
    return "\n".join(out)


# -- applying ----------------------------------------------------------------------------
def _finish(ws: Workspace, qdb: Database, r: dict, status: str, text: str, item: str | None = None) -> None:
    props: dict[str, Any] = {"Status": {"status": {"name": status}}}
    if item:
        props["Target Item ID"] = {"rich_text": _rt(item)}
    have = {p.name: p for p in qdb.properties}
    stamp = _now(ws)
    if "Result" in have and have["Result"].type == "rich_text":
        props["Result"] = {"rich_text": _rt(text)}
    else:
        props["Reason / Evidence"] = {"rich_text": _rt((r["reason"] + f"\n[{status.lower()} {stamp}] {text}").strip())}
    if status == "APPLIED" and "Applied At" in have and have["Applied At"].type == "date":
        props["Applied At"] = {"date": {"start": stamp}}
    ws.api.update_page(r["page_id"], props)


def _same(a: Any, b: Any) -> bool:
    def norm(v: Any) -> Any:
        if isinstance(v, dict) and "start" in v:
            return (v.get("start"), v.get("end") or None)
        return v if v not in ("", [], None) else None
    return norm(a) == norm(b)


def _apply_one(ws: Workspace, reg: Registry, qdb: Database, r: dict, refmap: dict, dry_run: bool) -> str:
    fresh = _read_row(ws.api.page(r["page_id"]))            # the user may have rejected it a second ago
    if fresh["status"] != "APPROVED":
        return f"#{r['num']} skipped: status is now {fresh['status']}."
    db = reg.database_by_id(r["ds"])
    if db is None:
        raise QueryError("the target database is no longer in the workspace map")
    try:
        eff = _effective(ws, reg, r)                        # the proposal as the user left it in the row
    except EditError as err:
        if dry_run:
            return f"#{r['num']} would be sent back to PENDING: {err}"
        ws.api.update_page(r["page_id"], {"Status": {"status": {"name": "PENDING"}}})
        _note(ws, qdb, r, f"sent back to PENDING, nothing applied: {err}")
        return (f"#{r['num']} NOT applied, sent back to PENDING: {err} "
                "The user can fix it in the row and approve it again.")
    props = eff["props"]
    blocks = [] if r["op"] == "SET-INACTIVE" else (eff["body"] or [])
    if not props and not blocks:
        raise QueryError("the proposal has no payload")
    batch, n = r["batch"], r["payload"].get("n")
    notion_props = {name: _to_notion(resolve_property(db, name), value, refmap, batch) for name, value in props.items()}
    title = next((props[p.name] for p in db.properties if p.type == "title" and p.name in props), "") or r["name"]
    note = _edit_note(eff)
    skipped = f" ⚠ not copied from the body (unsupported): {', '.join(sorted(set(eff['skipped'])))}." if eff["skipped"] else ""

    if r["op"] == "CREATE":
        if dry_run:
            return f"#{r['num']} would create {db.name}: {title}{note}"
        page = ws.api.create_page(db.data_source_id, notion_props, children=blocks[:100])
        pid = norm_id(page["id"])
        warn = skipped
        if len(blocks) > 100:
            try:
                ws.api.append_blocks(pid, blocks[100:])
            except NotionError as err:                      # the item exists; say what is missing instead of failing
                warn += f" ⚠ the body is incomplete ({err}): add the rest by hand."
        label = next((str(decode(p)) for p in page["properties"].values() if p["type"] == "unique_id"), "")
        refmap[(batch, n)] = pid
        ws.names.remember(db, Item(pid, title, label, db.name))
        item = f"{label} {pid}".strip()
        what = f"created {label or pid}{' with body' if blocks else ''}{note}{warn}"
        try:
            _finish(ws, qdb, r, "APPLIED", what, item=item)
        except NotionError as err:                          # created, but the row did not record it: say so loudly
            raise QueryError(f"CREATED {db.name} '{title}' ({item}) but could not mark the queue row APPLIED ({err}). "
                             "Do not apply it again; mark the row APPLIED by hand.") from err
        if note:
            _sync_preview(ws, reg, db, r, eff)
        return f"#{r['num']} applied · created {db.name}: {title}" + (f" ({label})" if label else "") + note + warn

    found = HEX_RE.search(r["item"])
    if not found:
        raise QueryError("the proposal does not say which item it changes")
    pid = found.group(0)
    page = ws.api.page(pid)
    now = _page_values(page, list(props))
    before = (r["before"] or {}).get("values") or {}
    moved = [k for k in props if k in before and not _same(now.get(k), before[k])]
    if moved:
        raise QueryError(f"{', '.join(moved)} changed since the proposal (now: "
                         + "; ".join(f"{k} = {format_value(now.get(k)) or 'empty'}" for k in moved) + "): propose again")
    if dry_run:
        return f"#{r['num']} would {r['op'].lower()} {db.name}: {title}{note}"
    added = {k: now.get(k) for k in props if k not in before}
    if added and r["op"] == "UPDATE":                       # properties the user added: remember their old values for revert
        snapshot = {"edited": (r["before"] or {}).get("edited", ""), "values": {**before, **added}}
        ws.api.update_page(r["page_id"], {"Before": {"rich_text": _rt(json.dumps(snapshot, ensure_ascii=False))}})
    warn = skipped
    if notion_props:
        ws.api.update_page(pid, notion_props)
    if blocks:
        try:
            ws.api.append_blocks(pid, blocks)
        except NotionError as err:
            warn += f" ⚠ the properties were updated but the body was not added ({err}): add it by hand."
    what = "updated " + ", ".join(props) if props else "added body"
    _finish(ws, qdb, r, "APPLIED", what + (" and added body" if blocks and props else "") + note + warn)
    if note:
        _sync_preview(ws, reg, db, r, eff)
    return f"#{r['num']} applied · {r['op'].lower()} {db.name}: {title}{note}{warn}"


def apply(ws: Workspace, ids: list | None = None, batch: str | None = None, dry_run: bool = False) -> str:
    """Perform APPROVED queue rows. Rows in other states are never touched."""
    _no_worker("apply")
    reg = ws.registry()
    qdb = _queue_db(ws)
    explicit = bool(ids or batch)
    rows = _fetch_rows(ws, qdb, ids, batch) if explicit else _fetch_rows(ws, qdb, status="APPROVED")
    notes = [f"#{r['num']} skipped: status is {r['status']}, not APPROVED." for r in rows if r["status"] != "APPROVED"]
    rows = [r for r in rows if r["status"] == "APPROVED"]

    def is_context(r: dict) -> bool:
        db = reg.database_by_id(r["ds"])
        return bool(db) and approval_level(db) == "context"

    contexts = [r for r in rows if is_context(r)]
    if contexts and explicit and len(rows) > 1:
        raise QueryError("Context changes are applied one at a time, on their own: "
                         + ", ".join(f"apply(ids=[{r['num']}])" for r in contexts))
    if contexts and not explicit:
        notes += [f"#{r['num']} left approved: context changes are applied one at a time, with apply(ids=[{r['num']}])."
                  for r in contexts]
        rows = [r for r in rows if r not in contexts]
    if not rows:
        return "Nothing approved to apply." + ("\n" + "\n".join(notes) if notes else "")

    refmap: dict[tuple[str, int], str] = {}
    for b in {r["batch"] for r in rows}:                    # changes of this batch applied earlier (for $N references)
        for earlier in _fetch_rows(ws, qdb, batch=b):
            found = HEX_RE.search(earlier["item"])
            if earlier["status"] == "APPLIED" and found and earlier["payload"].get("n"):
                refmap[(b, earlier["payload"]["n"])] = found.group(0)

    out = []
    for r in rows:
        try:
            out.append(_apply_one(ws, reg, qdb, r, refmap, dry_run))
        except (QueryError, NotionError) as err:
            if not dry_run and not str(err).startswith("CREATED "):
                try:
                    _finish(ws, qdb, r, "FAILED", str(err))
                except NotionError:
                    pass
            out.append(f"#{r['num']} {'would fail' if dry_run else 'FAILED'}: {err}")
    head = "DRY RUN: nothing changed." if dry_run else f"Applied {sum('applied' in line for line in out)} of {len(rows)}."
    return "\n".join([head, "", *out, *notes])


def revert(ws: Workspace, id: int | str, proposed_by: str | None = None) -> str:
    """Propose the inverse of an APPLIED change (a new PENDING row; nothing is undone until it is approved and applied)."""
    qdb = _queue_db(ws)
    reg = ws.registry()
    (row,) = _fetch_rows(ws, qdb, [id])
    if row["status"] != "APPLIED":
        raise QueryError(f"#{row['num']} is {row['status']}: only APPLIED changes can be reverted.")
    db = reg.database_by_id(row["ds"])
    if db is None:
        raise QueryError("The target database is no longer in the workspace map.")
    found = HEX_RE.search(row["item"])
    if not found:
        raise QueryError("The row does not record which item it changed.")
    pid = found.group(0)
    if row["op"] == "CREATE":
        change = {"operation": "SET-INACTIVE", "database": db.name, "item": pid}
    else:
        values = (row["before"] or {}).get("values")
        if not values:
            raise QueryError("The row has no 'Before' snapshot, so it cannot be reverted automatically.")
        change = {"operation": "UPDATE", "database": db.name, "item": pid, "properties": values}
    return propose(ws, [change], f"Revert of #{row['num']} ({row['name']}).", source="assistant", proposed_by=proposed_by)
