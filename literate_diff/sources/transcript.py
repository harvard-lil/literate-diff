"""The transcript source: collected agent conversations, as turns of rows.

Owns what is particular to a conversation: the transcript file and its
collection, the stream ordered by time with chapters fixed at a turn, the
`prompt:`/`response:` highlights, the work band, and the quote form that
shows words rather than lines.
"""

from __future__ import annotations

import html
from pathlib import Path

from ..message import inline_row, render_message
from ..model import Anchor, Item, Layer, SourceInfo, slug
from ..transcript import Thread, Turn, TurnBody, format_span, format_when, load_transcript
from .base import LoadContext, SourcePlugin


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


def default_ranges(lines, budget: int) -> list[tuple[int, int]]:
    """The opening, and the close it will be answered on."""
    lead = _lead(lines, budget)
    end = len(lines) - 1
    if lead >= end:
        return [(0, end)]
    start = _close(lines, lead)
    if start <= lead + 1:
        return [(0, end)]
    return [(0, lead), (start, end)]


TOOL_NAMES = {"claude-code": "Claude Code", "codex": "Codex"}


def tool_label(tool: str) -> str:
    """`Codex · ` ahead of a thread's counts: which agent's record it is."""
    if not tool:
        return ""
    return f"{TOOL_NAMES.get(tool, tool)} · "


