"""Run any tool from the terminal and print exactly what the model would see.

    agent overview
    agent overview --refresh
    agent find interactions -w Date=today
    agent find commitments -w Status=OPEN -w "Due<=+7d" --sort Due
    agent find people -w Organization=Bosch
    agent get INT-14
    agent person "Banffy"
    agent agenda yesterday today
"""
from __future__ import annotations

import argparse
import sys
import time

from . import tools
from .workspace import Workspace


def _parse_where(items: list[str]) -> dict[str, str]:
    """'Due<=+7d' → {'Due': '<=+7d'};  'Status=OPEN' → {'Status': 'OPEN'}."""
    where = {}
    for item in items:
        for i, ch in enumerate(item):
            if ch in "=<>!~":
                key, value = item[:i].strip(), item[i:]
                where[key] = value[1:] if value.startswith("=") else value
                break
        else:
            raise SystemExit(f"Bad condition '{item}': use PROP=VALUE")
    return where


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="agent", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stats", action="store_true", help="also print timing and API request count")
    sub = parser.add_subparsers(dest="tool", required=True)
    p = sub.add_parser("overview", help=tools.overview.__doc__.splitlines()[0])
    p.add_argument("--refresh", action="store_true", help="rebuild the workspace map from Notion")
    p = sub.add_parser("find", help="rows of one database, filtered")
    p.add_argument("database")
    p.add_argument("--where", "-w", action="append", default=[], metavar="PROP=VALUE",
                   help='condition, repeatable: -w Date=today -w "Due<=+7d" -w Status=!=DONE')
    p.add_argument("--search", "-s", help="text the title contains")
    p.add_argument("--sort", help="property to sort by; prefix with - for descending")
    p.add_argument("--limit", "-n", type=int, default=20)
    p = sub.add_parser("get", help="one item with its content")
    p.add_argument("item", help="ID like INT-14, a page ID/link, or a title")
    p.add_argument("--database", "-d")
    p = sub.add_parser("person", help="look up a person, tolerating misspellings")
    p.add_argument("name")
    p = sub.add_parser("agenda", help="what is dated in a period, plus overdue items")
    p.add_argument("start", nargs="?", default="today")
    p.add_argument("end", nargs="?", default="+7d")
    args = parser.parse_args(argv)

    ws = Workspace()
    start = time.monotonic()
    if args.tool == "overview":
        print(tools.overview(ws, refresh=args.refresh))
    elif args.tool == "find":
        print(tools.find(ws, args.database, _parse_where(args.where), args.search, args.sort, args.limit))
    elif args.tool == "get":
        print(tools.get(ws, args.item, args.database))
    elif args.tool == "person":
        print(tools.person(ws, args.name))
    elif args.tool == "agenda":
        print(tools.agenda(ws, args.start, args.end))
    if args.stats:
        api_calls = ws.api.request_count if "api" in ws.__dict__ else 0
        print(f"\n[{time.monotonic() - start:.1f}s, {api_calls} Notion requests]", file=sys.stderr)


if __name__ == "__main__":
    main()
