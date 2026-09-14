"""Collect agent sessions into a transcript file.

Collection is a separate phase from building. A git range is reproducible from
the repository; session logs are local, mutable, and eventually deleted, so the
transcript is a source artifact that lives next to the sidecar the way a
`.patch` file does. Keeping it separate also gives redaction somewhere to
happen: the output is plain YAML, meant to be read and edited before it is
shared.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SYSTEM_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
COMMAND_WRAPPER_RE = re.compile(
    r"</?(?:command-name|command-message|command-args|local-command-stdout"
    r"|local-command-caveat|user-prompt-submit-hook)>",
)
LOCAL_ONLY_RE = re.compile(
    r"^\s*<(?:command-name|local-command-stdout|local-command-caveat)>", re.S
)
# The harness delivers some of its own events as user messages. They are work,
# not speech, so they belong in the band with the tool calls. Listed explicitly:
# an unrecognised wrapper should show up as a turn -- visibly wrong and easy to
# fix -- rather than being dropped on a guess about what the tag means.
INJECTED = ("task-notification", "ci-monitor-event", "user-prompt-submit-hook")
INJECTED_RE = re.compile(r"^\s*<(" + "|".join(INJECTED) + r")>", re.S)
# Pressing escape writes a message in the user's voice that the user did not
# write. It marks the turn it lands in rather than starting one.
INTERRUPT_RE = re.compile(r"^\[Request interrupted by user[^\]]*\]\s*$")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
# The complement of what YAML allows in a document (PyYAML's reader check).
NON_PRINTABLE_RE = re.compile(
    "[^\t\n\r\x20-\x7e\x85\xa0-퟿-�\U00010000-\U0010ffff]"
)


def local_zone() -> str:
    """The zone the work happened in.

    Session logs are stamped UTC, which is four hours wrong for a document
    about someone's week: a turn at 20:00 local reads as the next morning.
    The zone is recorded in the transcript rather than read from the machine
    at build time, so a document does not change meaning when it is rebuilt
    somewhere else.
    """
    link = Path("/etc/localtime")
    if link.exists():
        parts = link.resolve().parts
        if "zoneinfo" in parts:
            name = "/".join(parts[parts.index("zoneinfo") + 1 :])
            try:
                ZoneInfo(name)
                return name
            except (ZoneInfoNotFoundError, ValueError):
                pass
    return datetime.now().astimezone().strftime("%z") or "UTC"


def project_dir(repo: str, home: Path) -> Path:
    """Claude CLI stores a project's sessions under a path-derived directory."""
    resolved = str(Path(repo).expanduser().resolve())
    return home / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", resolved)


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        if isinstance(b, dict) and b.get("type") == "text":
            out.append(b.get("text", ""))
    return "".join(out)


def _clean(text: str) -> str:
    """Drop what the harness injected, keeping what the person typed."""
    text = SYSTEM_REMINDER_RE.sub("", text)
    text = COMMAND_WRAPPER_RE.sub("", text)
    # Terminal output pasted into a prompt brings its colour codes along. YAML
    # cannot carry control characters even in a block scalar, so one of them
    # makes the whole transcript unreadable.
    text = ANSI_RE.sub("", text)
    text = NON_PRINTABLE_RE.sub("", text)
    # Trailing whitespace would make the YAML block scalars unreadable, and a
    # transcript nobody can read is a transcript nobody redacts.
    return "\n".join(line.rstrip() for line in text.strip().split("\n")).strip()


def _is_user_turn(rec: dict) -> bool:
    if rec.get("type") != "user" or rec.get("isMeta") or rec.get("isCompactSummary"):
        return False
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return False
    text = _text_of(content)
    if LOCAL_ONLY_RE.match(text or "") or INJECTED_RE.match(text or ""):
        return False
    if INTERRUPT_RE.match((text or "").strip()):
        return False
    return bool(_clean(text or "") or _has_image(content))


def _has_image(content) -> bool:
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "image" for b in content
    )


