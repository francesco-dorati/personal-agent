#!/bin/sh
# Start the MCP server over HTTP. Used by launchd (scripts/com.personal-agent.mcp.plist) or by hand.
cd "$(dirname "$0")/.." || exit 1
exec .venv/bin/agent-mcp --transport http "$@"
