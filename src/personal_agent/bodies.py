"""Page bodies: Markdown to Notion blocks and back, and the layout of a queue row's page.

A proposal can carry a `body` (Markdown). It is shown to the user as real Notion blocks in the
page of the queue row, under a "Body" heading, next to a "Properties" section with one
"Name: value" line per property. The user edits those in Notion; `proposals` reads them back
when the row is approved or applied, so what is written is what the user left there.

Supported: headings (#, ##, ###), paragraphs, bullet / numbered / to-do lists (one level of
nesting by indentation), quotes, dividers, code fences, and **bold**, *italic*, `code` and
[links](https://…) inside text. Reading back also keeps toggles and callouts; anything else
(images, tables, embeds) is reported as not copied, never silently dropped.
"""
from __future__ import annotations

import re
from typing import Any

from .notion_api import NotionAPI, plain_text

TEXT_CHUNK = 1900                 # Notion allows 2000 characters per rich-text part
MAX_BLOCKS = 300                  # blocks in one body, nested ones included
PROPERTIES_HEADING = "Properties"
BODY_HEADING = "Body"
HINT = ("Edit a value below before approving: what you leave here is what gets written. "
        "Add a line 'Property: value' to set another property; leave a value empty to clear it. "
        "Write or change the page body under Body.")

SIMPLE = ("paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item",
          "numbered_list_item", "to_do", "toggle", "quote", "callout")
_INLINE = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`|\*([^*\s][^*]*?)\*|\[([^\]]+)\]\((https?://[^)\s]+)\)")
_LIST = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(?:\[([ xX])\]\s+)?(.*)$")
_ANNOTATIONS = ("bold", "italic", "strikethrough", "underline", "code")
LANGUAGES = {"python", "javascript", "typescript", "json", "yaml", "bash", "shell", "sql", "html", "css", "java", "c",
             "c++", "c#", "go", "rust", "ruby", "swift", "kotlin", "r", "matlab", "markdown", "latex", "docker",
             "graphql", "plain text"}
LANGUAGE_ALIASES = {"py": "python", "js": "javascript", "ts": "typescript", "sh": "shell", "zsh": "shell",
                    "yml": "yaml", "cpp": "c++", "csharp": "c#", "md": "markdown", "text": "plain text", "txt": "plain text"}


def language(name: str) -> str:
    """A code-fence language Notion accepts (it refuses unknown ones); anything else is plain text."""
    name = LANGUAGE_ALIASES.get(name.lower(), name.lower())
    return name if name in LANGUAGES else "plain text"


# -- Markdown → blocks ---------------------------------------------------------------------
def rich_text(text: str) -> list[dict]:
    """Inline Markdown as a Notion rich-text array (parts of at most TEXT_CHUNK characters)."""
    parts: list[dict] = []

    def add(content: str, link: str | None = None, **flags: bool) -> None:
        for i in range(0, len(content), TEXT_CHUNK):
            part: dict[str, Any] = {"type": "text", "text": {"content": content[i:i + TEXT_CHUNK]}}
            if link:
                part["text"]["link"] = {"url": link}
            if flags:
                part["annotations"] = dict(flags)
            parts.append(part)

    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            add(text[pos:m.start()])
        bold, code, italic, label, url = m.groups()
        if bold is not None:
            add(bold, bold=True)
        elif code is not None:
            add(code, code=True)
        elif italic is not None:
            add(italic, italic=True)
        else:
            add(label, link=url)
        pos = m.end()
    if pos < len(text):
        add(text[pos:])
    return parts


def block(kind: str, text: str = "", **extra: Any) -> dict:
    return {"object": "block", "type": kind, kind: {"rich_text": rich_text(text), **extra}}


def divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def count_blocks(blocks: list[dict]) -> int:
    return sum(1 + count_blocks((b.get(b["type"]) or {}).get("children") or []) for b in blocks)


def markdown_to_blocks(md: str) -> list[dict]:
    """Markdown as Notion blocks. Lists nest one level by indentation; deeper levels are flattened."""
    blocks: list[dict] = []
    lines = (md or "").replace("\r\n", "\n").replace("\t", "  ").split("\n")
    paragraph: list[str] = []
    quote: list[str] = []
    last_list: dict | None = None

    def flush() -> None:
        nonlocal paragraph, quote
        if paragraph:
            blocks.append(block("paragraph", "\n".join(paragraph)))
        if quote:
            blocks.append(block("quote", "\n".join(quote)))
        paragraph, quote = [], []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        fence = re.match(r"^\s*```\s*([\w+-]*)\s*$", line)
        if fence:
            flush()
            last_list = None
            code: list[str] = []
            i += 1
            while i < len(lines) and not re.match(r"^\s*```\s*$", lines[i]):
                code.append(lines[i])
                i += 1
            text = "\n".join(code)
            chunks = [text[k:k + TEXT_CHUNK] for k in range(0, len(text), TEXT_CHUNK)] or [""]
            blocks.append({"object": "block", "type": "code", "code": {
                "rich_text": [{"type": "text", "text": {"content": c}} for c in chunks],
                "language": language(fence.group(1))}})
        elif not stripped:
            flush()
        elif re.fullmatch(r"-{3,}|\*{3,}|_{3,}", stripped):
            flush()
            last_list = None
            blocks.append(divider())
        elif (h := re.match(r"^(#{1,6})\s+(.*)$", stripped)):
            flush()
            last_list = None
            blocks.append(block(f"heading_{min(len(h.group(1)), 3)}", h.group(2)))
        elif (li := _LIST.match(line)):
            flush()
            indent, marker, checked, text = li.groups()
            if checked is not None:
                kind, extra = "to_do", {"checked": checked.lower() == "x"}
            else:
                kind, extra = ("numbered_list_item" if marker[0].isdigit() else "bulleted_list_item"), {}
            item = block(kind, text, **extra)
            if len(indent) >= 2 and last_list is not None:
                last_list[last_list["type"]].setdefault("children", []).append(item)
            else:
                blocks.append(item)
                last_list = item
        elif stripped.startswith(">"):
            if paragraph:
                flush()
            last_list = None
            quote.append(stripped[1:].lstrip())
        else:
            if quote:
                flush()
            last_list = None
            paragraph.append(stripped)
        i += 1
    flush()
    return blocks