@dataclass
class Turn:
    at: str
    prompt: str
    response: str = ""
    narration: list[str] = field(default_factory=list)
    tools: dict[str, int] = field(default_factory=dict)
    thinking_chars: int = 0
    out_tokens: int = 0
    attachments: list[str] = field(default_factory=list)
    images: int = 0
    events: int = 0
    end: str = ""
    session: str = ""
    compacted: bool = False
    interrupted: bool = False

    @property
    def seconds(self) -> int:
        if not self.end:
            return 0
        try:
            a = datetime.fromisoformat(self.at.replace("Z", "+00:00"))
            b = datetime.fromisoformat(self.end.replace("Z", "+00:00"))
        except ValueError:
            return 0
        return max(0, int((b - a).total_seconds()))


@dataclass
class Thread:
    id: str
    title: str
    sessions: list[str] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)
    tool: str = "claude-code"
    project: str = ""


def read_session(path: Path) -> tuple[str, list[Turn]]:
    """One session file to (title, turns). A turn is a user message and the
    work that followed it, up to the next user message."""
    title = ""
    turns: list[Turn] = []
    cur: Turn | None = None
    pending_text: list[str] = []
    session_id = path.stem

    for raw in path.open(errors="replace"):
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue

        kind = rec.get("type")
        if kind == "custom-title":
            title = rec.get("customTitle") or title
            continue

        if kind == "system" and rec.get("subtype") == "compact_boundary":
            if cur is not None:
                cur.compacted = True
            continue

        if kind == "attachment" and cur is not None:
            att = rec.get("attachment") or {}
            name = att.get("filename") or att.get("path") or ""
            if name:
                cur.attachments.append(Path(name).name)
            continue

        if kind not in ("user", "assistant"):
            continue

        ts = rec.get("timestamp") or ""
        message = rec.get("message") or {}
        content = message.get("content")

        if _is_user_turn(rec):
            if cur is not None:
                cur.response = _finish(cur, pending_text)
                turns.append(cur)
            pending_text = []
            cur = Turn(
                at=ts,
                prompt=_clean(_text_of(content)),
                images=sum(
                    1
                    for b in (content if isinstance(content, list) else [])
                    if isinstance(b, dict) and b.get("type") == "image"
                ),
                session=session_id,
            )
            continue

        if cur is None:
            continue
        if ts:
            cur.end = ts

        if message.get("role") == "user":
            body = _text_of(content) or ""
            if INJECTED_RE.match(body):
                cur.events += 1
            elif INTERRUPT_RE.match(body.strip()):
                cur.interrupted = True
            continue

        if message.get("role") == "assistant":
            usage = message.get("usage") or {}
            cur.out_tokens += int(usage.get("output_tokens") or 0)
            for b in content if isinstance(content, list) else []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and b.get("text", "").strip():
                    pending_text.append(b["text"])
                elif b.get("type") == "thinking":
                    cur.thinking_chars += len(b.get("thinking") or "")
                elif b.get("type") == "tool_use":
                    name = b.get("name") or "?"
                    cur.tools[name] = cur.tools.get(name, 0) + 1

    if cur is not None:
        cur.response = _finish(cur, pending_text)
        turns.append(cur)
    return title, turns


def _finish(turn: Turn, texts: list[str]) -> str:
    """The last assistant text block is the reply; earlier ones are narration
    wrapped around tool calls, and belong in the summary band instead."""
    if not texts:
        return ""
    turn.narration = [_clean(t) for t in texts[:-1] if _clean(t)]
    return _clean(texts[-1])


def _slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return s or "thread"


def turn_id(turn: Turn, taken: set[str], zone: str = "UTC") -> str:
    """Stable across re-collection: derived from when the turn happened, not
    from its position, so inserting an earlier session does not renumber.

    In the transcript's zone, so the id agrees with the time printed next to
    it -- a turn labelled `t0903-1652` should not read `20:52` on the page.
    """
    stamp = local_stamp(turn.at, zone)
    base = f"t{stamp[4:8]}-{stamp[9:13]}" if len(stamp) >= 13 else "t"
    candidate, n = base, 1
    while candidate in taken:
        n += 1
        candidate = f"{base}.{n}"
    taken.add(candidate)
    return candidate


