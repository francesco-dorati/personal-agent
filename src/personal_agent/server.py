"""MCP server: exposes the tools in `tools.py` to any MCP client.

Run with `agent-mcp` (stdio transport, for Claude Desktop / Code) or
`agent-mcp --transport http` (one long-lived server several clients connect to;
needs PERSONAL_AGENT_TOKEN, see README "Running it over HTTP").
"""
from __future__ import annotations

import argparse
import functools
import hmac
import inspect
import logging
import os
import threading
import time
import traceback
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from . import calllog, domain, habits, proposals, review as review_mod, tools
from .config import load_settings
from .guide import guide_text
from .notion_api import NotionError
from .query import QueryError
from .workspace import Workspace

mcp = MCPServer(
    "personal-agent",
    instructions=(
        "Read the user's personal Notion workspace: their life, work, meetings, "
        "commitments (tasks), people, goals and areas. Prefer these tools over a "
        "generic Notion connector for reading. If you have not been given the "
        "workspace guide, call `guide` first; then start with `overview`. Use `search` "
        "when you only know a name, `find` to list or filter one database. "
        "To change anything, use `propose` or a shortcut: it only writes a PENDING row in the "
        "Assistant Queue. Show the user the preview and wait for their OK; then `approve` and "
        "`apply`. Exception: habit logs and check-ins the user reported (`log_habit`, "
        "`log_checkin`) are written at once. `review` gives the weekly review. "
        "Nothing is ever deleted."
    ),
)
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITES = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)
log = logging.getLogger("personal-agent")


