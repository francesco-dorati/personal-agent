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

### Tools

| Tool | What it returns | Example |
|---|---|---|
| `overview` | Map of the workspace: sections, pages, databases, what each is for, item counts | `overview()` |
| `find` | Items of one database filtered by property, links shown as names | `find("Interactions", {"Date": "yesterday"})` |
| `get` | One item with all properties, links (with IDs) and page content | `get("INT-14")`, `get("Profile")` |
| `person` | A person by name, tolerating typos; asks when ambiguous | `person("Francss")` → Francesco |
| `agenda` | Everything dated in a period, by day, plus overdue items | `agenda("today", "+7d")` |
| `guide` | The agent guide (`AGENT.md`) with this installation's settings | `guide()` |

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
| `tools.py` | The tools as plain functions returning text |
| `guide.py` | `AGENT.md` + installation settings, served by the server |
| `evals.py` | Runs the regression cases in `evals/` |
| `server.py` / `cli.py` | Expose the same tools over MCP / in the terminal |

## Roadmap

1. Agent guide + Notion template (now).
2. Structure export and setup scripts.
3. MCP server: domain tools (`log_interaction`, `due`, `person`, `propose`…)
   with validation against the schemas.
4. Assistant Queue + local worker (Jetson) that proposes updates from email
   and calendar.