def local_stamp(at: str, zone: str) -> str:
    """`YYYYMMDD HHMM` in `zone`, from a UTC timestamp."""
    if not at:
        return ""
    try:
        when = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return at[:16].replace("-", "").replace(":", "")
    try:
        when = when.astimezone(ZoneInfo(zone))
    except (ZoneInfoNotFoundError, ValueError):
        pass
    return when.strftime("%Y%m%d %H%M")


#: Agents whose local logs `collect` reads.
TOOLS = ("claude-code", "codex")


def _claude_threads(
    repo: str, home: Path, sessions: list[str] | None
) -> tuple[list[Thread], str, bool]:
    """Claude sessions for `repo`, as (threads, where looked, store exists)."""
    directory = project_dir(repo, home)
    if not directory.is_dir():
        return [], str(directory), False
    found: list[Thread] = []
    for path in sorted(directory.glob("*.jsonl")):
        if sessions and not any(path.stem.startswith(s) for s in sessions):
            continue
        title, turns = read_session(path)
        if not turns:
            continue
        found.append(
            Thread(
                id=_slug(title or path.stem[:8]),
                title=title or f"Session {path.stem[:8]}",
                sessions=[path.stem],
                turns=turns,
                project=str(Path(repo).expanduser().resolve()),
            )
        )
    return found, str(directory), True


def collect(
    repo: str,
    home: Path,
    titles: list[str] | None = None,
    sessions: list[str] | None = None,
    since: str = "",
    merge_by_title: bool = False,
    zone: str = "UTC",
    warnings: list[str] | None = None,
    tools: list[str] | tuple[str, ...] = ("claude-code",),
) -> list[Thread]:
    warn = warnings if warnings is not None else []
    looked: list[str] = []
    present = False
    found: list[Thread] = []
    for tool in tools:
        if tool == "claude-code":
            threads, where, exists = _claude_threads(repo, home, sessions)
        elif tool == "codex":
            from .codex import collect_codex

            threads, where, exists = collect_codex(repo, home, sessions)
        else:
            raise SystemExit(f"unknown tool {tool!r}; known: {', '.join(TOOLS)}")
        looked.append(where)
        present = present or exists
        found += threads
    if not present:
        raise SystemExit(f"no sessions found for {repo} (looked in {', '.join(looked)})")

    if titles:
        found = [t for t in found if any(w.lower() in t.title.lower() for w in titles)]
    if since:
        for thread in found:
            thread.turns = [t for t in thread.turns if t.at >= since]
        found = [t for t in found if t.turns]

    if titles:
        for want in titles:
            if not any(want.lower() in t.title.lower() for t in found):
                warn.append(f"no session titled {want!r} under {', '.join(looked)}")

    if merge_by_title:
        found = _merge(found, warn)

    for thread in found:
        thread.turns.sort(key=lambda t: t.at)
        taken: set[str] = set()
        thread.turn_ids = [turn_id(t, taken, zone) for t in thread.turns]  # type: ignore[attr-defined]
    found.sort(key=lambda t: t.turns[0].at if t.turns else "")
    return found


