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

## Roadmap

1. Agent guide + Notion template (now).
2. Structure export and setup scripts.
3. MCP server: domain tools (`log_interaction`, `due`, `person`, `propose`…)
   with validation against the schemas.
4. Assistant Queue + local worker (Jetson) that proposes updates from email
   and calendar.