def _safe(fn):
    """Report failures as error results (is_error=True) the model can read.

    Expected problems (bad arguments, Notion refusing a request) pass their
    message through. Anything else is logged with its traceback and reported
    with its type and message, so the model can still tell the user what broke.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except (QueryError, NotionError) as err:
            raise ToolError(str(err)) from err
        except Exception as err:   # noqa: BLE001 - report everything to the client
            log.error("%s failed:\n%s", fn.__name__, traceback.format_exc())
            raise ToolError(f"Error in {fn.__name__}: {type(err).__name__}: {err}") from err
    return wrapper


_ws: Workspace | None = None


def _workspace() -> Workspace:
    global _ws
    if _ws is None:
        _ws = Workspace()
    return _ws


def _requests() -> int:
    """Notion requests made so far (0 before the first call)."""
    return _ws.api.request_count if _ws is not None and "api" in _ws.__dict__ else 0


def _logged(fn):
    """Write each call to the local call log (see calllog.py)."""
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        started, before = time.monotonic(), _requests()
        arguments = dict(signature.bind_partial(*args, **kwargs).arguments)
        try:
            result = fn(*args, **kwargs)
        except Exception as err:   # noqa: BLE001 - recorded, then re-raised for _safe
            calllog.record(fn.__name__, arguments, started, 0, _requests() - before,
                           error=f"{type(err).__name__}: {err}")
            raise
        calllog.record(fn.__name__, arguments, started, len(result), _requests() - before)
        return result
    return wrapper


@mcp.tool(annotations=READ_ONLY)
@_safe
@_logged
def overview(
    refresh: Annotated[bool, Field(description="Rebuild the map from Notion (about 30 s). "
                                               "Only after the structure changed.")] = False,
) -> str:
    """Map of the user's personal Notion workspace: every section, page and
    database (meetings/interactions, commitments/tasks, people, organizations,
    goals, areas, priorities…), what each is for and how many items it holds.
    Call this at the start of a session, before answering anything about the
    user."""
    return tools.overview(_workspace(), refresh=refresh)


@mcp.tool(annotations=READ_ONLY)
@_safe
@_logged
def find(
    database: Annotated[str, Field(description='Database name exactly as shown by overview, e.g. "Interactions".')],
    where: Annotated[dict[str, str] | None, Field(description=(
        'Filters as {property: value}. A value may start with an operator: "!=DONE", "~word" (contains), '
        '">=2026-10-01", "<=+7d", ">5", "empty", "not empty"; plain text equals (text: contains). '
        "Dates: YYYY-MM-DD, today, yesterday, tomorrow, +Nd, -Nd. Links: a name or ID, "
        'e.g. {"People": "Acar Cihan"}.'))] = None,
    search: Annotated[str | None, Field(description="Text the title contains.")] = None,
    sort: Annotated[str | None, Field(description='Property name, "-" prefix for descending, e.g. "-Due". '
                                                  "Default: recently edited.")] = None,
    limit: Annotated[int, Field(description="Maximum rows to return; the server caps it.")] = 20,
) -> str:
    """List items of one database in the user's Notion workspace, filtered by
    property values. Use the names shown by `overview`: "Interactions" for
    meetings/calls/emails, "Commitments" for tasks and deadlines, "People".
    Links to other items are shown as names; each row has an ID (e.g. INT-14)
    to pass to `get` for its full content.

    Example: find("Interactions", {"Date": "yesterday"})."""
    return tools.find(_workspace(), database, where, search, sort, limit)


@mcp.tool(annotations=READ_ONLY)
@_safe
@_logged
def search(
    text: Annotated[str, Field(description="Part of a title or an ID, e.g. a person, company or project name. "
                                           "Misspellings are tolerated.")],
    databases: Annotated[list[str] | None, Field(description="Only these databases (names as shown by overview). "
                                                              "Default: all databases and pages.")] = None,
    limit: Annotated[int, Field(description="Maximum matches to return (default 15, at most 50).")] = 15,
) -> str:
    """Find items of the user's Notion workspace by name when you do not know
    which database they live in: people, organizations, meetings, commitments,
    goals, pages. Returns ID, title and database for each match, best first.
    Searches titles and IDs only, not the text inside notes. Open a match with
    `get`."""
    return tools.search(_workspace(), text, databases, limit)


@mcp.tool(annotations=READ_ONLY)
@_safe
@_logged
def get(
    item: Annotated[str | list[str], Field(description=(
        "An ID like INT-14 or PER-2 (best), a page ID or link, or a title. "
        "Pass a list (at most 10) to open several at once."))],
    database: Annotated[str | None, Field(description="Narrow a title lookup to one database.")] = None,
    offset: Annotated[int, Field(description="Character offset into the page content, to read the rest of a "
                                             "long page. The truncation notice gives the value to use.")] = 0,
) -> str:
    """Open one item of the user's Notion workspace with everything in it:
    all properties, linked items (with their IDs) and the page content, e.g.
    meeting notes. Also opens text pages such as "Profile" or "Professional
    Direction". Long pages are cut after about 8000 characters, with a notice
    saying how to continue. If a title is ambiguous you get the candidates:
    ask the user which one."""
    return tools.get(_workspace(), item, database, offset)


@mcp.tool(annotations=READ_ONLY)
@_safe
@_logged
def person(
    name: Annotated[str, Field(description="Name as heard or written; misspellings are fine.")],
) -> str:
    """Look up a person in the user's People database by name, tolerating
    misspellings (e.g. from meeting transcripts), and return their details,
    organization, recent interactions and links. Use the spelling it returns.
    If the name is unclear you get the closest people: ask the user."""
    return tools.person(_workspace(), name)


@mcp.tool(annotations=READ_ONLY)
@_safe
@_logged
def agenda(
    start: Annotated[str, Field(description="First day: YYYY-MM-DD, today, yesterday, tomorrow, +Nd or -Nd.")] = "today",
    end: Annotated[str, Field(description="Last day, same formats.")] = "+7d",
) -> str:
    """What is dated in a period across the user's whole Notion workspace:
    commitments due, meetings and interactions, goal target dates, decisions
    to make, deadlines, grouped by day, plus overdue items that are not done.
    For "what did I do yesterday" use start="yesterday", end="yesterday"."""
    return tools.agenda(_workspace(), start, end)


@mcp.tool(annotations=WRITES)
@_safe
@_logged
def propose(
    changes: Annotated[list[dict[str, Any]], Field(description=(
        "The changes, each {operation, database, item?, properties?, allow_duplicate?}. operation: CREATE, UPDATE or "
        "SET-INACTIVE (there is no delete). database: name as shown by overview. item: for UPDATE and SET-INACTIVE, an "
        "ID like HAB-1, a page ID or a title. properties: {property: value}; select values must be existing options; "
        "relations take names or IDs; dates take YYYY-MM-DD, 'YYYY-MM-DD HH:MM' (user's time zone), now, today, "
        "yesterday. In a batch, refer to the Nth new item as '$N', e.g. {\"Habit\": \"$1\"}. A log row's Name is "
        "taken from the habit it links if omitted. body?: Markdown for the page content (CREATE: the new page's body; "
        "UPDATE: added at the end of the page, alone or with properties): headings, lists, - [ ] to-dos, quotes, "
        "code, **bold**, [links](url)."))],
    reason: Annotated[str, Field(description="Why, with the evidence: quote the user's words or the email.")],
    source: Annotated[str, Field(description='"me" if the user dictated it, "assistant" if you inferred it, '
                                             '"import" if it came from an email or document.')] = "assistant",
    dry_run: Annotated[bool, Field(description="Validate and show the preview without creating queue rows.")] = False,
) -> str:
    """Propose changes to the user's Notion workspace. This writes only PENDING
    rows in the Assistant Queue; nothing else changes until the user approves and
    the change is applied. Everything is validated first (properties, options,
    relations, duplicates, one check-in per day) and a bad change rejects the whole
    proposal. Show the user the returned preview and ask. Never delete: use
    SET-INACTIVE.

    The user can edit the proposal before approving it: every value, an extra
    'Property: value' line, and the body, directly in the queue row's page in
    Notion. approve, apply and queue always use their edited version (marked
    ✎): show it as it is, never write the original values back, and never
    "correct" an edit. To change a pending proposal yourself, reject it and
    propose again.

    Example: propose([{"operation": "CREATE", "database": "Habits Log",
    "properties": {"Habit": "Learn Mandarin", "Date": "now", "Value": 1}}],
    reason="User: 'did my Mandarin lesson'")."""
    return proposals.propose(_workspace(), changes, reason, source, dry_run=dry_run)


@mcp.tool(annotations=READ_ONLY)
@_safe
@_logged
def queue(
    status: Annotated[str, Field(description="PENDING (default), APPROVED, APPLIED, FAILED, REJECTED, EXPIRED or ALL.")] = "PENDING",
    batch: Annotated[str | None, Field(description="Only this batch (B-…).")] = None,
    limit: Annotated[int, Field(description="Maximum rows (at most 100).")] = 30,
) -> str:
    """List the Assistant Queue: what was proposed, its preview, and for finished
    rows what happened. Numbers like #12 are the IDs for approve, reject, apply.
    Open rows show the user's edited version (marked ✎) when they changed
    something in the row: that is what will be written."""
    return proposals.queue(_workspace(), status, batch, limit)


@mcp.tool(annotations=WRITES)
@_safe
@_logged
def approve(
    ids: Annotated[list[str | int] | None, Field(description="Queue numbers, e.g. [12, 13].")] = None,
    batch: Annotated[str | None, Field(description="A whole batch (B-…).")] = None,
    approved_by: Annotated[str, Field(description="The user's own words agreeing to these changes. Required; stored on the row.")] = "",
    confirmed: Annotated[bool, Field(description="Only after the user explicitly confirmed closing a goal or question, "
                                                 "or changing a target date.")] = False,
) -> str:
    """Mark PENDING rows APPROVED. Call this only after the user has said yes to
    exactly what the preview showed; never to move work along on your own. Context
    changes are approved one at a time. If the user edited the row, the reply
    shows the final values: tell them what will be written. An edit that cannot
    be applied (unknown option, bad date) blocks approval and says why.
    Disabled for background workers."""
    return proposals.approve(_workspace(), ids, batch, approved_by, confirmed)


@mcp.tool(annotations=WRITES)
@_safe
@_logged
def reject(
    ids: Annotated[list[str | int] | None, Field(description="Queue numbers.")] = None,
    batch: Annotated[str | None, Field(description="A whole batch (B-…).")] = None,
    reason: Annotated[str, Field(description="Why it was declined.")] = "",
) -> str:
    """Mark PENDING or APPROVED rows REJECTED. Nothing is applied."""
    return proposals.reject(_workspace(), ids, batch, reason)


@mcp.tool(annotations=WRITES)
@_safe
@_logged
def apply(
    ids: Annotated[list[str | int] | None, Field(description="Queue numbers to apply. Omit to apply every APPROVED row.")] = None,
    batch: Annotated[str | None, Field(description="A whole batch (B-…).")] = None,
    dry_run: Annotated[bool, Field(description="Check what would happen without changing anything.")] = False,
) -> str:
    """Perform APPROVED queue rows: create or update the real items, link them,
    and record the outcome on each row. Rows that are not APPROVED are never
    touched. An update fails (and says so) if the value changed since it was
    proposed. Context changes are applied one at a time. Disabled for background workers."""
    return proposals.apply(_workspace(), ids, batch, dry_run)


@mcp.tool(annotations=WRITES)
@_safe
@_logged
def revert(
    id: Annotated[str | int, Field(description="Queue number of an APPLIED row.")],
) -> str:
    """Propose the inverse of an applied change as a new PENDING row: an update
    restores the old values, a creation becomes inactive. Needs approval like
    anything else."""
    return proposals.revert(_workspace(), id)


@mcp.tool(annotations=READ_ONLY)
@_safe
@_logged
def refresh() -> str:
    """Start reloading the workspace map and all names from Notion (runs in the background, 1-2 minutes). Normally
    unnecessary: the server refreshes itself in the background. Call it after the
    user changed the structure of a database and the change is not showing up."""
    return tools.refresh(_workspace())


@mcp.tool(annotations=WRITES)
@_safe
@_logged
def log_habit(
    habit: Annotated[str | list[str], Field(description="Habit name, ID like HAB-1, or a list of them.")],
    date: Annotated[str, Field(description="YYYY-MM-DD, 'YYYY-MM-DD HH:MM', now, today or yesterday.")] = "now",
    value: Annotated[float | None, Field(description="Amount (pages, minutes, drinks). Default 1.")] = None,
    notes: Annotated[str | None, Field(description="Optional note stored on the log.")] = None,
    reason: Annotated[str, Field(description="The user's words. Defaults to a generic line.")] = "",
    source: Annotated[str, Field(description='"me" if dictated, "assistant" if inferred, "import" if from a document.')] = "me",
    dry_run: Annotated[bool, Field(description="Show the preview without writing anything.")] = False,
) -> str:
    """Log that the user did a habit: one Habits Log row per habit. When the user
    said it (source "me") it is written at once, no approval needed; if you
    inferred it (source "assistant") it is proposed for approval. Warns if the
    habit is paused/archived or already logged that day.

    Example: log_habit("Learn Mandarin", notes="lesson 12")."""
    return habits.log_habit(_workspace(), habit, date, value, notes, reason, source, dry_run)


@mcp.tool(annotations=WRITES)
@_safe
@_logged
def log_checkin(
    date: Annotated[str, Field(description="Day of the check-in: YYYY-MM-DD, today or yesterday.")] = "today",
    sleep_hours: Annotated[float | str | None, Field(description="Hours slept, 0-24 (7.5 or '7:30').")] = None,
    wakeup_time: Annotated[float | str | None, Field(description="Wake-up time as 'HH:MM' or decimal hours (7.75).")] = None,
    morning_energy: Annotated[float | None, Field(description="0-100.")] = None,
    evening_energy: Annotated[float | None, Field(description="0-100.")] = None,
    satisfaction: Annotated[float | None, Field(description="0-100.")] = None,
    log_complete: Annotated[bool | None, Field(description="True when the day's habit logs are all in (unlogged then means not done).")] = None,
    note: Annotated[str | None, Field(description="Free text for the day.")] = None,
    reason: Annotated[str, Field(description="The user's words.")] = "",
    source: Annotated[str, Field(description='"me", "assistant" or "import".')] = "me",
    dry_run: Annotated[bool, Field(description="Show the preview without writing anything.")] = False,
) -> str:
    """Record the day's Daily Check-In. Creates the day's row, or updates it if it
    exists (only the fields given). Written at once when the user said it
    (source "me"); proposed for approval otherwise.

    Example: log_checkin(sleep_hours=7.5, morning_energy=70, log_complete=True)."""
    return habits.log_checkin(_workspace(), date, sleep_hours, wakeup_time, morning_energy, evening_energy,
                              satisfaction, log_complete, note, reason, source, dry_run)


@mcp.tool(annotations=READ_ONLY)
@_safe
@_logged
def habits_status(
    date: Annotated[str, Field(description="Reference day; default today.")] = "today",
    include_inactive: Annotated[bool, Field(description="Also list paused/archived habits.")] = False,
) -> str:
    """How the user is doing on each active habit: progress against target for the
    day/week, streaks, limits for negative habits, what is unlogged, and whether
    today's check-in exists."""
    return habits.habits_status(_workspace(), date, include_inactive)


