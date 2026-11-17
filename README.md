# Personal Agent

A personal life-management system: **Notion** holds the data, an **AI agent**
reads and updates it.

- `AGENT.md`: the guide any agent reads first. It explains the whole system
  without containing data or IDs.
- `notion/`: how to get the Notion structure (template now, setup script later).
- `.env.example`: the settings. Only the root page ID is needed to start.

## Quick start (with Cowork / Claude)

1. Get the Notion structure (see `notion/README.md`).
2. Run `python3 setup.py`. It asks for your name, your Notion root page link,
   language and time zone, saves them in `.env`, and writes `AGENT.local.md`.
3. Connect Notion to Claude and give it **`AGENT.local.md`**: one file with
   the guide and your settings. Re-run setup after pulling a new `AGENT.md`
   (`python3 setup.py --render` skips the questions).

## MCP server

The server gives an agent fast, precise read access to the workspace: it
discovers the structure from the root page, shows links as names, tolerates
misspelled names and returns compact text.

### Writing: the Assistant Queue

Every write is a row in the **Assistant Queue** database first.
`propose` → the user approves (Approve button in Notion, or `approve` after their
OK in the chat) → `apply`. Nothing is deleted: removing means `SET-INACTIVE`.

- `propose` checks the change against the schema: unknown properties and select
  options are refused (options are never created), relations resolve by name or ID,
  dates are stored in your time zone, duplicates are blocked in collections and
  warned about in records, and a check-in is one per day. One bad change rejects
  the whole proposal. A log row without a name is named after its habit; a
  check-in after its day.
- `apply` only touches APPROVED rows. An update is refused if the value changed
  since the proposal. `$1`, `$2`… link a new item to another new item of the same batch.
- Closing a goal or question, moving a target date (`confirmed=true`), and context
  changes (one at a time) need extra care.
- **Direct logs.** Habit logs and check-ins the user reported (`log_habit`, `log_checkin`
  with source `me`) skip approval: the queue row is created APPROVED and applied in the
  same call, so it stays as history. Anything inferred (source `assistant`), worker mode,
  or `AGENT_DIRECT_LOGS=0` falls back to a normal proposal. A wrong log row is deleted by
  hand in Notion (logs have no inactive state); a check-in update is undone with `revert`.
- **Page body.** A change can carry a `body` (Markdown: headings, lists, `- [ ]` to-dos,
  quotes, code, **bold**, links). On CREATE it becomes the content of the new page, on
  UPDATE it is added at the end of the page (alone or with properties). `log_interaction`
  and `log_conversation` take a `body` too. Images, tables and embeds are not supported.
- **Editing before approving.** Every queue row is a page with a **Properties** section
  (one `Name: value` line per property) and a **Body** section. Change a value, add a
  line for another property (a state, a visibility…), leave a value empty to clear it, or
  rewrite the body, then approve. Dates are `2026-11-02 → 2026-11-08`, several relations or
  tags are separated by `;`. `queue`, `approve` and `apply` use your version (marked ✎) and
  the Preview column is updated to match; the agent is told what you changed and must not
  write its own values back. An edit that does not fit (unknown option, bad date, a line
  that is not a property) blocks approval; if you already pressed Approve, `apply` sends
  the row back to PENDING and writes nothing. Editing the **Payload** column is not needed.
- `AGENT_MODE=worker` (for the Jetson) makes `approve` and `apply` unavailable.
- Queue columns used: Name, Operation, Status, Target Database ID, Target Item ID,
  Payload, Before, Preview, Reason / Evidence, Proposed By, Batch ID, ID. Optional:
  **Result** (text) and **Applied At** (date); without them the outcome is appended
  to Reason / Evidence.

Tests: `uv run python -m unittest discover -s tests -v` (offline, fake Notion).

### Optional databases

- **Conversations** (Records): assistant conversations worth remembering even when
  nothing else changed (summary, conclusions, chat link, outcome, links to areas,
  goals, questions, people, commitments). Create it with
  `uv run python scripts/add_conversations_db.py --apply` (dry run without `--apply`),
  then `uv run agent server refresh`. Used by `log_conversation` and `review`.

### Tools

