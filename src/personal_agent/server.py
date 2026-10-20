"""MCP server: exposes the tools in `tools.py` to any MCP client.

Run with `agent-mcp` (stdio transport, for Claude Desktop / Code).
"""
from __future__ import annotations

import functools
import logging
import traceback

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from . import tools
from .workspace import Workspace

mcp = MCPServer(
    "personal-agent",
    instructions=(
        "Read the user's personal Notion workspace: their life, work, meetings, "
        "commitments (tasks), people, goals and areas. Prefer these tools over a "
        "generic Notion connector for reading. Start each session with `overview`."
    ),
)
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
log = logging.getLogger("personal-agent")


def _safe(fn):
    """Return errors as text the model can read, instead of a bare failure."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as err:   # noqa: BLE001 - report everything to the client
            log.error("%s failed:\n%s", fn.__name__, traceback.format_exc())
            return f"Error in {fn.__name__}: {type(err).__name__}: {err}"
    return wrapper
_ws: Workspace | None = None


def _workspace() -> Workspace:
    global _ws
    if _ws is None:
        _ws = Workspace()
    return _ws


@mcp.tool(annotations=READ_ONLY)
@_safe
def overview(refresh: bool = False) -> str:
    """Map of the user's personal Notion workspace: every section, page and
    database (meetings/interactions, commitments/tasks, people, organizations,
    goals, areas, priorities…), what each is for and how many items it holds.
    Call this at the start of a session, before answering anything about the
    user. Set refresh to true only if the user just changed the structure."""
    return tools.overview(_workspace(), refresh=refresh)


@mcp.tool(annotations=READ_ONLY)
@_safe
def find(database: str, where: dict[str, str] | None = None, search: str | None = None,
         sort: str | None = None, limit: int = 20) -> str:
    """List items of one database in the user's Notion workspace (name as
    shown by `overview`, e.g. "Interactions" for meetings/calls/emails,
    "Commitments" for tasks and deadlines, "People"), filtered by property
    values. Links to other items are shown as names; each row has an ID
    (e.g. INT-14) to pass to `get` for its full content.

    where: {property: value}. A value may start with an operator:
      "OPEN" equals (text: contains) · "!=DONE" · "~word" contains
      ">=2026-10-01" · "<=+7d" · ">5" · "empty" · "not empty"
      Dates: YYYY-MM-DD, today, yesterday, tomorrow, +Nd, -Nd.
      Links: a name or ID, e.g. {"People": "Acar Cihan"}.
    search: text the title contains.
    sort: property name, "-" prefix for descending (default: recently edited).

    Example: find("Interactions", {"Date": "yesterday"})."""
    return tools.find(_workspace(), database, where, search, sort, limit)


@mcp.tool(annotations=READ_ONLY)
@_safe
def get(item: str, database: str | None = None) -> str:
    """Open one item of the user's Notion workspace with everything in it:
    all properties, linked items (with their IDs) and the full page content,
    e.g. meeting notes. `item` is an ID like INT-14 or PER-2 (best), a page
    ID/link, or a title (pass `database` to narrow). Also opens text pages
    such as "Profile" or "Professional Direction". If a title is ambiguous
    you get the candidates: ask the user which one."""
    return tools.get(_workspace(), item, database)


@mcp.tool(annotations=READ_ONLY)
@_safe
def person(name: str) -> str:
    """Look up a person in the user's People database by name, tolerating
    misspellings (e.g. from meeting transcripts), and return their details,
    organization, recent interactions and links. Use the spelling it returns.
    If the name is unclear you get the closest people: ask the user."""
    return tools.person(_workspace(), name)


@mcp.tool(annotations=READ_ONLY)
@_safe
def agenda(start: str = "today", end: str = "+7d") -> str:
    """What is dated in a period across the user's whole Notion workspace:
    commitments due, meetings and interactions, goal target dates, decisions
    to make, deadlines, grouped by day, plus overdue items that are not done.
    start/end: YYYY-MM-DD, today, yesterday, tomorrow, +Nd, -Nd. For "what did
    I do yesterday" use start="yesterday", end="yesterday"."""
    return tools.agenda(_workspace(), start, end)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