@mcp.tool(annotations=WRITES)
@_safe
@_logged
def log_interaction(
    name: Annotated[str, Field(description="What happened and with whom, e.g. 'Call with Anna about the draft'.")],
    date: Annotated[str, Field(description="YYYY-MM-DD, 'YYYY-MM-DD HH:MM', now, today, yesterday.")] = "now",
    type: Annotated[str | None, Field(description="EVENT, INTERVIEW, MEETING, CALL, MESSAGE or E-MAIL.")] = None,
    category: Annotated[str | None, Field(description="e.g. INFORMATIVE, PROPOSAL, COLLABORATION, PERIODICAL-CHECK-IN.")] = None,
    direction: Annotated[str | None, Field(description="INGOING, OUTGOING or BOTH.")] = None,
    description: Annotated[str | None, Field(description="What was said or decided.")] = None,
    people: Annotated[list[str] | str | None, Field(description='Existing people (names or IDs).')] = None,
    organizations: Annotated[list[str] | str | None, Field(description='Existing organizations.')] = None,
    opportunities: Annotated[list[str] | str | None, Field(description='Existing opportunities.')] = None,
    areas: Annotated[list[str] | str | None, Field(description='Existing areas.')] = None,
    goals: Annotated[list[str] | str | None, Field(description='Existing goals.')] = None,
    commitments: Annotated[list[dict[str, Any]] | None, Field(description=(
        "Commitments this interaction created, each {name (verb first), due?, importance?, kind?, people?, goals?, "
        "areas?, opportunities?, period?, status?}. They are linked to the interaction; people default to the "
        "interaction's."))] = None,
    reason: Annotated[str, Field(description="The user's words / the evidence.")] = "",
    source: Annotated[str, Field(description='"me" if dictated, "assistant" if inferred, "import" if from a document.')] = "me",
    dry_run: Annotated[bool, Field(description="Show the preview without creating queue rows.")] = False,
    body: Annotated[str | None, Field(description="Markdown for the interaction's page: meeting notes, what was said.")] = None,
) -> str:
    """Dump-and-file: propose an interaction (something that already happened)
    plus the commitments it created, all linked, in one batch. Find the people,
    organizations and opportunities first; unknown names reject the proposal.

    Example: log_interaction("Call with Anna", type="CALL", people=["Anna"],
    commitments=[{"name": "Send the draft", "due": "2026-10-30"}])."""
    return domain.log_interaction(_workspace(), name, date, type, category, direction, description, people,
                                  organizations, opportunities, areas, goals, commitments, reason, source, dry_run,
                                  body=body)


