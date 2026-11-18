# Personal Agent · terminal app

A simple, keyboard-only app for your Personal Agent. You move with the arrow keys and
nothing needs typing except in Chat.

This branch (`tui`) shares no code with the server (`main`). It is a **client**
that will talk to the personal-agent MCP server over HTTP, so a machine that
only runs the app never needs the server code, and the other way round.

```
git clone -b tui --single-branch https://github.com/francesco-dorati/personal-agent personal-agent-tui
cd personal-agent-tui
uv run agent-tui
```

Your name on Home is your Mac account's first name (or `PA_USER_NAME`). Use a terminal with full colour
(iTerm2, Ghostty, WezTerm, Kitty); macOS Terminal shows washed-out colours.

**Icons work in any terminal.** They are drawn with block characters
(`▗▟█▙▖`), which every monospace font has, so no special font is needed.

**Where the arrows go.** When the sidebar has the arrows, the open tab is a
bright coloured block and the bottom bar says **Tabs**. Press → and the sidebar
dims, the page's selected row lights up with a coloured bar, and the bottom bar
names the page you are in. ← or Esc takes you back.

| Key        | What it does                         |
|------------|--------------------------------------|
| ↑ ↓        | Switch tab, or move inside a page    |
| → or Enter | Go into the page                     |
| ← or Esc   | Back to the tabs                     |
| 1 – 7      | Jump to a tab                        |
| A / X      | To review: approve / decline         |
| Space      | Habits: done today                   |
| Q          | Quit                                 |

## Use it like an app (macOS)

```
zsh macos/make-app.sh
```

This builds **Personal Agent.app** in `~/Applications` with its own icon. Drag
it into the Dock to pin it, or open it from Spotlight/Raycast by typing
"Personal Agent". Clicking it opens a window of your terminal (Ghostty if
installed, else iTerm2, else Terminal) running the app. Re-run the script if you
move this folder.

## Files

- `theme.py`: colours, the block-character icons, the tab list
- `macos/`: the app icon and the script that builds Personal Agent.app
- `panels.py`: one page per tab
- `app.py`: sidebar, layout, moving between tabs
- `app.tcss`: spacing and neutral colours
- `mock.py`: sample data, to be replaced by the MCP client

## Next

1. `client.py`: call the server's tools (`overview`, `agenda`, `queue`, `find`,
   `person`, `habits_status`) over streamable HTTP with OAuth, in place of `mock`.
2. Approve / Decline call `approve` / `reject`; Enter opens a row to edit it first.
3. Work areas come from the Areas database instead of being fixed.
4. Chat connects to a model (local on the Jetson first).
