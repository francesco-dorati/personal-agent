"""Habit tools, built on the queue (proposals.py) and the usual lookups.

    log_habit      "I did my Mandarin lesson"   → a proposed Habits Log row (per habit)
    log_checkin    "slept 7.5h, energy 70"      → a proposed Daily Check-In row (create, or update that day's)
    habits_status  "how am I doing?"            → progress against each habit's target, read-only

The two `log_*` tools write directly when the user reported the fact themselves (source "me"):
logs are low-stakes and append-only, so they skip approval (see proposals.record). The queue
row stays as history and `revert` undoes it. Anything inferred (source "assistant") is
proposed for approval as usual. Property names are matched loosely (case, spaces, dashes).
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any
from zoneinfo import ZoneInfo

from . import proposals
from .query import QueryError, parse_date, resolve_database
from .registry import Database
from .values import decode, norm_id
from .workspace import Workspace

HISTORY_DAYS = 180                                  # how far back logs are read (streaks, gaps, adherence)
PERIOD_DAYS = {"DAY": 1, "WEEK": 7, "MONTH": 30}
INACTIVE = {"paused", "archived", "inactive", "dropped", "closed", "abandoned"}
PER_LABEL = {"DAY": "today", "WEEK": "in the last 7 days", "MONTH": "this month"}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _prop(db: Database, *candidates: str) -> str | None:
    for candidate in candidates:
        for p in db.properties:
            if _norm(p.name) == _norm(candidate):
                return p.name
    return None


def _need(db: Database, *candidates: str) -> str:
    name = _prop(db, *candidates)
    if name is None:
        raise QueryError(f"{db.name} has no '{candidates[0]}' property (it has: {', '.join(p.name for p in db.properties)}).")
    return name


def _day(ws: Workspace, text: str) -> dt.date:
    text = "today" if (text or "").strip().lower() in ("", "now") else text
    return dt.date.fromisoformat(parse_date(text, ws.settings.timezone))


# -- log_habit ------------------------------------------------------------------------------
def log_habit(ws: Workspace, habit: str | list[str], date: str = "now", value: float | None = None,
              notes: str | None = None, reason: str = "", source: str = "me", dry_run: bool = False) -> str:
    """Log one Habits Log row per habit (a name, an ID like HAB-1, or a list); direct when source is "me"."""
    reg = ws.registry()
    habits_db, logs_db = resolve_database(reg, "Habits"), resolve_database(reg, "Habits Log")
    habit_rel, date_prop, value_prop = (_need(logs_db, "Habit"), _need(logs_db, "Date"), _need(logs_db, "Value"))
    notes_prop = _prop(logs_db, "Notes", "Note")
    category_rel = _prop(logs_db, "Category")
    if notes and not notes_prop:
        raise QueryError(f"{logs_db.name} has no Notes property, so the note cannot be stored.")
    status_prop, category_of = _prop(habits_db, "Status"), _prop(habits_db, "Category")
    names = [habit] if isinstance(habit, str) else list(habit)
    if not names:
        raise QueryError("Say which habit.")

    changes, titles, warnings = [], [], []
    for name in names:
        pid, title = proposals._resolve_item(ws, habits_db, str(name))
        page = ws.api.page(pid)
        status = decode(page["properties"][status_prop]) if status_prop in page["properties"] else None
        if status and status.lower() in INACTIVE:
            warnings.append(f"{title} is {status}: logged anyway; set it ACTIVE again if it is back.")
        props: dict[str, Any] = {habit_rel: pid, date_prop: date, value_prop: 1 if value is None else value}
        if notes:
            props[notes_prop] = notes
        category = decode(page["properties"][category_of]) if category_rel and category_of in page["properties"] else None
        if category:                                    # the Check button copies the category onto the log; so do we
            props[category_rel] = category
        changes.append({"operation": "CREATE", "database": logs_db.name, "properties": props})
        titles.append(title)

    why = reason.strip() or f"User reported: {', '.join(titles)} ({date})."
    return proposals.record(ws, changes, why, source=source, dry_run=dry_run) + "".join(f"\nNote: {w}" for w in warnings)


# -- log_checkin ----------------------------------------------------------------------------
def _hours(label: str, raw: Any) -> float:
    if isinstance(raw, str) and ":" in raw:                       # "07:45" → 7.75
        hh, _, mm = raw.partition(":")
        try:
            raw = int(hh) + int(mm) / 60
        except ValueError:
            raise QueryError(f"{label}: '{raw}' is not a time like 07:45.") from None
    try:
        number = float(raw)
    except (TypeError, ValueError):
        raise QueryError(f"{label} expects a number of hours (or HH:MM), got {raw!r}.") from None
    if not 0 <= number <= 24:
        raise QueryError(f"{label} must be between 0 and 24, got {number}.")
    return round(number, 2)


def _percent(label: str, raw: Any) -> float:
    try:
        number = float(raw)
    except (TypeError, ValueError):
        raise QueryError(f"{label} expects a number from 0 to 100, got {raw!r}.") from None
    if not 0 <= number <= 100:
        raise QueryError(f"{label} must be between 0 and 100, got {number}.")
    return int(number) if number.is_integer() else number


def log_checkin(ws: Workspace, date: str = "today", sleep_hours: float | str | None = None,
                wakeup_time: float | str | None = None, morning_energy: float | None = None,
                evening_energy: float | None = None, satisfaction: float | None = None,
                log_complete: bool | None = None, note: str | None = None, reason: str = "",
                source: str = "me", dry_run: bool = False) -> str:
    """Record that day's Daily Check-In: a new row, or an update of the existing one (only the fields given)."""
    reg = ws.registry()
    db = resolve_database(reg, "Daily Check-In")
    date_prop = _need(db, "Date")
    day = _day(ws, date).isoformat()
    values: dict[str, Any] = {}
    for arg, raw, candidates, check in (
            ("sleep_hours", sleep_hours, ("Sleep hours",), lambda r: _hours("sleep_hours", r)),
            ("wakeup_time", wakeup_time, ("Wake-up time", "Wakeup"), lambda r: _hours("wakeup_time", r)),
            ("morning_energy", morning_energy, ("Morning Energy",), lambda r: _percent("morning_energy", r)),
            ("evening_energy", evening_energy, ("Evening Energy",), lambda r: _percent("evening_energy", r)),
            ("satisfaction", satisfaction, ("Satisfaction",), lambda r: _percent("satisfaction", r)),
            ("log_complete", log_complete, ("Log Complete",), bool),
            ("note", note, ("Note", "Notes", "Highlight"), str)):
        if raw is None:
            continue
        values[_need(db, *candidates)] = check(raw)
    if not values:
        raise QueryError("Nothing to record: give at least one of sleep_hours, wakeup_time, morning_energy, "
                         "evening_energy, satisfaction, log_complete, note.")

    existing = ws.api.query(db.data_source_id, filter={"and": proposals._day_window(date_prop, day)}, limit=1)
    if existing:
        change = {"operation": "UPDATE", "database": db.name, "item": norm_id(existing[0]["id"]), "properties": values}
    else:
        change = {"operation": "CREATE", "database": db.name, "properties": {date_prop: day, **values}}
    why = reason.strip() or f"User reported their check-in for {day}."
    return proposals.record(ws, [change], why, source=source, dry_run=dry_run)