@mcp.tool(annotations=WRITES)
@_safe
@_logged
def add_commitment(
    name: Annotated[str, Field(description="Starts with a verb: 'Send the draft'.")],
    due: Annotated[str | None, Field(description="YYYY-MM-DD.")] = None,
    importance: Annotated[str | None, Field(description="LOW, NORMAL or HIGH.")] = None,
    kind: Annotated[str | None, Field(description="FOLLOW-UP, DEADLINE or TASK.")] = None,
    people: Annotated[list[str] | str | None, Field(description='Existing people.')] = None,
    goals: Annotated[list[str] | str | None, Field(description='Existing goals.')] = None,
    areas: Annotated[list[str] | str | None, Field(description='Existing areas.')] = None,
    opportunities: Annotated[list[str] | str | None, Field(description='Existing opportunities.')] = None,
    origin: Annotated[str | None, Field(description="Interaction it came from: ID like INT-16 or title.")] = None,
    period: Annotated[str | None, Field(description="Free text for recurring ones.")] = None,
    reason: Annotated[str, Field(description="The user's words / the evidence.")] = "",
    source: Annotated[str, Field(description='"me" if dictated, "assistant" if inferred, "import" if from a document.')] = "me",
    dry_run: Annotated[bool, Field(description="Show the preview without creating queue rows.")] = False,
) -> str:
    """Propose one commitment (status OPEN). Needs approval like any change."""
    return domain.add_commitment(_workspace(), name, due, importance, kind, people, goals, areas, opportunities,
                                 origin, period, reason, source, dry_run)


