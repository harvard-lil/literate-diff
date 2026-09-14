"""The doc source: reference documents, one unit per file, rows by sentence.

A standard the work follows, a runbook it changed, a design note it was
built from. The file is embedded as its copy of record and rendered as the
markdown it was written in, with every sentence addressable, so a claim can
quote the paragraph it rests on.

```yaml
sources:
  standards:
    type: doc
    files:
      - ../lil-engineering/docs/standards/deploys.md
      - path: notes/design.md
        title: The design note this started from
```

A document exported from somewhere else (a Google Doc as markdown) says where
it came from in YAML front matter, which the file keeps as its copy of record
and the page shows above the text:

```markdown
---
title: Deploy standard
origin: Google Docs
url: https://docs.google.com/document/d/…/edit
modified: 2026-08-14T17:36:37Z
retrieved: 2026-09-14
---
```

The same keys on a `files:` entry override the front matter.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import yaml

from ..message import inline_row, render_message
from ..model import Anchor, Item, Layer, SourceInfo, Unit, slug
from ..transcript import MONTHS, split_rows
from .base import LoadContext, SourcePlugin

FRONT_MATTER = re.compile(r"\A---[ \t]*\n(.*?\n)?---[ \t]*(?:\n|\Z)", re.S)
PROVENANCE = ("origin", "url", "modified", "retrieved")


def split_front_matter(text: str) -> tuple[dict, str]:
    """(front matter, body). Text that does not open with a YAML mapping
    between `---` lines has no front matter, and is all body."""
    m = FRONT_MATTER.match(text)
    if not m:
        return {}, text
    try:
        data = yaml.safe_load(m.group(1) or "")
    except yaml.YAMLError:
        return {}, text
    if not isinstance(data, dict):
        return {}, text
    return data, text[m.end():]


def _day(value) -> str:
    """`Aug. 14, 2026` from a date, a timestamp, or ISO text; other text as given."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if isinstance(value, (date, datetime)):
        return f"{MONTHS[value.month - 1]} {value.day}, {value.year}"
    return str(value)


@dataclass(kw_only=True)
class DocBody(Unit):
    text: str = ""
    origin: str = ""
    url: str = ""
    modified: str = ""
    retrieved: str = ""

    @property
    def is_prose(self) -> bool:
        return True


