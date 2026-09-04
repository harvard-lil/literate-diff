"""Render an annotated document to a single self-contained HTML file."""

from __future__ import annotations

import html
import json
import re
from importlib import resources

from markdown_it import MarkdownIt

from .annotate import AnnotatedFile, Anchor, Document

REF_RE = re.compile(r'<a href="(ld|ldq|ldc):#([^"]+)"([^>]*)>(.*?)</a>', re.S)

# `{category: name}` on its own line, immediately before an ordered list, binds
# that list to a category. Nested ordered lists inside such a list are not
# supported: the match stops at the first closing tag.
CAT_LIST_RE = re.compile(
    r"<p>\{category:\s*([\w.-]+)\}</p>\s*<ol(?: start=\"\d+\")?>(.*?)</ol>", re.S
)
CAT_ITEM_RE = re.compile(r"<li>(.*?)</li>", re.S)
CAT_ITEM_ID_RE = re.compile(r"^(\s*(?:<p>)?)\s*\{#([\w.-]+)\}\s*")
TAG_RE = re.compile(r"<[^>]+>")

# Paul Tol's "muted" qualitative scheme, which stays distinguishable under the
# common forms of colour-vision deficiency. Assigned to categories in the order
# they are declared; an explicit `color:` overrides.
PALETTE = [
    "#332288",  # indigo
    "#CC6677",  # rose
    "#117733",  # green
    "#DDCC77",  # sand
    "#88CCEE",  # cyan
    "#AA4499",  # purple
    "#44AA99",  # teal
    "#882255",  # wine
    "#999933",  # olive
    "#BBBBBB",  # grey
]


