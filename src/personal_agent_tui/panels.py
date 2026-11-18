"""One panel per tab. Data comes from `mock` for now."""
from __future__ import annotations

import datetime as dt

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import DataTable, Input, ListItem, ListView, Static

from . import mock
from .theme import C, TAB_BY_ID

STATUS = {
    "PENDING": ("Waiting for you", C["yellow"]),
    "APPROVED": ("Approved", C["green"]),
    "REJECTED": ("Declined", C["red"]),
}
VERB = {"CREATE": "New", "UPDATE": "Update", "SET-INACTIVE": "Archive"}
NOUN = {"Commitments": "to-do", "Areas": "work note", "Interactions": "meeting",
        "Goals": "goal", "People": "contact", "Habits": "habit"}
HOBBY_ICON = {"Climbing": "🧗", "Chinese": "📝", "Reading": "📚", "Photography": "📷"}


def kind(q: dict) -> str:
    return f"{VERB.get(q['op'], q['op'].title())} {NOUN.get(q['db'], q['db'].lower())}"


def section(title: str, color: str) -> Static:
    return Static(f"[b {color}]{title}[/]", classes="section")


def dots(days: list[int], color: str) -> str:
    return " ".join(f"[{color}]●[/]" if d else f"[{C['faint']}]○[/]" for d in days)


def streak(days: list[int]) -> int:
    n = 0
    for d in reversed(days):
        if not d:
            break
        n += 1
    return n


class Panel:
    """Mixin: which child gets focus when you press → on the sidebar."""

    def focus_target(self) -> Widget:
        return self  # type: ignore[return-value]


class Pick(ListView):
    """A list inside a panel (its panel stops its events before they reach the app)."""


# ── home ────────────────────────────────────────────────────────────────────

class HomePanel(VerticalScroll, Panel):
    can_focus = True

    def __init__(self, user: str, **kw) -> None:
        super().__init__(**kw)
        self.user = user

    def compose(self) -> ComposeResult:
        now = dt.datetime.now()
        part = ("evening" if now.hour < 5 else "morning" if now.hour < 12
                else "afternoon" if now.hour < 18 else "evening")
        yield Static(f"[b {C['text']}]Good {part}, {self.user}[/]", id="hello")
        yield Static(f"[{C['muted']}]{now:%A, %-d %B}[/]", id="date")

        pending = sum(1 for q in mock.QUEUE if q["status"] == "PENDING")
        due = sum(1 for _, w, done in mock.COMMITMENTS if w == "today" and not done)
        best = max(mock.HABITS, key=lambda h: streak(h[1]))
        with Horizontal(id="tiles"):
            yield Static(f"[b {C['pink']}]{pending}[/]\n[{C['muted']}]to review[/]", classes="tile")
            yield Static(f"[b {C['yellow']}]{due}[/]\n[{C['muted']}]due today[/]", classes="tile")
            yield Static(f"[b {C['green']}]{streak(best[1])} days[/]\n[{C['muted']}]{best[0]} streak[/]",
                         classes="tile")

        with Horizontal(id="home-cols"):
            with Vertical(classes="box"):
                yield section("Today", C["blue"])
                yield Static("\n".join(
                    f"[{C['muted']}]{t}[/]   [{TAB_BY_ID[k].color}]●[/]  {what}"
                    for t, what, k in mock.AGENDA))
            with Vertical(classes="box"):
                yield section("To do", C["orange"])
                yield Static("\n".join(
                    (f"[{C['green']}]✓[/]  [{C['faint']}]{n}[/]" if done
                     else f"[{C['muted']}]○[/]  {n}  [{C['muted']}]· {w}[/]")
                    for n, w, done in mock.COMMITMENTS))

        with Vertical(classes="box"):
            yield section("Habits · last 2 weeks", C["green"])
            yield Static("\n".join(
                f"{name.capitalize():<16} {dots(days, C['green'])}" for name, days in mock.HABITS))

        last = next(m for who, m in reversed(mock.AGENT_CHAT) if who == "agent")
        with Vertical(classes="box"):
            yield section("💬  Your assistant", C["purple"])
            yield Static(last)


