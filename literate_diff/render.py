"""Render an annotated document to a single self-contained HTML file."""

from __future__ import annotations

import html
import json
import re
from importlib import resources

from markdown_it import MarkdownIt

from .annotate import AnnotatedFile, Anchor, Document
from .message import inline_row, render_message
from .transcript import Turn, TurnBody, format_span, format_when

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


def _lead(lines, budget: int = 320) -> int:
    """The default highlight: enough rows to say what the message is about.

    Four rules, in order. Keep a heading with the paragraph under it, since a
    heading alone says nothing. Prefer to stop on a paragraph boundary rather
    than mid-thought, so the fold does not land between two sentences of one
    argument -- but give way at twice the budget, since a long paste with no
    blank line in it still has to fold somewhere. And do not fold a short tail:
    hiding two sentences behind a control costs the reader more than showing
    them.
    """
    if not lines:
        return 0
    spent = 0
    last = 0
    started = False
    for line in lines:
        if line.kind in ("blank", "fence", "tablesep"):
            if started and spent >= budget:
                break
            continue
        last = line.index
        if line.kind in ("heading", "rule") and not started:
            continue
        started = True
        spent += len(line.text)
        if spent >= budget * 2:
            break

    tail = [ln for ln in lines if ln.index > last and ln.kind not in ("blank", "fence")]
    if sum(len(ln.text) for ln in tail) < budget // 2:
        return len(lines) - 1
    return last


def _close(lines, first_shown: int, budget: int = 220) -> int:
    """Where the closing passage starts.

    A message's last paragraph is doing more work than its length suggests: it
    is what the next prompt answers. A reply ends on the recommendation or the
    question back; a long paste ends on the thing the person actually wanted
    asked. Folding it away leaves the turn after it unintelligible.
    """
    spent = 0
    start = len(lines) - 1
    for line in reversed(lines):
        if line.index <= first_shown:
            break
        if line.kind in ("blank", "fence", "tablesep"):
            if spent >= budget:
                break
            start = line.index
            continue
        start = line.index
        spent += len(line.text)
        if spent >= budget * 2:
            break
    while start < len(lines) and lines[start].kind in ("blank", "fence", "tablesep"):
        start += 1
    start = min(start, len(lines) - 1)

    # Do not open the closing passage half-way down a list or a table: back up
    # to the top of the block, and take the heading that introduces it.
    kind = lines[start].kind
    if kind in ("bullet", "table", "tablesep", "code", "fence"):
        family = {"table", "tablesep"} if kind in ("table", "tablesep") else {kind}
        if kind in ("code", "fence"):
            family = {"code", "fence"}
        while start > first_shown + 1 and lines[start - 1].kind in family:
            start -= 1
    back = start - 1
    while back > first_shown and lines[back].kind in ("blank", "fence"):
        back -= 1
    if back > first_shown and lines[back].kind == "heading":
        start = back
    return start


def _default_ranges(lines, budget: int) -> list[tuple[int, int]]:
    """The opening, and the close it will be answered on."""
    lead = _lead(lines, budget)
    end = len(lines) - 1
    if lead >= end:
        return [(0, end)]
    start = _close(lines, lead)
    if start <= lead + 1:
        return [(0, end)]
    return [(0, lead), (start, end)]


def _asset(name: str) -> str:
    return resources.files("literate_diff.assets").joinpath(name).read_text("utf-8")


