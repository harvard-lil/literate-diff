"""Render a document to a single self-contained HTML file.

The renderer owns the page: header, layers, chapters, references and quotes,
categories, claims and their evidence, terms, the table of contents, the map,
the embedded data block. What an item looks like is the plugin's.
"""

from __future__ import annotations

import html
import json
import re
from importlib import resources

from markdown_it import MarkdownIt

from . import __version__
from .model import Anchor, Document, Item, Layer

REF_RE = re.compile(r'<a href="(ld|ldq|ldc):#([^"]+)"([^>]*)>(.*?)</a>', re.S)

# `{category: name}` on its own line, immediately before an ordered list, binds
# that list to a category. `{claims}` does the same for a list of claims with
# no category. Nested ordered lists inside such a list are not supported: the
# match stops at the first closing tag.
CAT_LIST_RE = re.compile(
    r"<p>\{category:\s*([\w.-]+)\}</p>\s*<ol(?: start=\"\d+\")?>(.*?)</ol>", re.S
)
CLAIM_LIST_RE = re.compile(r"<p>\{claims\}</p>\s*<(ol|ul)(?: start=\"\d+\")?>(.*?)</\1>", re.S)
CAT_ITEM_RE = re.compile(r"<li>(.*?)</li>", re.S)
CAT_ITEM_ID_RE = re.compile(r"^(\s*(?:<p>)?)\s*\{#([\w.-]+)\}\s*")
TAG_RE = re.compile(r"<[^>]+>")
TARGET_RE = re.compile(r'data-ld-target="([^"]+)"')

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

DATA_ID = "ld-data"


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