class TranscriptSource(SourcePlugin):
    type = "transcript"
    evidence = "conversation"
    natural_order = True
    item_keys = ("prompt", "response", "anchors")
    v1_items_key = "turns"

    def __init__(self):
        self.threads: list[Thread] = []
        self.name = ""

    # --- loading ---------------------------------------------------------

    def load(self, ctx: LoadContext) -> tuple[list[Item], SourceInfo]:
        conf = ctx.conf
        self.name = ctx.name
        path = conf.get("file") or conf.get("path")
        if conf.get("text") is not None:
            text = conf["text"]
            path = path or "conversations.yaml"
        else:
            if not path:
                raise SystemExit(f"sources.{ctx.name} needs `file:` (a collected transcript)")
            full = Path(path) if Path(path).is_absolute() else ctx.base_dir / path
            if not full.is_file():
                raise SystemExit(f"transcript not found: {full}")
            text = full.read_text(encoding="utf-8")
        threads = load_transcript(text, ctx.warnings)
        self.threads = threads
        items: list[Item] = []
        for thread in threads:
            for turn in thread.turns:
                turn.thread_title = thread.title
                bodies = [turn.prompt] + ([turn.response] if turn.response is not None else [])
                for b in bodies:
                    b.source = ctx.name
                items.append(
                    Item(
                        key=f"{thread.id}:{turn.id}",
                        source=ctx.name,
                        plugin=self.type,
                        payload=turn,
                        bodies=bodies,
                    )
                )
        info = SourceInfo(name=ctx.name, type=self.type, label=conf.get("label") or ctx.name)
        if ctx.embed:
            info.embed[Path(path).name] = text
        info.counts = {"turns": len(items), "threads": len(threads),
                       "sessions": sum(len(t.sessions) or 1 for t in threads)}
        return items, info

    # --- binding -----------------------------------------------------------

    def bind_source(self, spec: dict, warnings: list[str]) -> None:
        per_thread = spec.get("threads") or {}
        known = {t.id: t for t in self.threads}
        for key, conf in per_thread.items():
            thread = known.get(key)
            if thread is None:
                warnings.append(f"threads: {key!r} is not in the transcript")
                continue
            conf = conf or {}
            thread.title = conf.get("title") or thread.title
            thread.note_md = conf.get("note", "") or ""
            for turn in thread.turns:
                turn.thread_title = thread.title

    def match(self, item: Item, pattern: str) -> bool:
        return pattern == item.key or pattern == item.payload.id

    def item_anchor_id(self, item: Item, n: int) -> str:
        return slug(f"turn-{item.key}")

    def body_dom(self, item: Item, unit, n: int) -> str:
        return f"t{n}p" if unit.kind == "prompt" else f"t{n}q"

    def sort_key(self, item: Item):
        # Turns without a timestamp keep the order they were collected in,
        # after everything that has one, rather than sorting to the front.
        return (item.payload.at == "", item.payload.at)

    def bind(self, item: Item, conf: dict, resolve, warnings, register) -> None:
        turn: Turn = item.payload
        base = item.anchor_id
        turn.anchor_id = base
        turn.note_md = conf.get("note", "") or item.note_md
        key = item.key
        for side, body in (("prompt", turn.prompt), ("response", turn.response)):
            if body is None:
                if conf.get(side):
                    warnings.append(f"{key}: no {side} to anchor `{side}:` to")
                continue
            spec = conf.get(side)
            specs = spec if isinstance(spec, list) else [spec] if spec else []
            if specs:
                found = [resolve(body, one) for one in specs]
                ranges = sorted((a.start, a.end) for a in found)
                if side == "prompt":
                    turn.prompt_ranges = ranges
                else:
                    turn.response_ranges = ranges
            else:
                found = [Anchor(file=body, start=0, end=len(body.lines) - 1, anchor_id="")]
            # The first passage answers to `-prompt`/`-response`; a second or
            # third is `-prompt2`, `-prompt3`, so each is quotable.
            for n, anchor in enumerate(found, start=1):
                register(anchor, f"{base}-{side}" + ("" if n == 1 else str(n)), quiet=True)

        for extra in conf.get("anchors") or []:
            if not extra.get("id"):
                warnings.append(f"{key}: `anchors` entry without an id is a no-op")
                continue
            side = extra.get("in", "prompt")
            body = turn.prompt if side == "prompt" else turn.response
            if body is None:
                warnings.append(f"{key}: anchor {extra['id']!r} names a missing {side}")
                continue
            register(resolve(body, extra), extra["id"])

    # --- rendering ---------------------------------------------------------

    def _message(self, r, turn: Turn, body: TurnBody, ranges, side: str) -> str:
        dom = r.body_dom[id(body)]
        n = len(body.lines)
        if not ranges:
            # A reply is given a little more room than a prompt: the reader is
            # there to judge what came back.
            ranges = default_ranges(body.lines, 320 if side == "prompt" else 460)
        shown = sum(b - a + 1 for a, b in ranges)
        more = (
            '<button type="button" class="ld-msg-more" aria-expanded="false">'
            f"show all ({n} lines)</button>"
            if n - shown > 0 else ""
        )
        who = "Prompt" if side == "prompt" else "Reply"
        return (
            f'<div class="ld-msg ld-msg-{side}" id="{html.escape(turn.anchor_id)}-{side}">'
            f'<div class="ld-who">{who}</div>'
            f'<div class="ld-msg-body">{render_message(body.lines, dom, ranges)}'
            f"{more}</div></div>"
        )

    def _work_band(self, turn: Turn) -> str:
        """What happened in between, as counts. Not expandable: the outcome of
        the work is the diff, and this is here to show its shape."""
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

    def render_item(self, r, layer: Layer, item: Item, show_source: bool) -> str:
        turn: Turn = item.payload
        stamp = format_when(turn.at, turn.zone)
        note = (
            f'<div class="ld-turn-note">{r.md(turn.note_md, r.here(item, 0), turn.id)}</div>'
            if turn.note_md.strip() else ""
        )
        # With more than one thread interleaved, the reader has to be told when
        # a turn came from a session opened alongside the main one.
        badge = (
            f'<span class="ld-turn-thread">{html.escape(turn.thread_title)}</span>'
            if show_source and turn.thread_title else ""
        )
        return (
            f'<article class="ld-turn" id="{html.escape(turn.anchor_id)}"'
            f' data-ld-thread="{html.escape(turn.thread)}">'
            f'<div class="ld-turn-head"><span class="ld-turn-time">{html.escape(stamp)}</span>'
            f'<a class="ld-turn-id" href="#{html.escape(turn.anchor_id)}"'
            f' data-ld-target="{html.escape(turn.anchor_id)}">{html.escape(turn.id)}</a>'
            f"{badge}</div>"
            f"{note}"
            f"{self._message(r, turn, turn.prompt, turn.prompt_ranges, 'prompt')}"
            f"{self._work_band(turn)}"
            + (
                self._message(r, turn, turn.response, turn.response_ranges, "reply")
                if turn.response is not None else ""
            )
            + "</article>"
        )

    def stream_key(self, item: Item) -> str:
        """Consecutive items sharing this key need no badge between them."""
        return item.payload.thread

    def render_head(self, r, layer: Layer) -> str:
        turns = [it.payload for it in layer.items if it.source == self.name]
        if not turns:
            return ""
        here = r.here_layer(layer)
        stamps = [t.at for t in turns if t.at]
        span = format_span(stamps[0], stamps[-1], turns[0].zone) if stamps else ""
        sessions = sum(len(t.sessions) or 1 for t in self.threads)
        meta = " · ".join(
            x for x in (
                f"{len(turns)} turns",
                span,
                f"{len(self.threads)} threads" if len(self.threads) > 1 else "",
                f"{sessions} sessions",
            ) if x
        )
        # Which sessions the stream is made of, and how much each contributed:
        # a reader judging the work needs to know it is looking at all of it.
        counts = "".join(
            f'<li class="ld-thread-row">'
            f'<div class="ld-thread-head"><span class="ld-thread-name">'
            f"{html.escape(thread.title)}</span>"
            f'<span class="ld-thread-count">{html.escape(tool_label(thread.tool))}'
            f'{len(thread.turns)} turns · '
            f"{len(thread.sessions) or 1} sessions</span></div>"
            + (
                f'<div class="ld-thread-note">{r.md(thread.note_md, here, thread.title)}</div>'
                if thread.note_md.strip() else ""
            )
            + "</li>"
            for thread in self.threads
        )
        return (
            f'<div class="ld-appendix-meta">{html.escape(meta)}</div>'
            f'<ul class="ld-threads">{counts}</ul>'
        )

    def quote(self, r, anchor: Anchor, target: str, label: str) -> str:
        """Quote a message the way `ldq:` quotes a diff: the words themselves,
        with a link through to where they were said."""
        body: TurnBody = anchor.file
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

    def toc_item(self, r, item: Item) -> str:
        # Turns are not listed one by one; the chapters carry the contents.
        return ""

    def chapter_landmark(self) -> str:
        return "ac-"

    def metaline(self, r, layer: Layer) -> list[str]:
        n = len(layer.items)
        return [f'<a href="#{layer.id}" data-ld-target="{layer.id}">{n} turns</a>'] if n else []

    def skill_fragment(self) -> str:
        return "transcript.md"
