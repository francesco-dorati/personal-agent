"""First-launch check: can this terminal draw the Nerd Font icons?

Terminals can't report which glyphs their font has, so we show three icons
and ask. The answer is saved per machine; I in the app switches it later.
"""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Center, Vertical
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from .theme import C, NERD, THEME


class IconCheckApp(App[str]):
    TITLE = "Personal Agent"
    CSS = f"""
    Screen {{ background: {C['bg']}; align: center middle; }}
    #box {{
        width: 70; height: auto; padding: 1 3;
        border: round {C['azure']}; border-title-align: left;
        background: {C['bg']};
    }}
    #icons {{ height: 3; content-align: center middle; text-align: center; }}
    #ask {{ height: auto; margin-bottom: 1; }}
    OptionList {{ height: auto; background: {C['bg']}; border: none; padding: 0; }}
    OptionList > .option-list--option {{ padding: 0 1; }}
    OptionList:focus {{ background-tint: #000000 0%; }}
    OptionList > .option-list--option-highlighted {{
        background: {C['azure']}; color: {C['ink']}; text-style: bold;
    }}
    #keys {{ height: 1; margin-top: 1; }}
    """
    BINDINGS = [("escape", "exit_basic", "Skip"), ("q", "exit_basic", "Skip")]

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical(id="box"):
                yield Static(
                    f"[{C['azure']}]{NERD['home']}[/]      "
                    f"[{C['amber']}]{NERD['review']}[/]      "
                    f"[{C['teal']}]{NERD['work']}[/]",
                    id="icons")
                yield Static(
                    f"[b {C['text']}]Can you see three small pictures above?[/]\n"
                    f"[{C['muted']}]A house, an inbox and a briefcase. If you see empty boxes, "
                    f"question marks or nothing, your terminal's font can't draw them.[/]",
                    id="ask")
                yield OptionList(
                    Option("Yes, I see the pictures", id="nerd"),
                    Option("No, use simple symbols instead", id="basic"),
                )
                yield Static(
                    f"[b {C['text']} on {C['line']}] ↑↓ [/] [{C['muted']}]Choose[/]    "
                    f"[b {C['text']} on {C['line']}] Enter [/] [{C['muted']}]Confirm[/]    "
                    f"[{C['faint']}]Change it later with I[/]",
                    id="keys")

    def on_mount(self) -> None:
        self.register_theme(THEME)
        self.theme = THEME.name
        self.query_one("#box").border_title = f"[b {C['azure']}] Quick check [/]"
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.exit(event.option.id)

    def action_exit_basic(self) -> None:
        self.exit("basic")
