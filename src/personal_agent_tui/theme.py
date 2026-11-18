"""Colours and the tab list.

Warm dark gray like Claude's dark mode, mid-tone pastel accents
(azure, orange, amber, teal, green, rose; no lilac). Accents are used as text
on the dark gray, or as a fill behind near-black text.
"""
from __future__ import annotations

from dataclasses import dataclass

from textual.theme import Theme

C = {
    "bg": "#262624",        # page
    "side": "#1f1e1d",      # sidebar, bottom bar
    "box": "#30302e",       # selected rows, chat bubbles
    "line": "#3e3d3a",      # quiet borders, key caps
    "ink": "#1a1918",       # text on a coloured fill
    "text": "#ece9e4",
    "muted": "#a9a49c",
    "faint": "#6d6963",
    # accents
    "azure": "#6cb4ee",
    "amber": "#e5b85c",
    "teal": "#5ec4b6",
    "rose": "#e48ba3",
    "peach": "#f0a37a",
    "green": "#8fcf7f",
    "orange": "#d97757",    # Claude's clay orange
    "red": "#e8776f",
    "key": "#8cc4f0",       # code: property names
    "str": "#a9d48f",       # code: values
}

THEME = Theme(
    name="claude-dark",
    primary=C["orange"],
    secondary=C["azure"],
    accent=C["amber"],
    warning=C["amber"],
    error=C["red"],
    success=C["green"],
    foreground=C["text"],
    background=C["bg"],
    surface=C["side"],
    panel=C["box"],
    dark=True,
)


@dataclass(frozen=True)
class Tab:
    id: str
    icon: str   # one flat, single-width symbol, drawn in the tab colour
    label: str
    color: str
    hint: str   # extra keys shown at the bottom while this tab is open


TABS: list[Tab] = [
    Tab("home", "⌂", "Home", C["azure"], ""),
    Tab("review", "✓", "To review", C["amber"], "A  Approve    X  Decline"),
    Tab("work", "◆", "Work", C["teal"], ""),
    Tab("hobbies", "✿", "Hobbies", C["rose"], ""),
    Tab("people", "☻", "People", C["peach"], ""),
    Tab("habits", "●", "Habits", C["green"], "Space  Done today"),
    Tab("chat", "❯", "Chat", C["orange"], "Enter  Send"),
]

TAB_BY_ID = {t.id: t for t in TABS}
