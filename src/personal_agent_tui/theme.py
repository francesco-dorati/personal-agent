"""Colours and the tab list.

High contrast: near-black background, bright saturated accents, and text that
stays readable (accents are only used on dark backgrounds, or as a fill
behind near-black text).
"""
from __future__ import annotations

from dataclasses import dataclass

from textual.theme import Theme

C = {
    "bg": "#0e0e12",        # page
    "side": "#16161d",      # sidebar
    "box": "#1c1c25",       # cards
    "line": "#2c2c38",      # dividers
    "ink": "#0b0b0f",       # text on a coloured fill
    "text": "#f4f4f6",
    "muted": "#a3a3b2",     # still ~7:1 on bg
    "faint": "#5d5d6c",
    "blue": "#4c8dff",
    "pink": "#ff4f9a",
    "sky": "#2bb5ff",
    "orange": "#ff9a1f",
    "teal": "#15d1b5",
    "green": "#3ee07a",
    "purple": "#a56bff",
    "yellow": "#ffd23f",
    "red": "#ff5c5c",
}

THEME = Theme(
    name="everyday",
    primary=C["blue"],
    secondary=C["purple"],
    accent=C["pink"],
    warning=C["yellow"],
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
    icon: str
    label: str
    color: str
    hint: str  # extra keys shown at the bottom while this tab is open


TABS: list[Tab] = [
    Tab("home", "🏠", "Home", C["blue"], ""),
    Tab("review", "📬", "To review", C["pink"], "A  Approve    X  Decline"),
    Tab("work", "💼", "Work", C["sky"], ""),
    Tab("hobbies", "🎨", "Hobbies", C["orange"], ""),
    Tab("people", "👋", "People", C["teal"], ""),
    Tab("habits", "🌱", "Habits", C["green"], "Space  Done today"),
    Tab("chat", "💬", "Chat", C["purple"], "Enter  Send"),
]

TAB_BY_ID = {t.id: t for t in TABS}