def json_for_html(data) -> str:
    """JSON that is safe inside a `<script>` data block: the tokenizer scans
    raw bytes for `</script` regardless of string context, so every `<` is
    written as `\\u003c`, which JSON parsers decode back transparently."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


class Renderer:
    def __init__(self, doc: Document, embed: bool = True):
        self.doc = doc
        self.embed = embed
        self.plugins = getattr(doc, "plugins", {})
        # DOM id prefix and document position of every anchorable body, so
        # arrows and jumps work the same way wherever a reference lands.
        self.body_dom: dict[int, str] = {}
        self.body_pos: dict[int, tuple] = {}
        self.item_pos: dict[int, tuple] = {}
        for layer in doc.layers:
            for ii, item in enumerate(layer.items):
                item.index = ii
                self.item_pos[id(item)] = (layer.index, ii)
                for body in item.bodies:
                    self.body_dom[id(body)] = body.dom_id
                    self.body_pos[id(body)] = (layer.index, ii)
        self.pos: dict[str, tuple] = {}
        for aid, anchor in doc.anchors.items():
            bp = self.body_pos.get(id(anchor.file))
            if bp is not None:
                self.pos[aid] = bp + (anchor.start,)

        self.cats: dict[str, dict] = {}
        for i, (name, conf) in enumerate(doc.categories.items()):
            color = conf.get("color") or PALETTE[i % len(PALETTE)]
            self.cats[name] = {**conf, "color": color, "ink": _ink_for(color)}
        # Filled while rendering. Items come from `{category:}` and `{claims}`
        # lists; flags from `ldc:` links. The document is rendered twice so that
        # flags can number themselves from items defined anywhere, and items can
        # list the flags that point at them.
        self.final = False
        self.lazy: dict[str, dict] = {}
        self.cat_items: dict[str, dict] = {}
        self.cat_counts: dict[str, int] = {}
        self.cat_flags: dict[str, list[dict]] = {}
        self.prev_items: dict[str, dict] = {}
        self.prev_flags: dict[str, list[dict]] = {}
        # What is being rendered, for claims and flags to know their evidence.
        self.current_layer: Layer | None = None
        self.current_evidence = ""
        self.claims: list[dict] = []
        self.terms_seen: set[str] = set()

    # --- positions -------------------------------------------------------

    def here(self, item: Item, row: int) -> tuple:
        return self.item_pos[id(item)] + (row,)

    def here_layer(self, layer: Layer) -> tuple:
        return (layer.index, -1, -1)

    def source_label(self, name: str) -> str:
        info = self.doc.sources.get(name)
        return (info.label or name) if info else name

    def warn(self, message: str) -> None:
        # Only the final pass reports, so a two-pass render does not say
        # everything twice.
        if self.final:
            self.doc.warnings.append(message)

    # --- markdown with references ----------------------------------------------

    def md(self, text: str, here: tuple | None = None, owner: str = "") -> str:
        """Render one annotation. `here` is the document position the text
        sits at, for reference arrows; `owner` a short label for where it
        lives, used when a category item lists the places that flag it."""
        if not text.strip():
            return ""
        out = _md.render(text)
        out = CAT_LIST_RE.sub(lambda m: self._cat_list(m, here, m.group(1), m.group(2)), out)
        out = CLAIM_LIST_RE.sub(lambda m: self._cat_list(m, here, "", m.group(2), m.group(1)), out)
        out = REF_RE.sub(lambda m: self._ref(m, here, owner), out)
        if self.doc.terms and self.current_layer is not None and self.current_layer.is_prose:
            out = self._link_terms(out)
        return out

    def _arrow(self, here, there) -> tuple[str, str]:
        arrow = ""
        if here is not None and there is not None:
            if there < here:
                arrow = '<span class="ld-arrow" aria-hidden="true">↑</span>'
            elif there > here:
                arrow = '<span class="ld-arrow" aria-hidden="true">↓</span>'
        direction = "back" if arrow.endswith("↑</span>") else "forward" if arrow else "here"
        return arrow, direction

    def _ref(self, m: re.Match, here, owner: str = "") -> str:
        scheme, target, _attrs, label = m.group(1), m.group(2), m.group(3), m.group(4)
        if scheme == "ldc":
            return self._flag(target, label, here, owner)

        # A plain link to a category item or claim: `ld:#cat-<item id>`.
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
        kind = self._evidence_of(target)
        return (
            f'<a class="ld-ref ld-ref-{direction}{cite}" href="#{html.escape(target)}"'
            + (f' title="in the {html.escape(kind or "document")}"' if cite else "")
            + f' data-ld-target="{html.escape(target)}">{arrow}{label}</a>'
        )

    def _quote(self, anchor: Anchor, target: str, label: str) -> str:
        plugin = self.plugins.get(anchor.file.source)
        if plugin is None:
            self.warn(f"quote of {target!r}: no plugin for source {anchor.file.source!r}")
            return label
        return plugin.quote(self, anchor, target, label)

    def _evidence_of(self, target: str) -> str:
        """What kind of evidence an id points at, by the plugin of its source."""
        anchor = self.doc.anchors.get(target)
        if anchor is None:
            return ""
        plugin = self.plugins.get(anchor.file.source)
        if plugin is None:
            return ""
        if hasattr(plugin, "evidence_of"):
            return plugin.evidence_of(anchor.file)
        return plugin.evidence

    # --- terms -------------------------------------------------------------------

    def _link_terms(self, out: str) -> str:
        """Link the first use of each term in this layer to its definition.
        Matches on word boundaries in text outside tags, code and links."""
        terms = self.doc.terms
        pending = {t for t in terms if terms[t]["id"] not in self.terms_seen}
        if not pending:
            return out
        pattern = re.compile(
            r"\b(" + "|".join(re.escape(t) for t in sorted(pending, key=len, reverse=True)) + r")\b",
            re.IGNORECASE,
        )
        lookup = {t.lower(): t for t in terms}
        parts = re.split(r"(<[^>]+>)", out)
        depth_skip = 0
        for i, part in enumerate(parts):
            if part.startswith("<"):
                tag = part[1:].split(None, 1)[0].rstrip(">/").lower()
                if tag in ("a", "code", "pre", "h1", "h2", "h3", "h4", "button"):
                    depth_skip += 1
                elif tag in ("/a", "/code", "/pre", "/h1", "/h2", "/h3", "/h4", "/button"):
                    depth_skip = max(0, depth_skip - 1)
                continue
            if depth_skip or not part.strip():
                continue

            def sub(m):
                word = m.group(1)
                term = terms[lookup[word.lower()]]
                if term["id"] in self.terms_seen:
                    return word
                self.terms_seen.add(term["id"])
                tip = html.escape(term["text"][:300])
                return (
                    f'<a class="ld-term" href="#{html.escape(term["id"])}"'
                    f' data-ld-target="{html.escape(term["id"])}" title="{tip}">{word}</a>'
                )

            parts[i] = pattern.sub(sub, part)
        return "".join(parts)

    # --- categories and claims -----------------------------------------------------

    def _cat_style(self, cat: str) -> str:
        conf = self.cats.get(cat) or {"color": PALETTE[-1], "ink": _ink_for(PALETTE[-1])}
        return f'--cat:{conf["color"]};--cat-ink:{conf["ink"]}'

    def _cat_label(self, cat: str) -> str:
        conf = self.cats.get(cat)
        return conf["label"] if conf else cat

    def _cat_list(self, m: re.Match, here, cat: str, inner: str, tag: str = "ol") -> str:
        """A category list, or a `{claims}` list: each item is a claim with an
        id, and lists what cites it and what it cites."""
        if cat and cat not in self.cats:
            self.warn(f"{{category: {cat}}} is not declared under `categories`")
        items = []
        counter = cat or "claim"
        layer = self.current_layer
        for im in CAT_ITEM_RE.finditer(inner):
            body = im.group(1)
            self.cat_counts[counter] = self.cat_counts.get(counter, 0) + 1
            n = self.cat_counts[counter]
            idm = CAT_ITEM_ID_RE.match(body)
            if idm:
                item_id = idm.group(2)
                body = idm.group(1) + body[idm.end() :]
            else:
                item_id = f"{counter}-{n}"
            if item_id in self.cat_items and self.final:
                self.doc.warnings.append(f"category item id {item_id!r} is used twice")
            plain = TAG_RE.sub("", body).strip()
            # The body's own references are rendered later by REF_RE; look at
            # the markdown-level links to know what the claim cites.
            cited = re.findall(r'href="(?:ld|ldq|ldc):#([^"]+)"', body)
            flags = self.prev_flags.get(item_id) or []
            kinds: list[str] = []
            for t in cited:
                # A claim that cites another claim (`ld:#cat-x`, `ldc:#x`)
                # rests on whatever that claim rests on.
                other = t[4:] if t.startswith("cat-") else t
                if other in self.prev_items:
                    found = self._item_kinds(other)
                else:
                    found = [self._evidence_of(t)]
                for k in found:
                    if k and k not in kinds:
                        kinds.append(k)
            for f in flags:
                if f.get("kind") and f["kind"] not in kinds:
                    kinds.append(f["kind"])
            self.cat_items[item_id] = {
                "cat": cat, "n": n, "plain": plain, "pos": here,
                "layer": layer.id if layer else "", "cites": cited,
            }
            supported = bool(cited or flags)
            if self.final:
                self.claims.append({
                    "id": item_id, "category": cat, "n": n, "text": plain,
                    "layer": layer.id if layer else "", "cites": cited,
                    "flagged_from": [f["owner"] for f in flags],
                    "evidence": kinds, "supported": supported,
                })
                if not supported and layer is not None and layer.claims == "required":
                    self.doc.warnings.append(
                        f"claim {item_id!r} in layer {layer.id!r} cites nothing and nothing flags it"
                    )

            badge = ""
            if cat:
                short = self.cats.get(cat, {}).get("short", "")
                badge = (
                    f'<span class="ld-cat-badge" style="{self._cat_style(cat)}"'
                    f' title="{html.escape(self._cat_label(cat))} {n}">{html.escape(short)}{n}</span>'
                )
            where = ""
            if self.final and flags:
                links = []
                for f in flags:
                    arrow, direction = self._arrow(here, f["pos"])
                    links.append(
                        f'<a class="ld-ref ld-ref-{direction}" href="#{f["id"]}"'
                        f' data-ld-target="{f["id"]}">{arrow}{html.escape(f["owner"] or "here")}</a>'
                    )
                where = f'<span class="ld-cat-where">{" ".join(links)}</span>'
            evidence = ""
            if self.final and layer is not None and (layer.claims or not cat):
                if kinds:
                    evidence = (
                        f'<span class="ld-evidence" title="what this claim rests on">'
                        f'{html.escape(" · ".join(kinds))}</span>'
                    )
                elif not supported:
                    evidence = (
                        '<span class="ld-evidence ld-unsupported"'
                        ' title="No evidence is cited for this claim">unsupported</span>'
                    )
            items.append(
                f'<li id="cat-{html.escape(item_id)}" data-ld-cat="{html.escape(cat)}"'
                + (f' data-ld-evidence="{html.escape(",".join(kinds))}"' if kinds else "")
                + f">{badge}{body}{where}{evidence}</li>"
            )
        if cat:
            return (
                f'<ol class="ld-cat-list" data-ld-cat="{html.escape(cat)}"'
                f' style="{self._cat_style(cat)}">{"".join(items)}</ol>'
            )
        return f'<{tag} class="ld-claims">{"".join(items)}</{tag}>'

    def _item_kinds(self, item_id: str) -> list[str]:
        """What a claim rests on, from the first pass: the sources it cites
        directly and the places that flag it. One level; a claim citing a
        claim citing a claim is not followed."""
        prev = self.prev_items.get(item_id) or {}
        kinds: list[str] = []
        for t in prev.get("cites") or []:
            if t.startswith("cat-") or t in self.prev_items:
                continue
            k = self._evidence_of(t)
            if k and k not in kinds:
                kinds.append(k)
        for f in self.prev_flags.get(item_id) or []:
            if f.get("kind") and f["kind"] not in kinds:
                kinds.append(f["kind"])
        return kinds

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
            # First pass: still record the flag so the item can link back.
            item = {"cat": "", "n": 0, "plain": "", "pos": None}
        # Numbered per item, so a flag elsewhere that fails to resolve cannot
        # shift the ids the first pass handed to the item's back-links.
        flag_id = f"flag-{item_id}-{len(self.cat_flags.get(item_id, [])) + 1}"
        self.cat_flags.setdefault(item_id, []).append(
            {"id": flag_id, "owner": owner, "pos": here, "kind": self.current_evidence}
        )
        cat = item["cat"]
        short = self.cats.get(cat, {}).get("short", "") if cat else ""
        tip = f'{self._cat_label(cat) if cat else "Claim"} {item["n"]}: {item["plain"]}'
        text = f'<span class="ld-cat-flag-label">{label}</span>' if label.strip() else ""
        return (
            f'<a class="ld-cat-flag" id="{flag_id}" href="#cat-{html.escape(item_id)}"'
            f' data-ld-target="cat-{html.escape(item_id)}" data-ld-cat="{html.escape(cat)}"'
            f' style="{self._cat_style(cat)}" title="{html.escape(tip[:300])}">'
            f'<span class="ld-cat-badge">{html.escape(short)}{item["n"]}</span>{text}</a>'
        )

    # --- layers --------------------------------------------------------------------

    def _layer_head(self, layer: Layer, tag: str = "h2") -> str:
        if layer.implicit:
            return ""
        title = f'<{tag} class="ld-layer-title">{html.escape(layer.title)}</{tag}>' if layer.title else ""
        sub = (
            f'<p class="ld-layer-subtitle">{html.escape(layer.subtitle or layer.goal)}</p>'
            if (layer.subtitle or layer.goal) else ""
        )
        stat = self._layer_stat(layer)
        meta = f'<div class="ld-layer-meta">{stat}</div>' if stat else ""
        return f'<header class="ld-layer-head">{title}{sub}{meta}</header>' if (title or sub) else ""

    def _layer_stat(self, layer: Layer) -> str:
        """How much is here: reading time for prose, counts for a stream."""
        if layer.is_prose:
            words = len(re.findall(r"\b\w[\w'-]*\b", re.sub(r"```.*?```", "", layer.text_md, flags=re.S)))
            if not words:
                return ""
            minutes = max(1, round(words / 200))
            return f"{minutes} min read"
        bits = []
        for name in layer.sources:
            info = self.doc.sources.get(name)
            if info is None:
                continue
            c = info.counts
            if info.type == "diff":
                bits.append(f'{c.get("files", 0)} files')
            elif info.type == "transcript":
                bits.append(f'{c.get("turns", 0)} turns')
            elif info.type == "terms":
                bits.append(f'{c.get("items", 0)} terms')
            elif c.get("items") is not None:
                bits.append(f'{c["items"]} items')
        return " · ".join(bits)

    def prose_layer(self, layer: Layer) -> str:
        self.current_layer = layer
        self.current_evidence = ""
        self.terms_seen = set()
        body = self.md(layer.text_md, self.here_layer(layer), layer.title or layer.id)
        if layer.implicit:
            return f'<div class="ld-plot" id="{html.escape(layer.id)}">{body}</div>' if body else ""
        return (
            f'<section class="ld-layer ld-layer-prose" id="{html.escape(layer.id)}">'
            f'{self._layer_head(layer)}<div class="ld-plot">{body}</div></section>'
        )

    def chapter_header(self, layer: Layer, chapter, landmark: str) -> str:
        if not chapter.title and not chapter.note_md.strip():
            return ""
        here = (layer.index, chapter.start, -1)
        note = (
            f'<div class="ld-chapter-note">{self.md(chapter.note_md, here, chapter.title or "chapter")}</div>'
            if chapter.note_md.strip() else ""
        )
        tag = "h3" if landmark == "ac-" else "h2"
        title = (
            f'<{tag} class="ld-chapter-title">{html.escape(chapter.title)}</{tag}>'
            if chapter.title else ""
        )
        cls = "ld-chapter ld-achapter" if landmark == "ac-" else "ld-chapter"
        return (
            f'<section class="{cls}" id="{landmark}{html.escape(chapter.anchor_id)}">'
            f"{title}{note}</section>"
        )

    def stream_layer(self, layer: Layer) -> str:
        self.current_layer = layer
        self.terms_seen = set()
        starts = {c.start: c for c in layer.chapters}
        plugins = [self.plugins[n] for n in layer.sources]
        landmark = plugins[0].chapter_landmark() if plugins else "ch-"
        # A badge marks where the stream crosses from one session to another;
        # a badge on every turn would say nothing.
        many = len({self.plugins[n].stream_key(it) if hasattr(self.plugins[n], "stream_key") else it.source
                    for n in layer.sources for it in layer.items}) > 1 if layer.items else False
        parts = []
        previous = None
        for ii, item in enumerate(layer.items):
            if ii in starts:
                parts.append(self.chapter_header(layer, starts[ii], landmark))
            plugin = self.plugins[item.source]
            key = plugin.stream_key(item) if hasattr(plugin, "stream_key") else item.source
            self.current_evidence = (
                plugin.evidence_of(item.unit) if hasattr(plugin, "evidence_of") else plugin.evidence
            )
            parts.append(plugin.render_item(self, layer, item, many and key != previous))
            previous = key
        self.current_evidence = ""
        body = "".join(parts)

        heads = "".join(p.render_head(self, layer) for p in plugins)
        note = (
            f'<div class="ld-appendix-note">{self.md(layer.note_md, self.here_layer(layer))}</div>'
            if layer.note_md.strip() else ""
        )
        if layer.implicit and layer.plugin == "transcript":
            # The v1 appendix: title, counts, sessions, note, stream.
            return (
                f'<section class="ld-appendix" id="{html.escape(layer.id)}">'
                f'<h2 class="ld-appendix-title">{html.escape(layer.title)}</h2>'
                f"{heads}{note}"
                f'<div class="ld-stream">{body}</div>'
                "</section>"
            )
        if layer.implicit:
            return body
        cls = "ld-layer ld-layer-stream" + (" ld-appendix" if layer.plugin == "transcript" else "")
        return (
            f'<section class="{cls}" id="{html.escape(layer.id)}">'
            f"{self._layer_head(layer)}{heads}{note}"
            f'<div class="ld-stream">{body}</div></section>'
        )

    # --- table of contents and map ----------------------------------------------

    def toc(self) -> str:
        out = []
        for layer in self.doc.layers:
            if layer.is_prose:
                if not layer.implicit and layer.title:
                    out.append(
                        f'<div class="ld-toc-chapter ld-toc-layer"><a href="#{html.escape(layer.id)}"'
                        f' data-ld-target="{html.escape(layer.id)}">{html.escape(layer.title)}</a></div>'
                    )
                continue
            plugins = [self.plugins[n] for n in layer.sources]
            if not plugins:
                continue
            landmark = plugins[0].chapter_landmark()
            listed = any(p.toc_item(self, it) for p in plugins for it in layer.items[:1])
            if not layer.implicit or layer.plugin == "transcript":
                out.append(
                    f'<div class="ld-toc-chapter ld-toc-layer"><a href="#{html.escape(layer.id)}"'
                    f' data-ld-target="{html.escape(layer.id)}">'
                    f'{html.escape(layer.title or ("Appendix" if layer.plugin == "transcript" else layer.id))}</a></div>'
                )
            if not listed:
                # Items are not listed one by one; the chapters carry it.
                if layer.chapters:
                    bounds = [c.start for c in layer.chapters] + [len(layer.items)]
                    items = "".join(
                        f'<li class="ld-toc-file"><a href="#{landmark}{html.escape(c.anchor_id)}"'
                        f' data-ld-target="{landmark}{html.escape(c.anchor_id)}">'
                        f'<span class="ld-toc-name">{html.escape(c.title or "…")}</span>'
                        f'<span class="ld-toc-path">{bounds[i + 1] - c.start} '
                        f'{"turns" if layer.plugin == "transcript" else "items"}</span></a></li>'
                        for i, c in enumerate(layer.chapters)
                    )
                    out.append(f'<ol class="ld-toc-list">{items}</ol>')
                continue
            starts = {c.start: c for c in layer.chapters}
            open_list = False
            for ii, item in enumerate(layer.items):
                chapter = starts.get(ii)
                if chapter is not None:
                    if open_list:
                        out.append("</ol>")
                    if chapter.title:
                        out.append(
                            f'<div class="ld-toc-chapter"><a href="#{landmark}{html.escape(chapter.anchor_id)}"'
                            f' data-ld-target="{landmark}{html.escape(chapter.anchor_id)}">'
                            f"{html.escape(chapter.title)}</a></div>"
                        )
                    out.append('<ol class="ld-toc-list">')
                    open_list = True
                elif not open_list:
                    out.append('<ol class="ld-toc-list">')
                    open_list = True
                out.append(self.plugins[item.source].toc_item(self, item))
            if open_list:
                out.append("</ol>")
        return "".join(out)

    def map(self, full: bool) -> str:
        """The shape of the debrief: three groups (summary, synthesis,
        evidence), rows within a group, boxes within a row. Full size it is
        the top-level contents; in the margin the same markup is a postage
        stamp with labels on hover and the box in view marked."""
        layers = [l for l in self.doc.layers if not l.implicit]
        if len(layers) < 2:
            return ""
        groups: dict[str, dict[int, list[Layer]]] = {}
        for layer in layers:
            groups.setdefault(layer.group, {}).setdefault(layer.row, []).append(layer)
        labels = {"summary": "Summary", "synthesis": "Synthesis", "evidence": "Evidence"}
        out = []
        for gname in ("summary", "synthesis", "evidence"):
            rows = groups.get(gname)
            if not rows:
                continue
            row_html = []
            for rn in sorted(rows):
                boxes = []
                for layer in rows[rn]:
                    meta = " · ".join(x for x in (
                        f"for {layer.audience}" if layer.audience else "", layer.budget) if x)
                    tip = html.escape(" — ".join(x for x in (layer.title or layer.id, layer.subtitle, meta) if x))
                    stat = self._layer_stat(layer)
                    boxes.append(
                        f'<a class="ld-map-box ld-map-{layer.kind}" href="#{html.escape(layer.id)}"'
                        f' data-ld-target="{html.escape(layer.id)}" data-ld-layer="{html.escape(layer.id)}"'
                        f' title="{tip}">'
                        f'<span class="ld-map-title">{html.escape(layer.title or layer.id)}</span>'
                        + (f'<span class="ld-map-sub">{html.escape(layer.subtitle)}</span>'
                           if full and layer.subtitle else "")
                        + (f'<span class="ld-map-stat">{html.escape(stat)}</span>' if full and stat else "")
                        + "</a>"
                    )
                row_html.append(f'<div class="ld-map-row ld-map-row-{rn}">{"".join(boxes)}</div>')
            out.append(
                f'<div class="ld-map-group ld-map-{gname}" data-ld-group="{html.escape(labels[gname])}">'
                f'{"".join(row_html)}</div>'
            )
        cls = "ld-map ld-map-full" if full else "ld-map ld-map-mini"
        return f'<nav class="{cls}" aria-label="Parts of this debrief">{"".join(out)}</nav>'

    # --- the page ------------------------------------------------------------------

    def render(self) -> str:
        # Two passes. Category flags need the numbering of items that may be
        # defined after them, and items list the flags that point at them; the
        # first pass collects both, the second emits them.
        self.final = False
        self._compose()
        self.prev_items, self.prev_flags = self.cat_items, self.cat_flags
        self.cat_items, self.cat_counts, self.cat_flags = {}, {}, {}
        self.lazy = {}
        self.claims = []
        self.final = True
        return self._compose()

    def _header_meta(self) -> tuple[str, str]:
        doc = self.doc
        described = [s for s in doc.sources.values() if s.name]
        sources_block = ""
        if described:
            rows = []
            for s in described:
                count = ""
                if s.type == "diff":
                    count = f'{s.counts.get("files", 0)} files'
                elif s.type == "transcript":
                    count = f'{s.counts.get("turns", 0)} turns'
                elif s.counts.get("items") is not None:
                    count = f'{s.counts["items"]} items'
                rows.append(
                    f'<div class="ld-source-row">'
                    f'<span class="ld-src">{html.escape(s.label or s.name)}</span>'
                    f'<code class="ld-range">{html.escape(s.range or "")}</code>'
                    f'<span class="ld-src-count">{count}</span></div>'
                )
            sources_block = f'<div class="ld-sources">{"".join(rows)}</div>'

        bits: list[str] = []
        diffs = [s for s in doc.sources.values() if s.type == "diff"]
        if not described:
            for s in doc.sources.values():
                if s.range:
                    bits.append(f'<code class="ld-range">{html.escape(s.range)}</code>')
                if s.label:
                    bits.append(html.escape(s.label))
        elif diffs:
            bits.append(f"{len(diffs)} repos" if len(diffs) > 1 else "1 repo")
        for layer in doc.layers:
            if layer.kind == "stream":
                for name in layer.sources:
                    bits += self.plugins[name].metaline(self, layer) if layer.plugin else []
                    break
        return " · ".join(bits), sources_block

    def data_block(self, presentation=None) -> str:
        """The sidecar and every source's copy of record, as JSON in a script
        data block, so the file can be queried without a browser and rebuilt
        without the repositories."""
        doc = self.doc
        data = {
            "format": "literate-diff",
            "version": 2,
            "tool": __version__,
            "title": doc.title,
            "layers": [
                {"id": l.id, "kind": l.kind, "group": l.group, "row": l.row, "title": l.title,
                 "subtitle": l.subtitle, "audience": l.audience, "budget": l.budget,
                 "goal": l.goal, "sources": l.sources}
                for l in doc.layers
            ],
            "sources": {
                name: {"type": s.type, "label": s.label, "range": s.range, "repo": s.repo,
                       "files": s.embed if self.embed else {}}
                for name, s in doc.sources.items()
            },
            "sidecar": doc.sidecar_text if self.embed else "",
            "brief": doc.brief,
            "claims": self.claims,
        }
        if presentation is not None and self.final:
            from .presentation import encode_presentation
            data["presentation"] = encode_presentation(data, presentation)
        return f'<script type="application/json" id="{DATA_ID}">{json_for_html(data)}</script>'

    def about(self) -> str:
        """For a person: what this file is and how to get the data out."""
        doc = self.doc
        srcs = "".join(
            f"<li><code>{html.escape(name or s.label)}</code> — {html.escape(s.type)}"
            + (f", <code>{html.escape(s.range)}</code>" if s.range else "")
            + "</li>"
            for name, s in doc.sources.items()
        )
        layers = "".join(
            f'<li><a href="#{html.escape(l.id)}" data-ld-target="{html.escape(l.id)}">'
            f"{html.escape(l.title or l.id)}</a>"
            + (f" — for {html.escape(l.audience)}" if l.audience else "")
            + (f", {html.escape(l.budget)}" if l.budget else "")
            + "</li>"
            for l in doc.layers
        )
        embedded = (
            "The sidecar and every source's copy of record are embedded in the "
            f"<code>#{DATA_ID}</code> data block, so this file can be queried "
            "without a browser and rebuilt without the repositories."
            if self.embed else
            "Sources are not embedded in this copy."
        )
        return (
            '<section class="ld-about" id="about">'
            "<h2>About this file</h2>"
            f"<p>A debrief, built with literate-diff: a summary for each reader, a synthesis "
            f"of the work, and the evidence it rests on, with every claim linked to what "
            f"supports it. {embedded}</p>"
            f'<ul class="ld-about-list">{layers}</ul>'
            f'<ul class="ld-about-list">{srcs}</ul>'
            "<pre class=\"ld-about-cmds\">"
            f"literate-diff extract page.html --about\n"
            f"literate-diff extract page.html --layer &lt;id&gt;\n"
            f"literate-diff extract page.html --claims\n"
            f"literate-diff extract page.html --to dir/   # then rebuild from dir/\n"
            f"pup 'script#{DATA_ID} text{{}}' &lt; page.html | jq .layers"
            "</pre>"
            "</section>"
        )

    def head_comment(self) -> str:
        """For an agent or a script, before anything else in the file."""
        doc = self.doc
        lines = [
            "<!--",
            f"Debrief: {doc.title}",
            "",
            "One HTML file, no external requests, built with literate-diff. Three parts:",
            "summary (what the author wants the reader to know), synthesis (why the",
            "author believes it, each claim citing evidence), evidence (what happened:",
            "the code diff, the conversation, statements and documents, embedded whole).",
            "Use it as a knowledge base: answer questions from the summary and synthesis",
            "layers, and check any claim against the evidence it cites.",
            "",
            "Layers, top to bottom (group / id / title):",
        ]
        for l in doc.layers:
            meta = " · ".join(x for x in (l.audience, l.budget) if x)
            lines.append(f"  {l.group:<9} #{l.id}  {l.title or l.kind}"
                         + (f" — {l.subtitle}" if l.subtitle else "") + (f"  ({meta})" if meta else ""))
        lines += ["", "Sources:"]
        for name, s in doc.sources.items():
            lines.append(f"  {name or s.label}: {s.type}" + (f" {s.range}" if s.range else ""))
        lines += [
            "",
            f'The data block <script type="application/json" id="{DATA_ID}"> holds the',
            "sidecar (YAML, the annotations), each source's copy of record (a .patch,",
            "a transcript YAML), the brief, and every claim with its evidence, as JSON",
            "with `<` escaped as \\u003c. Read it with:",
            "",
            f"  pup 'script#{DATA_ID} text{{}}' < page.html | jq '.claims[] | select(.supported|not)'",
            f"  htmlq -t '#{DATA_ID}' -f page.html | jq -r .sidecar",
            "  python3 -c 'import sys,json,re;h=open(sys.argv[1]).read();"
            f"print(json.loads(re.search(r\"id=\\\"{DATA_ID}\\\">({{.*?)</script>\",h,re.S).group(1))[\"sidecar\"])' page.html",
            "",
            "Or with the tool (uvx --from git+https://github.com/harvard-lil/literate-diff literate-diff):",
            "",
            "  literate-diff extract page.html --about      # this, as text",
            "  literate-diff extract page.html --layer <id> # one layer as markdown, quotes resolved",
            "  literate-diff extract page.html --claims     # every claim, its evidence, its kinds",
            "  literate-diff extract page.html --to dir/    # sidecar and sources; rebuild from dir/",
            "",
            "Ids: `ld:#id` links, `ldq:#id` quotes, `ldc:#id` flags a claim where it is",
            "delivered. Row ids in the page are <body>-r<n>; anchors map ids to rows",
            "in ld-data.presentation. The page is rendered from that data block.",
            "-->",
        ]
        return "\n".join(lines)

    def _compose(self) -> str:
        doc = self.doc
        metaline, sources_block = self._header_meta()
        # Chapters borrow the anchor of the item they open at, which is right
        # for `ld:` arrows and wrong for jumping: the reader asked for the
        # chapter, so land on its heading rather than inside the first prompt.
        landmarks = set()
        for layer in doc.layers:
            if layer.kind == "stream" and layer.sources:
                lm = self.plugins[layer.sources[0]].chapter_landmark()
                if lm != "ch-":
                    landmarks |= {f"{lm}{c.anchor_id}" for c in layer.chapters}

        header_plot = []
        body_parts = []
        for layer in doc.layers:
            if layer.is_prose:
                rendered = self.prose_layer(layer)
                (header_plot if layer.implicit else body_parts).append(rendered)
            else:
                body_parts.append(self.stream_layer(layer))
        body = "".join(body_parts)
        anchor_map = {
            aid: {"body": self.body_dom[id(a.file)], "start": a.start, "end": a.end}
            for aid, a in doc.anchors.items()
            if id(a.file) in self.body_dom and aid not in landmarks
        }
        markup = f"""<div class="ld-app">
