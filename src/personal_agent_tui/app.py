"""Personal Agent in the terminal.

Arrows move, → opens, ← or Esc goes back, 1-7 jump to a tab, Q quits.
"""
from __future__ import annotations

import os

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import ContentSwitcher, ListItem, ListView, Static

from . import mock
from .panels import PANELS, HomePanel
from .theme import C, TABS, TAB_BY_ID, THEME, Tab


def user_name() -> str:
    """PA_USER_NAME, else the first name of the account owner."""
    name = os.environ.get("PA_USER_NAME") or os.environ.get("USER_NAME")
    if not name:
        try:  # macOS/Linux: first name of the account owner (no pwd module on Windows)
            import pwd
            name = pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0].split(" ")[0]
        except (ImportError, KeyError, IndexError, AttributeError):
            name = ""
    return name or "there"


def subtitle(tab_id: str) -> str:
    """One short line under each tab name (from mock data for now)."""
    pending = sum(1 for q in mock.QUEUE if q["status"] == "PENDING")
    done_today = sum(1 for _, days in mock.HABITS if days[-1])
    return {
        "home": "Your day",
        "review": f"{pending} waiting" if pending else "All done",
        "work": f"{len(mock.AREAS)} areas",
        "hobbies": f"{len(mock.HOBBIES)} hobbies",
        "people": f"{len(mock.PEOPLE)} people",
        "habits": f"{done_today} of {len(mock.HABITS)} today",
        "chat": "Ask anything",
    }[tab_id]


class NavItem(ListItem):
    def __init__(self, tab: Tab) -> None:
        super().__init__(Static(), id=f"nav-{tab.id}")
        self.tab = tab
        self.badge = 0

    def paint(self, active: bool, lit: bool) -> None:
        """active: the open tab. lit: the sidebar has the arrow keys."""
        t = self.tab
        if active and lit:          # bright fill: arrows move here
            bg, ico, name, sub = t.color, C["ink"], C["ink"], C["ink"]
        elif active:                # open tab, but the page has the arrows
            bg, ico, name, sub = C["box"], t.color, t.color, C["muted"]
        elif lit:
            bg, ico, name, sub = C["side"], t.color, C["text"], C["muted"]
        else:                       # dimmed while the page has the arrows
            bg, ico, name, sub = C["side"], C["faint"], C["faint"], C["faint"]
        badge = ""
        if self.badge:
            badge = (f"  [b {t.color} on {C['ink']}] {self.badge} [/]" if active and lit
                     else f"  [b {C['ink']} on {C['amber']}] {self.badge} [/]" if lit or active
                     else f"  [{C['amber']}]{self.badge}[/]")
        text = (f"[not b {ico}]{t.icon}[/]   [b {name}]{t.label}[/]{badge}\n"
                f"    [{sub}]{subtitle(t.id)}[/]")
        self.styles.background = bg
        label = self.query_one(Static)
        label.styles.background = bg
        label.update(text)


class Sidebar(ListView):
    BINDINGS = [Binding("right", "open", "Open", show=False)]

    def action_open(self) -> None:
        self.app.action_focus_content()


class PersonalAgentApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "Personal Agent"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+q", "quit", "Quit", show=False),
        Binding("escape", "focus_sidebar", "Back", show=False),
        Binding("left", "focus_sidebar", "Back", show=False),
        *[Binding(str(i + 1), f"jump('{t.id}')", t.label, show=False) for i, t in enumerate(TABS)],
    ]

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with Vertical(id="side"):
                yield Static(f"[b {C['text']}]Personal Agent[/]", id="brand")
                yield Sidebar(*[NavItem(t) for t in TABS], id="sidebar")
                yield Static(f"[{C['amber']}]●[/] [{C['muted']}]Sample data[/]", id="conn")
            with Vertical(id="main"):
                yield Static(id="title")
                with ContentSwitcher(initial="home", id="switcher"):
                    for t in TABS:
                        cls = PANELS[t.id]
                        if cls is HomePanel:
                            yield cls(user_name(), id=t.id, classes="panel")
                        else:
                            yield cls(id=t.id, classes="panel")
        yield Static(id="hints")

    def on_mount(self) -> None:
        self.register_theme(THEME)
        self.theme = THEME.name
        self.query_one(Sidebar).focus()
        self.watch(self.screen, "focused", lambda _: self.repaint(), init=False)
        self.refresh_badges()

    # helpers
    def current(self) -> str:
        return self.query_one("#switcher", ContentSwitcher).current or "home"

    _lit = True

    def sidebar_lit(self) -> bool:
        # While the window itself is unfocused nothing has focus: keep the last state.
        if self.focused is not None:
            self._lit = isinstance(self.focused, Sidebar)
        return self._lit

    def repaint(self) -> None:
        """Redraw everything that shows where the arrow keys go."""
        tab = TAB_BY_ID[self.current()]
        lit = self.sidebar_lit()
        for item in self.query(NavItem):
            item.paint(item.tab.id == tab.id, lit)
        self.query_one("#title", Static).update(
            f"[{tab.color}]{tab.icon}[/]   [b {tab.color}]{tab.label}[/]   [{C['muted']}]{subtitle(tab.id)}[/]")
        self.query_one("#title").styles.border_bottom = ("heavy", tab.color)
        self.paint_hints(tab, lit)

    def refresh_badges(self) -> None:
        self.query_one("#nav-review", NavItem).badge = sum(
            1 for q in mock.QUEUE if q["status"] == "PENDING")
        self.repaint()

    def switch_to(self, tab_id: str) -> None:
        self.query_one("#switcher", ContentSwitcher).current = tab_id
        self.repaint()

    def paint_hints(self, tab: Tab, lit: bool) -> None:
        def key(k: str, what: str) -> str:
            return f"[b {C['text']} on {C['line']}] {k} [/] [{C['muted']}]{what}[/]"

        if lit:
            mode = f"[b {C['ink']} on {tab.color}]  Tabs  [/]"
            parts = [key("↑↓", "Switch tab"), key("→", "Open"), key("1-7", "Jump")]
        else:
            mode = f"[b {C['ink']} on {tab.color}]  {tab.label}  [/]"
            move = {"home": "Scroll", "hobbies": "Scroll", "chat": ""}.get(tab.id, "Move")
            parts = [key("↑↓", move)] if move else []
            for chunk in filter(None, tab.hint.split("    ")):
                k, what = chunk.split("  ", 1)
                parts.append(key(k, what))
            parts.append(key("Esc" if tab.id == "chat" else "←", "Back to tabs"))
        parts.append(key("Q", "Quit"))
        self.query_one("#hints", Static).update(f"  {mode}    " + "    ".join(parts))

    # events / actions
    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "sidebar" and isinstance(event.item, NavItem):
            self.switch_to(event.item.tab.id)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "sidebar":
            self.action_focus_content()

    def action_focus_content(self) -> None:
        self.query_one(f"#{self.current()}").focus_target().focus()

    def action_focus_sidebar(self) -> None:
        self.query_one(Sidebar).focus()

    def action_jump(self, tab_id: str) -> None:
        self.query_one(Sidebar).index = [t.id for t in TABS].index(tab_id)
        self.switch_to(tab_id)


def main() -> None:
    PersonalAgentApp().run()


if __name__ == "__main__":
    main()
