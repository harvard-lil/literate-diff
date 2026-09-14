"""The conversation side of a document: threads, turns, and their text rows.

A message is modelled the way a file diff is -- as a list of rows -- so that the
anchor grammar (`at:`, `nth:`, `span:`, `through:`) and the `ld:`/`ldq:` schemes
reach into a conversation without learning anything new. Rows are sentences
rather than lines, which is the granularity a highlight wants: a prompt is
usually one long paragraph, and the part worth quoting is a sentence of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from .model import Row as BaseRow
from .model import Unit

# A sentence end: terminal punctuation, optional closing quote or bracket, then
# space and something that starts a new sentence.
SENTENCE_END = re.compile(r"([.!?][\"')\]]?)\s+(?=[A-Z0-9\"'(\[`*_-])")
# Splitting at these would cut a word, a label or a name, not a sentence.
ABBREV = ("e.g", "i.e", "cf", "vs", "etc", "approx", "no", "fig", "eq",
          "mr", "mrs", "ms", "dr", "prof", "st", "jr", "sr", "inc", "ltd")
INITIAL = re.compile(r"(?:^|[\s(\[*_])[A-Za-z]\.$")

# AP style: the four short months and May are set whole, the rest abbreviated.
MONTHS = (
    "Jan.", "Feb.", "March", "April", "May", "June",
    "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec.",
)

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
QUOTE = re.compile(r"^\s*>\s?(.*)$")
TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")
RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")


def when(at: str, zone: str):
    """A UTC timestamp on the transcript's clock, or None if unreadable."""
    if not at:
        return None
    try:
        moment = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return None
    try:
        return moment.astimezone(ZoneInfo(zone))
    except (ZoneInfoNotFoundError, ValueError):
        return moment


def format_when(at: str, zone: str) -> str:
    """`Monday, Sept. 1 4:06PM`."""
    moment = when(at, zone)
    if moment is None:
        return at[:16].replace("T", " ")
    hour = moment.hour % 12 or 12
    meridiem = "AM" if moment.hour < 12 else "PM"
    return (
        f"{moment.strftime('%A')}, {MONTHS[moment.month - 1]} {moment.day} "
        f"{hour}:{moment.minute:02d}{meridiem}"
    )


def format_span(first: str, last: str, zone: str) -> str:
    """`Aug. 31 – Sept. 4, 2026`, collapsed when it is one day."""
    a, b = when(first, zone), when(last, zone)
    if a is None or b is None:
        return ""
    head = f"{MONTHS[a.month - 1]} {a.day}"
    if (a.year, a.month, a.day) == (b.year, b.month, b.day):
        return f"{head}, {a.year}"
    tail = f"{MONTHS[b.month - 1]} {b.day}" if a.month != b.month else str(b.day)
    return f"{head} – {tail}, {b.year}"


@dataclass
class Row(BaseRow):
    """One row of a message: a sentence of prose, a line of code. Carries the
    block structure the renderer needs to put the markdown back together
    around it."""

    # kind: prose | code | fence | blank | heading | bullet | quote | table | tablesep | rule
    block: int = 0  # source line, so sentences of one list item stay one item
    level: int = 0  # heading level, or bullet indent
    marker: str = ""  # the bullet's own marker, kept for ordered lists


def _split_sentences(text: str) -> list[str]:
    """Split a line into sentences, declining the splits that would cut
    something that only looks like one."""
    out: list[str] = []
    start = 0
    for m in SENTENCE_END.finditer(text):
        head = text[start : m.end(1)]
        tail = head.rsplit(" ", 1)[-1].rstrip(".!?\"')]").lower()
        if tail in ABBREV or INITIAL.search(head):
            continue
        # A split inside `code` or **bold** would leave the markup unclosed.
        if head.count("`") % 2 or head.count("**") % 2:
            continue
        out.append(head.strip())
        start = m.end()
    rest = text[start:].strip()
    if rest:
        out.append(rest)
    return out or [text.strip()]


@dataclass(kw_only=True)
class TurnBody(Unit):
    """One message, as rows."""

    # kind: "prompt" | "response"

    @property
    def is_prose(self) -> bool:
        return True


@dataclass
class Work:
    """What happened between the prompt and the reply, as counts. Deliberately
    not expandable: the outcome of the work is the diff, and the narration is
    here to make the band legible, not to be read."""

    seconds: int = 0
    tokens: int = 0
    thinking: int = 0
    tools: dict[str, int] = field(default_factory=dict)
    attachments: list[str] = field(default_factory=list)
    images: int = 0
    events: int = 0
    narration: list[str] = field(default_factory=list)
    compacted: bool = False
    interrupted: bool = False

    @property
    def tool_count(self) -> int:
        return sum(self.tools.values())

    def summary(self) -> str:
        bits = []
        if self.seconds >= 60:
            bits.append(f"{round(self.seconds / 60)} min")
        elif self.seconds:
            bits.append(f"{self.seconds}s")
        if self.tokens:
            bits.append(
                f"{self.tokens / 1000:.1f}k tokens".replace(".0k", "k")
                if self.tokens >= 1000
                else f"{self.tokens} tokens"
            )
        if self.tools:
            top = sorted(self.tools.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
            named = ", ".join(f"{k} ×{v}" for k, v in top)
            bits.append(f"{self.tool_count} tool calls ({named})")
        return " · ".join(bits)


@dataclass
class Turn:
    id: str
    at: str
    thread: str
    prompt: TurnBody
    response: TurnBody | None
    work: Work
    session: str = ""
    # Filled by the annotator.
    note_md: str = ""
    anchor_id: str = ""
    thread_title: str = ""
    zone: str = "UTC"
    # Highlights are lists: one decision often turns on two passages of a
    # reply that are pages apart -- the options and the recommendation.
    prompt_ranges: list[tuple[int, int]] = field(default_factory=list)
    response_ranges: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class Thread:
    id: str
    title: str
    sessions: list[str] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)
    note_md: str = ""
    zone: str = "UTC"
    tool: str = ""  # the agent whose log it was collected from


