"""The weekly review, read-only: what needs attention across the workspace.

    review   commitments overdue / due soon / waiting · open questions past or near their
             decide-by date · goals and areas due for review, at risk or past target ·
             opportunity deadlines · people not contacted in a while · lapsed habits ·
             check-in trend (sleep, energy) · open conversations · pending proposals

Every section looks its database up by name and its properties loosely (case, spaces,
dashes); a missing database or property just drops that section. Nothing is written:
after the review, stamp what the user went through with update_item(..., reviewed=True).
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from . import habits, proposals
from .habits import _day, _local_day, _norm, _prop
from .registry import Database
from .tools import _resolve_relations
from .values import decode, format_value
from .workspace import Workspace

CLOSED = {"done", "dropped", "closed", "cancelled", "canceled", "declined", "rejected", "accepted", "achieved",
          "abandoned", "resolved", "parked", "inactive", "archived", "paused", "applied", "expired", "failed"}
EVERY = {"daily": 1, "weekly": 7, "biweekly": 14, "monthly": 30, "bimonthly": 61, "quarterly": 91,
         "sixmonthly": 182, "sixmonths": 182, "halfyearly": 182, "yearly": 365, "annually": 365}
MAX_LINES = 8                 # per section; the rest is counted


# -- small helpers ------------------------------------------------------------------------
def _rows(ws: Workspace, db: Database, limit: int = 500) -> list[dict]:
    return ws.api.query(db.data_source_id, limit=limit)


def _values(ws: Workspace, reg, db: Database, row: dict) -> dict:
    return _resolve_relations(ws, reg, db, {n: decode(p) for n, p in row["properties"].items()})


def _title(db: Database, values: dict) -> str:
    title = next((values.get(p.name) for p in db.properties if p.type == "title"), None) or "Untitled"
    label = next((values.get(p.name) for p in db.properties if p.type == "unique_id" and values.get(p.name)), "")
    return f"{label} · {title}" if label else title


def _date(values: dict, prop: str | None, tz) -> dt.date | None:
    value = values.get(prop) if prop else None
    start = value.get("start") if isinstance(value, dict) else None
    return _local_day(start, tz) if start else None


def _is_open(values: dict, prop: str | None) -> bool:
    state = values.get(prop) if prop else None
    return not (isinstance(state, str) and state.lower() in CLOSED)


def _section(title: str, lines: list[str]) -> list[str]:
    if not lines:
        return []
    more = len(lines) - MAX_LINES
    return ["", f"{title} ({len(lines)})", *lines[:MAX_LINES], *([f"  … and {more} more"] if more > 0 else [])]


def _days(n: int) -> str:
    return f"{n}d"


def _with(values: dict, prop: str | None) -> str:
    who = format_value(values.get(prop)) if prop else ""
    return f" · with {who}" if who else ""


# -- sections ----------------------------------------------------------------------------
def _commitments(ws, reg, today, horizon, tz) -> list[str]:
    db = reg.find_database("Commitments")
    if not db:
        return []
    due_p, status_p, people_p = _prop(db, "Due"), _prop(db, "Status"), _prop(db, "People")
    late, soon, waiting = [], [], []
    for row in _rows(ws, db):
        v = _values(ws, reg, db, row)
        if not _is_open(v, status_p):
            continue
        due, state = _date(v, due_p, tz), (v.get(status_p) or "") if status_p else ""
        line = f"- {_title(db, v)}" + _with(v, people_p)
        if due and due < today:
            late.append((due, f"{line} · due {due} ({_days((today - due).days)} late){' · ' + state if state else ''}"))
        elif due and due <= horizon:
            soon.append((due, f"{line} · due {due:%a %d %b}"))
        elif state.lower() == "waiting":
            waiting.append((due or dt.date.max, f"{line} · waiting{', due ' + str(due) if due else ''}"))
    return (_section("Commitments overdue", [l for _, l in sorted(late)])
            + _section(f"Commitments due by {horizon}", [l for _, l in sorted(soon)])
            + _section("Waiting on others", [l for _, l in sorted(waiting)]))


def _questions(ws, reg, today, horizon, tz) -> list[str]:
    db = reg.find_database("Open Questions")
    if not db:
        return []
    by_p, status_p, lean_p = _prop(db, "Decide By"), _prop(db, "Status"), _prop(db, "Current Leaning")
    lines = []
    for row in _rows(ws, db):
        v = _values(ws, reg, db, row)
        if not _is_open(v, status_p):
            continue
        by = _date(v, by_p, tz)
        if not by or by > horizon:
            continue
        when = f"decide by {by} ({_days((today - by).days)} past)" if by < today else f"decide by {by:%a %d %b}"
        lean = f" · leaning: {format_value(v.get(lean_p))[:80]}" if lean_p and v.get(lean_p) else ""
        lines.append((by, f"- {_title(db, v)} · {when}{lean}"))
    return _section("Decisions due", [l for _, l in sorted(lines)])


def _review_due(v: dict, last_p: str | None, every_p: str | None, today: dt.date, tz) -> str | None:
    """'never reviewed' / 'review overdue by Nd' / None."""
    if not last_p:
        return None
    every = EVERY.get(_norm(str(v.get(every_p) or ""))) if every_p else None
    last = _date(v, last_p, tz)
    if last is None:
        return "never reviewed"
    if every and (today - last).days > every:
        return f"last reviewed {last} ({_days((today - last).days)} ago, every {every}d)"
    return None


def _goals_and_areas(ws, reg, today, tz) -> list[str]:
    out: list[str] = []
    db = reg.find_database("Goals")
    if db:
        status_p, last_p = _prop(db, "Status"), _prop(db, "Last Reviewed")
        every_p = _prop(db, "Review Frequency", "Review Period")
        target_p, progress_p = _prop(db, "Target Date"), _prop(db, "Progress")
        lines = []
        for row in _rows(ws, db):
            v = _values(ws, reg, db, row)
            state = str(v.get(status_p) or "").lower() if status_p else ""
            if state and state != "active":
                continue
            flags = []
            target = _date(v, target_p, tz)
            if target and target < today:
                flags.append(f"target {target} passed")
            progress = str(v.get(progress_p) or "") if progress_p else ""
            if progress.upper() in ("AT-RISK", "OFF-TRACK"):
                flags.append(progress)
            due = _review_due(v, last_p, every_p, today, tz)
            if due:
                flags.append(due)
            if flags:
                lines.append(f"- {_title(db, v)} · " + " · ".join(flags))
        out += _section("Goals needing attention", lines)
    db = reg.find_database("Areas")
    if db:
        status_p, last_p = _prop(db, "Status"), _prop(db, "Last Reviewed")
        every_p = _prop(db, "Review Period", "Review Frequency")
        lines = []
        for row in _rows(ws, db):
            v = _values(ws, reg, db, row)
            if str(v.get(status_p) or "active").lower() != "active":
                continue
            due = _review_due(v, last_p, every_p, today, tz)
            if due:
                lines.append(f"- {_title(db, v)} · {due}")
        out += _section("Areas due for review", lines)
    return out


def _opportunities(ws, reg, today, horizon, tz) -> list[str]:
    db = reg.find_database("Opportunities")
    if not db:
        return []
    dl_p, status_p = _prop(db, "Deadline"), _prop(db, "Status")
    lines = []
    for row in _rows(ws, db):
        v = _values(ws, reg, db, row)
        if not _is_open(v, status_p):
            continue
        dl = _date(v, dl_p, tz)
        if dl and dl <= horizon:
            when = f"deadline {dl} passed" if dl < today else f"deadline {dl:%a %d %b}"
            state = f" · {v.get(status_p)}" if status_p and v.get(status_p) else ""
            lines.append((dl, f"- {_title(db, v)} · {when}{state}"))
    return _section("Opportunity deadlines", [l for _, l in sorted(lines)])


def _people(ws, reg, today, contact_days, tz) -> list[str]:
    db = reg.find_database("People")
    last_p = _prop(db, "Last Contact") if db else None
    if not last_p:
        return []
    rel_p = _prop(db, "Relationship")
    lines, never = [], 0
    for row in _rows(ws, db):
        v = _values(ws, reg, db, row)
        last = _date(v, last_p, tz)
        if last is None:
            never += 1
            continue
        gap = (today - last).days
        if gap > contact_days:
            kind = f" ({v.get(rel_p)})" if rel_p and v.get(rel_p) else ""
            lines.append((-gap, f"- {_title(db, v)}{kind} · last contact {last} ({_days(gap)} ago)"))
    out = _section(f"Not contacted in {contact_days}+ days", [l for _, l in sorted(lines)])
    if out and never:
        out.append(f"  ({never} people have no interaction recorded)")
    return out


def _habits(ws, today) -> list[str]:
    try:
        text = habits.habits_status(ws, today.isoformat())
    except Exception:                                   # noqa: BLE001 - no Habits databases: no section
        return []
    lines, keep = [], False
    for line in text.splitlines():
        if not line.strip():
            continue
        if not line.startswith("- "):
            keep = line.startswith(("Lapsed", "Slipping"))
            continue
        if keep:
            lines.append(line)
    return _section("Habits lapsed or slipping", lines)


def _checkins(ws, reg, today, tz) -> list[str]:
    db = reg.find_database("Daily Check-In")
    date_p = _prop(db, "Date") if db else None
    if not date_p:
        return []
    fields = [(label, _prop(db, *names)) for label, names in (
        ("sleep", ("Sleep hours",)), ("morning energy", ("Morning Energy",)),
        ("evening energy", ("Evening Energy",)), ("satisfaction", ("Satisfaction",)))]
    fields = [(label, p) for label, p in fields if p]
    start = today - dt.timedelta(days=13)
    weeks: list[list[dict]] = [[], []]                  # [previous 7 days, last 7 days]
    for row in ws.api.query(db.data_source_id, limit=60,
                            filter={"property": date_p, "date": {"on_or_after": start.isoformat()}}):
        v = {n: decode(p) for n, p in row["properties"].items()}
        day = _date(v, date_p, tz)
        if day and start <= day <= today:
            weeks[0 if day < today - dt.timedelta(days=6) else 1].append(v)

    def avg(rows: list[dict], prop: str) -> float | None:
        nums = [r[prop] for r in rows if isinstance(r.get(prop), (int, float))]
        return sum(nums) / len(nums) if nums else None

    lines = [f"- logged {len(weeks[1])}/7 days (previous week {len(weeks[0])}/7)"]
    for label, prop in fields:
        now, before = avg(weeks[1], prop), avg(weeks[0], prop)
        if now is None and before is None:
            continue
        fmt = (lambda x: "–" if x is None else f"{x:.1f}") if label == "sleep" else \
              (lambda x: "–" if x is None else f"{x:.0f}")
        delta = ""
        if now is not None and before is not None:
            diff = now - before
            delta = f" ({'+' if diff >= 0 else ''}{fmt(diff)})"
        lines.append(f"- {label}: {fmt(now)}{delta}  vs {fmt(before)} the week before")
    return ["", "Check-ins, last 7 days", *lines]


def _conversations(ws, reg, today, tz) -> list[str]:
    db = reg.find_database("Conversations")
    if not db:
        return []
    out_p, date_p = _prop(db, "Outcome"), _prop(db, "Date")
    lines = []
    for row in _rows(ws, db, limit=200):
        v = _values(ws, reg, db, row)
        if str(v.get(out_p) or "").upper() != "OPEN":
            continue
        day = _date(v, date_p, tz)
        lines.append((day or dt.date.min, f"- {_title(db, v)}" + (f" · {day}" if day else "")))
    return _section("Conversations left open", [l for _, l in sorted(lines, reverse=True)])


def _queue(ws, reg) -> list[str]:
    if not reg.find_database(proposals.QUEUE_NAME):
        return []
    try:
        qdb = proposals._queue_db(ws)
        rows = proposals._fetch_rows(ws, qdb, status="PENDING")
    except Exception:                                   # noqa: BLE001 - malformed queue: skip the section
        return []
    return ["", f"Proposals waiting for approval: {len(rows)}" + (" (see queue)" if rows else "")] if rows else []


# -- the review --------------------------------------------------------------------------
def review(ws: Workspace, date: str = "today", horizon_days: int = 7, contact_days: int = 60,
           sections: list[str] | None = None) -> str:
    """Everything that needs attention, grouped and ranked; read-only."""
    from zoneinfo import ZoneInfo
    reg, tz = ws.registry(), ZoneInfo(ws.settings.timezone)
    today = _day(ws, date)
    horizon = today + dt.timedelta(days=max(0, int(horizon_days)))
    builders: dict[str, Any] = {
        "commitments": lambda: _commitments(ws, reg, today, horizon, tz),
        "decisions": lambda: _questions(ws, reg, today, horizon, tz),
        "goals": lambda: _goals_and_areas(ws, reg, today, tz),
        "opportunities": lambda: _opportunities(ws, reg, today, horizon, tz),
        "people": lambda: _people(ws, reg, today, int(contact_days), tz),
        "habits": lambda: _habits(ws, today),
        "checkins": lambda: _checkins(ws, reg, today, tz),
        "conversations": lambda: _conversations(ws, reg, today, tz),
        "queue": lambda: _queue(ws, reg),
    }
    wanted = [s.strip().lower() for s in (sections or builders)]
    unknown = [s for s in wanted if s not in builders]
    if unknown:
        from .query import QueryError
        raise QueryError(f"Unknown section(s): {', '.join(unknown)}. Use: {', '.join(builders)}.")
    out = [f"Review {today} ({today:%a}) · looking ahead to {horizon}"]
    for name in wanted:
        out += builders[name]()
    if len(out) == 1:
        out.append("\nNothing needs attention.")
    out += ["", "Read-only. After going through it with the user: update_item(..., reviewed=true) stamps "
                "Last Reviewed; propose updates for anything they decide."]
    return "\n".join(out)
