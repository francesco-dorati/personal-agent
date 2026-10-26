"""Local log of tool calls: which tool, which arguments, how long, how big, whether it failed.

One JSON line per call in logs/calls.jsonl (git-ignored; override with PERSONAL_AGENT_LOG).
Results are not stored, only their size. Arguments are, so the file can contain names:
keep it local. Read it with `agent server log`.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_FILE = Path(os.environ.get("PERSONAL_AGENT_LOG", REPO_ROOT / "logs" / "calls.jsonl"))
MAX_BYTES = 5_000_000          # past this the file rolls over to calls.1.jsonl
SOURCE = "mcp"                  # the terminal (`agent server <tool>`) sets this to "cli"


def record(tool: str, args: dict, started: float, chars: int, requests: int, error: str | None = None) -> None:
    entry = {
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tool": tool,
        "source": SOURCE,
        "args": args,
        "ms": round((time.monotonic() - started) * 1000),
        "requests": requests,
        "chars": chars,
        "error": error,
    }
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_BYTES:
            LOG_FILE.replace(LOG_FILE.with_suffix(".1.jsonl"))
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass                     # logging must never break a tool call


def read(count: int = 20) -> list[dict]:
    if not LOG_FILE.exists():
        return []
    entries = []
    for line in LOG_FILE.read_text(encoding="utf-8").splitlines()[-count:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _arg(value: object) -> str:
    return value if isinstance(value, str) and value and " " not in value else json.dumps(value, ensure_ascii=False)


def format_entries(entries: list[dict]) -> str:
    if not entries:
        return f"No calls logged yet ({LOG_FILE})."
    lines = [f"{'when':<11}  {'from':<4} {'tool':<9} {'arguments':<56} {'time':>5} {'req':>3} {'size':>6}"]
    for e in entries:
        args = " ".join(f"{k}={_arg(v)}" for k, v in e.get("args", {}).items())
        args = args if len(args) <= 56 else args[:55] + "…"
        mark = " ✗" if e.get("error") else ""
        lines.append(f"{e['time'][5:16].replace('T', ' ')}  {e.get('source', '?'):<4} {e['tool']:<9} {args:<56} "
                     f"{e['ms'] / 1000:>4.1f}s {e['requests']:>3} {e['chars'] / 1000:>5.1f}k{mark}")
        if e.get("error"):
            lines.append(f"    ↳ {e['error'][:110]}")
    return "\n".join(lines)