| Tool | What it returns | Example |
|---|---|---|
| `overview` | Map of the workspace: sections, pages, databases, what each is for, item counts | `overview()` |
| `find` | Items of one database filtered by property, links shown as names | `find("Interactions", {"Date": "yesterday"})` |
| `search` | Items by title or ID across all databases, best match first | `search("Acar")` |
| `get` | One item with all properties, links (with IDs) and page content | `get("INT-14")`, `get("Profile")` |
| `person` | A person by name, tolerating typos; asks when ambiguous | `person("Francss")` → Francesco |
| `agenda` | Everything dated in a period, by day, plus overdue items | `agenda("today", "+7d")` |
| `guide` | The agent guide (`AGENT.md`) with this installation's settings | `guide()` |
| `propose` | Validates changes (with an optional `body`) and writes them as PENDING rows in the Assistant Queue. Changes nothing else | `propose([{"operation": "CREATE", "database": "Habits Log", "properties": {"Habit": "Learn Mandarin", "Date": "now"}}], reason="…")` |
| `queue` | The Assistant Queue with previews and outcomes | `queue()`, `queue("APPLIED")` |
| `approve` / `reject` | Decide pending rows (approve needs the user's own words) | `approve([12], approved_by="yes")` |
| `apply` | Performs APPROVED rows and records the result on each | `apply()`, `apply([12], dry_run=True)` |
| `revert` | Proposes the inverse of an applied change | `revert(12)` |
| `log_habit` | Writes a Habits Log row per habit at once (direct log; warns if paused or already logged) | `log_habit("Learn Mandarin")` |
| `log_checkin` | Writes the day's Daily Check-In at once (creates, or updates that day's row) | `log_checkin(sleep_hours=7.5, morning_energy=70)` |
| `habits_status` | Progress, streaks, limits and unlogged habits (read-only) | `habits_status()` |
| `review` | Weekly review (read-only): overdue/upcoming commitments, waiting items, decisions due, goals and areas due for review, deadlines, people not contacted, lapsed habits, check-in trend, open conversations, pending proposals | `review()`, `review(sections=["commitments", "checkins"])` |
| `log_conversation` | Proposes a Conversations record (summary, conclusions, link, outcome) plus new follow-up commitments, linked | `log_conversation("Low energy lately", summary="…", outcome="OPEN")` |
| `log_interaction` | Proposes an interaction plus the commitments it created, linked in one batch | `log_interaction("Call with Anna", people=["Anna"], commitments=[{"name": "Send the draft"}])` |
| `add_commitment` / `complete_commitment` | A new commitment; mark one DONE or DROPPED | `complete_commitment("COM-4")` |
| `update_item` / `set_inactive` | Change fields (can stamp Last Reviewed); retire an item | `update_item("Habits", "HAB-1", reviewed=True)` |
| `add_person` / `add_organization` | Create after a look-alike check | `add_person("Jane Doe", organization="Bosch")` |
| `refresh` | Reload the workspace map and names in the background | `refresh()` |

The server also offers the guide as a **prompt**, `start-session` (guide +
current workspace map in one click; in Claude Desktop under **+**), and as a
**resource**, `guide://agent`. With the server installed there is nothing to
paste into project instructions.

`find` conditions: `"OPEN"` equals (text: contains) · `"!=DONE"` · `"~word"`
contains · `">=2026-10-01"` · `"<=+7d"` · `">5"` · `"empty"` · `"not empty"`.
Dates accept `YYYY-MM-DD`, `today`, `yesterday`, `tomorrow`, `+Nd`, `-Nd`.
Links accept a name or an ID (`{"People": "..."}`, `{"Goals": "GOAL-4"}`).

### Command line

`agent server …` calls the MCP server's tools the way a model does and prints
exactly what it gets back. `agent server list` shows every tool with its
signature, the description the model reads, and examples.

```bash
uv sync                                           # once: install
uv run agent server list                          # all tools, syntax, descriptions
uv run agent server overview                      # map of the workspace
uv run agent server overview refresh=true         # rebuild the map after structure changes
uv run agent server find Interactions '{"Date": "yesterday"}'
uv run agent server find database=Commitments where='{"Status": "OPEN", "Due": "<=+7d"}' sort=Due
uv run agent server find '{"database": "People", "where": {"Organization": "Bosch"}, "limit": 5}'
uv run agent server search Acar                   # by name, across all databases
uv run agent server get INT-14                    # by ID, page link or title
uv run agent server get '{"item": ["INT-14", "PER-2"]}'   # several at once
uv run agent server get INT-14 offset=8000        # the rest of a long page
uv run agent server person "Banffy"
uv run agent server agenda yesterday +7d
uv run agent server review                        # weekly review
uv run agent server review sections=commitments,checkins horizon_days=14
uv run agent server log_habit habit='Learn Mandarin'   # written at once (direct log)
uv run agent server log_checkin sleep_hours=7 morning_energy=60 dry_run=true
uv run agent server guide                         # the guide as the model receives it
uv run agent --stats server agenda                # also show time and Notion requests
uv run agent server log                           # last 20 calls: who called what, how long, how big
uv run agent eval                                 # regression checks (see evals/README.md)
```

Arguments can be positional (in the order `list` shows), `name=value`, or the
exact JSON object a model sends. The call is printed on stderr first, so you
see the request and then the result. Every call, from a model or from the
terminal, is also logged to `logs/calls.jsonl` (git-ignored; it contains the
arguments, so it can contain names).

### Running it

```bash
uv run agent-mcp                                                  # MCP server over stdio
npx @modelcontextprotocol/inspector uv run agent-mcp              # try the tools in the MCP Inspector
```

Claude Desktop (Settings → Developer → Edit Config), inside the existing object:

```json
"mcpServers": {
  "personal-agent": {
    "command": "/absolute/path/to/uv",
    "args": ["--directory", "/absolute/path/to/personal-agent", "run", "agent-mcp"]
  }
}
```

