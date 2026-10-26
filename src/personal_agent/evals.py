"""Regression checks: run tool calls and check what comes back.

A case file (JSON) holds a list of cases:

    {
      "name": "weekly-update",                       # short id
      "question": "What came out of yesterday's weekly update?",
      "calls": [{"tool": "find", "args": {"database": "Interactions",
                                          "where": {"Date": "2026-10-20"}}}],
      "expect": ["INT-14"],                          # must all appear (case-insensitive)
      "expect_not": ["CVPR call"],                   # must not appear
      "why": "the reason this case exists"
    }

`calls` are the tool calls a good agent should make for `question`; the case
passes if their combined output contains every `expect` and no `expect_not`.
Run with `agent eval`. `agent eval --questions` prints the questions to try
by hand in a chat, with the tools the model should use.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import tools
from .config import REPO_ROOT
from .guide import guide_text
from .notion_api import NotionError
from .query import QueryError
from .workspace import Workspace

DEFAULT_FILES = [REPO_ROOT / "evals" / "cases.local.json", REPO_ROOT / "evals" / "cases.example.json"]


def _call(ws: Workspace, tool: str, args: dict) -> str:
    if tool == "guide":
        return guide_text(ws.settings)
    fn = getattr(tools, tool, None)
    if fn is None or tool.startswith("_") or tool == "format_row":
        raise ValueError(f"unknown tool '{tool}'")
    return fn(ws, **args)


def load_cases(path: Path | None) -> tuple[Path, list[dict]]:
    for candidate in ([path] if path else DEFAULT_FILES):
        if candidate and candidate.exists():
            return candidate, json.loads(candidate.read_text())
    raise SystemExit("No case file: create evals/cases.local.json (see evals/README.md).")


def run(path: Path | None = None, only: str | None = None, verbose: bool = False) -> int:
    file, cases = load_cases(path)
    if only:
        cases = [c for c in cases if only in c["name"]]
    ws = Workspace()
    shown = file.resolve().relative_to(REPO_ROOT) if file.resolve().is_relative_to(REPO_ROOT) else file
    print(f"{len(cases)} cases from {shown}\n")
    failed = 0
    for case in cases:
        start = time.monotonic()
        try:
            output = "\n\n".join(_call(ws, c["tool"], c.get("args", {})) for c in case["calls"])
        except (QueryError, NotionError) as err:   # what the model would see as an error result
            output = f"Error: {err}"
        except Exception as err:   # noqa: BLE001 - a crash is a failure, keep going
            output = f"CRASH: {type(err).__name__}: {err}"
        low = output.lower()
        missing = [e for e in case.get("expect", []) if e.lower() not in low]
        unwanted = [e for e in case.get("expect_not", []) if e.lower() in low]
        ok = not missing and not unwanted and not output.startswith("CRASH")
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {case['name']}  ({time.monotonic() - start:.1f}s)")
        if not ok:
            if missing:
                print(f"      missing: {missing}")
            if unwanted:
                print(f"      should not contain: {unwanted}")
            if case.get("why"):
                print(f"      why it matters: {case['why']}")
        if verbose or not ok:
            print("      " + "\n      ".join(output.splitlines()[:12]))
    print(f"\n{len(cases) - failed}/{len(cases)} passed")
    return 1 if failed else 0


def questions(path: Path | None = None) -> None:
    """Print the questions to ask in a chat, with the expected tool path."""
    _, cases = load_cases(path)
    for i, case in enumerate(cases, 1):
        if not case.get("question"):
            continue
        path_ = " → ".join(f"{c['tool']}({', '.join(f'{k}={v!r}' for k, v in c.get('args', {}).items())})"
                           for c in case["calls"])
        print(f"{i}. {case['question']}\n   expected: {path_}\n   answer must mention: {', '.join(case.get('expect', []))}\n")