@mcp.tool(annotations=WRITES)
@_safe
@_logged
def complete_commitment(
    commitment: Annotated[str, Field(description="ID like COM-4, page ID or title.")],
    status: Annotated[str, Field(description="DONE or DROPPED.")] = "DONE",
    done_via: Annotated[str | None, Field(description="Interaction that closed it (ID or title).")] = None,
    reason: Annotated[str, Field(description="The user's words / the evidence.")] = "",
    source: Annotated[str, Field(description='"me" if dictated, "assistant" if inferred, "import" if from a document.')] = "me",
    dry_run: Annotated[bool, Field(description="Show the preview without creating queue rows.")] = False,
) -> str:
    """Propose marking a commitment DONE or DROPPED, optionally linking the interaction."""
    return domain.complete_commitment(_workspace(), commitment, status, done_via, reason, source, dry_run)


@mcp.tool(annotations=WRITES)
@_safe
@_logged
def update_item(
    database: Annotated[str, Field(description="Database name as shown by overview.")],
    item: Annotated[str, Field(description="ID like HAB-1, page ID or title.")],
    fields: Annotated[dict[str, Any] | None, Field(description="{property: new value}, same value rules as propose.")] = None,
    reviewed: Annotated[bool, Field(description="Also set Last Reviewed to today (databases that have it).")] = False,
    reason: Annotated[str, Field(description="The user's words / the evidence.")] = "",
    source: Annotated[str, Field(description='"me" if dictated, "assistant" if inferred, "import" if from a document.')] = "me",
    dry_run: Annotated[bool, Field(description="Show the preview without creating queue rows.")] = False,
) -> str:
    """Propose changing fields of one existing item. Goal/question closing and
    target-date changes still need confirmation at approval."""
    return domain.update_item(_workspace(), database, item, fields, reviewed, reason, source, dry_run)


@mcp.tool(annotations=WRITES)
@_safe
@_logged
def set_inactive(
    database: Annotated[str, Field(description="Database name as shown by overview.")],
    item: Annotated[str, Field(description="ID like HAB-1, page ID or title.")],
    reason: Annotated[str, Field(description="The user's words / the evidence.")] = "",
    source: Annotated[str, Field(description='"me" if dictated, "assistant" if inferred, "import" if from a document.')] = "me",
    dry_run: Annotated[bool, Field(description="Show the preview without creating queue rows.")] = False,
) -> str:
    """Propose retiring an item (status becomes its inactive option). Nothing is ever deleted."""
    return domain.set_inactive(_workspace(), database, item, reason, source, dry_run)