def split_rows(text: str) -> list[Row]:
    """A message to rows: sentences inside prose, lines inside code and tables.

    Sentence granularity is what a highlight wants -- the part of a prompt worth
    quoting is a sentence of it, and prompts are mostly one long paragraph. The
    block a row came from is recorded so the renderer can rebuild the markdown
    around it.
    """
    rows: list[Row] = []
    in_code = False
    for block, raw in enumerate((text or "").split("\n")):
        stripped = raw.strip()

        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            rows.append(Row("fence", raw, block=block))
            continue
        if in_code:
            rows.append(Row("code", raw, block=block))
            continue
        if not stripped:
            rows.append(Row("blank", "", block=block))
            continue
        if RULE.match(raw):
            rows.append(Row("rule", "", block=block))
            continue

        heading = HEADING.match(stripped)
        if heading:
            rows.append(
                Row("heading", heading.group(2).strip(), block=block, level=len(heading.group(1)))
            )
            continue

        if TABLE_SEP.match(raw) and "|" in raw:
            rows.append(Row("tablesep", stripped, block=block))
            continue
        if stripped.startswith("|"):
            rows.append(Row("table", stripped, block=block))
            continue

        quote = QUOTE.match(raw)
        if quote:
            for sentence in _split_sentences(quote.group(1).strip()):
                rows.append(Row("quote", sentence, block=block))
            continue

        bullet = BULLET.match(raw)
        if bullet:
            indent, marker, body = bullet.groups()
            for i, sentence in enumerate(_split_sentences(body.strip())):
                rows.append(
                    Row(
                        "bullet",
                        sentence,
                        block=block,
                        level=len(indent) // 2,
                        marker=marker if i == 0 else "",
                    )
                )
            continue

        indent = raw[: len(raw) - len(raw.lstrip())]
        for i, sentence in enumerate(_split_sentences(stripped)):
            rows.append(Row("prose", (indent if i == 0 else "") + sentence, block=block))

    while rows and rows[-1].kind == "blank":
        rows.pop()
    for i, row in enumerate(rows):
        row.index = i
    return rows


def load_transcript(path_or_text: str, warnings: list[str]) -> list[Thread]:
    """Threads from a collected transcript: a path, or the YAML text itself."""
    if "\n" not in path_or_text and Path(path_or_text).is_file():
        text = Path(path_or_text).read_text(encoding="utf-8")
    else:
        text = path_or_text
    data = yaml.safe_load(text) or {}
    zone = str(data.get("timezone") or "UTC")
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        warnings.append(f"transcript timezone {zone!r} is not a zone; using UTC")
        zone = "UTC"
    threads: list[Thread] = []
    for raw in data.get("threads") or []:
        thread = Thread(
            id=raw.get("id") or "thread",
            title=raw.get("title") or raw.get("id") or "Conversation",
            sessions=list(raw.get("sessions") or []),
            zone=zone,
            # Transcripts collected before threads carried their own `tool:`
            # name it once, at the top.
            tool=str(raw.get("tool") or data.get("tool") or ""),
        )
        for entry in raw.get("turns") or []:
            tid = str(entry.get("id") or f"t{len(thread.turns)}")
            key = f"{thread.id}:{tid}"
            prompt_rows = split_rows(entry.get("prompt") or "")
            if not prompt_rows:
                warnings.append(f"{key}: turn has no prompt text; skipped")
                continue
            response_text = entry.get("response") or ""
            work_raw = entry.get("work") or {}
            thread.turns.append(
                Turn(
                    id=tid,
                    at=str(entry.get("at") or ""),
                    thread=thread.id,
                    zone=zone,
                    session=str(entry.get("session") or ""),
                    prompt=TurnBody(
                        key=f"{key}#prompt",
                        path=key,
                        lines=prompt_rows,
                        kind="prompt",
                        label=thread.title,
                    ),
                    response=(
                        TurnBody(
                            key=f"{key}#response",
                            path=key,
                            lines=split_rows(response_text),
                            kind="response",
                            label=thread.title,
                        )
                        if response_text.strip()
                        else None
                    ),
                    work=Work(
                        seconds=int(work_raw.get("seconds") or 0),
                        tokens=int(work_raw.get("tokens") or 0),
                        thinking=int(work_raw.get("thinking") or 0),
                        images=int(work_raw.get("images") or 0),
                        events=int(work_raw.get("events") or 0),
                        tools=dict(entry.get("tools") or {}),
                        attachments=list(entry.get("attachments") or []),
                        narration=list(entry.get("narration") or []),
                        compacted=bool(entry.get("compacted")),
                        interrupted=bool(entry.get("interrupted")),
                    ),
                )
            )
        if thread.turns:
            threads.append(thread)
        else:
            warnings.append(f"transcript thread {thread.id!r} has no usable turns")
    return threads
