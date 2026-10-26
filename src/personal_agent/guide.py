"""The agent guide (AGENT.md) with this installation's settings filled in.

Served by the MCP server as a tool, a prompt and a resource, so any client
that installs the server also gets the rules, with nothing to paste.
"""
from __future__ import annotations

from .config import REPO_ROOT, Settings

GUIDE_FILE = REPO_ROOT / "AGENT.md"


def guide_text(settings: Settings) -> str:
    guide = GUIDE_FILE.read_text()
    name = settings.user_name or "the user"
    installation = f"""## 0. This installation

- The user is **{name}**. Their time zone is {settings.timezone}: read and
  write dates in it.
- The root page is already configured in the personal-agent server: you do
  not need its ID. Use the server's tools (section 1b).

"""
    cut = guide.index("\n## ")          # after the intro, before section 1
    return guide[: cut + 1] + "\n" + installation + guide[cut + 1:]
