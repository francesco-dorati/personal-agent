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

**Icons.** In the Mac app (below) the sidebar has real icons: a house, an
inbox, a briefcase, a palette, people, a sprout, speech bubbles. The app ships
its own fonts, so they always show. In a terminal they also show in Ghostty and
WezTerm (icon font built in); anywhere else simple symbols are used
(`PA_ICONS=nerd` forces the icons).

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

## Platforms

The TUI runs in any terminal on macOS, Linux and Windows, and `agent-tui-serve`
serves it to any browser. Only the app window below is macOS-specific.

## Use it like an app (macOS)

```
zsh macos/make-app.sh
```

Add a logo name to choose the app icon (pictures in `macos/logos/`): stars
`star`, `rose`, `needle`, `horizon`, `constellation`, `burst`, `fivepoint`, or
`buddy`, `sprout`, `hearth`, `owl`. For example `zsh macos/make-app.sh rose`.

Builds **Personal Agent.app** in `~/Applications`: its own window, menu and Dock
icon (not a terminal tab). Drag it into the Dock to pin it, or open it from
Spotlight/Raycast. Q in the app (or ⌘Q) closes it. Needs Apple's command line
tools (`xcode-select --install`). Re-run the script after moving this folder.
If something goes wrong, see `~/Library/Logs/PersonalAgent.log`.

How it works: `agent-tui-serve` serves the TUI as a web page (textual-serve)
with bundled fonts, and a small Swift window (`macos/app/main.swift`) shows it.

## Files

- `theme.py`: colours, icons, the tab list
- `serve.py`, `web/`: the page for the Mac app (template + bundled fonts)
- `macos/`: the app icon, the Swift window and the script that builds the app
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
