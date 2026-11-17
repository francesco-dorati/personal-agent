"""Domain wrappers: thin layers that build changes and hand them to `proposals.propose`.

    log_interaction       the dump-and-file workflow: an interaction plus the commitments it created
    add_commitment        a new commitment (verb-first name, due date, links)
    complete_commitment   DONE or DROPPED, optionally linking the interaction that closed it
    update_item           change fields of any item; can stamp Last Reviewed
    set_inactive          retire an item (nothing is ever deleted)
    add_person / add_organization   check for look-alikes first, then create
    log_conversation      a conversation worth remembering (summary + link), plus follow-ups

Like everything that writes, these only put PENDING rows in the Assistant Queue.
"""
from __future__ import annotations

import difflib
import re
from typing import Any

from . import proposals
from .habits import _need
from .query import QueryError, resolve_database
from .workspace import Workspace


def _listed(value: Any) -> list | None:
    if value is None:
        return None
    return [value] if isinstance(value, str) else list(value)


def _fill(db, props: dict[str, Any], spec: list[tuple[Any, tuple[str, ...]]]) -> None:
    """Copy every given (non-None, non-empty) argument onto the property it names."""
    for value, candidates in spec:
        if value is None or value == [] or value == "":
            continue
        props[_need(db, *candidates)] = value


def _create(db_name: str, props: dict, allow_duplicate: bool = False, body: str | None = None) -> dict:
    change = {"operation": "CREATE", "database": db_name, "properties": props}
    if allow_duplicate:
        change["allow_duplicate"] = True
    if body and body.strip():
        change["body"] = body
    return change


def _propose(ws, changes, reason, default_reason, source, dry_run):
    return proposals.propose(ws, changes, reason.strip() or default_reason, source=source, dry_run=dry_run)


# -- interactions and commitments -------------------------------------------------------------
def _commitment_props(db, spec: dict, inherit_people: list | None, interaction_ref: str | None) -> dict:
    allowed = {"name", "due", "importance", "kind", "status", "people", "goals", "areas", "opportunities",
               "open_questions", "period"}
    extra = set(spec) - allowed
    if extra:
        raise QueryError(f"Unknown commitment field(s): {', '.join(sorted(extra))}. Use: {', '.join(sorted(allowed))}.")
    if not spec.get("name"):
        raise QueryError("Every commitment needs a name, starting with a verb (e.g. 'Send the draft').")
    props: dict[str, Any] = {}
    people = _listed(spec.get("people")) or inherit_people
    status = spec.get("status") or "OPEN"
    _fill(db, props, [
        (spec["name"], ("Name",)), (spec.get("due"), ("Due",)), (spec.get("importance"), ("Importance",)),
        (spec.get("kind"), ("Kind",)), (status, ("Status",)), (people, ("People",)),
        (_listed(spec.get("goals")), ("Goals",)), (_listed(spec.get("areas")), ("Areas",)),
        (_listed(spec.get("opportunities")), ("Opportunities",)),
        (_listed(spec.get("open_questions")), ("Open Questions",)), (spec.get("period"), ("Period",)),
        (interaction_ref, ("Origin",))])
    return props


def log_interaction(ws: Workspace, name: str, date: str = "now", type: str | None = None, category: str | None = None,
                    direction: str | None = None, description: str | None = None,
                    people: list[str] | str | None = None, organizations: list[str] | str | None = None,
                    opportunities: list[str] | str | None = None, areas: list[str] | str | None = None,
                    goals: list[str] | str | None = None, commitments: list[dict] | None = None,
                    reason: str = "", source: str = "me", dry_run: bool = False, body: str | None = None) -> str:
    """Propose an interaction (something that happened) together with the commitments it created, linked.
    `body` (Markdown) becomes the content of the interaction's page, e.g. the meeting notes."""
    reg = ws.registry()
    idb, cdb = resolve_database(reg, "Interactions"), resolve_database(reg, "Commitments")
    people_l = _listed(people)
    props: dict[str, Any] = {}
    _fill(idb, props, [
        (name, ("Name",)), (date, ("Date",)), (type, ("Type",)), (category, ("Category",)),
        (direction, ("Direction",)), (description, ("Description",)), (people_l, ("People",)),
        (_listed(organizations), ("Organizations",)), (_listed(opportunities), ("Opportunities",)),
        (_listed(areas), ("Areas",)), (_listed(goals), ("Goals",))])
    changes = [_create(idb.name, props, body=body)]
    for spec in commitments or []:
        if not isinstance(spec, dict):
            raise QueryError("Each commitment must be an object like {name, due, importance, kind, people}.")
        changes.append(_create(cdb.name, _commitment_props(cdb, spec, people_l, "$1")))
    return _propose(ws, changes, reason, f"User reported: {name} ({date}).", source, dry_run)


