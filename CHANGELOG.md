# Changelog

Structure and behaviour changes that existing users need to apply.

## Unreleased

- Proposals can carry a page **body** (Markdown) on CREATE and UPDATE (`propose`, and
  `log_interaction` / `log_conversation` via `body`). It is written as the content of the
  new page when the row is applied.
- **Edit a queue item before approving it.** Each queue row's page now shows the proposal
  as editable text: a Properties section (`Name: value`) and a Body. What you leave there is
  what `apply` writes; you can change values, add properties (e.g. a state) and rewrite the
  body. `queue` / `approve` / `apply` report your edits (✎) and update the Preview column;
  invalid edits block approval (or send an approved row back to PENDING) and nothing is
  written. Guarded changes (closing a goal…) are re-checked on the edited values. Rows
  created before this change keep working as they were. No structure change is needed.
- `agent-mcp --transport http`: serve the MCP endpoint over streamable HTTP (default
  `127.0.0.1:8765/mcp`) so several clients share one running server. Requires
  `PERSONAL_AGENT_TOKEN` in `.env` (bearer auth, checked on every request); stdio stays
  the default. New: `scripts/run-http.sh`, `scripts/com.personal-agent.mcp.plist`
  (launchd), `PERSONAL_AGENT_ALLOWED_HOSTS`. The registry cache file is now written atomically.
- Habit logs and check-ins the user reported are written directly (no approval): the
  queue row is created APPROVED and applied in the same call. Inferred ones, worker
  mode and `AGENT_DIRECT_LOGS=0` still go through approval.
- New tool `review`: the weekly review in one read-only call.
- New tool `log_conversation` and the **Conversations** database (structure change:
  create it with `scripts/add_conversations_db.py --apply`; it adds a "Conversations"
  relation column to Areas, Goals, Open Questions, People and Commitments).
- Domain tools: `log_interaction`, `add_commitment`, `complete_commitment`, `update_item`, `set_inactive`, `add_person`, `add_organization`. `log_habit` now warns about a same-day duplicate only for CHECK habits.
- `habits_status` ranks habits by how far each is from its own rhythm (lapsed, slipping, due, on track) with 28-day and 84-day adherence; weekly targets use a rolling 7 days.
- The workspace map is served from cache even when stale (refreshed in the background, warmed at server start): a cold rebuild took ~70-90s and timed out in Claude Desktop (60s limit).
- Names (titles and IDs of every database) are cached on disk and warmed at server start; reads may be a few minutes old and refresh in the background, writes always use a copy under 30 seconds old. Cold `search` went from 57s to under 1s.
- `agent refresh` (and a `refresh` tool) reload the workspace map and all names now; a running server adopts a newer on-disk copy.
- Habit tools: `log_habit`, `log_checkin` (both propose via the queue) and `habits_status` (read-only).
- Write path through the Assistant Queue: `propose`, `queue`, `approve`, `reject`,
  `apply`, `revert`. Validation against the schemas, duplicate and one-per-day
  checks, conflict check on update, `$N` references inside a batch, guards for
  goals/questions and context changes, `AGENT_MODE=worker`, no delete.
  Structure change: the Assistant Queue database needs the columns listed in the
  README (optional: Result, Applied At). Offline tests in `tests/`.
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
