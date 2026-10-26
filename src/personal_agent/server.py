"""MCP server: exposes the tools in `tools.py` to any MCP client.

Run with `agent-mcp` (stdio transport, for Claude Desktop / Code).
"""
from __future__ import annotations

import functools
import inspect
import logging
import time
import traceback
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from . import calllog, tools
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
        "when you only know a name, `find` to list or filter one database."
    ),
)
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
