"""Mock data for the sketch.

Everything here is made up (the repo is public). The next step replaces this
module with a client that calls the MCP server's tools over HTTP (overview,
agenda, queue, find, person, habits_status) and returns the same shapes.
"""
from __future__ import annotations

AGENDA = [
    ("09:30", "Standup with the lab team", "work"),
    ("11:00", "Experiment run #14 review", "work"),
    ("14:00", "Call with a mentor", "people"),
    ("18:30", "Climbing gym", "hobbies"),
]

COMMITMENTS = [
    ("Send weekly update to supervisor", "today", False),
    ("Reply to the PhD lead", "tomorrow", False),
    ("Book flights for spring trip", "Fri", False),
    ("Push dataset fix", "done", True),
]

QUEUE = [
    {
        "id": "Q-41", "op": "CREATE", "db": "Commitments", "title": "Reply to the PhD lead",
        "status": "PENDING", "source": "assistant",
        "props": {"Name": "Reply to the PhD lead", "Due": "2026-11-20", "Area": "Job search", "Status": "OPEN"},
        "body": "- [ ] confirm start date\n- [ ] ask about funding",
    },
    {
        "id": "Q-42", "op": "UPDATE", "db": "Areas", "title": "Internship · weekly log",
        "status": "PENDING", "source": "assistant",
        "props": {"Area": "Internship", "Week": "2026-11-16 → 2026-11-22"},
        "body": "Ran ablations on the energy-aware policy; sim-to-real gap narrowed.",
    },
    {
        "id": "Q-43", "op": "CREATE", "db": "Interactions", "title": "Coffee with Alex",
        "status": "PENDING", "source": "me",
        "props": {"Person": "Alex Rivera", "Date": "2026-11-18", "Type": "In person"},
        "body": "Talked about the robotics meetup and a possible collab.",
    },
    {
        "id": "Q-44", "op": "SET-INACTIVE", "db": "Goals", "title": "Learn Rust basics",
        "status": "PENDING", "source": "assistant",
        "props": {"Goal": "Learn Rust basics", "State": "INACTIVE"},
        "body": "",
    },
]

AREAS = [
    {
        "name": "Internship", "icon": "</>", "status": "active",
        "context": "Research internship on humanoid control. Focus: energy-aware policies.",
        "log": [("W46", "Set up the real-robot eval loop."), ("W47", "Ablations on reward terms.")],
        "open": ["Write mid-term report", "Prepare lab demo"],
    },
    {
        "name": "Startup", "icon": "{ }", "status": "active",
        "context": "Early-stage robotics startup. Role: AI researcher.",
        "log": [("W46", "Perception benchmark draft."), ("W47", "Investor demo prep.")],
        "open": ["Clean up grasping repo"],
    },
    {
        "name": "Thesis", "icon": "§", "status": "planning",
        "context": "MSc thesis topic still open; two candidate directions.",
        "log": [("W45", "Shortlisted two topics.")],
        "open": ["Email possible supervisor"],
    },
    {
        "name": "Job search", "icon": "->", "status": "active",
        "context": "Research positions for next year.",
        "log": [("W47", "One lead moving forward.")],
        "open": ["Reply to the PhD lead", "Update CV"],
    },
]

HOBBIES = [
    ("Climbing", "2x / week", "Last session: Tue · project: blue 6b", "orange"),
    ("Chinese", "15 min / day", "HSK 2 deck · 340 cards", "pink"),
    ("Reading", "1 book / month", "Now: a sci-fi novel, 62%", "sky"),
    ("Photography", "Weekends", "Film roll #7 to develop", "teal"),
]

PEOPLE = [
    ("Alex Rivera", "friend", "yesterday", "invite to meetup"),
    ("Dr. Chen", "PhD lead", "5 days ago", "reply about start date"),
    ("Marta", "family", "2 weeks ago", "call this weekend"),
    ("Sam Okafor", "colleague", "today", "—"),
    ("Giulia", "friend", "1 month ago", "catch up"),
]

# last 14 days, oldest first; 1 = done
HABITS = [
    ("workout", [1, 0, 1, 1, 0, 1, 1, 1, 0, 1, 1, 0, 1, 1]),
    ("reading", [1, 1, 1, 0, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1]),
    ("chinese", [0, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 1, 0]),
    ("no phone in bed", [0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1, 1, 1]),
]

AGENT_CHAT = [
    ("agent", "Evening. 3 meetings done today, 1 commitment due tomorrow."),
    ("agent", "You haven't logged a workout since Sunday. Did you go today?"),
    ("me", "not yet, going tomorrow morning"),
    ("agent", "Noted. I'll ask again tomorrow at 12:00. Want me to queue a reminder?"),
]
