"""The tools, as plain functions returning text.

The MCP server (`server.py`) and the command line (`cli.py`) both call these
functions, so running a tool from the terminal shows exactly what the model
receives.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .blocks import render_page
from .names import Item
from .notion_api import NotionError

from .query import QueryError, build_filter, build_sort, parse_date, resolve_database
from .registry import Database, Registry
from .values import decode, format_value, norm_id
from .workspace import Workspace

def _count(db: Database) -> str:
    if db.row_count is None:
        return ""
    if db.row_count > 100:
        return "100+ items"
    return "empty" if db.row_count == 0 else f"{db.row_count} item{'s' if db.row_count != 1 else ''}"


def _one_line(text: str, limit: int = 140) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def overview(ws: Workspace, refresh: bool = False) -> str:
    """Map of the workspace: every section, page and database, what each is
    for, and how many items each database holds. Call this first."""
    reg = ws.registry(refresh=refresh)
    entries: list[tuple[int, list[str], str]] = []
    for db in reg.databases:
        details = ", ".join(x for x in ("database", _count(db)) if x)
        line = f"{db.name} ({details})"
        if db.description:
            line += f": {_one_line(db.description)}"
        entries.append((db.order, db.path, line))
    for page in reg.pages:
        state = "page, empty" if page.is_empty else "page"
        line = f"{page.name} ({state})"
        if page.intro:
            line += f": {_one_line(page.intro)}"
        entries.append((page.order, page.path, line))

    # Group by path, in the order things appear in Notion.
    entries.sort(key=lambda e: e[0])
    groups: dict[tuple[str, ...], list[str]] = {}
    for _, path, line in entries:
        groups.setdefault(tuple(path), []).append(line)

    built = datetime.fromtimestamp(reg.built_at, ZoneInfo(ws.settings.timezone)).strftime("%Y-%m-%d %H:%M")
    out = [f"Workspace: {reg.root_title} (map built {built})", ""]
    for path in groups:
        out.append(" › ".join(path) if path else "(top level)")
        out += [f"  - {line}" for line in groups[path]]
        out.append("")
    undescribed = [d.name for d in reg.databases if not d.description]
    if undescribed:
        out.append("No description yet (ask the user what these are for): " + ", ".join(undescribed))
    return "\n".join(out).rstrip()


# --------------------------------------------------------------------------
LONG_TEXT = 90
MAX_LIMIT = 100


def _resolve_relations(ws: Workspace, reg: Registry, db: Database, values: dict) -> dict:
    out = {}
    for prop in db.properties:
        value = values.get(prop.name)
        if prop.type == "relation" and value:
            target = reg.database_by_id(prop.relation_to)
            value = [ws.names.name_of(target, pid) for pid in value]
        out[prop.name] = value
    return out


def format_row(db: Database, page_id: str, values: dict) -> str:
    """One item as a compact block: header line, short fields, links, long text."""
    title_prop = next((p for p in db.properties if p.type == "title"), None)
    label = next((values[p.name] for p in db.properties if p.type == "unique_id" and values.get(p.name)), "")
    title = values.get(title_prop.name) if title_prop else "Untitled"
    lines = [f"{label + ' · ' if label else ''}{title or 'Untitled'}  [id {page_id}]"]
    short, links, long = [], [], []
    for prop in db.properties:
        if prop.type in ("title", "unique_id"):
            continue
        text = format_value(values.get(prop.name))
        if not text:
            continue
        if prop.type == "relation":
            links.append(f"{prop.name}: {text}")
        elif len(text) > LONG_TEXT:
            long.append(f"{prop.name}: {text}")
        else:
            short.append(f"{prop.name}: {text}")
    for group in (short, links):
        if group:
            lines.append("  " + " · ".join(group))
    lines += [f"  {line}" for line in long]
    return "\n".join(lines)


def find(ws: Workspace, database: str, where: dict[str, str] | None = None, search: str | None = None,
         sort: str | None = None, limit: int = 20) -> str:
    """Rows of one database, filtered. Links are shown as names."""
    reg = ws.registry()
    try:
        db = resolve_database(reg, database)
        conditions = dict(where or {})
        if search:
            title = next(p.name for p in db.properties if p.type == "title")
            conditions[title] = f"~{search}"
        notes: list[str] = []
        notion_filter = build_filter(reg, db, conditions, ws.names, ws.settings.timezone, notes)
        sorts = build_sort(db, sort)
    except QueryError as err:
        return f"Error: {err}"
    limit = max(1, min(limit, MAX_LIMIT))
    rows = ws.api.query(db.data_source_id, filter=notion_filter, sorts=sorts, limit=limit + 1)
    more = len(rows) > limit
    rows = rows[:limit]

    described = " and ".join(f"{k} {v}" if str(v)[:1] in "<>!~=" else f"{k} = {v}" for k, v in conditions.items())
    head = f"{db.name}: {len(rows)}{'+' if more else ''} result{'s' if len(rows) != 1 else ''}"
    head += f" where {described}" if described else ""
    head += f", sorted by {sort}" if sort else ", most recently edited first"
    if notes:
        head += "\nNote: " + "; ".join(notes) + "."
    if not rows:
        return head + ". Nothing matches."
    blocks = []
    for row in rows:
        values = {name: decode(prop) for name, prop in row["properties"].items()}
        blocks.append(format_row(db, norm_id(row["id"]), _resolve_relations(ws, reg, db, values)))
    tail = f"\n\nMore results exist: narrow with `where` or raise `limit` (max {MAX_LIMIT})." if more else ""
    return head + "\n\n" + "\n\n".join(blocks) + tail


# --------------------------------------------------------------------------
# get / person / agenda


LABEL_RE = re.compile(r"^\s*([A-Za-z]+)-(\d+)\s*$")
HEX_RE = re.compile(r"[0-9a-fA-F]{32}")
CLOSED_STATES = {"done", "dropped", "closed", "cancelled", "canceled", "declined", "rejected",
                 "achieved", "abandoned", "resolved", "accepted", "inactive", "completed"}


def _load_row(ws: Workspace, page_id: str) -> dict | None:
    try:
        return ws.api.page(page_id)
    except NotionError as err:
        if err.status in (400, 404):
            return None
        raise


def _row_database(reg: Registry, page: dict) -> Database | None:
    parent = page.get("parent", {})
    source = (parent.get("data_source_id") or "").replace("-", "")
    return reg.database_by_id(source) if source else None


def _locate(ws: Workspace, item: str, database: str | None) -> tuple[str, Database | None] | str:
    """Find a page from an ID like INT-14, a page ID or link, or a title.
    Returns (page_id, database or None) or an error/choice message."""
    reg = ws.registry()
    label = LABEL_RE.match(item)
    if label:
        db = reg.database_by_prefix(label.group(1))
        if db:
            prop = next(p for p in db.properties if p.type == "unique_id" and p.prefix.upper() == label.group(1).upper())
            rows = ws.api.query(db.data_source_id, filter={"property": prop.name, "unique_id": {"equals": int(label.group(2))}}, limit=1)
            return (norm_id(rows[0]["id"]), db) if rows else f"Error: no item {item.upper()} in {db.name}."
    hexid = HEX_RE.search(item.replace("-", ""))
    if hexid:
        return hexid.group(0).lower(), None
    # By title: in one database, or everywhere (databases and text pages).
    try:
        dbs = [resolve_database(reg, database)] if database else reg.databases
    except QueryError as err:
        return f"Error: {err}"
    candidates: list[tuple[Item, float]] = []
    for db in dbs:
        candidates += ws.names.match(db, item, cutoff=0.7)
    if not database:
        for page in reg.pages:
            score = 1.0 if page.name.lower() == item.strip().lower() else 0.0
            if score:
                candidates.append((Item(page.page_id, page.name, "", "page"), score))
    candidates.sort(key=lambda c: -c[1])
    if not candidates:
        return f"Error: nothing called '{item}'. Try find(..., search=...) or check the spelling."
    best, score = candidates[0]
    close = [c for c in candidates[1:] if c[1] >= score - 0.05]
    if close and score < 1.0:
        options = "\n".join(f"- {i.label + ' · ' if i.label else ''}{i.title} ({i.database})" for i, _ in [candidates[0]] + close[:7])
        return f"'{item}' could be several items; ask which one, or call get with its ID:\n{options}"
    return best.page_id, reg.find_database(best.database)


def get(ws: Workspace, item: str, database: str | None = None) -> str:
    """One item with all its properties, links (with IDs) and page content."""
    located = _locate(ws, item, database)
    if isinstance(located, str):
        return located
    page_id, db = located
    page = _load_row(ws, page_id)
    if page is None:
        return f"Error: no page with ID {page_id}, or the integration can't see it."
    reg = ws.registry()
    db = db or _row_database(reg, page)
    values = {name: decode(prop) for name, prop in page.get("properties", {}).items()}
    if db is None:   # a plain page (Profile, Direction…)
        title = next((v for k, v in values.items() if isinstance(v, str)), "Untitled")
        head = f"{title}  [page, id {page_id}]"
    else:
        # Links with their IDs, so the model can follow them with get().
        shown = {}
        for prop in db.properties:
            value = values.get(prop.name)
            if prop.type == "relation" and value:
                target = reg.database_by_id(prop.relation_to)
                items = ws.names.items(target) if target else {}
                value = [f"{items[p].title} ({items[p].label})" if p in items and items[p].label
                         else (items[p].title if p in items else p) for p in value]
            shown[prop.name] = value
        head = f"[{db.name}] " + format_row(db, page_id, shown)
    body = render_page(ws.api, page_id)
    edited = page.get("last_edited_time", "")[:10]
    return f"{head}\n  Last edited: {edited}\n\nPage content:\n{body or '(empty)'}"


def person(ws: Workspace, name: str) -> str:
    """Find a person by name, tolerating misspellings; full details if clear."""
    reg = ws.registry()
    people = next((d for d in reg.databases if d.name.lower() in ("people", "contacts")), None)
    if people is None:
        return "Error: no People database in the workspace."
    matches = ws.names.match(people, name, cutoff=0.5)
    if not matches:
        return f"No person matches '{name}'. Use find('{people.name}', search=...) to browse."
    best, score = matches[0]
    others = [m for m in matches[1:4] if m[1] >= 0.6]
    # Clear if it's a strong match, or a fair one with no rival close behind.
    rival = others[0][1] if others else 0.0
    clear = (score >= 0.85 and rival < score - 0.05) or (score >= 0.65 and rival < score - 0.15)
    if not clear:
        lines = [f"'{name}' is not a clear match. Closest people (ask the user which one):"]
        lines += [f"- {i.label + ' · ' if i.label else ''}{i.title} (match {int(s * 100)}%)" for i, s in matches[:5]]
        return "\n".join(lines)
    note = "" if score == 1.0 else f"Note: '{name}' matched {best.title} ({int(score * 100)}%). Use this spelling.\n\n"
    also = ("\n\nOther possible matches: " + ", ".join(f"{i.title} ({i.label})" for i, _ in others)) if others else ""
    return note + get(ws, best.page_id) + also


def _date_props(db: Database) -> list[str]:
    return [p.name for p in db.properties
            if p.type == "date" and not any(w in p.name.lower() for w in ("review", "created", "edited"))]


def _open_filter(db: Database) -> tuple[str, str, list[str]] | None:
    """A Status property (name, type, closed options), if the database has one."""
    for prop in db.properties:
        if prop.type in ("select", "status") and prop.name.lower() == "status":
            closed = [o.name for o in prop.options if o.name.lower() in CLOSED_STATES]
            if closed:
                return prop.name, prop.type, closed
    return None


def agenda(ws: Workspace, start: str = "today", end: str = "+7d") -> str:
    """Everything dated in a period across the workspace, plus overdue items."""
    reg = ws.registry()
    tz = ws.settings.timezone
    try:
        first, last = parse_date(start, tz), parse_date(end, tz)
    except QueryError as err:
        return f"Error: {err}"
    if last < first:
        first, last = last, first
    by_day: dict[str, list[str]] = {}
    overdue: list[str] = []
    for db in reg.databases:
        props = _date_props(db)
        if not props:
            continue
        status = _open_filter(db)
        in_range = [{"and": [{"property": p, "date": {"on_or_after": first}},
                             {"property": p, "date": {"on_or_before": last}}]} for p in props]
        rows = ws.api.query(db.data_source_id, filter=in_range[0] if len(in_range) == 1 else {"or": in_range}, limit=100)
        late = []
        if status:
            not_closed = [{"property": status[0], status[1]: {"does_not_equal": c}} for c in status[2]]
            late_conds = [{"and": [{"property": p, "date": {"before": first}}, *not_closed]} for p in props]
            late = ws.api.query(db.data_source_id, filter=late_conds[0] if len(late_conds) == 1 else {"or": late_conds}, limit=50)
        for rows_, bucket in ((rows, "range"), (late, "late")):
            for row in rows_:
                values = {n: decode(p) for n, p in row["properties"].items()}
                values = _resolve_relations(ws, reg, db, values)
                title = next((values[p.name] for p in db.properties if p.type == "title"), "") or "Untitled"
                label = next((values[p.name] for p in db.properties if p.type == "unique_id" and values.get(p.name)), "")
                state = f" · {status[0]}: {values.get(status[0])}" if status and values.get(status[0]) else ""
                people = next((format_value(values[p.name]) for p in db.properties
                               if p.type == "relation" and p.name.lower() == "people" and values.get(p.name)), "")
                for prop in props:
                    day = (values.get(prop) or {}).get("start") if isinstance(values.get(prop), dict) else None
                    if not day:
                        continue
                    day = day[:10]
                    line = f"{label + ' · ' if label else ''}{title} [{db.name}, {prop}]{state}{' · with ' + people if people else ''}"
                    is_range = bool((values.get(prop) or {}).get("end"))
                    if bucket == "late" and day < first and not is_range:   # periods aren't deadlines
                        overdue.append(f"  - {day}: {line}")
                    elif bucket == "range" and first <= day <= last:
                        by_day.setdefault(day, []).append(f"  - {line}")
    out = [f"Agenda {first} → {last} ({tz})"]
    if overdue:
        out += ["", "Overdue (date passed, not closed)"] + sorted(set(overdue))
    for day in sorted(by_day):
        weekday = date.fromisoformat(day).strftime("%a")
        out += ["", f"{day} ({weekday})"] + by_day[day]
    if len(out) == 1:
        out.append("Nothing dated in this period and nothing overdue.")
    return "\n".join(out)
