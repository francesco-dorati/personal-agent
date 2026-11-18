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


# Two icon sets. NERD: flat pictograms from a Nerd Font (house, inbox, ...).
# BASIC: plain symbols that every font can draw. Which one is used is decided
# once per machine (see iconcheck.py), can be forced with PA_ICONS=nerd|basic,
# and switched any time with the I key.
NERD = {
    "home": "\uf015",         # house
    "review": "\uf01c",       # inbox
    "work": "\uf0b1",         # briefcase
    "hobbies": "\U000f03d8",  # palette
    "people": "\uf0c0",       # users
    "habits": "\U000f0e66",   # sprout
    "chat": "\uf086",         # speech bubbles
    "calendar": "\uf073",
    "todo": "\uf046",         # checked box
    "assistant": "\uf075",    # speech bubble
    "Climbing": "\U000f0d7f", # hiking
    "Chinese": "\uf1ab",      # language
    "Reading": "\uf02d",      # book
    "Photography": "\uf030",  # camera
}
BASIC = {
    "home": "⌂", "review": "✉", "work": "⚒", "hobbies": "✿", "people": "☺",
    "habits": "↻", "chat": "❯", "calendar": "◷", "todo": "☑", "assistant": "❯",
    "Climbing": "▲", "Chinese": "✎", "Reading": "☰", "Photography": "◉",
}
SETS = {"nerd": NERD, "basic": BASIC}
_mode = "basic"


def icon_mode() -> str:
    return _mode


def set_icon_mode(mode: str) -> None:
    global _mode
    _mode = mode if mode in SETS else "basic"


def icon(name: str) -> str:
    return SETS[_mode].get(name, "•")


@dataclass(frozen=True)
class Tab:
    id: str
    label: str
    color: str
    hint: str   # extra keys shown at the bottom while this tab is open

    @property
    def icon(self) -> str:   # one flat, single-width pictogram, drawn in the tab colour
        return icon(self.id)


TABS: list[Tab] = [
    Tab("home", "Home", C["azure"], ""),
    Tab("review", "To review", C["amber"], "A  Approve    X  Decline"),
    Tab("work", "Work", C["teal"], ""),
    Tab("hobbies", "Hobbies", C["rose"], ""),
    Tab("people", "People", C["peach"], ""),
    Tab("habits", "Habits", C["green"], "Space  Done today"),
    Tab("chat", "Chat", C["orange"], "Enter  Send"),
]

TAB_BY_ID = {t.id: t for t in TABS}
