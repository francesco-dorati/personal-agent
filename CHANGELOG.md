# Changelog

Structure and behaviour changes that existing users need to apply.

## Unreleased
- MCP server (`agent-mcp`) and CLI (`agent`) with a first tool: `overview`,
  which maps the workspace from the root page (sections, pages, databases,
  descriptions, item counts).
- `find`: rows of any database filtered by property values (dates like
  `today`/`+7d`, select options, links by name with fuzzy matching), with
  links shown as names.
- `get` (one item with links and page content, by ID, link or title),
  `person` (fuzzy name lookup) and `agenda` (dated items in a period, plus
  overdue ones).

## 0.1.0 - 2026-10-20
- First version: agent guide (`AGENT.md`) and Notion template.