### Running it over HTTP

`uv run agent-mcp` (stdio) is started by each client as its own process. With
`--transport http` the server instead runs once, stays up, and any number of
clients connect to the same URL (Cowork, Claude Code, the Jetson worker). They
share one warm workspace cache, so the first call is fast for everyone. The
tools and the Notion write path (queue, approve, apply) are unchanged.

1. Put a token in `.env` (the server refuses to start without one):
   ```bash
   python3 -c "import secrets; print('PERSONAL_AGENT_TOKEN=' + secrets.token_urlsafe(32))" >> .env
   ```
2. Start it: `uv run agent-mcp --transport http` (defaults: `127.0.0.1:8765`, path `/mcp`;
   `--host`, `--port`, `--path` or `PERSONAL_AGENT_HOST/PORT/PATH` change them).
3. Register it in a client, e.g. Claude Code:
   ```bash
   claude mcp add --transport http personal-agent http://127.0.0.1:8765/mcp \
     --header "Authorization: Bearer <your token>"
   ```
4. Keep it running on macOS: `cp scripts/com.personal-agent.mcp.plist ~/Library/LaunchAgents/`
   then `launchctl load ~/Library/LaunchAgents/com.personal-agent.mcp.plist`
   (log in `logs/http.log`; `launchctl unload …` stops it).

Reaching it from another device (e.g. the Jetson): start with `--host 0.0.0.0`
and set `PERSONAL_AGENT_ALLOWED_HOSTS` to the name or IP the client uses
(a Tailscale name works well). With only the static token, use your LAN or
Tailscale, never a public URL: the token is the only guard and the data is
personal. The connection is plain HTTP, so rely on Tailscale/WireGuard for
encryption off the machine.

#### From anywhere, for hosted assistants (OAuth)

Assistants that run in the cloud (the Claude app, ChatGPT, ...) cannot send a
static header and cannot see your tailnet. They need a public HTTPS URL and an
OAuth login. Set in `.env`:

```
PERSONAL_AGENT_PUBLIC_URL=https://<machine>.<tailnet>.ts.net   # the HTTPS address assistants use
PERSONAL_AGENT_OWNER_PASSWORD=<long random password, min. 12 characters>
```

Then keep the server on `127.0.0.1:8765` and publish it with Tailscale Funnel
(`sudo tailscale funnel --bg 8765`) or a Cloudflare Tunnel. Add
`https://<your public host>/mcp` as a custom connector in the assistant; it
registers itself, sends you to `/login`, and you type the owner password once.

- Only the owner password gives out tokens. Five wrong passwords lock the login
  page for 15 minutes.
- Access tokens last 1 hour, refresh tokens 30 days (rotated on use). They are
  stored only as hashes in `.state/oauth.json`; deleting that file logs every
  assistant out.
- The static `PERSONAL_AGENT_TOKEN` keeps working (Claude Code, the Jetson worker).
- With `PERSONAL_AGENT_PUBLIC_URL` empty, none of the OAuth endpoints exist.
- Write tools still only create pending rows in the Assistant Queue.

Notes:
- The Notion integration in `NOTION_TOKEN` must be connected to the root page
  (root page → ••• → Connections).
- The workspace map is cached in `.cache/` for 15 minutes; the first build
  takes about 30–40 s. Run `uv run agent overview` once to warm it up.
- After changing the code, quit Claude Desktop (⌘Q) and reopen it.

### Code layout (`src/personal_agent/`)

| File | Role |
|---|---|
| `notion_api.py` | Notion REST client: auth, pagination, rate limit, retries |
| `registry.py` | Discovery: walks the page tree from the root, maps every database |
| `workspace.py` | Settings + API client + cached registry and names |
| `values.py` | Notion property values → plain values |
| `names.py` | Page ID ↔ name lookups and fuzzy matching |
| `query.py` | `find` conditions → Notion filters and sorts |
| `blocks.py` | Page content → compact Markdown-like text |
| `tools.py` | The read tools as plain functions returning text |
| `proposals.py` | Write path: the Assistant Queue (`propose` … `revert`) and direct logs |
| `habits.py` | `log_habit`, `log_checkin`, `habits_status` |
| `domain.py` | Shortcuts that build proposals (interactions, commitments, people, conversations…) |
| `review.py` | The weekly review |
| `calllog.py` | Call log in `logs/calls.jsonl` |
| `guide.py` | `AGENT.md` + installation settings, served by the server |
| `evals.py` | Runs the regression cases in `evals/` |
| `server.py` / `cli.py` | Expose the same tools over MCP / in the terminal |

## Roadmap

1. Agent guide + Notion template: done.
2. MCP server: read tools, write path, domain shortcuts, habits, review,
   conversations: done.
3. Remote access: Streamable HTTP transport behind an HTTPS tunnel with OAuth, so
   the server works from the phone and claude.ai without the desktop app.
4. Always-on host (Jetson): runs the server and a worker (`AGENT_MODE=worker`)
   that proposes updates from email and calendar, plus check-in prompts.
5. Structure export and setup scripts for new users.
