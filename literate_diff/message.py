"""Render one message: markdown, with every row still addressable.

A message is rows, because that is what anchors resolve against. It is also
markdown, because that is how it was written and how it reads. So the renderer
rebuilds the block structure -- headings, lists, tables, code, quotes -- around
rows that keep their own ids, and renders each row's text as inline markdown.

Rows outside the highlight are marked `ld-elided` rather than dropped, so the
whole message is in the page and a reference into a folded row can open it.
"""

from __future__ import annotations

import html

from markdown_it import MarkdownIt

from .transcript import Row

_md = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("strikethrough")

# Kinds that are their own block rather than part of a paragraph.
_SOLO = {"heading", "rule", "fence", "code", "table", "tablesep", "blank"}


def _inline(text: str) -> str:
    """Inline markdown only: a row is part of a block, never a block itself."""
    return _md.renderInline(text)


def inline_row(row: Row) -> str:
    """One row's text for a context where it stands alone -- a quote block."""
    if row.kind in ("code", "fence"):
        return html.escape(row.text)
    if row.kind == "bullet" and row.marker:
        return f"{html.escape(row.marker)} {_inline(row.text)}"
    return _inline(row.text)


def _shown(index: int, ranges: list[tuple[int, int]]) -> bool:
    return any(a <= index <= b for a, b in ranges)


def _row_span(row: Row, dom: str, shown: bool, tag: str = "span") -> str:
    cls = f"ld-prow ld-p{row.kind}" + ("" if shown else " ld-elided")
    # A real trailing space, not CSS generated content: the clipboard does not
    # copy `::after`, and these get pasted into tickets and mail.
    body = _inline(row.text) + (" " if row.kind in ("prose", "bullet", "quote") else "")
    return f'<{tag} class="{cls}" id="{dom}-r{row.index}">{body or "&nbsp;"}</{tag}>'


def _runs(rows: list[Row]) -> list[tuple[str, list[Row]]]:
    """Group rows into the blocks they came from."""
    out: list[tuple[str, list[Row]]] = []
    for row in rows:
        kind = row.kind
        group = {"code": "code", "fence": "code", "table": "table", "tablesep": "table"}.get(
            kind, kind if kind in _SOLO else ("bullet" if kind == "bullet" else "prose")
        )
        if kind == "quote":
            group = "quote"
        if out and out[-1][0] == group and group not in ("heading", "rule"):
            out[-1][1].append(row)
        else:
            out.append((group, [row]))
    return out


def render_message(rows: list[Row], dom: str, ranges: list[tuple[int, int]]) -> str:
    """The message as HTML. `ranges` are the highlighted row spans; everything
    else is present but folded."""
    parts: list[str] = []
    gap_open = False

    for group, run in _runs(rows):
        visible = [r for r in run if _shown(r.index, ranges)]
        if group == "blank":
            # A paragraph break separates two blocks that are already separate
            # elements, so it needs no element of its own. Emitting one cost a
            # sixth of the appendix in spans that rendered nothing. Row indices
            # come from the message, not the DOM, so the numbering is unmoved
            # and an anchor covering a blank simply finds nothing there.
            continue

        if not visible:
            if not gap_open:
                parts.append('<div class="ld-gap ld-gap-block" aria-hidden="true">…</div>')
                gap_open = True
        else:
            gap_open = False

        block_cls = "" if visible else " ld-elided"
        parts.append(_block(group, run, dom, ranges, block_cls))

    return "".join(parts)


def _block(group: str, run: list[Row], dom: str, ranges, block_cls: str) -> str:
    if group == "heading":
        row = run[0]
        level = min(max(row.level + 2, 3), 6)
        return (
            f'<h{level} class="ld-pheadingline{block_cls}">'
            f"{_row_span(row, dom, _shown(row.index, ranges))}</h{level}>"
        )

    if group == "rule":
        row = run[0]
        return (
            f'<div class="ld-prule{block_cls}">'
            f'<span class="ld-prow ld-prule-row" id="{dom}-r{row.index}"></span></div>'
        )

    if group == "code":
        lines = "\n".join(
            f'<span class="ld-prow ld-pcode'
            f'{"" if _shown(r.index, ranges) else " ld-elided"}" id="{dom}-r{r.index}">'
            f'{html.escape(r.text) or "&nbsp;"}</span>'
            for r in run
            if r.kind != "fence"
        )
        return f'<pre class="ld-pcodeblock{block_cls}"><code>{lines}</code></pre>'

    if group == "table":
        return _table(run, dom, ranges, block_cls)

    if group == "quote":
        inner = _list_or_para(run, dom, ranges, "p", "ld-pquoteline")
        return f'<blockquote class="ld-pquote{block_cls}">{inner}</blockquote>'

    if group == "bullet":
        return _list(run, dom, ranges, block_cls)

    return _list_or_para(run, dom, ranges, "p", "ld-ppara", block_cls)


def _list_or_para(run, dom, ranges, tag, cls, block_cls="") -> str:
    body = _with_gaps(run, dom, ranges)
    return f'<{tag} class="{cls}{block_cls}">{body}</{tag}>'


def _with_gaps(run, dom, ranges) -> str:
    """Rows of one block, with a marker where a run of them is folded."""
    out = []
    gap = False
    for row in run:
        shown = _shown(row.index, ranges)
        if not shown and not gap:
            out.append('<span class="ld-gap" aria-hidden="true">… </span>')
            gap = True
        elif shown:
            gap = False
        out.append(_row_span(row, dom, shown))
    return "".join(out)


def _list(run: list[Row], dom: str, ranges, block_cls: str) -> str:
    ordered = bool(run and run[0].marker and run[0].marker[:1].isdigit())
    tag = "ol" if ordered else "ul"
    items: list[list[Row]] = []
    for row in run:
        if row.marker or not items:
            items.append([row])
        else:
            items[-1].append(row)
    body = []
    for item in items:
        visible = any(_shown(r.index, ranges) for r in item)
        body.append(
            f'<li class="ld-pitem{"" if visible else " ld-elided"}">'
            f"{_with_gaps(item, dom, ranges)}</li>"
        )
    return f'<{tag} class="ld-plist{block_cls}">{"".join(body)}</{tag}>'


def _table(run: list[Row], dom: str, ranges, block_cls: str) -> str:
    rows = []
    for row in run:
        shown = _shown(row.index, ranges)
        cls = "ld-prow ld-ptable" + ("" if shown else " ld-elided")
        if row.kind == "tablesep":
            # The `|---|` line is markdown punctuation, not content.
            continue
        cells = [c.strip() for c in row.text.strip().strip("|").split("|")]
        tds = "".join(f"<td>{_inline(c)}</td>" for c in cells)
        rows.append(f'<tr class="{cls}" id="{dom}-r{row.index}">{tds}</tr>')
    return (
        f'<div class="ld-ptablewrap{block_cls}">'
        f'<table class="ld-ptableblock"><tbody>{"".join(rows)}</tbody></table></div>'
    )
