"""One panel per tab. Data comes from `mock` for now."""
from __future__ import annotations

import datetime as dt

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import DataTable, Input, ListItem, ListView, Static

from . import mock
from .theme import C, TAB_BY_ID, icon

STATUS = {
    "PENDING": ("waiting for you", C["amber"]),
    "APPROVED": ("approved", C["green"]),
    "REJECTED": ("declined", C["red"]),
}
VERB = {"CREATE": "new", "UPDATE": "update", "SET-INACTIVE": "archive"}
NOUN = {"Commitments": "to-do", "Areas": "work note", "Interactions": "meeting",
        "Goals": "goal", "People": "contact", "Habits": "habit"}


def kind(q: dict) -> str:
    return f"{VERB.get(q['op'], q['op'].lower())} {NOUN.get(q['db'], q['db'].lower())}"


def card(title: str, body: str, color: str, *, classes: str = "") -> Static:
    """A rounded box with its title in the top border, like the first sketch."""
    w = Static(body, classes=f"card {classes}".strip())
    w.border_title = f"[b {color}] {title} [/]"  # icons in titles: bold is fine now (same font)
    w.styles.border = ("round", color)
    return w


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
            yield card(f"{icon('review')}  To review", f"[b {C['amber']}]{pending}[/] [{C['muted']}]waiting[/]", C["amber"], classes="tile")
            yield card(f"{icon('todo')}  Due today", f"[b {C['peach']}]{due}[/] [{C['muted']}]to-do[/]", C["peach"], classes="tile")
            yield card(f"{icon('habits')}  Best streak", f"[b {C['green']}]{streak(best[1])} days[/] [{C['muted']}]{best[0]}[/]",
                       C["green"], classes="tile")

        with Horizontal(id="home-cols"):
            yield card(f"{icon('calendar')}  Today", "\n".join(
                f"[{C['muted']}]{t}[/]  [{TAB_BY_ID[k].color}]●[/] {what}" for t, what, k in mock.AGENDA),
                C["azure"])
            yield card(f"{icon('todo')}  To do", "\n".join(
                (f"[{C['green']}]●[/] [{C['faint']}]{n}[/]" if done
                 else f"[{C['faint']}]○[/] {n} [{C['muted']}]· {w}[/]")
                for n, w, done in mock.COMMITMENTS), C["peach"])

        yield card(f"{icon('habits')}  Habits · last 2 weeks", "\n".join(
            f"{name.capitalize():<16} {dots(days, C['green'])}" for name, days in mock.HABITS), C["green"])

        last = next(m for who, m in reversed(mock.AGENT_CHAT) if who == "agent")
        yield card(f"{icon('assistant')}  Assistant", f"[{C['orange']}]❯[/] {last}", C["orange"])


# ── to review ───────────────────────────────────────────────────────────────

def review_label(q: dict) -> str:
    _, color = STATUS[q["status"]]
    return (f"[{color}]●[/] [b]{q['title']}[/]\n"
            f"  [{C['muted']}]{kind(q)}[/] [{C['faint']}]· {q['id']}[/]")


def fields(props: dict[str, str]) -> str:
    width = max((len(k) for k in props), default=0)
    return "\n".join(
        f"  [{C['key']}]{k.lower():<{width}}[/] [{C['faint']}]=[/] [{C['str']}]\"{v}\"[/]"
        for k, v in props.items())


