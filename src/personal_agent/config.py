"""Settings, read from the environment or the `.env` file at the repo root."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / ".cache"


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
            if m:
                values[m.group(1)] = m.group(2).strip('"').strip("'")
    return values


@dataclass(frozen=True)
class Settings:
    notion_token: str
    root_page_id: str
    user_name: str = ""
    timezone: str = "UTC"


def load_settings(env_file: Path | None = None) -> Settings:
    """Environment variables win over the .env file."""
    file_values = _read_env_file(env_file or Path(os.environ.get("PERSONAL_AGENT_ENV", REPO_ROOT / ".env")))

    def get(key: str, default: str = "") -> str:
        return os.environ.get(key) or file_values.get(key) or default

    token, root = get("NOTION_TOKEN"), get("NOTION_ROOT_PAGE_ID")
    missing = [k for k, v in (("NOTION_TOKEN", token), ("NOTION_ROOT_PAGE_ID", root)) if not v]
    if missing:
        raise RuntimeError(f"Missing settings: {', '.join(missing)}. Run `python3 setup.py` or set them in .env.")
    return Settings(
        notion_token=token,
        root_page_id=root.replace("-", ""),
        user_name=get("USER_NAME"),
        timezone=get("USER_TIMEZONE", "UTC"),
    )