def _merge(threads: list[Thread], warn: list[str]) -> list[Thread]:
    """Sessions sharing a title are one piece of work, resumed.

    A session resumed after a compaction repeats the turns that were carried
    over, so the same prompt appears in both files with the same timestamp.
    Those are one turn, not two. A Claude session and a Codex thread that
    share a title stay separate threads: each is one agent's record.
    """
    by_title: dict[tuple[str, str], Thread] = {}
    out: list[Thread] = []
    for thread in threads:
        first = by_title.get((thread.tool, thread.title))
        if first is None:
            by_title[(thread.tool, thread.title)] = thread
            out.append(thread)
            continue
        have = {(t.at, t.prompt) for t in first.turns}
        fresh = [t for t in thread.turns if (t.at, t.prompt) not in have]
        dropped = len(thread.turns) - len(fresh)
        if dropped:
            warn.append(
                f"{thread.title!r}: {dropped} turns of session "
                f"{thread.sessions[0][:8]} also appear in {first.sessions[0][:8]} "
                "(resumed session); kept one copy"
            )
        first.sessions += thread.sessions
        first.turns += fresh
    return out


# --- YAML output --------------------------------------------------------------


def _block(text: str, indent: str) -> str:
    """A YAML literal block scalar, indented two under its key.

    `|-` because the trailing newline is not part of what anyone said. Lines are
    right-stripped here as well as at collection, so that a hand-edited
    transcript cannot reintroduce trailing whitespace the reader cannot see. A
    first line that begins with a space needs the explicit indentation
    indicator, or YAML infers the block's indent from it and rejects the rest.
    """
    if not text:
        return ' ""'
    lines = [line.rstrip() for line in text.split("\n")]
    head = "|-2" if lines and lines[0][:1].isspace() else "|-"
    body = "\n".join(indent + line if line else "" for line in lines)
    return f" {head}\n" + body


def to_yaml(threads: list[Thread], meta: dict) -> str:
    out = [
        "# literate-diff transcript.",
        "#",
        "# Collected from local agent session logs, which are neither shared nor",
        "# permanent -- this file is the copy of record. Read it before it goes",
        "# anywhere: prompts and replies quote whatever was on screen at the time.",
        "# Editing is expected. Cut turns, redact lines, fix a title.",
        f"collected: {meta.get('collected', '')}",
        "# Timestamps below are UTC, as the logs record them. `timezone` is the",
        "# clock they are shown on, and the one the turn ids were derived from.",
        f"timezone: {meta.get('timezone', 'UTC')}",
        "threads:",
    ]
    for thread in threads:
        ids = getattr(thread, "turn_ids", [f"t{i}" for i in range(len(thread.turns))])
        out.append(f"  - id: {thread.id}")
        out.append(f"    title: {json.dumps(thread.title)}")
        out.append(f"    tool: {thread.tool}")
        out.append(f"    sessions: [{', '.join(thread.sessions)}]")
        out.append("    turns:")
        for tid, turn in zip(ids, thread.turns):
            out.append(f"      - id: {tid}")
            out.append(f"        at: {turn.at}")
            if turn.session and len(thread.sessions) > 1:
                out.append(f"        session: {turn.session}")
            out.append("        prompt:" + _block(turn.prompt, " " * 10))
            if turn.response:
                out.append("        response:" + _block(turn.response, " " * 10))
            work = []
            if turn.seconds:
                work.append(f"seconds: {turn.seconds}")
            if turn.out_tokens:
                work.append(f"tokens: {turn.out_tokens}")
            if turn.thinking_chars:
                work.append(f"thinking: {turn.thinking_chars}")
            if turn.images:
                work.append(f"images: {turn.images}")
            if turn.events:
                work.append(f"events: {turn.events}")
            if work:
                out.append("        work: {" + ", ".join(work) + "}")
            if turn.tools:
                pairs = ", ".join(
                    f"{k}: {v}" for k, v in sorted(turn.tools.items(), key=lambda kv: -kv[1])
                )
                out.append("        tools: {" + pairs + "}")
            if turn.attachments:
                uniq = list(dict.fromkeys(turn.attachments))
                out.append(f"        attachments: {json.dumps(uniq)}")
            if turn.narration:
                out.append("        narration:")
                for line in turn.narration:
                    out.append("          -" + _block(line, " " * 12))
            if turn.compacted:
                out.append("        compacted: true")
            if turn.interrupted:
                out.append("        interrupted: true")
    return "\n".join(out) + "\n"