# -- habits_status --------------------------------------------------------------------------
def _local_day(stamp: str, tz: ZoneInfo) -> dt.date:
    if len(stamp) <= 10:
        return dt.date.fromisoformat(stamp)
    moment = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return (moment.astimezone(tz) if moment.tzinfo else moment).date()


def _period(per: str, today: dt.date) -> tuple[dt.date, dt.date] | None:
    if per == "DAY":
        return today, today
    if per == "WEEK":                                   # a rolling week: today and the 6 days before
        return today - dt.timedelta(days=6), today
    if per == "MONTH":
        first = today.replace(day=1)
        return first, (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    return None


def _count(logs: list[tuple[dt.date, float]], start: dt.date, end: dt.date, measure: str) -> float:
    inside = [(d, v) for d, v in logs if start <= d <= end]
    return sum(v for _, v in inside) if measure == "COUNT" else float(len({d for d, _ in inside}))


def _num(value: float | None) -> str:
    if value is None:
        return "?"
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _streak(logs: list[tuple[dt.date, float]], per: str, target: float, today: dt.date, measure: str,
            floor: dt.date) -> str:
    if per == "DAY":
        done = {d for d, _ in logs}
        day = today if today in done else today - dt.timedelta(days=1)
        n = 0
        while day in done and day >= floor:
            n, day = n + 1, day - dt.timedelta(days=1)
        return f"streak {n}d{'+' if day < floor else ''}" if n else ""
    if per == "WEEK":
        start = today - dt.timedelta(days=6)
        n = 1 if _count(logs, start, today, measure) >= target else 0
        week = start - dt.timedelta(days=7)               # back in blocks of 7 days
        while week >= floor - dt.timedelta(days=7) and _count(logs, week, week + dt.timedelta(days=6), measure) >= target:
            n, week = n + 1, week - dt.timedelta(days=7)
        return f"streak {n} week{'s' if n != 1 else ''}" if n else ""
    return ""


def _adherence(logs, per: str, target: float, measure: str, today: dt.date, days: int, age: int | None) -> float | None:
    """Share of the expected amount actually done in the last `days` days (0..1); a young habit is judged on its age."""
    days = min(days, age) if age is not None else days
    if days < 1:
        return None
    start = today - dt.timedelta(days=days - 1)
    expected = target / PERIOD_DAYS[per] * days
    return min(1.0, _count(logs, start, today, measure) / expected) if expected > 0 else None


def _assess(logs, per: str, target: float, measure: str, today: dt.date, met: bool, started: dt.date | None):
    """(level, gap, since, a28, a84): level 0 lapsed, 1 slipping, 2 due, 3 fine.

    A lapse is judged against the habit's own rhythm: a daily habit missed once is a blip, a
    habit that normally happens every few days and has been dark for weeks is a problem."""
    age = (today - started).days + 1 if started and started <= today else None
    gap = max(PERIOD_DAYS[per] / target, 1.0)
    last = max((d for d, v in logs if v > 0), default=None)
    since = (today - last).days if last else None
    a28 = _adherence(logs, per, target, measure, today, 28, age)
    a84 = _adherence(logs, per, target, measure, today, 84, age)
    dark = since if since is not None else (age if age is not None else HISTORY_DAYS + 1)
    if met:
        return 3, gap, since, a28, a84
    if dark > max(14, 3 * gap):
        return 0, gap, since, a28, a84
    if (a28 is not None and a28 < 0.5 and dark >= 3) or dark >= 2 * gap + 2:
        return 1, gap, since, a28, a84
    return 2, gap, since, a28, a84


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{round(value * 100)}%"


def habits_status(ws: Workspace, date: str = "today", include_inactive: bool = False) -> str:
    """Progress of every active habit against its target, streaks, and whether today's check-in exists."""
    reg, tz = ws.registry(), ws.settings.timezone
    zone = ZoneInfo(tz)
    habits_db, logs_db = resolve_database(reg, "Habits"), resolve_database(reg, "Habits Log")
    h_status, h_measure, h_target = _prop(habits_db, "Status"), _prop(habits_db, "Measure"), _prop(habits_db, "Target")
    h_per, h_type = _prop(habits_db, "Target per"), _prop(habits_db, "Type")
    h_started = _prop(habits_db, "Started")
    l_habit, l_date, l_value = _need(logs_db, "Habit"), _need(logs_db, "Date"), _prop(logs_db, "Value")
    today = _day(ws, date)
    floor = today - dt.timedelta(days=HISTORY_DAYS)

    by_habit: dict[str, list[tuple[dt.date, float]]] = {}
    for row in ws.api.query(logs_db.data_source_id, limit=3000,
                            filter={"property": l_date, "date": {"on_or_after": floor.isoformat()}}):
        stamp = (decode(row["properties"][l_date]) or {}).get("start")
        if not stamp:
            continue
        day = _local_day(stamp, zone)
        if day > today:
            continue
        value = decode(row["properties"][l_value]) if l_value else None
        for pid in decode(row["properties"][l_habit]) or []:
            by_habit.setdefault(pid, []).append((day, 1.0 if value is None else float(value)))

    # Before a habit has a Started date, tracking is assumed to begin with the first log anywhere.
    first_log = min((d for entries in by_habit.values() for d, _ in entries), default=None)
    ranked, fine, limits, loose, skipped = [], [], [], [], 0
    for row in ws.api.query(habits_db.data_source_id, limit=500):
        props = row["properties"]
        title = next((decode(p) for p in props.values() if p["type"] == "title"), None) or "Untitled"
        label = next((decode(p) for p in props.values() if p["type"] == "unique_id"), "") or ""
        status = (decode(props[h_status]) if h_status else None) or ""
        if status.lower() in INACTIVE and not include_inactive:
            skipped += 1
            continue
        measure = ((decode(props[h_measure]) if h_measure else None) or "CHECK").upper()
        target = decode(props[h_target]) if h_target else None
        per = ((decode(props[h_per]) if h_per else None) or "").upper()
        kind = ((decode(props[h_type]) if h_type else None) or "POSITIVE").upper()
        logs = by_habit.get(norm_id(row["id"]), [])
        last = max((d for d, v in logs if v > 0), default=None)
        since = f"last {last} ({(today - last).days}d ago)" if last else f"no log in the last {HISTORY_DAYS} days"
        head = f"{label + ' · ' if label else ''}{title}" + (f" [{status}]" if status.lower() in INACTIVE else "")
        window = _period(per, today)

        started_raw = (decode(props[h_started]) or {}).get("start") if h_started and props.get(h_started) else None
        started = dt.date.fromisoformat(started_raw[:10]) if started_raw else first_log
        if kind == "NEGATIVE":
            if window and target is not None:
                count = _count(logs, *window, measure)
                verdict = "OVER the limit" if count > target else "within the limit"
                avg = _count(logs, today - dt.timedelta(days=27), today, measure) / 28 * PERIOD_DAYS[per]
                limits.append(f"- {head}: {_num(count)}/{_num(target)} {PER_LABEL[per]} (limit) · {verdict} · "
                              f"28d average {avg:.1f} per {PERIOD_DAYS[per]}d · {since}")
            else:
                limits.append(f"- {head}: no limit set · {since}")
        elif window is None or target is None:
            loose.append(f"- {head}: no target set · {since}")
        else:
            count = _count(logs, *window, measure)
            met = count >= target
            level, gap, days_since, a28, a84 = _assess(logs, per, target, measure, today, met, started)
            streak = _streak(logs, per, target, today, measure, floor)
            rhythm = f"usually every {_num(round(gap, 1))}d" if gap > 1 else "daily"
            quiet = ("" if days_since is None else f"quiet for {days_since}d") if level < 3 else ""
            trend = f"28d {_pct(a28)} · 84d {_pct(a84)}"
            parts = [f"{_num(count)}/{_num(target)} {PER_LABEL[per]}" + (" ✓" if met else ""), quiet or None,
                     rhythm if level < 3 else None, trend, streak or None, None if level < 3 else since]
            line = f"- {head}: " + " · ".join(x for x in parts if x)
            if level == 3:
                fine.append(line)
            else:
                ranked.append((level, -(days_since if days_since is not None else HISTORY_DAYS) / gap, line))

    ranked.sort()
    names = {0: "Lapsed: dark far longer than usual", 1: "Slipping", 2: "Due: a short miss, otherwise on rhythm"}
    sections = [(names[lv], [ln for l, _, ln in ranked if l == lv]) for lv in (0, 1, 2)]
    out = [f"Habits on {today} ({today:%a}); weekly targets count the 7 days {today - dt.timedelta(days=6)} → {today}"]
    for title, lines in (*sections, ("Done / on track", fine), ("Limits", limits), ("No target", loose)):
        if lines:
            out += ["", title, *lines]
    if len(out) == 1:
        out.append("\nNo active habits.")
    if skipped:
        out.append(f"\n({skipped} paused or archived habit(s) left out.)")

    checkin_db = reg.find_database("Daily Check-In")
    if checkin_db:
        date_prop = _prop(checkin_db, "Date")
        rows = ws.api.query(checkin_db.data_source_id, limit=1,
                            filter={"and": proposals._day_window(date_prop, today.isoformat())}) if date_prop else []
        complete = _prop(checkin_db, "Log Complete")
        if rows:
            done = decode(rows[0]["properties"][complete]) if complete else None
            out.append(f"\nCheck-in {today}: exists" + (f", Log Complete: {'yes' if done else 'no'}" if complete else ""))
        else:
            out.append(f"\nCheck-in {today}: not logged yet")
    return "\n".join(out)