# -- blocks → plain text (previews, comparisons) ---------------------------------------------
def plain(blocks: list[dict], depth: int = 0) -> str:
    out: list[str] = []
    number = 0
    for b in blocks:
        kind = b["type"]
        data = b.get(kind) or {}
        text = "".join(p.get("text", {}).get("content", "") for p in data.get("rich_text") or [])
        number = number + 1 if kind == "numbered_list_item" else 0
        pad = "  " * depth
        if kind.startswith("heading_"):
            out.append("#" * int(kind[-1]) + " " + text)
        elif kind == "bulleted_list_item":
            out.append(f"{pad}- {text}")
        elif kind == "numbered_list_item":
            out.append(f"{pad}{number}. {text}")
        elif kind == "to_do":
            out.append(f"{pad}- [{'x' if data.get('checked') else ' '}] {text}")
        elif kind == "quote":
            out.append(f"> {text}")
        elif kind == "divider":
            out.append("---")
        elif kind == "code":
            out.append(f"```\n{text}\n```")
        else:
            out.append(pad + text)
        if data.get("children"):
            out.append(plain(data["children"], depth + 1))
    return "\n".join(out).strip()


# -- Notion blocks (as read) → blocks (as written) ---------------------------------------------
def _write_rich_text(parts: list[dict] | None) -> list[dict]:
    out = []
    for part in parts or []:
        content = (part.get("text") or {}).get("content", part.get("plain_text", ""))
        if not content:
            continue
        item: dict[str, Any] = {"type": "text", "text": {"content": content[:TEXT_CHUNK + 100]}}
        link = (part.get("text") or {}).get("link")
        if link and link.get("url"):
            item["text"]["link"] = {"url": link["url"]}
        flags = {k: True for k in _ANNOTATIONS if (part.get("annotations") or {}).get(k)}
        if flags:
            item["annotations"] = flags
        out.append(item)
    return out