class ReviewPanel(Horizontal, Panel):
    BINDINGS = [
        Binding("a", "decide('APPROVED')", "Approve"),
        Binding("x", "decide('REJECTED')", "Decline"),
    ]

    def compose(self) -> ComposeResult:
        yield ListView(*[ListItem(Static(review_label(q))) for q in mock.QUEUE],
                       id="review-list", classes="pick")
        yield card("", "", C["amber"], classes="detail")

    def on_mount(self) -> None:
        self.show(0)

    def focus_target(self) -> Widget:
        return self.query_one("#review-list")

    def show(self, i: int | None) -> None:
        if i is None:
            return
        q = mock.QUEUE[i]
        label, color = STATUS[q["status"]]
        who = "you said this" if q["source"] == "me" else "suggested by your assistant"
        notes = "\n".join(f"  {line.replace('- [ ]', '○')}" for line in q["body"].splitlines()) \
            or f"  [{C['faint']}]no notes[/]"
        buttons = ""
        if q["status"] == "PENDING":
            buttons = (f"\n\n  [b {C['ink']} on {C['green']}]  A  Approve  [/]   "
                       f"[b {C['ink']} on {C['red']}]  X  Decline  [/]")
        d = self.query_one(".detail", Static)
        d.border_title = f"[b {C['amber']}] {q['id']} [/][{C['muted']}]{kind(q)} → {q['db']} [/]"
        d.update(
            f"[b {C['text']}]{q['title']}[/]\n"
            f"[{color}]● {label}[/] [{C['muted']}]· {who}[/]\n\n"
            f"[{C['faint']}]# fields[/]\n{fields(q['props'])}\n\n"
            f"[{C['faint']}]# notes[/]\n[{C['text']}]{notes}[/]"
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
        self.app.notify(q["title"], title=STATUS[status][0].capitalize(),
                        severity="information" if status == "APPROVED" else "warning")
        self.app.refresh_badges()


# ── work ────────────────────────────────────────────────────────────────────

class WorkPanel(Horizontal, Panel):
    def compose(self) -> ComposeResult:
        items = []
        for a in mock.AREAS:
            dot = C["green"] if a["status"] == "active" else C["amber"]
            state = "Active" if a["status"] == "active" else "Planning"
            items.append(ListItem(Static(f"[b]{a['name']}[/]\n[{dot}]●[/] [{C['muted']}]{state}[/]")))
        yield ListView(*items, id="area-list", classes="pick")
        yield card("", "", C["teal"], classes="detail")

    def on_mount(self) -> None:
        self.show(0)

    def focus_target(self) -> Widget:
        return self.query_one("#area-list")

    def show(self, i: int | None) -> None:
        if i is None:
            return
        a = mock.AREAS[i]
        log = "\n".join(f"[{C['muted']}]Week {w[1:]}[/]  {t}" for w, t in a["log"])
        todo = "\n".join(f"[{C['faint']}]○[/] {t}" for t in a["open"])
        d = self.query_one(".detail", Static)
        d.border_title = f"[b {C['teal']}] {a['name']} [/]"
        d.update(
            f"[{C['muted']}]{a['context']}[/]\n\n"
            f"[b {C['azure']}]Recent weeks[/]\n{log}\n\n"
            f"[b {C['peach']}]Still to do[/]\n{todo}"
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
                yield card(f"{icon(name)}  {name}",
                           f"[b {C[color]}]{cadence}[/]\n[{C['muted']}]{note}[/]", C[color], classes="hobby")


# ── people ──────────────────────────────────────────────────────────────────

def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


class PeoplePanel(Vertical, Panel):
    def compose(self) -> ComposeResult:
        yield DataTable(id="people-table", cursor_type="row")

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_columns("Name", "Who", "Last talked", "Next")
        for name, rel, last, nxt in mock.PEOPLE:
            t.add_row(f"[b]{name}[/]", cap(rel), cap(last),
                      f"[{C['peach']}]{cap(nxt)}[/]" if nxt != "—" else f"[{C['faint']}]—[/]")

    def focus_target(self) -> Widget:
        return self.query_one(DataTable)


# ── habits ──────────────────────────────────────────────────────────────────

def habit_label(name: str, days: list[int]) -> str:
    s = streak(days)
    tail = (f"[b {C['peach']}]{s} day{'s' if s != 1 else ''} in a row[/]" if s
            else f"[{C['faint']}]no streak[/]")
    return (f"[b]{name.capitalize():<16}[/] {dots(days, C['green'])}   "
            f"[{C['muted']}]{sum(days):>2} of 14[/]   {tail}")


class HabitsPanel(Vertical, Panel):
    BINDINGS = [Binding("space", "log", "Done today")]

    def compose(self) -> ComposeResult:
        yield Static(f"[{C['muted']}]Last two weeks. Today is the dot on the right.[/]", id="habits-head")
        yield ListView(*[ListItem(Static(habit_label(n, d))) for n, d in mock.HABITS],
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
            return Horizontal(Static(f"[{C['orange']}]❯[/] {text}", classes="msg msg-agent"),
                              classes="row row-agent")
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