def add_commitment(ws: Workspace, name: str, due: str | None = None, importance: str | None = None,
                   kind: str | None = None, people: list[str] | str | None = None,
                   goals: list[str] | str | None = None, areas: list[str] | str | None = None,
                   opportunities: list[str] | str | None = None, origin: str | None = None,
                   period: str | None = None, reason: str = "", source: str = "me", dry_run: bool = False) -> str:
    """Propose one commitment. `origin` is the interaction (ID like INT-16 or title) it came from."""
    cdb = resolve_database(ws.registry(), "Commitments")
    props = _commitment_props(cdb, {"name": name, "due": due, "importance": importance, "kind": kind,
                                    "people": people, "goals": goals, "areas": areas,
                                    "opportunities": opportunities, "period": period}, None, origin)
    return _propose(ws, [_create(cdb.name, props)], reason, f"User asked to track: {name}.", source, dry_run)


def complete_commitment(ws: Workspace, commitment: str, status: str = "DONE", done_via: str | None = None,
                        reason: str = "", source: str = "me", dry_run: bool = False) -> str:
    """Propose closing a commitment (DONE, or DROPPED), optionally linking the interaction that did it."""
    cdb = resolve_database(ws.registry(), "Commitments")
    if status.strip().upper() not in ("DONE", "DROPPED"):
        raise QueryError("status must be DONE or DROPPED.")
    props: dict[str, Any] = {_need(cdb, "Status"): status.strip().upper()}
    if done_via:
        props[_need(cdb, "Done via")] = [done_via]
    change = {"operation": "UPDATE", "database": cdb.name, "item": commitment, "properties": props}
    return _propose(ws, [change], reason, f"User said {commitment} is {status.lower()}.", source, dry_run)


# -- generic edits --------------------------------------------------------------------------
def update_item(ws: Workspace, database: str, item: str, fields: dict[str, Any] | None = None,
                reviewed: bool = False, reason: str = "", source: str = "me", dry_run: bool = False) -> str:
    """Propose changing fields of one item. `reviewed=True` also sets Last Reviewed to today."""
    db = resolve_database(ws.registry(), database)
    props = dict(fields or {})
    if reviewed:
        props[_need(db, "Last Reviewed")] = "today"
    if not props:
        raise QueryError("Nothing to change: give `fields` (and/or reviewed=true).")
    change = {"operation": "UPDATE", "database": db.name, "item": item, "properties": props}
    return _propose(ws, [change], reason, f"User asked to update {item}.", source, dry_run)


def set_inactive(ws: Workspace, database: str, item: str, reason: str = "", source: str = "me",
                 dry_run: bool = False) -> str:
    """Propose retiring an item by setting its status to the inactive option. Never deletes."""
    db = resolve_database(ws.registry(), database)
    change = {"operation": "SET-INACTIVE", "database": db.name, "item": item}
    return _propose(ws, [change], reason, f"User asked to retire {item}.", source, dry_run)


# -- people and organizations: check before create ---------------------------------------------
def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _look_alikes(ws: Workspace, db, name: str) -> list[str]:
    target, found = name.strip().lower(), []
    for entry in ws.names.items(db, fresh=True).values():
        title = entry.title.strip().lower()
        a, b = _words(title), _words(target)
        close = (title == target or difflib.SequenceMatcher(None, title, target).ratio() >= 0.8
                 or (a and b and (a <= b or b <= a) and min(len(a), len(b)) >= 1 and len(a & b) >= min(2, len(a), len(b))))
        if close:
            found.append(f"{entry.title}{' (' + entry.label + ')' if entry.label else ''}")
    return found


def _add_entity(ws, db_name, name, spec, allow_duplicate, reason, source, dry_run):
    db = resolve_database(ws.registry(), db_name)
    same = [] if allow_duplicate else _look_alikes(ws, db, name)
    if same:
        raise QueryError(f"{db.name} already has something like '{name}': {', '.join(same[:5])}. "
                         "Use that item (update_item), or pass allow_duplicate=true if it is really a different one.")
    props: dict[str, Any] = {}
    _fill(db, props, [(name, ("Name",)), *spec])
    return _propose(ws, [_create(db.name, props, allow_duplicate)], reason, f"User asked to add {name}.", source, dry_run)