def convert_blocks(api: NotionAPI, blocks: list[dict], skipped: list[str], depth: int = 0) -> list[dict]:
    """Blocks as read from Notion → blocks that can be created elsewhere. Unsupported kinds go to `skipped`."""
    out: list[dict] = []
    for b in blocks:
        kind = b["type"]
        data = b.get(kind) or {}
        if kind in SIMPLE:
            new: dict[str, Any] = {"object": "block", "type": kind, kind: {"rich_text": _write_rich_text(data.get("rich_text"))}}
            if kind == "to_do":
                new[kind]["checked"] = bool(data.get("checked"))
            if kind == "callout" and (data.get("icon") or {}).get("type") == "emoji":
                new[kind]["icon"] = data["icon"]
            children = convert_blocks(api, api.block_children(b["id"]), skipped, depth + 1) if b.get("has_children") else []
            if children and depth == 0:
                new[kind]["children"] = children
                out.append(new)
            else:                                   # Notion accepts two levels per request: flatten deeper ones
                out.append(new)
                out.extend(children)
        elif kind == "code":
            out.append({"object": "block", "type": "code", "code": {
                "rich_text": _write_rich_text(data.get("rich_text")), "language": language(data.get("language") or "")}})
        elif kind == "divider":
            out.append(divider())
        else:
            skipped.append(kind.replace("_", " "))
    return out


def strip_blank(blocks: list[dict]) -> list[dict]:
    """Drop empty paragraphs at the start and the end (the placeholder left for typing)."""
    def blank(b: dict) -> bool:
        return b["type"] == "paragraph" and not any(p["text"]["content"].strip() for p in b["paragraph"]["rich_text"])
    start, end = 0, len(blocks)
    while start < end and blank(blocks[start]):
        start += 1
    while end > start and blank(blocks[end - 1]):
        end -= 1
    return blocks[start:end]


# -- the page of a queue row ----------------------------------------------------------------------
def row_blocks(shown: dict[str, str], body: list[dict]) -> list[dict]:
    """What the user sees and edits in the queue row: one line per property, then the body."""
    blocks = [block("quote", HINT), block("heading_2", PROPERTIES_HEADING)]     # no icon: Notion rejects unknown ones
    blocks += [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [
        {"type": "text", "text": {"content": f"{name}: {text}"[:TEXT_CHUNK]}}]}} for name, text in shown.items()]
    blocks.append(block("heading_2", BODY_HEADING))
    blocks += body or [block("paragraph", "")]
    return blocks


def split_row(blocks: list[dict]) -> tuple[list[tuple[str, str]], list[dict] | None]:
    """(property lines, body blocks) of a queue row's page, as read from Notion.
    The body is None when the Body heading is gone."""
    section = ""
    lines: list[tuple[str, str]] = []
    body: list[dict] | None = None
    for b in blocks:
        kind = b["type"]
        parts = (b.get(kind) or {}).get("rich_text") or []
        text = "".join(p.get("plain_text", "") for p in parts)
        if kind == "heading_2" and text.strip().lower() == PROPERTIES_HEADING.lower():
            section = "props"
        elif kind == "heading_2" and text.strip().lower() == BODY_HEADING.lower():
            section, body = "body", []
        elif section == "props" and kind == "paragraph":
            for line in text.split("\n"):
                m = re.match(r"^\s*([^:]+?)\s*:\s*(.*)$", line)
                if m:
                    lines.append((m.group(1), m.group(2)))
        elif section == "body" and body is not None:
            body.append(b)
    return lines, body
