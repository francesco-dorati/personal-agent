"""Discovery: build a map of the workspace starting from the root page.

Walks the page tree under the root page and records every text page and every
database (with its data source, properties, options and relations). Nothing
is hardcoded: a database added anywhere under the root shows up on the next
refresh. The result is cached in `.cache/registry.json`.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .notion_api import NotionAPI, NotionError, plain_text

MAX_DEPTH = 6
CONTAINER_BLOCKS = {"toggle", "column_list", "column", "synced_block", "callout", "quote"}
HEADINGS = {"heading_1", "heading_2", "heading_3"}


@dataclass
class Option:
    name: str
    description: str = ""


@dataclass
class Property:
    name: str
    type: str
    description: str = ""
    options: list[Option] = field(default_factory=list)
    relation_to: str = ""          # data source id of the related database
    prefix: str = ""               # unique_id prefix, e.g. "INT"


@dataclass
class Database:
    name: str
    path: list[str]                # e.g. ["Content", "Collections"]
    database_id: str
    data_source_id: str
    page_id: str = ""              # wrapper page holding the database, if any
    description: str = ""          # database description, else the wrapper page's intro
    properties: list[Property] = field(default_factory=list)
    row_count: int | None = None   # None = not counted; 101 means "more than 100"
    order: int = 0                 # position in the page tree (reading order)


@dataclass
class Page:
    name: str
    path: list[str]
    page_id: str
    intro: str = ""                # first paragraph of the page
    is_empty: bool = False
    order: int = 0


REGISTRY_VERSION = 2


@dataclass
class Registry:
    root_page_id: str
    root_title: str
    built_at: float
    pages: list[Page] = field(default_factory=list)
    databases: list[Database] = field(default_factory=list)
    version: int = REGISTRY_VERSION

    # -- lookups ------------------------------------------------------------
    def database_by_id(self, data_source_id: str) -> Database | None:
        return next((d for d in self.databases if d.data_source_id == data_source_id), None)

    def database_by_prefix(self, prefix: str) -> Database | None:
        key = prefix.upper()
        return next((d for d in self.databases for p in d.properties
                     if p.type == "unique_id" and p.prefix.upper() == key), None)

    def find_database(self, name: str) -> Database | None:
        key = name.strip().lower()
        return next((d for d in self.databases if d.name.lower() == key), None)

    # -- persistence --------------------------------------------------------
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False))

    @classmethod
    def load(cls, path: Path) -> "Registry":
        raw = json.loads(path.read_text())
        dbs = []
        for d in raw["databases"]:
            props = [Property(**{**p, "options": [Option(**o) for o in p["options"]]}) for p in d["properties"]]
            dbs.append(Database(**{**d, "properties": props}))
        return cls(raw["root_page_id"], raw["root_title"], raw["built_at"],
                   [Page(**p) for p in raw["pages"]], dbs, raw.get("version", 1))


# --------------------------------------------------------------------------
def _block_text(block: dict) -> str:
    return plain_text(block.get(block["type"], {}).get("rich_text"))


class _Builder:
    def __init__(self, api: NotionAPI, count_rows: bool):
        self.api, self.count_rows = api, count_rows
        self.pages: list[Page] = []
        self.databases: list[Database] = []
        self._seen_databases: set[str] = set()
        self._counter = 0

    def _next(self) -> int:
        self._counter += 1
        return self._counter

    def walk(self, block_id: str, path: list[str], depth: int, holder: str = "", intro: str = "") -> None:
        if depth <= MAX_DEPTH:
            self._walk_blocks(self.api.block_children(block_id), path, depth, holder, intro)

    def _page(self, block: dict, path: list[str], depth: int) -> None:
        if depth > MAX_DEPTH:
            return
        title = block["child_page"].get("title") or "Untitled"
        children = self.api.block_children(block["id"])
        intro = next((_block_text(b) for b in children if b["type"] == "paragraph" and _block_text(b)), "")
        page = Page(title, path, block["id"].replace("-", ""), intro, is_empty=not children, order=self._next())
        n_before = len(self.databases)
        self.pages.append(page)
        # Look inside the page for databases and sub-pages.
        self._walk_blocks(children, path + [title], depth + 1, page.page_id, intro)
        inner = self.databases[n_before:]
        # A page that holds a database of the same name (or only databases) is
        # reported as that database, not as a separate page.
        if inner and (self._only_wrapper(children) or any(d.name == title for d in inner)):
            self.pages.remove(page)
            for d in inner:
                if d.name == title or len(inner) == 1:
                    d.order = page.order

    def _walk_blocks(self, blocks: list[dict], path: list[str], depth: int, holder: str, intro: str) -> None:
        """Visit a list of sibling blocks. A heading groups the blocks after it."""
        heading: str | None = None
        for block in blocks:
            kind = block["type"]
            here = path + ([heading] if heading else [])
            if kind in HEADINGS:
                heading = _block_text(block) or None
                if block[kind].get("is_toggleable") and block.get("has_children"):
                    self.walk(block["id"], path + ([heading] if heading else []), depth + 1, holder, intro)
            elif kind == "child_page":
                self._page(block, here, depth)
            elif kind == "child_database":
                self._database(block["id"], here, holder, intro)
            elif kind in CONTAINER_BLOCKS and block.get("has_children"):
                label = _block_text(block) if kind == "toggle" else ""
                self.walk(block["id"], here + ([label] if label else []), depth + 1, holder, intro)

    @staticmethod
    def _only_wrapper(children: list[dict]) -> bool:
        """True if the page holds databases and at most short text around them."""
        kinds = {b["type"] for b in children}
        return "child_database" in kinds and not ({"child_page", "heading_1", "heading_2"} & kinds)

    def _database(self, database_id: str, path: list[str], holder: str, intro: str) -> None:
        database_id = database_id.replace("-", "")
        if database_id in self._seen_databases:
            return
        self._seen_databases.add(database_id)
        try:
            db = self.api.database(database_id)
        except NotionError as err:   # linked view of a database we can't open
            if err.status in (403, 404):
                return
            raise
        name = plain_text(db.get("title")) or "Untitled"
        # Drop the wrapper page's own name from the path ("People" page → "People" db).
        if path and path[-1] == name:
            path = path[:-1]
        description = plain_text(db.get("description")) or intro
        for source in db.get("data_sources", []):
            ds = self.api.data_source(source["id"])
            props = [self._property(p) for p in ds.get("properties", {}).values()]
            props.sort(key=lambda p: (p.type != "title", p.name.lower()))
            count = len(self.api.query(source["id"], limit=101)) if self.count_rows else None
            ds_name = plain_text(ds.get("title")) or source.get("name") or name
            self.databases.append(Database(
                name=ds_name if len(db.get("data_sources", [])) > 1 else name,
                path=path, database_id=database_id, data_source_id=source["id"].replace("-", ""),
                page_id=holder, description=description, properties=props, row_count=count,
                order=self._next(),
            ))

    @staticmethod
    def _property(raw: dict) -> Property:
        kind = raw["type"]
        options = [Option(o["name"], o.get("description") or "")
                   for o in raw.get(kind, {}).get("options", [])] if kind in ("select", "multi_select", "status") else []
        relation_to = (raw.get("relation", {}).get("data_source_id") or "").replace("-", "")
        prefix = (raw.get("unique_id") or {}).get("prefix") or "" if kind == "unique_id" else ""
        return Property(raw["name"], kind, raw.get("description") or "", options, relation_to, prefix)


def build_registry(api: NotionAPI, root_page_id: str, *, count_rows: bool = True) -> Registry:
    try:
        root = api.page(root_page_id)
    except NotionError as err:
        if err.status == 404:
            raise RuntimeError(
                "The Notion integration cannot see the root page. In Notion, open the root page, "
                "click ••• → Connections, and add your integration (pages below it are included)."
            ) from err
        raise
    title_prop = next((p for p in root.get("properties", {}).values() if p.get("type") == "title"), {})
    builder = _Builder(api, count_rows)
    builder.walk(root_page_id, [], 0)
    return Registry(root_page_id, plain_text(title_prop.get("title")) or "Root",
                    time.time(), builder.pages, builder.databases)
