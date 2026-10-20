"""Render a page's content (Notion blocks) as compact Markdown-like text."""
from __future__ import annotations

from .notion_api import NotionAPI, plain_text

MAX_DEPTH = 3


def render_page(api: NotionAPI, page_id: str, max_chars: int = 8000) -> str:
    lines: list[str] = []
    _render(api, page_id, 0, lines)
    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + f"\n… (truncated, {len(text) - max_chars} more characters)"
    return text


def _render(api: NotionAPI, block_id: str, depth: int, lines: list[str]) -> None:
    pad = "  " * depth
    number = 0
    for block in api.block_children(block_id):
        kind = block["type"]
        data = block.get(kind, {}) or {}
        text = plain_text(data.get("rich_text"))
        number = number + 1 if kind == "numbered_list_item" else 0
        if kind == "paragraph":
            line = text
        elif kind.startswith("heading_"):
            line = "#" * int(kind[-1]) + " " + text
        elif kind == "bulleted_list_item":
            line = f"- {text}"
        elif kind == "numbered_list_item":
            line = f"{number}. {text}"
        elif kind == "to_do":
            line = f"- [{'x' if data.get('checked') else ' '}] {text}"
        elif kind == "toggle":
            line = f"▸ {text}"
        elif kind == "quote":
            line = f"> {text}"
        elif kind == "callout":
            line = f"! {text}"
        elif kind == "code":
            line = f"```\n{text}\n```"
        elif kind == "divider":
            line = "---"
        elif kind == "child_page":
            line = f"[sub-page: {data.get('title', '')}]"
        elif kind == "child_database":
            line = f"[database: {data.get('title', '')}]"
        elif kind == "table_row":
            line = " | ".join(plain_text(cell) for cell in data.get("cells", []))
        elif kind in ("table", "column_list", "column", "synced_block"):
            line = None
        elif kind in ("bookmark", "embed", "link_preview"):
            line = f"[link: {data.get('url', '')}]"
        elif kind in ("image", "file", "pdf", "video", "audio"):
            line = f"[{kind}{': ' + plain_text(data.get('caption')) if data.get('caption') else ''}]"
        elif kind == "link_to_page":
            line = "[link to another page]"
        else:
            line = f"[{kind.replace('_', ' ')}]"   # e.g. meeting notes, unsupported blocks
        if line is not None and (line.strip() or kind == "paragraph"):
            lines.append(pad + line if line else "")
        if block.get("has_children") and kind not in ("child_page", "child_database") and depth < MAX_DEPTH:
            _render(api, block["id"], depth + (0 if line is None else 1), lines)
