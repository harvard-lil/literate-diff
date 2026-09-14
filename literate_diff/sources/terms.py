"""The terms source: definitions, linked from the first use in each layer.

```yaml
sources:
  glossary:
    type: terms
    items:
      - term: digest
        aliases: [digests]
        text: The hash of an image's manifest; names exactly one set of bytes.
      - term: OIDC role
        text: An AWS role a GitHub Actions job may assume by presenting a signed token.
```

A term's first use in each prose layer becomes a link with the definition
on hover, so a layer stays readable where it sits without repeating the
glossary. Terms are matched on word boundaries outside code, links and
headings.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..message import inline_row, render_message
from ..model import Anchor, Item, Layer, SourceInfo, Unit, slug
from ..transcript import split_rows
from .base import LoadContext, SourcePlugin


@dataclass(kw_only=True)
class TermBody(Unit):
    term: str = ""
    aliases: list[str] = field(default_factory=list)
    text: str = ""

    @property
    def is_prose(self) -> bool:
        return True


class TermsSource(SourcePlugin):
    type = "terms"
    evidence = "definition"
    natural_order = False

    def load(self, ctx: LoadContext) -> tuple[list[Item], SourceInfo]:
        conf = ctx.conf
        raw = conf.get("items")
        text = ""
        fname = ""
        if raw is None and (conf.get("file") or conf.get("text") is not None):
            if conf.get("text") is not None:
                text = conf["text"]
                fname = conf.get("file") or "terms.yaml"
            else:
                full = ctx.base_dir / conf["file"]
                if not full.is_file():
                    raise SystemExit(f"terms file not found: {full}")
                text = full.read_text(encoding="utf-8")
                fname = Path(conf["file"]).name
            raw = yaml.safe_load(text) or []
            if isinstance(raw, dict) and "items" in raw:
                raw = raw["items"]
        if isinstance(raw, dict):
            raw = [{"term": k, "text": v} for k, v in raw.items()]
        if not isinstance(raw, list):
            raise SystemExit(f"sources.{ctx.name}: `items:` must be a list or a mapping")
        items: list[Item] = []
        for i, entry in enumerate(raw):
            if not isinstance(entry, dict) or not entry.get("term") or not entry.get("text"):
                ctx.warn(f"sources.{ctx.name}: item {i} needs `term:` and `text:`")
                continue
            term = str(entry["term"])
            aliases = [str(a) for a in (entry.get("aliases") or [])]
            body = TermBody(
                key=f"{ctx.name}:{term}", path=term, source=ctx.name, kind="term",
                label=term, term=term, aliases=aliases, text=str(entry["text"]),
                lines=split_rows(str(entry["text"])),
            )
            items.append(Item(key=body.key, source=ctx.name, plugin=self.type,
                              payload=body, bodies=[body], title=term))
        info = SourceInfo(name=ctx.name, type=self.type, label=conf.get("label") or ctx.name)
        if ctx.embed and text:
            info.embed[fname] = text
        info.counts = {"items": len(items)}
        return items, info

    def match(self, item: Item, pattern: str) -> bool:
        return pattern in (item.key, item.payload.term)

    def item_anchor_id(self, item: Item, n: int) -> str:
        return slug("term-" + item.payload.term)

    def body_dom(self, item: Item, unit, n: int) -> str:
        return f"g{n}"

    def render_item(self, r, layer: Layer, item: Item, show_source: bool) -> str:
        body: TermBody = item.payload
        dom = r.body_dom[id(body)]
        aliases = (
            f'<span class="ld-term-aliases">also {html.escape(", ".join(body.aliases))}</span>'
            if body.aliases else ""
        )
        ranges = [(0, len(body.lines) - 1)]
        return (
            f'<article class="ld-term-item" id="{html.escape(item.anchor_id)}">'
            f'<span class="ld-term-name">{html.escape(body.term)}</span>{aliases}'
            f'<div class="ld-msg-body">{render_message(body.lines, dom, ranges)}</div>'
            "</article>"
        )

    def quote(self, r, anchor: Anchor, target: str, label: str) -> str:
        body: TermBody = anchor.file
        rows = "".join(
            f'<span class="ld-qrow ld-q{line.kind}"><span class="ld-qtext">{inline_row(line)}</span></span>'
            for line in body.lines[anchor.start : anchor.end + 1]
        )
        head = (
            f'<span class="ld-qhead"><span class="ld-qwho">{html.escape(body.term)}</span>'
            f'<a class="ld-qjump" href="#{html.escape(target)}"'
            f' data-ld-target="{html.escape(target)}">go to definition ↦</a></span>'
        )
        return (
            '<span class="ld-quote ld-quote-said">'
            f'<button type="button" class="ld-quote-btn" aria-expanded="false"'
            f' data-ld-target="{html.escape(target)}">{label or html.escape(body.term)}</button>'
            f'<span class="ld-quote-body" hidden>{head}{rows}</span></span>'
        )

    def toc_item(self, r, item: Item) -> str:
        return ""

    def skill_fragment(self) -> str:
        return "terms.md"


PLUGIN = TermsSource