def _ink_for(color: str) -> str:
    """Black or white text, whichever reads against `color`."""
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        r, g, b = (int(c[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "#ffffff"
    return "#1c1c1a" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#ffffff"

_md = MarkdownIt("commonmark", {"html": True, "linkify": False}).enable(
    ["table", "strikethrough"]
)


def _asset(name: str) -> str:
    return resources.files("literate_diff.assets").joinpath(name).read_text("utf-8")


class Renderer:
    def __init__(self, doc: Document):
        self.doc = doc
        self.sources = {
            d["name"]: d for d in (doc.meta.get("sources") or []) if d.get("name")
        }
        self.file_index = {id(af.diff): fi for fi, af in enumerate(doc.files)}
        # Document position of every anchor, for computing back/forward arrows.
        self.pos: dict[str, tuple[int, int]] = {}
        for aid, anchor in doc.anchors.items():
            fi = self.file_index.get(id(anchor.file))
            if fi is not None:
                self.pos[aid] = (fi, anchor.start)

        # Categories: colour by declaration order unless one was given.
        self.cats: dict[str, dict] = {}
        for i, (name, conf) in enumerate(doc.categories.items()):
            color = conf.get("color") or PALETTE[i % len(PALETTE)]
            self.cats[name] = {**conf, "color": color, "ink": _ink_for(color)}
        # Filled while rendering. Items come from `{category:}` lists; flags
        # from `ldc:` links. The document is rendered twice so that flags can
        # number themselves from items defined anywhere, and items can list the
        # flags that point at them.
        self.final = False
        self.cat_items: dict[str, dict] = {}
        self.cat_counts: dict[str, int] = {}
        self.cat_flags: dict[str, list[dict]] = {}
        self.prev_items: dict[str, dict] = {}
        self.prev_flags: dict[str, list[dict]] = {}

    def source_label(self, name: str) -> str:
        d = self.sources.get(name)
        return (d.get("label") or name) if d else name

    # --- markdown with reference/quote links ---------------------------------

    def md(self, text: str, here: tuple[int, int] | None = None, owner: str = "") -> str:
        """Render one annotation.

        `here` is the document position (file index, row) the text sits at, for
        computing reference arrows. `owner` is a short label for where the text
        lives -- a file name or section title -- used when a category item lists
        the places that flag it.
        """
        if not text.strip():
            return ""
        out = _md.render(text)
        out = CAT_LIST_RE.sub(lambda m: self._cat_list(m, here), out)
        return REF_RE.sub(lambda m: self._ref(m, here, owner), out)

    def warn(self, message: str) -> None:
        # Only the final pass reports, so a two-pass render does not say
        # everything twice.
        if self.final:
            self.doc.warnings.append(message)

    def _arrow(self, here, there) -> tuple[str, str]:
        arrow = ""
        if here is not None and there is not None:
            if there < here:
                arrow = '<span class="ld-arrow" aria-hidden="true">↑</span>'
            elif there > here:
                arrow = '<span class="ld-arrow" aria-hidden="true">↓</span>'
        direction = "back" if arrow.endswith("↑</span>") else "forward" if arrow else "here"
        return arrow, direction

    def _ref(self, m: re.Match, here: tuple[int, int] | None, owner: str = "") -> str:
        scheme, target, _attrs, label = m.group(1), m.group(2), m.group(3), m.group(4)
        if scheme == "ldc":
            return self._flag(target, label, here, owner)

        # A plain link to a category item: `ld:#cat-<item id>`.
        if scheme == "ld" and target.startswith("cat-"):
            item = self.cat_items.get(target[4:]) or self.prev_items.get(target[4:])
            if item is not None:
                arrow, direction = self._arrow(here, item["pos"])
                return (
                    f'<a class="ld-ref ld-ref-{direction}" href="#{html.escape(target)}"'
                    f' data-ld-target="{html.escape(target)}">{arrow}{label}</a>'
                )

        anchor = self.doc.anchors.get(target)
        if anchor is None:
            self.warn(f"reference to unknown id {target!r}")
            return f'<span class="ld-ref ld-ref-broken" title="unknown id">{label}</span>'

        if scheme == "ldq":
            return self._quote(anchor, target, label)

        arrow, direction = self._arrow(here, self.pos.get(target))
        return (
            f'<a class="ld-ref ld-ref-{direction}" href="#{html.escape(target)}"'
            f' data-ld-target="{html.escape(target)}">{arrow}{label}</a>'
        )

    # --- categories ----------------------------------------------------------

    def _cat_style(self, cat: str) -> str:
        conf = self.cats.get(cat) or {"color": PALETTE[-1], "ink": _ink_for(PALETTE[-1])}
        return f'--cat:{conf["color"]};--cat-ink:{conf["ink"]}'

    def _cat_label(self, cat: str) -> str:
        conf = self.cats.get(cat)
        return conf["label"] if conf else cat

    def _cat_list(self, m: re.Match, here) -> str:
        cat = m.group(1)
        if cat not in self.cats:
            self.warn(f"{{category: {cat}}} is not declared under `categories`")
        items = []
        for im in CAT_ITEM_RE.finditer(m.group(2)):
            body = im.group(1)
            self.cat_counts[cat] = self.cat_counts.get(cat, 0) + 1
            n = self.cat_counts[cat]
            idm = CAT_ITEM_ID_RE.match(body)
            if idm:
                item_id = idm.group(2)
                body = idm.group(1) + body[idm.end() :]
            else:
                item_id = f"{cat}-{n}"
            if item_id in self.cat_items and self.final:
                self.doc.warnings.append(f"category item id {item_id!r} is used twice")
            plain = TAG_RE.sub("", body).strip()
            self.cat_items[item_id] = {"cat": cat, "n": n, "plain": plain, "pos": here}
            short = self.cats.get(cat, {}).get("short", "")
            badge = (
                f'<span class="ld-cat-badge" style="{self._cat_style(cat)}"'
                f' title="{html.escape(self._cat_label(cat))} {n}">{html.escape(short)}{n}</span>'
            )
            where = ""
            flags = self.prev_flags.get(item_id) or []
            if self.final and flags:
                links = []
                for f in flags:
                    arrow, direction = self._arrow(here, f["pos"])
                    links.append(
                        f'<a class="ld-ref ld-ref-{direction}" href="#{f["id"]}"'
                        f' data-ld-target="{f["id"]}">{arrow}{html.escape(f["owner"] or "here")}</a>'
                    )
                where = f'<span class="ld-cat-where">{" ".join(links)}</span>'
            items.append(
                f'<li id="cat-{html.escape(item_id)}" data-ld-cat="{html.escape(cat)}">'
                f"{badge}{body}{where}</li>"
            )
        return (
            f'<ol class="ld-cat-list" data-ld-cat="{html.escape(cat)}"'
            f' style="{self._cat_style(cat)}">{"".join(items)}</ol>'
        )

    def _flag(self, item_id: str, label: str, here, owner: str) -> str:
        # Items defined later in the document than this flag are known only
        # from the first pass.
        item = self.cat_items.get(item_id) or self.prev_items.get(item_id)
        if item is None:
            if self.final:
                self.warn(f"flag ldc:#{item_id} names no category item")
                return (
                    f'<span class="ld-ref ld-ref-broken" title="unknown category item">'
                    f"{label or item_id}</span>"
                )
            # First pass: items defined later in the document are not known yet.
            # Still record the flag so the item can link back to it.
            item = {"cat": "", "n": 0, "plain": "", "pos": None}
        # Numbered per item, so a flag elsewhere that fails to resolve cannot
        # shift the ids the first pass handed to the item's back-links.
        flag_id = f"flag-{item_id}-{len(self.cat_flags.get(item_id, [])) + 1}"
        self.cat_flags.setdefault(item_id, []).append({"id": flag_id, "owner": owner, "pos": here})
        cat = item["cat"]
        short = self.cats.get(cat, {}).get("short", "")
        tip = f'{self._cat_label(cat)} {item["n"]}: {item["plain"]}'
        text = f'<span class="ld-cat-flag-label">{label}</span>' if label.strip() else ""
        return (
            f'<a class="ld-cat-flag" id="{flag_id}" href="#cat-{html.escape(item_id)}"'
            f' data-ld-target="cat-{html.escape(item_id)}" data-ld-cat="{html.escape(cat)}"'
            f' style="{self._cat_style(cat)}" title="{html.escape(tip[:300])}">'
            f'<span class="ld-cat-badge">{html.escape(short)}{item["n"]}</span>{text}</a>'
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
        if anchor.file.source:
            path = (
                f'<span class="ld-src">{html.escape(self.source_label(anchor.file.source))}'
                f"</span> {path}"
            )
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
                        f'<div class="ld-section-note">{self.md(s.note_md, (fi, s.anchor.start), s.title or af.diff.path.split("/")[-1])}</div>'
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
                f'{self.md(note.text_md, (fi, note.anchor.start), af.diff.path.split("/")[-1])}</aside>'
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
        src = (
            f'<span class="ld-src" data-ld-src="{html.escape(d.source)}">'
            f"{html.escape(self.source_label(d.source))}</span>"
            if d.source
            else ""
        )
        note = (
            f'<div class="ld-filenote">{self.md(af.note_md, (fi, 0), af.diff.path.split("/")[-1])}</div>'
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
            f"{src}"
            f'<code class="ld-path">{html.escape(d.path)}</code>'
            f"{badge}{rename}{title}"
            f'<span class="ld-spacer"></span>{stats}</summary>'
            f'<div class="ld-body"><div class="ld-diffwrap">{self.file_table(fi, af)}</div>'
            f'<div class="ld-gutter">{self.file_notes(fi, af)}</div></div>'
            f"</details></section>"
        )

    def chapter_header(self, ci: int, chapter) -> str:
        if not chapter.title and not chapter.note_md.strip():
            return ""
        note = (
            f'<div class="ld-chapter-note">{self.md(chapter.note_md, (chapter.start, -1), chapter.title or "chapter")}</div>'
            if chapter.note_md.strip()
            else ""
        )
        title = (
            f'<h2 class="ld-chapter-title">{html.escape(chapter.title)}</h2>'
            if chapter.title
            else ""
        )
        return (
            f'<section class="ld-chapter" id="ch-{html.escape(chapter.anchor_id)}">'
            f"{title}{note}</section>"
        )

    def toc_file_item(self, fi: int, af: AnnotatedFile) -> str:
        subs = "".join(
            f'<li><a href="#{html.escape(s.anchor_id)}" data-ld-target="{html.escape(s.anchor_id)}">'
            f"{html.escape(s.title)}</a></li>"
            for s in af.sections
            if s.title
        )
        label = af.title or af.diff.path.split("/")[-1]
        src = (
            f'<span class="ld-toc-src">{html.escape(self.source_label(af.diff.source))}</span>'
            if af.diff.source
            else ""
        )
        return (
            f'<li class="ld-toc-file"><a href="#f{fi}" data-ld-target="f{fi}">'
            f'<span class="ld-toc-name">{html.escape(label)}</span>'
            f'<span class="ld-toc-path">{src}{html.escape(af.diff.path)}</span></a>'
            + (f'<ul class="ld-toc-sub">{subs}</ul>' if subs else "")
            + "</li>"
        )

    def toc(self) -> str:
        starts = {c.start: c for c in self.doc.chapters}
        if not starts:
            items = "".join(
                self.toc_file_item(fi, af) for fi, af in enumerate(self.doc.files)
            )
            return f'<ol class="ld-toc-list">{items}</ol>'

        out = []
        open_list = False
        for fi, af in enumerate(self.doc.files):
            chapter = starts.get(fi)
            if chapter is not None:
                if open_list:
                    out.append("</ol>")
                if chapter.title:
                    out.append(
                        f'<div class="ld-toc-chapter"><a href="#ch-{html.escape(chapter.anchor_id)}"'
                        f' data-ld-target="ch-{html.escape(chapter.anchor_id)}">'
                        f"{html.escape(chapter.title)}</a></div>"
                    )
                out.append('<ol class="ld-toc-list">')
                open_list = True
            elif not open_list:
                out.append('<ol class="ld-toc-list">')
                open_list = True
            out.append(self.toc_file_item(fi, af))
        if open_list:
            out.append("</ol>")
        return "".join(out)

    def render(self) -> str:
        # Two passes. Category flags need the numbering of items that may be
        # defined after them, and items list the flags that point at them; the
        # first pass collects both, the second emits them.
        self.final = False
        self._compose()
        self.prev_items, self.prev_flags = self.cat_items, self.cat_flags
        self.cat_items, self.cat_counts, self.cat_flags = {}, {}, {}
        self.final = True
        return self._compose()

    def _compose(self) -> str:
        doc = self.doc
        m = doc.meta
        adds = sum(f.diff.additions for f in doc.files)
        dels = sum(f.diff.deletions for f in doc.files)
        described = [d for d in (m.get("sources") or []) if d.get("name")]
        if described:
            rows = "".join(
                f'<div class="ld-source-row">'
                f'<span class="ld-src">{html.escape(d.get("label") or d["name"])}</span>'
                f'<code class="ld-range">{html.escape(d.get("range", ""))}</code>'
                f'<span class="ld-src-count">'
                f'{sum(1 for f in doc.files if f.diff.source == d["name"])} files</span>'
                "</div>"
                for d in described
            )
            sources_block = f'<div class="ld-sources">{rows}</div>'
        else:
            sources_block = ""

        meta_bits = []
        if not described:
            if m.get("range"):
                meta_bits.append(f'<code class="ld-range">{html.escape(m["range"])}</code>')
            if m.get("repo"):
                meta_bits.append(html.escape(m["repo"]))
        else:
            meta_bits.append(f"{len(described)} repos")
        meta_bits.append(f"{len(doc.files)} files")
        meta_bits.append(f'<span class="ld-stat-add">+{adds}</span>')
        meta_bits.append(f'<span class="ld-stat-del">−{dels}</span>')

        starts = {c.start: (ci, c) for ci, c in enumerate(doc.chapters)}
        body_parts = []
        for fi, af in enumerate(doc.files):
            if fi in starts:
                body_parts.append(self.chapter_header(*starts[fi]))
            body_parts.append(self.file_section(fi, af))
        body = "".join(body_parts)
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
    {sources_block}
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
