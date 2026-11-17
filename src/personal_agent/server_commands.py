"""`agent server …`: use the MCP server's tools from the terminal, the way a model does.

    agent server list [--full]        every tool: signature, one-line summary, example
    agent server log [N]              the last N logged calls
    agent server <tool> [arguments]   call a tool and print what the model gets back

The call goes through the same MCP server object that `agent-mcp` serves, so
argument validation, descriptions and results are the ones a model sees.

Arguments can be written in three equivalent ways:

    agent server find Interactions '{"Date": "yesterday"}'       positional, in signature order
    agent server find database=Interactions limit=5              name=value
    agent server find '{"database": "Interactions", "limit": 5}' the exact JSON a model sends
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from typing import Any

EXAMPLES: dict[str, list[str]] = {
    "overview": [
        "agent server overview",
        "agent server overview refresh=true",
    ],
    "find": [
        """agent server find Interactions '{"Date": "yesterday"}'""",
        """agent server find database=Commitments where='{"Status": "OPEN", "Due": "<=+7d"}' sort=Due""",
        """agent server find '{"database": "People", "where": {"Organization": "Bosch"}, "limit": 5}'""",
    ],
    "search": [
        "agent server search Acar",
        "agent server search text=Bosch databases=Organizations,Opportunities",
        """agent server search '{"text": "weekly", "limit": 5}'""",
    ],
    "get": [
        "agent server get INT-14",
        """agent server get '{"item": ["INT-14", "PER-2"]}'""",
        'agent server get item=Weekly database=Interactions',
        "agent server get INT-14 offset=8000",
    ],
    "person": [
        'agent server person "Banffy"',
    ],
    "agenda": [
        "agent server agenda",
        "agent server agenda today +7d",
        "agent server agenda start=yesterday end=yesterday",
    ],
    "guide": [
        "agent server guide",
    ],
    "propose": [
        """agent server propose '{"changes": [{"operation": "CREATE", "database": "Habits Log", "properties": {"Habit": "Learn Mandarin", "Date": "now", "Value": 1}}], "reason": "test", "dry_run": true}'""",
    ],
    "queue": [
        "agent server queue",
        "agent server queue status=APPLIED limit=10",
    ],
    "approve": [
        """agent server approve '{"ids": [12], "approved_by": "yes, log it"}'""",
    ],
    "reject": [
        "agent server reject ids=12 reason='not today'",
    ],
    "apply": [
        "agent server apply",
        "agent server apply dry_run=true",
        """agent server apply '{"ids": [12]}'""",
    ],
    "revert": [
        "agent server revert 12",
    ],
    "log_habit": [
        "agent server log_habit habit='Learn Mandarin'",
        "agent server log_habit habit='Learn Mandarin' dry_run=true",
    ],
    "log_checkin": [
        "agent server log_checkin sleep_hours=7.5 morning_energy=70 dry_run=true",
    ],
    "log_interaction": [
        """agent server log_interaction '{"name": "Call with Anna", "type": "CALL", "people": ["Anna"], "commitments": [{"name": "Send the draft", "due": "2026-10-30"}], "dry_run": true}'""",
    ],
    "add_commitment": [
        "agent server add_commitment name='Send the draft' due=2026-10-30 dry_run=true",
    ],
    "complete_commitment": [
        "agent server complete_commitment commitment=COM-4 dry_run=true",
    ],
    "update_item": [
        """agent server update_item database=Habits item=HAB-1 reviewed=true dry_run=true""",
    ],
    "set_inactive": [
        "agent server set_inactive database=Habits item=HAB-3 dry_run=true",
    ],
    "add_person": [
        "agent server add_person name='Jane Doe' organization=Bosch dry_run=true",
    ],
    "add_organization": [
        "agent server add_organization name='ACME Robotics' category=STARTUP dry_run=true",
    ],
    "refresh": [
        "agent server refresh",
    ],
    "habits_status": [
        "agent server habits_status",
    ],
    "review": [
        "agent server review",
        "agent server review horizon_days=14 contact_days=90",
        "agent server review sections=commitments,habits,checkins",
    ],
    "log_conversation": [
        """agent server log_conversation '{"title": "Low energy lately", "summary": "...", "outcome": "OPEN", "dry_run": true}'""",
    ],
}


# ---------------------------------------------------------------- schema helpers

def _types(prop: dict[str, Any]) -> set[str]:
    """All JSON types a property accepts (handles Optional via anyOf)."""
    found: set[str] = set()

    def walk(schema: dict[str, Any]) -> None:
        t = schema.get("type")
        if t:
            found.update(t if isinstance(t, list) else [t])
        for key in ("anyOf", "oneOf"):
            for sub in schema.get(key, []):
                walk(sub)

    walk(prop)
    return found


def _label(prop: dict[str, Any]) -> str:
    types = sorted(_types(prop) - {"null"})
    return "|".join(types) or "any"


def _signature(name: str, schema: dict[str, Any]) -> str:
    required = set(schema.get("required", []))
    parts = []
    for pname, prop in schema.get("properties", {}).items():
        text = f"{pname}{'' if pname in required else '?'}: {_label(prop)}"
        if pname not in required and prop.get("default") is not None:
            text += f" = {json.dumps(prop['default'])}"
        parts.append(text)
    return f"{name}({', '.join(parts)})"


def _schema(tool: Any) -> dict[str, Any]:
    return getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {}


# ---------------------------------------------------------------- argument parsing

def _coerce(name: str, raw: str, prop: dict[str, Any]) -> Any:
    types = _types(prop)
    if raw == "null" and "null" in types:
        return None
    if "array" in types and raw.lstrip().startswith("["):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise SystemExit(f"Argument '{name}': not valid JSON: {raw!r}") from None
    if "string" in types:
        return raw                                  # keep "today", "5", "INT-14" as text
    if "array" in types:
        return [part.strip() for part in raw.split(",") if part.strip()]   # People,Interactions
    if "boolean" in types and raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise SystemExit(f"Argument '{name}' expects {_label(prop)}, got {raw!r}.") from None


def parse_arguments(schema: dict[str, Any], tokens: list[str]) -> dict[str, Any]:
    """Turn command-line tokens into the arguments object a model would send."""
    props: dict[str, Any] = schema.get("properties", {})
    if len(tokens) == 1 and tokens[0].lstrip().startswith("{"):
        try:
            args = json.loads(tokens[0])
        except json.JSONDecodeError as err:
            raise SystemExit(f"The JSON arguments are not valid JSON: {err}") from None
        if not isinstance(args, dict):
            raise SystemExit("The JSON arguments must be an object.")
        return args

    args = {}
    free = list(props)                              # positional slots, in signature order
    for token in tokens:
        match = re.match(r"([A-Za-z_]\w*)=(.*)$", token, re.DOTALL)
        if match and match.group(1) in props:
            key, raw = match.group(1), match.group(2)
        else:
            free = [p for p in free if p not in args]
            if not free:
                raise SystemExit(f"Too many arguments: {token!r}. See: agent server list")
            key, raw = free[0], token
        if key in args:
            raise SystemExit(f"Argument '{key}' given twice.")
        args[key] = _coerce(key, raw, props[key])
    return args


# ---------------------------------------------------------------- server access

def _server():
    from . import server       # imported lazily: needs the `mcp` package
    return server


def request_count() -> int:
    return _server()._requests()


async def _tools() -> list[Any]:
    return await _server().mcp.list_tools()


# ---------------------------------------------------------------- list

def _summary(description: str, limit: int = 100) -> str:
    """First sentence of a tool description, on one line."""
    text = " ".join(description.split())
    text = re.sub(r"\s*\([^)]*\)", "", text)          # drop parentheticals
    text = re.split(r"(?<!e\.g)(?<!i\.e)\.\s", text, maxsplit=1)[0].rstrip(".")
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def list_text(full: bool = False) -> str:
    mcp = _server().mcp
    tools = asyncio.run(_tools())
    out = [f"{mcp.name} MCP server: {len(tools)} tools"
           + (", all read-only" if all(getattr(getattr(t, "annotations", None), "read_only_hint", False)
                                       for t in tools) else ""),
           "call:  agent server <tool> [args]      args: positional | name=value | '{json}'",
           ""]
    if full:
        out += ["instructions sent to the model:",
                *[f"  {line}" for line in (mcp.instructions or "(none)").splitlines()], ""]
    for tool in tools:
        out.append(_signature(tool.name, _schema(tool)))
        if full:
            out.extend(f"    {line}".rstrip() for line in (tool.description or "").splitlines())
            for pname, prop in _schema(tool).get("properties", {}).items():
                if prop.get("description"):
                    out.append(f"  - {pname} ({_label(prop)}): {prop['description']}")
            out.extend(f"  e.g. {example}" for example in EXAMPLES.get(tool.name, []))
        else:
            out.append(f"    {_summary(tool.description or '')}")
            examples = EXAMPLES.get(tool.name)
            out.append(f"  e.g. {examples[0] if examples else f'agent server {tool.name}'}")
        out.append("")
    if not full:
        out.append("agent server list --full   full descriptions, argument docs, more examples")
    out.append("agent server log [N]       last N logged calls (default 20)")
    return "\n".join(out).rstrip()


# ---------------------------------------------------------------- call

async def _call(name: str, tokens: list[str]) -> int:
    tools = {t.name: t for t in await _tools()}
    if name not in tools:
        raise SystemExit(f"Unknown server command '{name}'. Available: {', '.join(tools)}. "
                         "See: agent server list")
    arguments = parse_arguments(_schema(tools[name]), tokens)
    call = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in arguments.items())
    print(f"→ {name}({call})", file=sys.stderr)
    print(f"  tools/call {json.dumps({'name': name, 'arguments': arguments}, ensure_ascii=False)}\n",
          file=sys.stderr)
    try:
        result = await _server().mcp.call_tool(name, arguments)
    except Exception as err:       # noqa: BLE001 - show what the model would be told
        print(f"Error: {err}")
        return 1
    texts = [block.text for block in getattr(result, "content", []) if hasattr(block, "text")]
    print("\n".join(texts))
    return 1 if getattr(result, "is_error", False) else 0


def run(action: str, tokens: list[str]) -> int:
    if action == "log":
        from . import calllog
        try:
            count = int(tokens[0]) if tokens else 20
        except ValueError:
            raise SystemExit("Usage: agent server log [N]") from None
        print(calllog.format_entries(calllog.read(count)))
        return 0
    if action == "list":
        print(list_text(full="--full" in tokens))
        return 0
    from . import calllog
    calllog.SOURCE = "cli"          # tell terminal calls apart from a model's
    return asyncio.run(_call(action, tokens))
