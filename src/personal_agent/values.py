"""Turn Notion property values into plain Python values.

Each property becomes one of: str, number, bool, a date dict, a list of str,
or a list of related page IDs. Unknown types become None.
"""
from __future__ import annotations

from typing import Any

from .notion_api import plain_text


def norm_id(page_id: str) -> str:
    return page_id.replace("-", "")


def decode(prop: dict) -> Any:
    kind = prop.get("type")
    value = prop.get(kind)
    if value is None:
        return None
    if kind in ("title", "rich_text"):
        return plain_text(value) or None
    if kind in ("select", "status"):
        return value.get("name")
    if kind == "multi_select":
        return [o["name"] for o in value] or None
    if kind == "date":
        return {"start": value.get("start"), "end": value.get("end")}
    if kind in ("number", "checkbox", "url", "email", "phone_number"):
        return value
    if kind == "relation":
        return [norm_id(r["id"]) for r in value] or None
    if kind == "unique_id":
        number = value.get("number")
        return f"{value['prefix']}-{number}" if value.get("prefix") else (str(number) if number is not None else None)
    if kind == "formula":
        return decode({"type": value.get("type"), value.get("type"): value.get(value.get("type"))})
    if kind == "rollup":
        sub = value.get("type")
        if sub == "array":
            items = [decode(v) for v in value.get("array", [])]
            return [i for i in items if i not in (None, [], "")] or None
        return decode({"type": sub, sub: value.get(sub)})
    if kind == "people":
        return [p.get("name") or p.get("id") for p in value] or None
    if kind in ("created_time", "last_edited_time"):
        return value
    if kind == "place":
        return value.get("name") or value.get("address")
    if kind == "files":
        return [f.get("name") for f in value] or None
    return None


def format_date(value: dict | None) -> str:
    if not value or not value.get("start"):
        return ""
    start = value["start"][:16].replace("T", " ")
    end = (value.get("end") or "")[:16].replace("T", " ")
    return f"{start} → {end}" if end else start


def format_value(value: Any) -> str:
    """Plain text for a decoded value (relations must be resolved first)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, dict) and "start" in value:
        return format_date(value)
    if isinstance(value, list):
        return ", ".join(format_value(v) for v in value if v not in (None, ""))
    return str(value)