@mcp.tool(annotations=WRITES)
@_safe
@_logged
def add_person(
    name: Annotated[str, Field(description="Full name.")],
    organization: Annotated[str | None, Field(description="Existing organization.")] = None,
    title: Annotated[str | None, Field(description="Job title.")] = None,
    relationship: Annotated[str | None, Field(description="Recruiter, Academic, Technical, Mentor, Manager, Peer, Personal.")] = None,
    familiarity: Annotated[str | None, Field(description="Collaborated, In-Person, Call, Online, No-Contact.")] = None,
    email: Annotated[str | None, Field(description="E-mail address.")] = None,
    summary: Annotated[str | None, Field(description="Who they are to the user, in a line.")] = None,
    fields: Annotated[list[str] | str | None, Field(description='Existing fields.')] = None,
    areas: Annotated[list[str] | str | None, Field(description='Existing areas.')] = None,
    channels: Annotated[str | None, Field(description="How to reach them (LinkedIn, WhatsApp…).")] = None,
    allow_duplicate: Annotated[bool, Field(description="Only after the look-alike check showed it is a different person.")] = False,
    reason: Annotated[str, Field(description="The user's words / the evidence.")] = "",
    source: Annotated[str, Field(description='"me" if dictated, "assistant" if inferred, "import" if from a document.')] = "me",
    dry_run: Annotated[bool, Field(description="Show the preview without creating queue rows.")] = False,
) -> str:
    """Propose a new person. Refuses if someone with a similar name exists: use that person instead."""
    return domain.add_person(_workspace(), name, organization, title, relationship, familiarity, email, summary,
                             fields, areas, channels, allow_duplicate, reason, source, dry_run)


@mcp.tool(annotations=WRITES)
@_safe
@_logged
def add_organization(
    name: Annotated[str, Field(description="Organization name.")],
    category: Annotated[str | None, Field(description="STARTUP, COMPANY, LAB, INSTITUTE, UNIVERSITY, PROGRAM.")] = None,
    relationship: Annotated[str | None, Field(description="WORKED-WITH, CURRENT, CONTACTED, TARGET, NONE.")] = None,
    website: Annotated[str | None, Field(description="URL.")] = None,
    country: Annotated[str | None, Field(description="Existing place.")] = None,
    fields: Annotated[list[str] | str | None, Field(description='Existing fields.')] = None,
    part_of: Annotated[str | None, Field(description="Parent organization.")] = None,
    allow_duplicate: Annotated[bool, Field(description="Only after the look-alike check showed it is a different one.")] = False,
    reason: Annotated[str, Field(description="The user's words / the evidence.")] = "",
    source: Annotated[str, Field(description='"me" if dictated, "assistant" if inferred, "import" if from a document.')] = "me",
    dry_run: Annotated[bool, Field(description="Show the preview without creating queue rows.")] = False,
) -> str:
    """Propose a new organization. Refuses if one with a similar name exists."""
    return domain.add_organization(_workspace(), name, category, relationship, website, country, fields, part_of,
                                   allow_duplicate, reason, source, dry_run)


@mcp.tool(annotations=READ_ONLY)
@_safe
@_logged
def review(
    date: Annotated[str, Field(description="Reference day; default today.")] = "today",
    horizon_days: Annotated[int, Field(description="How far ahead 'due soon' looks (days).")] = 7,
    contact_days: Annotated[int, Field(description="People not contacted for more than this many days are listed.")] = 60,
    sections: Annotated[list[str] | None, Field(description=(
        "Only these sections: commitments, decisions, goals, opportunities, people, habits, checkins, "
        "conversations, queue. Default: all."))] = None,
) -> str:
    """The weekly review, read-only: overdue and upcoming commitments, things
    waiting on others, decisions past or near their decide-by date, goals at
    risk or past target, goals and areas due for review, opportunity deadlines,
    people not contacted in a while, lapsed habits, the check-in trend (sleep,
    energy) and open conversations. Go through it with the user, then stamp what
    they reviewed with update_item(reviewed=true) and propose any updates."""
    return review_mod.review(_workspace(), date, horizon_days, contact_days, sections)