def add_person(ws: Workspace, name: str, organization: str | None = None, title: str | None = None,
               relationship: str | None = None, familiarity: str | None = None, email: str | None = None,
               summary: str | None = None, fields: list[str] | str | None = None,
               areas: list[str] | str | None = None, channels: str | None = None,
               allow_duplicate: bool = False, reason: str = "", source: str = "me", dry_run: bool = False) -> str:
    """Propose a new person, after checking nobody similar exists."""
    spec = [(organization, ("Organization",)), (title, ("Title",)), (relationship, ("Relationship",)),
            (familiarity, ("Familiarity",)), (email, ("E-Mail", "Email")), (summary, ("Summary",)),
            (_listed(fields), ("Fields",)), (_listed(areas), ("Related Areas", "Areas")),
            (channels, ("Contact Channels",))]
    return _add_entity(ws, "People", name, spec, allow_duplicate, reason, source, dry_run)


def add_organization(ws: Workspace, name: str, category: str | None = None, relationship: str | None = None,
                     website: str | None = None, country: str | None = None, fields: list[str] | str | None = None,
                     part_of: str | None = None, allow_duplicate: bool = False, reason: str = "",
                     source: str = "me", dry_run: bool = False) -> str:
    """Propose a new organization, after checking nothing similar exists."""
    spec = [(category, ("Category",)), (relationship, ("Relationship",)), (website, ("Website",)),
            (country, ("Country",)), (_listed(fields), ("Fields",)), (part_of, ("Part Of",))]
    return _add_entity(ws, "Organizations", name, spec, allow_duplicate, reason, source, dry_run)


# -- conversations ----------------------------------------------------------------------------
OUTCOMES = ("CHANGED", "NO-CHANGE", "OPEN")


def log_conversation(ws: Workspace, title: str, summary: str, date: str = "today", conclusions: str | None = None,
                     outcome: str = "NO-CHANGE", link: str | None = None, areas: list[str] | str | None = None,
                     goals: list[str] | str | None = None, open_questions: list[str] | str | None = None,
                     people: list[str] | str | None = None, commitments: list[str] | str | None = None,
                     follow_ups: list[dict] | None = None, reason: str = "", source: str = "assistant",
                     dry_run: bool = False, body: str | None = None) -> str:
    """Propose a Conversations record: what was explored and concluded, linked to what it touched.

    `commitments` links existing ones; `follow_ups` creates new commitments, linked to the record."""
    reg = ws.registry()
    try:
        db = resolve_database(reg, "Conversations")
    except QueryError as err:
        raise QueryError(f"{err} Create it with `uv run python scripts/add_conversations_db.py --apply`.") from err
    if not (summary or "").strip():
        raise QueryError("`summary` is required: 3-6 lines on what was explored and concluded.")
    if str(outcome).upper() not in OUTCOMES:
        raise QueryError(f"`outcome` must be one of {', '.join(OUTCOMES)}.")
    changes = []
    if follow_ups:
        cdb = resolve_database(reg, "Commitments")
        for spec in follow_ups:
            if not isinstance(spec, dict):
                raise QueryError("Each follow-up must be an object like {name, due, importance, kind}.")
            changes.append(_create(cdb.name, _commitment_props(cdb, spec, _listed(people), None)))
    linked = (_listed(commitments) or []) + [f"${n}" for n in range(1, len(changes) + 1)]
    props: dict[str, Any] = {}
    _fill(db, props, [
        (title, ("Name",)), (date, ("Date",)), (summary.strip(), ("Summary",)),
        ((conclusions or "").strip(), ("Conclusions",)), (str(outcome).upper(), ("Outcome",)), (link, ("Link",)),
        (_listed(areas), ("Areas",)), (_listed(goals), ("Goals",)), (_listed(open_questions), ("Open Questions",)),
        (_listed(people), ("People",)), (linked, ("Commitments",))])
    changes.append(_create(db.name, props, body=body))  # last: it links the follow-ups created before it
    return _propose(ws, changes, reason, f"Conversation worth keeping: {title} ({date}).", source, dry_run)
