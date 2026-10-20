"""Turn simple conditions into Notion filters.

A condition is `property: value`. The value may start with an operator:

    "OPEN"           equal (text: contains)        "!=DONE"     not equal
    ">=2026-10-01"   on/after, greater or equal     "<=+7d"      on/before
    ">5" "<5"        comparisons                    "~cvpr"      contains
    "empty"          no value                       "not empty"  has a value

Dates accept YYYY-MM-DD, today, yesterday, tomorrow, +Nd, -Nd (days from today).
Select/status values are matched case-insensitively. Relations accept a name
or an ID like PER-12.
"""
from __future__ import annotations

import difflib
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .names import Names
from .registry import Database, Property, Registry


class QueryError(ValueError):
    """A problem the model can fix by changing its arguments."""


def _closest(word: str, choices: list[str], n: int = 3) -> str:
    near = difflib.get_close_matches(word, choices, n=n, cutoff=0.3) or choices[:8]
    return ", ".join(near)


def resolve_database(reg: Registry, name: str) -> Database:
    key = name.strip().lower()
    for db in reg.databases:
        if db.name.lower() in (key, key + "s", key.rstrip("s")):
            return db
    names = [d.name for d in reg.databases]
    raise QueryError(f"No database called '{name}'. Closest: {_closest(name, names)}. Call overview to see all.")


def resolve_property(db: Database, name: str) -> Property:
    key = name.strip().lower()
    for prop in db.properties:
        if prop.name.lower() == key:
            return prop
    raise QueryError(f"{db.name} has no property '{name}'. Properties: {', '.join(p.name for p in db.properties)}.")


def parse_date(text: str, tz: str) -> str:
    today = datetime.now(ZoneInfo(tz)).date()
    t = text.strip().lower()
    if t == "today":
        return today.isoformat()
    if t == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    if t == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    m = re.fullmatch(r"([+-]\d+)d", t)
    if m:
        return (today + timedelta(days=int(m.group(1)))).isoformat()
    try:
        return date.fromisoformat(t[:10]).isoformat()
    except ValueError:
        raise QueryError(f"Not a date: '{text}'. Use YYYY-MM-DD, today, yesterday, tomorrow, +7d or -30d.")


def _split_operator(raw: str) -> tuple[str, str]:
    raw = str(raw).strip()
    if raw.lower() in ("empty", "not empty"):
        return raw.lower(), ""
    for op in (">=", "<=", "!=", ">", "<", "~", "="):
        if raw.startswith(op):
            return op, raw[len(op):].strip()
    return "", raw


def build_filter(reg: Registry, db: Database, where: dict[str, str], names: Names, tz: str,
                 notes: list[str] | None = None) -> dict | None:
    """`notes` collects remarks for the reader, e.g. how a fuzzy name was matched."""
    notes = notes if notes is not None else []
    parts = [_condition(reg, db, resolve_property(db, key), value, names, tz, notes) for key, value in where.items()]
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else {"and": parts}


def _condition(reg: Registry, db: Database, prop: Property, raw: str, names: Names, tz: str,
               notes: list[str]) -> dict:
    op, value = _split_operator(raw)
    kind = prop.type
    base = {"property": prop.name}
    if op in ("empty", "not empty"):
        key = "is_empty" if op == "empty" else "is_not_empty"
        if kind in ("formula", "rollup", "unique_id"):
            raise QueryError(f"Can't test '{prop.name}' for emptiness.")
        return {**base, kind: {key: True}}

    if kind in ("title", "rich_text", "url", "email", "phone_number"):
        cond = {"=": "equals", "!=": "does_not_equal", "~": "contains", "": "contains"}.get(op)
        if not cond:
            raise QueryError(f"'{prop.name}' is text: use a value, =value, !=value or ~value.")
        return {**base, kind: {cond: value}}

    if kind in ("select", "status", "multi_select"):
        options = [o.name for o in prop.options]
        match = next((o for o in options if o.lower() == value.lower()), None)
        if match is None:
            raise QueryError(f"'{value}' is not an option of {prop.name}. Options: {', '.join(options)}.")
        if kind == "multi_select":
            return {**base, kind: {"does_not_contain" if op == "!=" else "contains": match}}
        return {**base, kind: {"does_not_equal" if op == "!=" else "equals": match}}

    if kind == "date":
        day = parse_date(value, tz)
        cond = {"": "equals", "=": "equals", ">=": "on_or_after", "<=": "on_or_before",
                ">": "after", "<": "before"}.get(op)
        if not cond:
            raise QueryError(f"'{prop.name}' is a date: use =, >=, <=, > or <.")
        return {**base, "date": {cond: day}}

    if kind == "number":
        cond = {"": "equals", "=": "equals", "!=": "does_not_equal", ">=": "greater_than_or_equal_to",
                "<=": "less_than_or_equal_to", ">": "greater_than", "<": "less_than"}.get(op)
        try:
            return {**base, "number": {cond: float(value)}}
        except (TypeError, ValueError):
            raise QueryError(f"'{prop.name}' is a number: '{raw}' is not.")

    if kind == "checkbox":
        return {**base, "checkbox": {"equals": value.lower() in ("yes", "true", "1", "checked")}}

    if kind == "relation":
        target = reg.database_by_id(prop.relation_to)
        if target is None:
            raise QueryError(f"'{prop.name}' links to a database outside the workspace.")
        found = names.match(target, value)
        if not found:
            raise QueryError(f"No item in {target.name} matches '{value}'. Use find on {target.name} to look.")
        best, score = found[0]
        close = [i for i, s in found[1:] if s >= score - 0.05]
        if close and score < 1.0:
            options = ", ".join(f"{i.title} ({i.label})" if i.label else i.title for i in [best] + close)
            raise QueryError(f"'{value}' matches several {target.name}: {options}. Be more specific.")
        if score < 1.0:
            notes.append(f"{prop.name} '{value}' matched {best.title}{' (' + best.label + ')' if best.label else ''}")
        return {**base, "relation": {"does_not_contain" if op == "!=" else "contains": best.page_id}}

    if kind == "formula":
        # The result type isn't in the schema: infer it from the value.
        try:
            day = parse_date(value, tz)
            cond = {"": "equals", "=": "equals", ">=": "on_or_after", "<=": "on_or_before",
                    ">": "after", "<": "before"}[op]
            return {**base, "formula": {"date": {cond: day}}}
        except (QueryError, KeyError):
            pass
        try:
            number = float(value)
            cond = {"": "equals", "=": "equals", "!=": "does_not_equal", ">=": "greater_than_or_equal_to",
                    "<=": "less_than_or_equal_to", ">": "greater_than", "<": "less_than"}[op]
            return {**base, "formula": {"number": {cond: number}}}
        except (ValueError, KeyError):
            pass
        cond = {"": "contains", "~": "contains", "=": "equals", "!=": "does_not_equal"}.get(op, "contains")
        return {**base, "formula": {"string": {cond: value}}}

    raise QueryError(f"Filtering on '{prop.name}' ({kind}) isn't supported yet.")


def build_sort(db: Database, sort: str | None) -> list[dict]:
    """`sort` is a property name, prefixed with '-' for descending."""
    if not sort:
        return [{"timestamp": "last_edited_time", "direction": "descending"}]
    descending = sort.startswith("-")
    prop = resolve_property(db, sort.lstrip("-+ "))
    return [{"property": prop.name, "direction": "descending" if descending else "ascending"}]