# ── to review ───────────────────────────────────────────────────────────────

def review_label(q: dict) -> str:
    _, color = STATUS[q["status"]]
    return f"[{color}]●[/]  [b]{q['title']}[/]\n    [{C['muted']}]{kind(q)}[/]"


class ReviewPanel(Horizontal, Panel):
    BINDINGS = [
        Binding("a", "decide('APPROVED')", "Approve"),
        Binding("x", "decide('REJECTED')", "Decline"),
    ]

    def compose(self) -> ComposeResult:
        yield Pick(*[ListItem(Static(review_label(q))) for q in mock.QUEUE],
                   id="review-list", classes="pick")
        yield Static(id="review-detail", classes="detail")

    def on_mount(self) -> None:
        self.show(0)

    def focus_target(self) -> Widget:
        return self.query_one("#review-list")

    def show(self, i: int | None) -> None:
        if i is None:
            return
        q = mock.QUEUE[i]
        label, color = STATUS[q["status"]]
        width = max(len(k) for k in q["props"])
        fields = "\n".join(f"[{C['muted']}]{k:<{width}}[/]   {v}" for k, v in q["props"].items())
        note = q["body"].replace("- [ ]", "○") if q["body"] else f"[{C['faint']}]No notes[/]"
        who = "You said this" if q["source"] == "me" else "Suggested by your assistant"
        buttons = ""
        if q["status"] == "PENDING":
            buttons = (f"\n\n[b {C['ink']} on {C['green']}]  A  Approve  [/]   "
                       f"[b {C['ink']} on {C['red']}]  X  Decline  [/]")
        self.query_one("#review-detail", Static).update(
            f"[{C['pink']}]{kind(q)}[/]\n"
            f"[b {C['text']}]{q['title']}[/]\n"
            f"[{color}]● {label}[/]  [{C['muted']}]· {who}[/]\n\n"
            f"{fields}\n\n"
            f"[b {C['muted']}]Notes[/]\n{note}"
            f"{buttons}"
        )

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        event.stop()
        self.show(event.list_view.index)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()

    def action_decide(self, status: str) -> None:
        lv = self.query_one("#review-list", ListView)
        if lv.index is None:
            return
        q = mock.QUEUE[lv.index]
        q["status"] = status
        lv.highlighted_child.query_one(Static).update(review_label(q))
        self.show(lv.index)
        self.app.notify(f"{q['title']}", title=STATUS[status][0],
                        severity="information" if status == "APPROVED" else "warning")
        self.app.refresh_badges()


# ── work ────────────────────────────────────────────────────────────────────

class WorkPanel(Horizontal, Panel):
    def compose(self) -> ComposeResult:
        items = []
        for a in mock.AREAS:
            dot = C["green"] if a["status"] == "active" else C["yellow"]
            state = "Active" if a["status"] == "active" else "Planning"
            items.append(ListItem(Static(f"[b]{a['name']}[/]\n[{dot}]●[/] [{C['muted']}]{state}[/]")))
        yield Pick(*items, id="area-list", classes="pick")
        yield Static(id="area-detail", classes="detail")

    def on_mount(self) -> None:
        self.show(0)

    def focus_target(self) -> Widget:
        return self.query_one("#area-list")

    def show(self, i: int | None) -> None:
        if i is None:
            return
        a = mock.AREAS[i]
        log = "\n".join(f"[{C['muted']}]Week {w[1:]}[/]   {t}" for w, t in a["log"])
        todo = "\n".join(f"[{C['muted']}]○[/]  {t}" for t in a["open"])
        self.query_one("#area-detail", Static).update(
            f"[b {C['text']}]{a['name']}[/]\n[{C['muted']}]{a['context']}[/]\n\n"
            f"[b {C['sky']}]Recent weeks[/]\n{log}\n\n"
            f"[b {C['orange']}]Still to do[/]\n{todo}"
        )

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        event.stop()
        self.show(event.list_view.index)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()


