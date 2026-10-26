# Changelog

Structure and behaviour changes that existing users need to apply.

## Unreleased
- New tool `search`: items by title or ID across all databases and pages.
- `get` takes a list of items (at most 10) and an `offset`; pages over 8000
  characters are cut with a notice saying how to read the rest. `find` and
  `agenda` also say when a row cap hides results.
- Every argument now has its own description in the tool schema (shown by
  `agent server list --full`); the tool descriptions are shorter.
- Each tool call is logged to `logs/calls.jsonl` (tool, arguments, time, Notion
  requests, result size, error, and whether it came from a model or the
  terminal); `agent server log [N]` shows the latest.
- MCP server (`agent-mcp`) and CLI (`agent`) with a first tool: `overview`,
  which maps the workspace from the root page (sections, pages, databases,
  descriptions, item counts).
- The server's tools are run from the terminal with `agent server <tool>` (was
  `agent <tool>`); `agent server list` shows every tool, its syntax and the
  description the model reads. `agent eval` is unchanged.
- Failures are now real MCP errors (`is_error`), not normal-looking text: bad
  arguments, unknown names and Notion refusals reach the model as an error
  result with the same readable message; unexpected crashes are logged with a
  traceback. Ambiguous names ("which one?") are still ordinary text.
- `find`: rows of any database filtered by property values (dates like
  `today`/`+7d`, select options, links by name with fuzzy matching), with
  links shown as names.
- `get` (one item with links and page content, by ID, link or title),
  `person` (fuzzy name lookup) and `agenda` (dated items in a period, plus
  overdue ones).
- The agent guide is served by the server: `guide` tool, `start-session`
  prompt and `guide://agent` resource.
- `agent eval`: regression cases for the tools (`evals/`).

## 0.1.0 - 2026-10-20
- First version: agent guide (`AGENT.md`) and Notion template.
