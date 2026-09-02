"""Render an annotated document to a single self-contained HTML file."""

from __future__ import annotations

import html
import json
import re
from importlib import resources

from markdown_it import MarkdownIt

from .annotate import AnnotatedFile, Anchor, Document

REF_RE = re.compile(r'<a href="(ld|ldq):#([^"]+)"([^>]*)>(.*?)</a>', re.S)

_md = MarkdownIt("commonmark", {"html": True, "linkify": False}).enable(
    ["table", "strikethrough"]
)


def _asset(name: str) -> str:
    return resources.files("literate_diff.assets").joinpath(name).read_text("utf-8")


class Renderer:
    def __init__(self, doc: Document):
        self.doc = doc
        self.file_index = {id(af.diff): fi for fi, af in enumerate(doc.files)}
        # Document position of every anchor, for computing back/forward arrows.
        self.pos: dict[str, tuple[int, int]] = {}
        for aid, anchor in doc.anchors.items():
            fi = self.file_index.get(id(anchor.file))
            if fi is not None:
                self.pos[aid] = (fi, anchor.start)

    # --- markdown with reference/quote links ---------------------------------

    def md(self, text: str, here: tuple[int, int] | None = None) -> str:
        if not text.strip():
            return ""
        out = _md.render(text)
        return REF_RE.sub(lambda m: self._ref(m, here), out)

    def _ref(self, m: re.Match, here: tuple[int, int] | None) -> str:
        scheme, target, _attrs, label = m.group(1), m.group(2), m.group(3), m.group(4)
        anchor = self.doc.anchors.get(target)
        if anchor is None:
            self.doc.warnings.append(f"reference to unknown id {target!r}")
            return f'<span class="ld-ref ld-ref-broken" title="unknown id">{label}</span>'

        if scheme == "ldq":
            return self._quote(anchor, target, label)

        arrow = ""
        there = self.pos.get(target)
        if here is not None and there is not None:
            if there < here:
                arrow = '<span class="ld-arrow" aria-hidden="true">↑</span>'
            elif there > here:
                arrow = '<span class="ld-arrow" aria-hidden="true">↓</span>'
        direction = "back" if arrow.endswith("↑</span>") else "forward" if arrow else "here"
        return (
            f'<a class="ld-ref ld-ref-{direction}" href="#{html.escape(target)}"'
            f' data-ld-target="{html.escape(target)}">{arrow}{label}</a>'
        )

    def _quote(self, anchor: Anchor, target: str, label: str) -> str:
        rows = []
        for line in anchor.file.lines[anchor.start : anchor.end + 1]:
            if line.kind == "hunk":
                continue
            sign = {"add": "+", "del": "-"}.get(line.kind, " ")
            no = line.new_no or line.old_no or ""
            rows.append(
                f'<span class="ld-qrow ld-{line.kind}">'
                f'<span class="ld-qno">{no}</span>'
                f'<span class="ld-qsign">{sign}</span>'
                f'<span class="ld-qtext">{html.escape(line.text) or "&nbsp;"}</span>'
                "</span>"
            )
        body = "".join(rows)
        path = html.escape(anchor.file.path)
        return (
            '<span class="ld-quote">'
            f'<button type="button" class="ld-quote-btn" aria-expanded="false"'
            f' data-ld-target="{html.escape(target)}">{label}</button>'
            f'<span class="ld-quote-body" hidden>'
            f'<span class="ld-qhead"><code>{path}</code>'
            f'<a class="ld-qjump" href="#{html.escape(target)}"'
            f' data-ld-target="{html.escape(target)}">go to context ↦</a></span>'
            f"{body}</span></span>"
        )

    # --- diff table ----------------------------------------------------------

    def file_table(self, fi: int, af: AnnotatedFile) -> str:
        sections_at: dict[int, list] = {}
        for s in af.sections:
            sections_at.setdefault(s.anchor.start, []).append(s)

        marked: dict[int, list[str]] = {}
        for note in af.notes:
            for i in range(note.anchor.start, note.anchor.end + 1):
                marked.setdefault(i, []).append(note.anchor_id)
        parts = ['<table class="ld-diff"><tbody>']
        for line in af.diff.lines:
            for s in sections_at.get(line.index, []):
                parts.append(
                    f'<tr class="ld-sectionrow" id="{html.escape(s.anchor_id)}">'
                    '<td colspan="3"><div class="ld-section">'
                    + (f'<h3 class="ld-section-title">{html.escape(s.title)}</h3>' if s.title else "")
                    + (
                        f'<div class="ld-section-note">{self.md(s.note_md, (fi, s.anchor.start))}</div>'
                        if s.note_md.strip()
                        else ""
                    )
                    + "</div></td></tr>"
                )

            rid = f"f{fi}-r{line.index}"
            if line.kind == "hunk":
                label = html.escape(line.text)
                parts.append(
                    f'<tr class="ld-row ld-hunk" id="{rid}"><td class="ld-no"></td>'
                    f'<td class="ld-no"></td><td class="ld-text">{label or "&nbsp;"}</td></tr>'
                )
                continue
            if line.kind == "message":
                parts.append(
                    f'<tr class="ld-row ld-message" id="{rid}"><td class="ld-no"></td>'
                    f'<td class="ld-no"></td><td class="ld-text">{html.escape(line.text)}</td></tr>'
                )
                continue

            cls = f"ld-row ld-{line.kind}"
            note_ids = marked.get(line.index)
            if note_ids:
                cls += " ld-marked"
            sign = {"add": "+", "del": "-"}.get(line.kind, " ")
            parts.append(
                f'<tr class="{cls}" id="{rid}"'
                + (f' data-ld-notes="{html.escape(",".join(note_ids))}"' if note_ids else "")
                + f'><td class="ld-no">{line.old_no or ""}</td>'
                f'<td class="ld-no">{line.new_no or ""}</td>'
                f'<td class="ld-text"><span class="ld-sign">{sign}</span>'
                f'{html.escape(line.text) or "&nbsp;"}</td></tr>'
            )
        parts.append("</tbody></table>")
        return "".join(parts)

    def file_notes(self, fi: int, af: AnnotatedFile) -> str:
        out = []
        for note in af.notes:
            row_id = f"f{fi}-r{note.anchor.start}"
            out.append(
                f'<aside class="ld-note" id="{html.escape(note.anchor_id)}"'
                f' data-ld-row="{row_id}">'
                f'{self.md(note.text_md, (fi, note.anchor.start))}</aside>'
            )
        return "".join(out)

    # --- page ----------------------------------------------------------------

    def file_section(self, fi: int, af: AnnotatedFile) -> str:
        d = af.diff
        badge = {
            "added": '<span class="ld-badge ld-badge-add">added</span>',
            "deleted": '<span class="ld-badge ld-badge-del">deleted</span>',
            "renamed": '<span class="ld-badge ld-badge-ren">renamed</span>',
        }.get(d.status, "")
        rename = ""
        if d.status == "renamed" and d.old_path and d.old_path != d.path:
            rename = f'<span class="ld-rename">from <code>{html.escape(d.old_path)}</code></span>'
        title = f'<span class="ld-filetitle">{html.escape(af.title)}</span>' if af.title else ""
        note = (
            f'<div class="ld-filenote">{self.md(af.note_md, (fi, 0))}</div>'
            if af.note_md.strip()
            else ""
        )
        stats = (
            f'<span class="ld-stat ld-stat-add">+{d.additions}</span>'
            f'<span class="ld-stat ld-stat-del">−{d.deletions}</span>'
        )
        open_attr = "" if af.collapsed else " open"
        return (
            f'<section class="ld-file" id="f{fi}" data-ld-path="{html.escape(d.path)}">'
            f"{note}"
            f'<details class="ld-fileblock"{open_attr}>'
            f'<summary class="ld-filehead">'
            f'<span class="ld-chev" aria-hidden="true">▸</span>'
            f'<code class="ld-path">{html.escape(d.path)}</code>'
            f"{badge}{rename}{title}"
            f'<span class="ld-spacer"></span>{stats}</summary>'
            f'<div class="ld-body"><div class="ld-diffwrap">{self.file_table(fi, af)}</div>'
            f'<div class="ld-gutter">{self.file_notes(fi, af)}</div></div>'
            f"</details></section>"
        )

    def toc(self) -> str:
        items = []
        for fi, af in enumerate(self.doc.files):
            subs = "".join(
                f'<li><a href="#{html.escape(s.anchor_id)}" data-ld-target="{html.escape(s.anchor_id)}">'
                f"{html.escape(s.title)}</a></li>"
                for s in af.sections
                if s.title
            )
            label = af.title or af.diff.path.split("/")[-1]
            items.append(
                f'<li class="ld-toc-file"><a href="#f{fi}" data-ld-target="f{fi}">'
                f'<span class="ld-toc-name">{html.escape(label)}</span>'
                f'<span class="ld-toc-path">{html.escape(af.diff.path)}</span></a>'
                + (f'<ul class="ld-toc-sub">{subs}</ul>' if subs else "")
                + "</li>"
            )
        return f'<ol class="ld-toc-list">{"".join(items)}</ol>'

    def render(self) -> str:
        doc = self.doc
        m = doc.meta
        adds = sum(f.diff.additions for f in doc.files)
        dels = sum(f.diff.deletions for f in doc.files)
        meta_bits = []
        if m.get("range"):
            meta_bits.append(f'<code class="ld-range">{html.escape(m["range"])}</code>')
        if m.get("repo"):
            meta_bits.append(html.escape(m["repo"]))
        meta_bits.append(f"{len(doc.files)} files")
        meta_bits.append(f'<span class="ld-stat-add">+{adds}</span>')
        meta_bits.append(f'<span class="ld-stat-del">−{dels}</span>')

        body = "".join(self.file_section(fi, af) for fi, af in enumerate(doc.files))
        anchor_map = {
            aid: {"file": self.file_index[id(a.file)], "start": a.start, "end": a.end}
            for aid, a in doc.anchors.items()
            if id(a.file) in self.file_index
        }
        return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(doc.title)}</title>
<style>{_asset("style.css")}</style>
</head><body>
<div class="ld-app">
<nav class="ld-toc" aria-label="Contents">
  <div class="ld-toc-head">Contents</div>
  {self.toc()}
</nav>
<main class="ld-main">
  <header class="ld-header">
    <h1>{html.escape(doc.title)}</h1>
    {f'<p class="ld-subtitle">{html.escape(doc.subtitle)}</p>' if doc.subtitle else ""}
    <div class="ld-metaline">{" · ".join(meta_bits)}</div>
    {f'<div class="ld-plot">{self.md(doc.plot_md, (-1, -1))}</div>' if doc.plot_md.strip() else ""}
  </header>
  {body}
  <footer class="ld-footer">Generated by literate-diff.</footer>
</main>
</div>
<script>window.LD_ANCHORS = {json.dumps(anchor_map)};</script>
<script>{_asset("app.js")}</script>
</body></html>
"""


def render_document(doc: Document) -> str:
    return Renderer(doc).render()
