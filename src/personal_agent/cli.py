"""Command line for the personal agent.

MCP server tools: run them as a model would, and print exactly what it gets back.

    agent server list [--full]                     every tool: signature, summary, example
    agent server log [N]                           the last N logged calls (who called what, how long)
    agent server overview
    agent server find Interactions '{"Date": "yesterday"}'
    agent server find database=Commitments where='{"Status": "OPEN"}' sort=Due
    agent server get INT-14
    agent server person "Banffy"
    agent server agenda yesterday today
    agent server queue                             what is waiting for approval
    agent server apply dry_run=true                what applying the approved rows would do

Other commands:

    agent eval                                     regression checks (see evals/README.md)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="agent", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stats", action="store_true",
                        help="also print timing and API request count (server commands)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("server", help="call the MCP server's tools as a model would (start: agent server list)",
                       description="Call the MCP server's tools as a model would. "
                                   "`agent server list` shows every tool with its syntax; `agent server log` the call history.")
    p.add_argument("action", metavar="list|TOOL", help="`list`, `log`, or a tool name: overview, refresh, find, search, get, person, agenda, guide, propose, queue, approve, reject, apply, revert, log_habit, log_checkin, habits_status, log_interaction, add_commitment, complete_commitment, update_item, set_inactive, add_person, add_organization")
    p.add_argument("rest", nargs=argparse.REMAINDER, metavar="ARGUMENTS",
                   help='positional, name=value, or one JSON object, e.g. find Interactions \'{"Date": "yesterday"}\'')
    sub.add_parser("refresh", help="reload the workspace map and all names from Notion now (run before a session)")
    p = sub.add_parser("eval", help="run the regression cases in evals/")
    p.add_argument("--file", type=Path, help="case file (default: evals/cases.local.json, else the example)")
    p.add_argument("-k", dest="only", help="only cases whose name contains this")
    p.add_argument("-v", "--verbose", action="store_true", help="show output of passing cases too")
    p.add_argument("--questions", action="store_true", help="print questions to try by hand in a chat")
    args = parser.parse_args(argv)

    if args.command == "eval":
        from . import evals
        if args.questions:
            evals.questions(args.file)
            return
        sys.exit(evals.run(args.file, args.only, args.verbose))

    if args.command == "refresh":
        from .server import _workspace
        start = time.monotonic()
        dbs, items = _workspace().refresh_all()
        print(f"Refreshed {dbs} databases and {items} items in {time.monotonic() - start:.0f}s.")
        return

    from . import server_commands
    start = time.monotonic()
    status = server_commands.run(args.action, args.rest)
    if args.stats and args.action != "list":
        print(f"\n[{time.monotonic() - start:.1f}s, {server_commands.request_count()} Notion requests]",
              file=sys.stderr)
    sys.exit(status)


if __name__ == "__main__":
    main()
