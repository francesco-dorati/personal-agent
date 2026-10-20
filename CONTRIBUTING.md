# Changing the system

The system has two halves that must stay in step:

| Half | Lives in | Examples |
|---|---|---|
| **Structure** | Notion | databases, properties, select options, descriptions, page tree |
| **Behaviour** | this repo | `AGENT.md`, later the MCP server and scripts |

Personal data never enters the repo or the template.

## Source of truth

- **Behaviour**: the repo. Edit `AGENT.md` here, commit, push.
- **Structure**: your own Notion workspace (the reference instance). You change
  structure there, in the Notion UI, while using it.
- **Template**: a published, empty copy of the structure. It is derived: never
  edit it by hand.

## When you change something

### Behaviour only (e.g. a new rule in AGENT.md)
1. Edit, commit, push. Done: users pull the repo.

### Structure (new database, new property, new option, renamed thing)
1. Make the change in your own Notion and give it a description.
2. If agents must behave differently, update `AGENT.md` too (usually not
   needed: databases are discovered from their descriptions).
3. Refresh the template:
   - **Now (manual):** apply the same change to the template page by hand, or
     re-create the template (duplicate your root page, empty every database,
     re-publish) for larger changes.
   - **Planned (scripted):** `export-structure` writes `notion/structure.json`
     from your workspace; `apply-structure` updates the template (or anyone's
     workspace) from that file, adding what is missing without touching data.
4. Note the change in `CHANGELOG.md` so existing users know what to add.

## Existing users

A Notion duplicate is a one-time copy: people who already duplicated the
template do not receive later changes. They update by:
- **Now:** following `CHANGELOG.md` and adding the change by hand.
- **Planned:** running `apply-structure` against their own root page. It adds
  missing databases, properties and options, and never deletes or renames
  their data.