@mcp.tool(annotations=WRITES)
@_safe
@_logged
def log_conversation(
    title: Annotated[str, Field(description="What it was about, e.g. 'Low energy since moving to Germany'.")],
    summary: Annotated[str, Field(description="3-6 lines: what was explored and what came out of it. Not the transcript.")],
    date: Annotated[str, Field(description="Day of the conversation: YYYY-MM-DD, today or yesterday.")] = "today",
    conclusions: Annotated[str | None, Field(description="What the user concluded or decided, in their words if possible.")] = None,
    outcome: Annotated[str, Field(description="CHANGED (it changed the workspace), NO-CHANGE, or OPEN (unresolved).")] = "NO-CHANGE",
    link: Annotated[str | None, Field(description="Link to the chat.")] = None,
    areas: Annotated[list[str] | str | None, Field(description="Existing areas it touched.")] = None,
    goals: Annotated[list[str] | str | None, Field(description="Existing goals it touched.")] = None,
    open_questions: Annotated[list[str] | str | None, Field(description="Existing open questions it touched.")] = None,
    people: Annotated[list[str] | str | None, Field(description="Existing people it was about.")] = None,
    commitments: Annotated[list[str] | str | None, Field(description="Existing commitments it touched.")] = None,
    follow_ups: Annotated[list[dict[str, Any]] | None, Field(description=(
        "New commitments it produced, each {name (verb first), due?, importance?, kind?}; linked to the record."))] = None,
    reason: Annotated[str, Field(description="Why it is worth keeping / the user's words.")] = "",
    source: Annotated[str, Field(description='"assistant" when you summarised it (default), "me" if the user dictated it.')] = "assistant",
    dry_run: Annotated[bool, Field(description="Show the preview without creating queue rows.")] = False,
    body: Annotated[str | None, Field(description="Markdown for the record's page, if the summary is not enough.")] = None,
) -> str:
    """Keep a conversation worth remembering in Conversations, even when nothing
    else changed: a short summary, conclusions and the chat link, linked to the
    areas, goals, questions and people it touched. Proposes only; needs approval.
    Offer it at the end of a substantial conversation; search Conversations before
    discussing a recurring topic.

    Example: log_conversation("Feeling low on energy", summary="...", outcome="OPEN",
    areas=["Health"], open_questions=["..."])."""
    return domain.log_conversation(_workspace(), title, summary, date, conclusions, outcome, link, areas, goals,
                                   open_questions, people, commitments, follow_ups, reason, source, dry_run, body=body)


@mcp.tool(annotations=READ_ONLY)
@_safe
@_logged
def guide() -> str:
    """The rules for working with the user's personal Notion workspace: what
    each section means, how to read and write, approval rules and workflows.
    Call this once at the start of a session unless these rules are already
    in your instructions."""
    return guide_text(_workspace().settings)


@mcp.resource("guide://agent", name="agent-guide", title="Agent guide",
              description="Rules for working with the personal Notion workspace.",
              mime_type="text/markdown")
def guide_resource() -> str:
    return guide_text(_workspace().settings)


@mcp.prompt(name="start-session", title="Start session",
            description="Load the agent guide and the current workspace map into the chat.")
def start_session() -> str:
    ws = _workspace()
    try:
        workspace_map = tools.overview(ws)
    except Exception as err:   # noqa: BLE001
        workspace_map = f"(Could not load the workspace map: {err}. Call `overview` to retry.)"
    return (
        "You are my personal agent for this session. Follow the guide below, "
        "use the personal-agent tools, and answer from my Notion workspace.\n\n"
        f"{guide_text(ws.settings)}\n\n---\n\n# Current workspace map\n\n{workspace_map}\n\n"
        "Reply with one short line confirming you are ready, then wait for my request."
    )


OAUTH_PUBLIC_PATHS = frozenset({"/authorize", "/token", "/register", "/revoke", "/login", "/healthz"})