<nav class="ld-toc" aria-label="Contents">
  {self.map(full=False)}
  <div class="ld-toc-head">Contents</div>
  {self.toc()}
  <div class="ld-toc-chapter ld-toc-about"><a href="#about" data-ld-target="about">About this file</a></div>
</nav>
<main class="ld-main">
  <header class="ld-header">
    <h1>{html.escape(doc.title)}</h1>
    {f'<p class="ld-subtitle">{html.escape(doc.subtitle)}</p>' if doc.subtitle else ""}
    <div class="ld-metaline">{metaline}</div>
    {sources_block}
    <p class="ld-readers">This debrief is designed to be read by people or by agents. An agent
    given the file will find instructions at the top for using it as a knowledge base to
    answer your questions.</p>
    {"".join(header_plot)}
  </header>
  {self.map(full=True)}
  {body}
  {self.about()}
  <footer class="ld-footer">A debrief, built with literate-diff {__version__}.</footer>
</main>
</div>"""
        presentation = {"html": markup, "anchors": anchor_map, "rows": self.lazy}
        return f"""<!doctype html>
{self.head_comment()}
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="literate-diff {__version__}">
<title>{html.escape(doc.title)}</title>
<style>{_asset("style.css")}</style>
</head><body>
<noscript>This debrief requires JavaScript to display. Its embedded sources remain
available with literate-diff extract.</noscript>
<div id="ld-root"></div>
{self.data_block(presentation)}
<script>{_asset("presentation.js")}</script>
<script>{_asset("app.js")}</script>
</body></html>
"""


def render_document(doc: Document, embed: bool = True) -> str:
    r = Renderer(doc, embed=embed)
    out = r.render()
    doc.claims = r.claims  # type: ignore[attr-defined]
    return out
