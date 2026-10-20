# Notion structure

The Notion side of the system: the page tree and the databases the agent expects.

## Get your own copy

1. Open the template: https://personal-assistant-template.notion.site/Life-Assistant-Template-3ff3920e80bd81158221d107a58bc1fa.
2. Click **Duplicate** (top right). Notion copies every page and database into
   your workspace, with all properties, options, descriptions and the
   relations between the databases.
3. Rename the copy as you like and copy its ID (the 32-character hex string at
   the end of its URL) into `.env` as `NOTION_ROOT_PAGE_ID`.
4. Fill it in. Start with Context (Profile, Constraints, Priorities,
   Preferences, Operating Rules), then add records as life happens.

## What is in the template

```
Life Assistant (Template)
├── Context:   Data Model · Profile · Constraints* · Priorities* · Preferences*
│              Direction (personal · academic · professional · financial)
│              Background (personal · academic · professional) · Operating Rules*
├── Content:   Areas* · Goals* · Open Questions*
├── Collections: Opportunities* · Organizations* · People* · University Courses*
│              Habits · Skills · Books · Supporting Databases (Fields*, Countries*)
└── Records:   Interactions* · Commitments* · Decisions · Monthly Expenses · Logs
```
`*` = database. Pages without `*` are text pages or placeholders for databases
still to be built.

## Maintainer notes

- The template is derived from the maintainer's own workspace: see
  `../CONTRIBUTING.md` for how changes reach it.
- Planned: `structure.json` (exported structure) and a setup script that
  builds the structure through the Notion API, so the repo alone is enough.