class BearerAuth:
    """ASGI middleware: every request must carry `Authorization: Bearer <token>`.

    The token is either the static `PERSONAL_AGENT_TOKEN` (Claude Code, the Jetson worker) or, when
    OAuth is on, an access token issued by `OwnerOAuthProvider` (hosted assistants). The OAuth
    endpoints themselves stay reachable without a token; they refuse everyone but the owner.
    """

    def __init__(self, app, token: str, oauth=None, resource_metadata_url: str | None = None) -> None:
        self.app = app
        self._token = token.encode()
        self._oauth = oauth
        self._metadata_url = resource_metadata_url

    def _is_public(self, path: str) -> bool:
        return self._oauth is not None and (path in OAUTH_PUBLIC_PATHS or path.startswith("/.well-known/"))

    async def _allowed(self, value: bytes) -> bool:
        if hmac.compare_digest(value, self._token):
            return True
        return self._oauth is not None and await self._oauth.load_access_token(value.decode("utf-8", "replace")) is not None

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and not self._is_public(scope["path"]):
            supplied = dict(scope["headers"]).get(b"authorization", b"")
            scheme, _, value = supplied.partition(b" ")
            if scheme.lower() != b"bearer" or not await self._allowed(value.strip()):
                body = b'{"error": "unauthorized"}'
                challenge = b"Bearer"
                if self._metadata_url:    # tells OAuth-capable clients where to log in
                    challenge = f'Bearer resource_metadata="{self._metadata_url}"'.encode()
                await send({"type": "http.response.start", "status": 401, "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", challenge),
                ]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def build_http_app(host: str, path: str, token: str, extra_hosts: tuple[str, ...] = (),
                   oauth=None, public_url: str | None = None):
    """The MCP endpoint at `path`, behind the bearer-token check.

    With `oauth` (an `OwnerOAuthProvider`) and `public_url` (the HTTPS address assistants use),
    the OAuth endpoints are served too and OAuth access tokens are accepted next to the static token.
    """
    from mcp.server.transport_security import TransportSecuritySettings

    security = None
    if extra_hosts:    # e.g. a Tailscale name or LAN IP; loopback is always allowed
        security = TransportSecuritySettings(
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", *[f"{h}:*" for h in extra_hosts], *extra_hosts],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*",
                             *[f"http://{h}:*" for h in extra_hosts], *[f"https://{h}" for h in extra_hosts]],
        )
    elif host not in ("127.0.0.1", "localhost", "::1"):
        security = TransportSecuritySettings(enable_dns_rebinding_protection=False)   # token is the guard
    app = mcp.streamable_http_app(streamable_http_path=path, host=host, transport_security=security)
    metadata_url = None
    if oauth is not None:
        from mcp.server.auth.routes import build_resource_metadata_url, create_auth_routes, create_protected_resource_routes
        from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions

        from .oauth import SCOPE

        # AuthSettings keeps a path-less issuer without a trailing slash, which RFC 8414 compares exactly.
        urls = AuthSettings(issuer_url=public_url.rstrip("/"), resource_server_url=public_url.rstrip("/") + path,
                            validate_token_resource=False)
        issuer, resource = urls.issuer_url, urls.resource_server_url
        routes = [
            *create_auth_routes(
                oauth, issuer,
                client_registration_options=ClientRegistrationOptions(
                    enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]),
                revocation_options=RevocationOptions(enabled=True)),
            *create_protected_resource_routes(resource, [issuer], scopes_supported=[SCOPE],
                                              resource_name="Personal Agent"),
            *oauth.login_routes(),
        ]
        app.router.routes[:0] = routes
        metadata_url = str(build_resource_metadata_url(resource))
    return BearerAuth(app, token, oauth, metadata_url)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="agent-mcp", description="Personal Agent MCP server.")
    parser.add_argument("--transport", choices=("stdio", "http"),
                        default=os.environ.get("PERSONAL_AGENT_TRANSPORT", "stdio"))
    parser.add_argument("--host", default=os.environ.get("PERSONAL_AGENT_HOST", "127.0.0.1"),
                        help="HTTP only. Default 127.0.0.1 (this machine). Use 0.0.0.0 to reach it from other devices.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PERSONAL_AGENT_PORT", "8765")))
    parser.add_argument("--path", default=os.environ.get("PERSONAL_AGENT_PATH", "/mcp"))
    args = parser.parse_args(argv)

    if args.transport == "stdio":
        threading.Thread(target=_workspace().warm, daemon=True).start()    # first tool call is then fast
        mcp.run()
        return

    settings = load_settings()
    if not settings.http_token or len(settings.http_token) < 24:
        raise SystemExit(
            "PERSONAL_AGENT_TOKEN is missing or too short (min. 24 characters). Set it in .env. Generate one with:\n"
            "  python3 -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
    import uvicorn
    from urllib.parse import urlparse

    from .oauth import MIN_PASSWORD_LENGTH, OwnerOAuthProvider

    oauth, hosts = None, settings.allowed_hosts
    if settings.public_url:
        if not settings.public_url.startswith("https://"):
            raise SystemExit("PERSONAL_AGENT_PUBLIC_URL must start with https:// (e.g. https://jetson.your-tailnet.ts.net).")
        if len(settings.owner_password) < MIN_PASSWORD_LENGTH:
            raise SystemExit(
                f"PERSONAL_AGENT_OWNER_PASSWORD is missing or shorter than {MIN_PASSWORD_LENGTH} characters. "
                "It is the password you type on the login page when an assistant connects."
            )
        oauth = OwnerOAuthProvider(settings.public_url, settings.owner_password, settings.state_dir / "oauth.json")
        hosts = (*hosts, urlparse(settings.public_url).hostname or "")
    logging.basicConfig(level=logging.INFO)
    threading.Thread(target=_workspace().warm, daemon=True).start()
    log.info("Serving on http://%s:%s%s (%s)", args.host, args.port, args.path,
             f"bearer token or OAuth via {settings.public_url}" if oauth else "bearer token required")
    uvicorn.run(build_http_app(args.host, args.path, settings.http_token, hosts, oauth, settings.public_url),
                host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
