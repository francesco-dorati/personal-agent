"""Serve the TUI to the Personal Agent.app window (or any browser).

    agent-tui-serve [PORT]

Prints `READY <url>` once it is listening, so the Mac app knows what to load.
The page ships its own fonts (Fira Code + Nerd Font symbols), so the icons
show no matter which fonts the Mac has.
"""
from __future__ import annotations

import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import textual_serve
from textual_serve.server import Server

WEB = Path(__file__).parent / "web"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def statics() -> Path:
    """textual-serve's own css/js plus our fonts, in one folder."""
    out = Path(tempfile.gettempdir()) / "personal-agent-tui-static"
    shutil.copytree(Path(textual_serve.__file__).parent / "static", out, dirs_exist_ok=True)
    shutil.copytree(WEB / "fonts", out / "fonts", dirs_exist_ok=True)
    return out


def exit_with_parent() -> None:
    """If the Mac app goes away (even if killed), stop serving."""
    parent = os.getppid()

    def watch() -> None:
        while os.getppid() == parent:
            time.sleep(1)
        os._exit(0)

    threading.Thread(target=watch, daemon=True).start()


def main() -> None:
    if os.environ.get("PA_APP_CHILD"):
        exit_with_parent()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else free_port()
    os.environ["PA_IN_APP"] = "1"   # the app always has the icon font
    server = Server(
        f'"{sys.executable}" -m personal_agent_tui',
        host="127.0.0.1",
        port=port,
        title="Personal Agent",
        statics_path=statics(),
        templates_path=WEB / "templates",
    )
    print(f"READY http://127.0.0.1:{port}/?fontsize=16", flush=True)
    server.serve()


if __name__ == "__main__":
    main()