class Renderer:
    def __init__(self, doc: Document):
        self.doc = doc
        self.sources = {
            d["name"]: d for d in (doc.meta.get("sources") or []) if d.get("name")
        }
        self.file_index = {id(af.diff): fi for fi, af in enumerate(doc.files)}
        # Every anchorable body -- a file's diff or one message -- gets a DOM id
        # prefix and a document position, so arrows and jumps work the same way
        # whether a reference lands in the diff or in the appendix.
        self.body_dom: dict[int, str] = {
            id(af.diff): f"f{fi}" for fi, af in enumerate(doc.files)
        }
        self.body_pos: dict[int, int] = {
            id(af.diff): fi for fi, af in enumerate(doc.files)
        }
        self.turns: list[Turn] = doc.turns
        after = len(doc.files)
        for ti, turn in enumerate(self.turns):
            turn.dom_index = ti  # type: ignore[attr-defined]
            self.body_dom[id(turn.prompt)] = f"t{ti}p"
            self.body_pos[id(turn.prompt)] = after + ti
            if turn.response is not None:
                self.body_dom[id(turn.response)] = f"t{ti}q"
                self.body_pos[id(turn.response)] = after + ti

        # Document position of every anchor, for computing back/forward arrows.
        self.pos: dict[str, tuple[int, int]] = {}
        for aid, anchor in doc.anchors.items():
            bi = self.body_pos.get(id(anchor.file))
            if bi is not None:
                self.pos[aid] = (bi, anchor.start)

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
        # Rows of files that render folded shut, handed to the client as data
        # rather than markup. See `file_table`.
        self.lazy: dict[str, dict] = {}
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
        # A reference with no label is a citation, not a phrase: the prose has
        # already said the thing, and this says where it came from. Render it
        # as a marker rather than an arrow adrift in the sentence.
        cite = " ld-cite" if not label.strip() else ""
        return (
            f'<a class="ld-ref ld-ref-{direction}{cite}" href="#{html.escape(target)}"'
            + (' title="in the conversation"' if cite else "")
            + f' data-ld-target="{html.escape(target)}">{arrow}{label}</a>'
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
        if isinstance(anchor.file, TurnBody):
            return self._quote_prose(anchor, target, label)
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

    def _row_data(self, fi: int, af: AnnotatedFile):
        """A file's diff as rows and section headers, for the client to build.

        A collapsed file is markup nobody has asked to see: 145 bytes of table
        scaffolding per line for about 47 bytes of code. Handing over the rows
        instead costs the text and little else, and nothing is lost that worked
        before -- a folded `<details>` is already invisible to find-in-page.
        """
        sections_at: dict[int, list] = {}
        for sec in af.sections:
            sections_at.setdefault(sec.anchor.start, []).append(sec)
        marked: dict[int, list[str]] = {}
        for note in af.notes:
            for i in range(note.anchor.start, note.anchor.end + 1):
                marked.setdefault(i, []).append(note.anchor_id)

        rows = []
        for line in af.diff.lines:
            rows.append(
                [
                    line.kind[0],  # c(ontext) a(dd) d(el) h(unk) m(essage)
                    line.old_no or 0,
                    line.new_no or 0,
                    line.text,
                    ",".join(marked.get(line.index, ())),
                ]
            )
        sections = {
            str(at): "".join(self.section_row(fi, af, sec) for sec in secs)
            for at, secs in sections_at.items()
        }
        return {"rows": rows, "sections": sections}

    def section_row(self, fi: int, af: AnnotatedFile, sec) -> str:
        owner = sec.title or af.diff.path.split("/")[-1]
        note = (
            f'<div class="ld-section-note">'
            f"{self.md(sec.note_md, (fi, sec.anchor.start), owner)}</div>"
            if sec.note_md.strip()
            else ""
        )
        title = (
            f'<h3 class="ld-section-title">{html.escape(sec.title)}</h3>' if sec.title else ""
        )
        return (
            f'<tr class="ld-sectionrow" id="{html.escape(sec.anchor_id)}">'
            f'<td colspan="3"><div class="ld-section">{title}{note}</div></td></tr>'
        )

    def file_table(self, fi: int, af: AnnotatedFile) -> str:
        # Folded shut: hand the client the rows and let it build the table the
        # first time someone opens the file.
        if af.collapsed:
            self.lazy[f"f{fi}"] = self._row_data(fi, af)
            return '<table class="ld-diff"><tbody></tbody></table>'

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
                parts.append(self.section_row(fi, af, s))

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
        lazy = f' data-ld-lazy="f{fi}"' if af.collapsed else ""
        return (
            f'<section class="ld-file" id="f{fi}" data-ld-path="{html.escape(d.path)}">'
            f"{note}"
            f'<details class="ld-fileblock"{open_attr}{lazy}>'
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

    def _quote_prose(self, anchor: Anchor, target: str, label: str) -> str:
        """Quote a message the way `ldq:` quotes a diff: the words themselves,
        with a link through to where they were said."""
        body = anchor.file
        rows = [
            f'<span class="ld-qrow ld-q{line.kind}">'
            f'<span class="ld-qtext">{inline_row(line) or "&nbsp;"}</span></span>'
            for line in body.lines[anchor.start : anchor.end + 1]
        ]
        who = "said" if body.kind == "prompt" else "replied"
        head = (
            f'<span class="ld-qhead"><span class="ld-qwho">'
            f"{html.escape(body.label)} — {who}</span>"
            f'<a class="ld-qjump" href="#{html.escape(target)}"'
            f' data-ld-target="{html.escape(target)}">go to context ↦</a></span>'
        )

        # A quote with no label is the sentence itself, not a reference to it:
        # show it, the way a pulled quote sits in a paragraph. With a label it
        # stays a control, for citing a passage the prose is not reciting.
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

    # --- appendix ------------------------------------------------------------

    def message(self, turn: Turn, body: TurnBody, ranges, side: str) -> str:
        """One message, rendered as the markdown it was written in, folded to
        its highlight."""
        dom = self.body_dom[id(body)]
        n = len(body.lines)
        if not ranges:
            # A reply is given a little more room than a prompt: the reader is
            # there to judge what came back.
            ranges = _default_ranges(body.lines, 320 if side == "prompt" else 460)
        shown = sum(b - a + 1 for a, b in ranges)
        hidden = n - shown
        more = (
            '<button type="button" class="ld-msg-more" aria-expanded="false">'
            f"show all ({n} lines)</button>"
            if hidden > 0
            else ""
        )
        who = "Prompt" if side == "prompt" else "Reply"
        return (
            f'<div class="ld-msg ld-msg-{side}" id="{html.escape(turn.anchor_id)}-{side}">'
            f'<div class="ld-who">{who}</div>'
            f'<div class="ld-msg-body">{render_message(body.lines, dom, ranges)}'
            f"{more}</div></div>"
        )

    def work_band(self, turn: Turn) -> str:
        """What happened in between, as counts. Not expandable: the outcome of
        the work is the diff above, and this is here to show its shape."""
        work = turn.work
        summary = work.summary()
        if not summary and not work.attachments:
            return ""
        bits = [f'<span class="ld-work-counts">{html.escape(summary)}</span>']
        if work.attachments:
            names = ", ".join(html.escape(a) for a in work.attachments[:4])
            extra = f" +{len(work.attachments) - 4}" if len(work.attachments) > 4 else ""
            bits.append(f'<span class="ld-work-att">attached {names}{extra}</span>')
        if work.images:
            bits.append(f'<span class="ld-work-att">{work.images} image(s)</span>')
        if work.events:
            bits.append(
                f'<span class="ld-work-att">{work.events} background '
                f'{"report" if work.events == 1 else "reports"}</span>'
            )
        if work.compacted:
            bits.append('<span class="ld-work-att">context compacted</span>')
        if work.interrupted:
            bits.append('<span class="ld-work-att">interrupted</span>')
        line = work.narration[0] if work.narration else ""
        if line:
            line = line.split("\n")[0]
            if len(line) > 120:
                line = line[:119].rstrip() + "…"
            bits.append(f'<span class="ld-work-said">{html.escape(line)}</span>')
        return f'<div class="ld-work">{"".join(bits)}</div>'

    def turn_block(self, turn: Turn, show_thread: bool) -> str:
        stamp = format_when(turn.at, turn.zone)
        note = (
            f'<div class="ld-turn-note">'
            f"{self.md(turn.note_md, self.pos.get(turn.anchor_id), turn.id)}</div>"
            if turn.note_md.strip()
            else ""
        )
        # With more than one thread interleaved, the reader has to be told when
        # a turn came from a session opened alongside the main one.
        badge = (
            f'<span class="ld-turn-thread">{html.escape(turn.thread_title)}</span>'
            if show_thread and turn.thread_title
            else ""
        )
        return (
            f'<article class="ld-turn" id="{html.escape(turn.anchor_id)}"'
            f' data-ld-thread="{html.escape(turn.thread)}">'
            f'<div class="ld-turn-head"><span class="ld-turn-time">{html.escape(stamp)}</span>'
            f'<a class="ld-turn-id" href="#{html.escape(turn.anchor_id)}"'
            f' data-ld-target="{html.escape(turn.anchor_id)}">{html.escape(turn.id)}</a>'
            f"{badge}</div>"
            f"{note}"
            f"{self.message(turn, turn.prompt, turn.prompt_ranges, 'prompt')}"
            f"{self.work_band(turn)}"
            + (
                self.message(turn, turn.response, turn.response_ranges, "reply")
                if turn.response is not None
                else ""
            )
            + "</article>"
        )

    def appendix(self) -> str:
        doc = self.doc
        if not doc.turns:
            return ""
        conf = doc.appendix if isinstance(doc.appendix, dict) else {}
        title = conf.get("title") or "Appendix: the conversation"
        here = (len(doc.files), -1)
        intro = (
            f'<div class="ld-appendix-note">{self.md(conf.get("note", ""), here)}</div>'
            if conf.get("note")
            else ""
        )

        stamps = [t.at for t in doc.turns if t.at]
        span = format_span(stamps[0], stamps[-1], doc.turns[0].zone) if stamps else ""
        sessions = sum(len(t.sessions) or 1 for t in doc.threads)
        meta = " · ".join(
            x
            for x in (
                f"{len(doc.turns)} turns",
                span,
                f"{len(doc.threads)} threads" if len(doc.threads) > 1 else "",
                f"{sessions} sessions",
            )
            if x
        )

        # Which sessions the stream is made of, and how much each contributed:
        # a reader judging the work needs to know it is looking at all of it.
        counts = "".join(
            f'<li class="ld-thread-row">'
            f'<div class="ld-thread-head"><span class="ld-thread-name">'
            f"{html.escape(thread.title)}</span>"
            f'<span class="ld-thread-count">{len(thread.turns)} turns · '
            f"{len(thread.sessions) or 1} sessions</span></div>"
            + (
                f'<div class="ld-thread-note">'
                f"{self.md(thread.note_md, here, thread.title)}</div>"
                if thread.note_md.strip()
                else ""
            )
            + "</li>"
            for thread in doc.threads
        )
        sources_list = f'<ul class="ld-threads">{counts}</ul>'
        notes = ""

        many = len(doc.threads) > 1
        starts = {c.start: c for c in doc.appendix_chapters}
        body = []
        previous = ""
        for i, turn in enumerate(doc.turns):
            chapter = starts.get(i)
            if chapter is not None:
                body.append(self.appendix_chapter(chapter))
            # Only where the stream crosses from one session to another: a
            # badge on all 243 would say nothing.
            body.append(self.turn_block(turn, many and turn.thread != previous))
            previous = turn.thread

        return (
            '<section class="ld-appendix" id="appendix">'
            f'<h2 class="ld-appendix-title">{html.escape(title)}</h2>'
            f'<div class="ld-appendix-meta">{html.escape(meta)}</div>'
            f"{sources_list}{intro}{notes}"
            f'<div class="ld-stream">{"".join(body)}</div>'
            "</section>"
        )

    def appendix_chapter(self, chapter) -> str:
        here = (len(self.doc.files) + chapter.start, -1)
        note = (
            f'<div class="ld-chapter-note">'
            f'{self.md(chapter.note_md, here, chapter.title or "chapter")}</div>'
            if chapter.note_md.strip()
            else ""
        )
        title = (
            f'<h3 class="ld-chapter-title">{html.escape(chapter.title)}</h3>'
            if chapter.title
            else ""
        )
        return (
            f'<section class="ld-chapter ld-achapter" id="ac-{html.escape(chapter.anchor_id)}">'
            f"{title}{note}</section>"
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
            return f'<ol class="ld-toc-list">{items}</ol>' + self.toc_appendix()

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
        return "".join(out) + self.toc_appendix()

    def toc_appendix(self) -> str:
        doc = self.doc
        if not doc.turns:
            return ""
        head = (
            '<div class="ld-toc-chapter"><a href="#appendix" data-ld-target="appendix">'
            "Appendix</a></div>"
        )
        if not doc.appendix_chapters:
            return head
        bounds = [c.start for c in doc.appendix_chapters] + [len(doc.turns)]
        items = "".join(
            f'<li class="ld-toc-file"><a href="#ac-{html.escape(c.anchor_id)}"'
            f' data-ld-target="ac-{html.escape(c.anchor_id)}">'
            f'<span class="ld-toc-name">{html.escape(c.title or "…")}</span>'
            f'<span class="ld-toc-path">{bounds[i + 1] - c.start} turns</span></a></li>'
            for i, c in enumerate(doc.appendix_chapters)
        )
        return head + f'<ol class="ld-toc-list">{items}</ol>'

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
        turns = len(doc.turns)
        if turns:
            meta_bits.append(
                f'<a href="#appendix" data-ld-target="appendix">{turns} turns</a>'
            )
        meta_bits.append(f'<span class="ld-stat-add">+{adds}</span>')
        meta_bits.append(f'<span class="ld-stat-del">−{dels}</span>')

        starts = {c.start: (ci, c) for ci, c in enumerate(doc.chapters)}
        body_parts = []
        for fi, af in enumerate(doc.files):
            if fi in starts:
                body_parts.append(self.chapter_header(*starts[fi]))
            body_parts.append(self.file_section(fi, af))
        body_parts.append(self.appendix())
        body = "".join(body_parts)
        # Chapters borrow the anchor of the turn they open at, which is right
        # for `ld:` arrows and wrong for jumping: the reader asked for the
        # chapter, so land on its heading rather than inside the first prompt.
        landmarks = {f"ac-{c.anchor_id}" for c in doc.appendix_chapters}
        anchor_map = {
            aid: {"body": self.body_dom[id(a.file)], "start": a.start, "end": a.end}
            for aid, a in doc.anchors.items()
            if id(a.file) in self.body_dom and aid not in landmarks
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
<script>window.LD_ANCHORS = {json.dumps(anchor_map)};
window.LD_ROWS = {json.dumps(self.lazy, separators=(",", ":"))};</script>
<script>{_asset("app.js")}</script>
</body></html>
"""


def render_document(doc: Document) -> str:
    return Renderer(doc).render()
