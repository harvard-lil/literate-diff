"""The notes source: primary sources a layer introduces itself.

A thing a colleague said in Slack, a pattern the author knows from elsewhere,
a page on the web. Each is a statement with who said it, when, where, and a
URL if there is one. A claim that cites a note is supported, with evidence
of kind *attestation* (someone's word) or *reference* (something a reader
can follow a link to). The tool never judges the evidence; it only says
whether there is any, and what kind.

```yaml
sources:
  said:
    type: notes
    items:
      - id: rebecca-slack
        by: Rebecca
        on: 2026-09-01
        where: "#h2o in Slack"
        text: dev and prod images that are closer together would help
      - id: cdn-pattern
        by: Jack
        text: hashed assets on a CDN, kept across deploys, is the common shape
        url: https://example.org/pattern
```
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..message import inline_row, render_message
from ..model import Anchor, Item, Layer, SourceInfo, Unit, slug
from ..transcript import split_rows
from .base import LoadContext, SourcePlugin


@dataclass(kw_only=True)
class NoteBody(Unit):
    by: str = ""
    on: str = ""
    where: str = ""
    url: str = ""
    text: str = ""

    @property
    def is_prose(self) -> bool:
        return True

    @property
    def evidence(self) -> str:
        return "reference" if self.url else "attestation"


class NotesSource(SourcePlugin):
    type = "notes"
    evidence = "attestation"
    natural_order = False

    def load(self, ctx: LoadContext) -> tuple[list[Item], SourceInfo]:
        conf = ctx.conf
        raw = conf.get("items")
        text = ""
        fname = ""
        if raw is None and conf.get("file"):
            full = ctx.base_dir / conf["file"]
            if not full.is_file():
                raise SystemExit(f"notes file not found: {full}")
            text = full.read_text(encoding="utf-8")
            fname = Path(conf["file"]).name
            raw = yaml.safe_load(text) or []
            if isinstance(raw, dict):
                raw = raw.get("items") or []
        if raw is None and conf.get("text") is not None:
            text = conf["text"]
            fname = conf.get("file") or "notes.yaml"
            raw = yaml.safe_load(text) or []
            if isinstance(raw, dict):
                raw = raw.get("items") or []
        if not isinstance(raw, list):
            raise SystemExit(f"sources.{ctx.name}: `items:` must be a list")
        items: list[Item] = []
        for i, entry in enumerate(raw):
            if not isinstance(entry, dict) or not entry.get("text"):
                ctx.warn(f"sources.{ctx.name}: item {i} needs `text:`")
                continue
            nid = slug(str(entry.get("id") or f"{ctx.name}-{i + 1}"))
            body = NoteBody(
                key=f"{ctx.name}:{nid}", path=nid, source=ctx.name, kind="note",
                label=str(entry.get("by") or ""),
                by=str(entry.get("by") or ""), on=str(entry.get("on") or ""),
                where=str(entry.get("where") or ""), url=str(entry.get("url") or ""),
                text=str(entry["text"]),
                lines=split_rows(str(entry["text"])),
            )
            items.append(Item(key=body.key, source=ctx.name, plugin=self.type,
                              payload=body, bodies=[body], title=nid))
        info = SourceInfo(name=ctx.name, type=self.type, label=conf.get("label") or ctx.name)
        if ctx.embed and text:
            info.embed[fname] = text
        info.counts = {"items": len(items)}
        return items, info

    def match(self, item: Item, pattern: str) -> bool:
        return pattern in (item.key, item.payload.path)

    def item_anchor_id(self, item: Item, n: int) -> str:
        # A note is cited by its own id: `ld:#rebecca-slack`.
        return item.payload.path

    def body_dom(self, item: Item, unit, n: int) -> str:
        return f"n{n}"

    def evidence_of(self, unit) -> str:
        return getattr(unit, "evidence", self.evidence)

    def _who(self, body: NoteBody, target: str = "") -> str:
        bits = []
        if body.by:
            bits.append(html.escape(body.by))
        if body.on:
            bits.append(html.escape(body.on))
        if body.where:
            bits.append(html.escape(body.where))
        who = ", ".join(bits)
        if body.url:
            who += (" · " if who else "") + f'<a href="{html.escape(body.url)}" rel="noopener">{html.escape(body.url)}</a>'
        kind = f'<span class="ld-note-kind">{body.evidence}</span>'
        return kind + who

    def render_item(self, r, layer: Layer, item: Item, show_source: bool) -> str:
        body: NoteBody = item.payload
        dom = r.body_dom[id(body)]
        note = (
            f'<div class="ld-doc-note">{r.md(item.note_md, r.here(item, 0), body.path)}</div>'
            if item.note_md.strip() else ""
        )
        ranges = [(0, len(body.lines) - 1)]
        return (
            f'<article class="ld-note-item" id="{html.escape(item.anchor_id)}">'
            f'<div class="ld-note-who">{self._who(body)}'
            f' <a class="ld-turn-id" href="#{html.escape(item.anchor_id)}"'
            f' data-ld-target="{html.escape(item.anchor_id)}">{html.escape(body.path)}</a></div>'
            f"{note}"
            f'<div class="ld-msg-body">{render_message(body.lines, dom, ranges)}</div>'
            "</article>"
        )

    def quote(self, r, anchor: Anchor, target: str, label: str) -> str:
        body: NoteBody = anchor.file
        rows = [
            f'<span class="ld-qrow ld-q{line.kind}">'
            f'<span class="ld-qtext">{inline_row(line) or "&nbsp;"}</span></span>'
            for line in body.lines[anchor.start : anchor.end + 1]
        ]
        head = (
            f'<span class="ld-qhead"><span class="ld-qwho">{self._who(body)}</span>'
            f'<a class="ld-qjump" href="#{html.escape(target)}"'
            f' data-ld-target="{html.escape(target)}">go to source ↦</a></span>'
        )
        if not label.strip():
            return (
                '<span class="ld-quote ld-quote-said ld-quote-open">'
                f'<span class="ld-quote-body">{head}{"".join(rows)}</span></span>'
            )
        return (
            '<span class="ld-quote ld-quote-said">'
            f'<button type="button" class="ld-quote-btn" aria-expanded="false"'
            f' data-ld-target="{html.escape(target)}">{label}</button>'
            f'<span class="ld-quote-body" hidden>{head}{"".join(rows)}</span></span>'
        )

    def toc_item(self, r, item: Item) -> str:
        return ""

    def metaline(self, r, layer: Layer) -> list[str]:
        return []

    def outline(self, items: list[Item], info: SourceInfo) -> list[str]:
        return []

    def skill_fragment(self) -> str:
        return "notes.md"


PLUGIN = NotesSource