# ── hobbies ─────────────────────────────────────────────────────────────────

class HobbiesPanel(VerticalScroll, Panel):
    can_focus = True

    def compose(self) -> ComposeResult:
        with Grid(id="hobby-grid"):
            for name, cadence, note, color in mock.HOBBIES:
                yield Static(
                    f"{HOBBY_ICON.get(name, '✨')}  [b {C['text']}]{name}[/]\n"
                    f"[b {C[color]}]{cadence}[/]\n[{C['muted']}]{note}[/]",
                    classes="box hobby")


# ── people ──────────────────────────────────────────────────────────────────

class PeoplePanel(Vertical, Panel):
    def compose(self) -> ComposeResult:
        yield DataTable(id="people-table", cursor_type="row", show_cursor=True)

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_columns("Name", "Who", "Last talked", "Next")
        for name, rel, last, nxt in mock.PEOPLE:
            t.add_row(f"[b]{name}[/]", rel[:1].upper() + rel[1:], last[:1].upper() + last[1:],
                      f"[{C['teal']}]{nxt[:1].upper() + nxt[1:]}[/]" if nxt != "—" else f"[{C['faint']}]—[/]")

    def focus_target(self) -> Widget:
        return self.query_one(DataTable)


# ── habits ──────────────────────────────────────────────────────────────────

def habit_label(name: str, days: list[int]) -> str:
    s = streak(days)
    tail = f"[b {C['orange']}]🔥 {s} day{'s' if s != 1 else ''}[/]" if s else f"[{C['faint']}]No streak[/]"
    return (f"[b]{name.capitalize():<16}[/]  {dots(days, C['green'])}   "
            f"[{C['muted']}]{sum(days)} of 14[/]   {tail}")


class HabitsPanel(Vertical, Panel):
    BINDINGS = [Binding("space", "log", "Done today")]

    def compose(self) -> ComposeResult:
        yield Static(f"[{C['muted']}]Last two weeks. Today is the dot on the right.[/]", id="habits-head")
        yield Pick(*[ListItem(Static(habit_label(n, d))) for n, d in mock.HABITS],
                   id="habit-list", classes="pick")

    def focus_target(self) -> Widget:
        return self.query_one("#habit-list")

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        event.stop()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        self.action_log()

    def action_log(self) -> None:
        lv = self.query_one("#habit-list", ListView)
        if lv.index is None:
            return
        name, days = mock.HABITS[lv.index]
        days[-1] = 0 if days[-1] else 1
        lv.highlighted_child.query_one(Static).update(habit_label(name, days))
        self.app.notify(name.capitalize(), title="Done today" if days[-1] else "Unmarked")


# ── chat ────────────────────────────────────────────────────────────────────

class ChatPanel(Vertical, Panel):
    def compose(self) -> ComposeResult:
        with VerticalScroll(id="chat"):
            for who, text in mock.AGENT_CHAT:
                yield self.bubble(who, text)
        yield Input(placeholder="Write a message…", id="chat-input")

    @staticmethod
    def bubble(who: str, text: str) -> Horizontal:
        if who == "agent":
            return Horizontal(Static(text, classes="msg msg-agent"), classes="row row-agent")
        return Horizontal(Static(text, classes="msg msg-me"), classes="row row-me")

    def focus_target(self) -> Widget:
        return self.query_one("#chat-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(self.bubble("me", text))
        chat.mount(self.bubble("agent", "I'm not connected yet, so I can't answer for now."))
        event.input.value = ""
        chat.scroll_end(animate=False)


PANELS = {
    "home": HomePanel,
    "review": ReviewPanel,
    "work": WorkPanel,
    "hobbies": HobbiesPanel,
    "people": PeoplePanel,
    "habits": HabitsPanel,
    "chat": ChatPanel,
}
