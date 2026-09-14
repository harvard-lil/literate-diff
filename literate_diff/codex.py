"""Collect Codex threads into transcript turns.

Codex -- the CLI, the IDE extension and the desktop app -- writes each thread
to a rollout file under `~/.codex/sessions/YYYY/MM/DD/`, and moves it to
`~/.codex/archived_sessions/` when the thread is archived. Every line is
`{timestamp, type, payload}`. The first is `session_meta`, which records the
directory the thread ran in; what the model read and wrote are
`response_item` records; `event_msg` records are the harness's own events,
token counts among them. Names given to threads are in
`~/.codex/session_index.jsonl`, one line per rename, latest last.

A turn means what it means for a Claude session: a message the person typed
and the work that followed it, up to the next one.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .collect import Thread, Turn, _clean, _finish, _slug

TOOL = "codex"

# Codex delivers its own context as user messages. They are the harness
# speaking, not the person, so they are not turns. Listed explicitly, as for
# Claude: an unrecognised block shows up as a turn -- visibly wrong and easy to
# fix -- rather than being dropped on a guess about what it is.
CONTEXT = (
    "<environment_context>",
    "# AGENTS.md instructions",
    "<user_instructions>",
    "<recommended_plugins>",
    "<skill>",
    "<in-app-browser-context",
)
# Background reports arriving mid-turn: work, like a Claude task notification.
EVENTS = ("<subagent_notification>",)
# Written when the person stops a turn; it marks the turn it follows.
INTERRUPT = "<turn_aborted>"
# An attached image arrives as text parts wrapped around the image part.
IMAGE_WRAPPER = ("<image", "</image>")

# The desktop app and the IDE extension put what they know (open files,
# attachments, the browser) above the words the person typed, under a header.
REQUEST = re.compile(r"^## My request(?: for Codex)?:[ \t]*\n", re.M)
FILE_LISTS = ("# Files mentioned by the user:", "# Files pasted by the user:")
FILE_LINE = re.compile(r"^## .+?: (\S.*?)\s*$", re.M)


def codex_root(home: Path) -> Path:
    return home / ".codex"


def rollouts(root: Path) -> list[Path]:
    live = sorted((root / "sessions").rglob("rollout-*.jsonl"))
    archived = sorted((root / "archived_sessions").glob("rollout-*.jsonl"))
    return live + archived


def thread_names(root: Path) -> dict[str, str]:
    """Thread id to the name it was last given."""
    names: dict[str, str] = {}
    index = root / "session_index.jsonl"
    if not index.is_file():
        return names
    for raw in index.open(errors="replace"):
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if rec.get("id") and rec.get("thread_name"):
            names[rec["id"]] = rec["thread_name"]
    return names


def _first_record(path: Path) -> dict:
    with path.open(errors="replace") as fh:
        line = fh.readline()
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        return {}
    return rec if isinstance(rec, dict) else {}


def _user_message(content) -> tuple[str, list[str], int, set[str]]:
    """One user message to (prompt, attachments, images, markers).

    `markers` holds `interrupt` and `event` when the message carries those
    blocks. The prompt is empty when everything in the message was context.
    """
    texts: list[str] = []
    attachments: list[str] = []
    images = 0
    markers: set[str] = set()
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "input_image":
            images += 1
            continue
        if block.get("type") != "input_text":
            continue
        text = block.get("text") or ""
        request = REQUEST.search(text)
        if request:
            preamble = text[: request.start()]
            if preamble.lstrip().startswith(FILE_LISTS):
                attachments += [Path(m.group(1)).name for m in FILE_LINE.finditer(preamble)]
            text = text[request.end() :]
        head = text.lstrip()
        if head.startswith(INTERRUPT):
            markers.add("interrupt")
        elif head.startswith(EVENTS):
            markers.add("event")
        elif head.startswith(CONTEXT) or head.startswith(IMAGE_WRAPPER):
            continue
        elif _clean(text):
            texts.append(_clean(text))
    return "\n\n".join(texts), attachments, images, markers


def read_rollout(path: Path) -> tuple[dict, list[Turn]]:
    """One rollout file to (session_meta payload, turns)."""
    meta: dict = {}
    turns: list[Turn] = []
    cur: Turn | None = None
    pending: list[str] = []
    last_total = None

    for raw in path.open(errors="replace"):
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        kind = rec.get("type")
        payload = rec.get("payload") or {}
        ts = rec.get("timestamp") or ""

        if kind == "session_meta":
            meta = meta or payload
            continue

        if kind == "compacted":
            if cur is not None:
                cur.compacted = True
            continue

        if kind == "event_msg":
            event = payload.get("type")
            if event == "token_count":
                # The same totals are reported more than once; count a
                # response's output only when the running total moves.
                info = payload.get("info") or {}
                total = (info.get("total_token_usage") or {}).get("total_tokens")
                if total is not None and total != last_total:
                    last_total = total
                    if cur is not None:
                        last = info.get("last_token_usage") or {}
                        cur.out_tokens += int(last.get("output_tokens") or 0)
            elif cur is not None and event == "turn_aborted":
                cur.interrupted = True
            elif cur is not None and event == "context_compacted":
                cur.compacted = True
            continue

        if kind != "response_item":
            continue
        item = payload.get("type") or ""

        if item == "message" and payload.get("role") == "user":
            prompt, attachments, images, markers = _user_message(payload.get("content"))
            if cur is not None:
                if "interrupt" in markers:
                    cur.interrupted = True
                if "event" in markers:
                    cur.events += 1
            if prompt or (images and not markers):
                if cur is not None:
                    cur.response = _finish(cur, pending)
                    turns.append(cur)
                pending = []
                cur = Turn(
                    at=ts,
                    prompt=prompt,
                    images=images,
                    attachments=attachments,
                    session=str(meta.get("id") or ""),
                )
            continue

        if cur is None:
            continue
        if item == "message" and payload.get("role") != "assistant":
            # Developer messages are settings re-sent when a thread is
            # resumed, hours later; they are not part of the turn's work.
            continue
        if ts:
            cur.end = ts

        if item == "message":
            for block in payload.get("content") or []:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "output_text"
                    and (block.get("text") or "").strip()
                ):
                    pending.append(block["text"])
        elif item in ("function_call", "custom_tool_call"):
            name = payload.get("name") or "?"
            cur.tools[name] = cur.tools.get(name, 0) + 1
        elif item.endswith("_call"):
            # web_search_call, tool_search_call, local_shell_call: the kind of
            # call is its name.
            name = item[: -len("_call")]
            cur.tools[name] = cur.tools.get(name, 0) + 1
        # Reasoning is stored encrypted, with at most a few summary headings,
        # so there is no count comparable to Claude's thinking to record.

    if cur is not None:
        cur.response = _finish(cur, pending)
        turns.append(cur)
    return meta, turns


def _same_dir(a: str, b: str) -> bool:
    return a == b or Path(a).expanduser().resolve() == Path(b)


def _untitled(turns: list[Turn]) -> str:
    """Codex lists an unnamed thread by its first message; so does this."""
    first = turns[0].prompt.strip().split("\n")[0] if turns else ""
    return first[:60].rstrip() + ("…" if len(first) > 60 else "") or "Codex thread"


def collect_codex(
    repo: str, home: Path, sessions: list[str] | None = None
) -> tuple[list[Thread], str, bool]:
    """Threads that ran in `repo`, as (threads, where looked, store exists).

    Threads Codex spawned as subagents are skipped: their work reaches the
    person through the parent thread, as a Claude subagent's does.
    """
    root = codex_root(home)
    where = str(root / "sessions")
    if not (root / "sessions").is_dir() and not (root / "archived_sessions").is_dir():
        return [], where, False
    project = str(Path(repo).expanduser().resolve())
    names = thread_names(root)
    seen: set[str] = set()
    found: list[Thread] = []
    for path in rollouts(root):
        head = _first_record(path)
        if head.get("type") != "session_meta":
            continue
        meta = head.get("payload") or {}
        source = meta.get("source")
        if isinstance(source, dict) and "subagent" in source:
            continue
        if not meta.get("cwd") or not _same_dir(meta["cwd"], project):
            continue
        sid = str(meta.get("id") or path.stem)
        if sid in seen:
            continue
        if sessions and not any(sid.startswith(s) for s in sessions):
            continue
        seen.add(sid)
        _, turns = read_rollout(path)
        if not turns:
            continue
        title = names.get(sid) or _untitled(turns)
        found.append(
            Thread(
                id=_slug(title),
                title=title,
                sessions=[sid],
                turns=turns,
                tool=TOOL,
                project=project,
            )
        )
    return found, where, True