class DocSource(SourcePlugin):
    type = "doc"
    evidence = "document"
    natural_order = False
    v1_items_key = ""

    def load(self, ctx: LoadContext) -> tuple[list[Item], SourceInfo]:
        conf = ctx.conf
        entries = conf.get("files")
        if entries is None and conf.get("file"):
            entries = [conf["file"]]
        if conf.get("text") is not None:
            entries = [{"path": conf.get("file") or "document.md", "text": conf["text"]}]
        if not isinstance(entries, list) or not entries:
            raise SystemExit(f"sources.{ctx.name} needs `files:` (a list of paths)")
        items: list[Item] = []
        info = SourceInfo(name=ctx.name, type=self.type, label=conf.get("label") or ctx.name)
        for entry in entries:
            if isinstance(entry, str):
                entry = {"path": entry}
            path = str(entry.get("path") or "")
            if entry.get("text") is not None:
                text = entry["text"]
            else:
                full = Path(path) if Path(path).is_absolute() else ctx.cwd / path
                if not full.is_file():
                    raise SystemExit(f"document not found: {full}")
                text = full.read_text(encoding="utf-8", errors="replace")
            name = Path(path).name
            front, prose = split_front_matter(text)
            about = {**front, **{k: v for k, v in entry.items() if v is not None}}
            title = str(about.get("title") or "")
            body = DocBody(
                key=f"{ctx.name}:{name}", path=name, source=ctx.name, kind="doc",
                label=title or name, text=text, lines=split_rows(prose),
                **{k: str(about.get(k) or "") if k in ("origin", "url")
                   else (_day(about[k]) if about.get(k) else "") for k in PROVENANCE},
            )
            items.append(Item(key=body.key, source=ctx.name, plugin=self.type, payload=body,
                              bodies=[body], title=title))
            if ctx.embed:
                info.embed[name] = text
        info.counts = {"items": len(items)}
        return items, info

    def match(self, item: Item, pattern: str) -> bool:
        from fnmatch import fnmatch
        return fnmatch(item.key, pattern) or fnmatch(item.payload.path, pattern)

    def item_anchor_id(self, item: Item, n: int) -> str:
        return slug("doc-" + item.payload.path)

    def auto_ids(self, item: Item) -> list[str]:
        return [slug("file:" + item.key)]

    def body_dom(self, item: Item, unit, n: int) -> str:
        return f"d{n}"

    def render_item(self, r, layer: Layer, item: Item, show_source: bool) -> str:
        body: DocBody = item.payload
        dom = r.body_dom[id(body)]
        note = (
            f'<div class="ld-doc-note">{r.md(item.note_md, r.here(item, 0), body.path)}</div>'
            if item.note_md.strip() else ""
        )
        title = f'<span class="ld-doc-title">{html.escape(item.title)}</span>' if item.title else ""
        ranges = [(0, len(body.lines) - 1)]
        return (
            f'<section class="ld-doc" id="{html.escape(item.anchor_id)}">'
            f'<div class="ld-doc-head"><code class="ld-path">{html.escape(body.path)}</code>{title}'
            f"{self._provenance(body)}</div>"
            f"{note}"
            f'<div class="ld-doc-body ld-msg-body">{render_message(body.lines, dom, ranges)}</div>'
            "</section>"
        )

    def _provenance(self, body: DocBody) -> str:
        """Where an exported copy came from and how old it is: the page shows
        the copy, and the original may have changed since."""
        bits = []
        if body.url:
            where = html.escape(body.origin or "original")
            bits.append(f'<a href="{html.escape(body.url)}">{where}</a>')
        elif body.origin:
            bits.append(html.escape(body.origin))
        if body.modified:
            bits.append(f"last modified {html.escape(body.modified)}")
        if body.retrieved:
            bits.append(f"retrieved {html.escape(body.retrieved)}")
        return f'<span class="ld-doc-prov">{" · ".join(bits)}</span>' if bits else ""

    def quote(self, r, anchor: Anchor, target: str, label: str) -> str:
        body: DocBody = anchor.file
        rows = "".join(
            f'<span class="ld-qrow ld-q{line.kind}"><span class="ld-qtext">{inline_row(line) or "&nbsp;"}</span></span>'
            for line in body.lines[anchor.start : anchor.end + 1]
        )
        head = (
            f'<span class="ld-qhead"><span class="ld-qwho">{html.escape(body.path)}</span>'
            f'<a class="ld-qjump" href="#{html.escape(target)}"'
            f' data-ld-target="{html.escape(target)}">go to document ↦</a></span>'
        )
        if not label.strip():
            return (
                '<span class="ld-quote ld-quote-said ld-quote-open">'
                f'<span class="ld-quote-body">{head}{rows}</span></span>'
            )
        return (
            '<span class="ld-quote ld-quote-said">'
            f'<button type="button" class="ld-quote-btn" aria-expanded="false"'
            f' data-ld-target="{html.escape(target)}">{label}</button>'
            f'<span class="ld-quote-body" hidden>{head}{rows}</span></span>'
        )

    def toc_item(self, r, item: Item) -> str:
        return (
            f'<li class="ld-toc-file"><a href="#{html.escape(item.anchor_id)}"'
            f' data-ld-target="{html.escape(item.anchor_id)}">'
            f'<span class="ld-toc-name">{html.escape(item.title or item.payload.path)}</span>'
            f'<span class="ld-toc-path">{html.escape(item.payload.path)}</span></a></li>'
        )

    def outline(self, items: list[Item], info: SourceInfo) -> list[str]:
        return [f"  {it.key}:\n    note: |\n      \n" for it in items]

    def skill_fragment(self) -> str:
        return "doc.md"


PLUGIN = DocSource
