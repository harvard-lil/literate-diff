"""Load the annotation sidecar and bind it to parsed diff lines."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field

import yaml

from .parse import FileDiff, Line
from .transcript import Row, Thread, Turn, TurnBody, load_transcript


class AnnotationError(Exception):
    pass


@dataclass
class Anchor:
    """A resolved row range within one body -- a file's diff, or a message."""

    file: FileDiff | TurnBody
    start: int  # index into file.lines
    end: int  # inclusive
    anchor_id: str


@dataclass
class Section:
    title: str
    note_md: str
    anchor: Anchor
    anchor_id: str


@dataclass
class SideNote:
    text_md: str
    anchor: Anchor
    anchor_id: str


@dataclass
class AppendixChapter:
    """A titled run of the conversation. The stream is chronological, so a
    chapter is fixed by the turn it opens at."""

    title: str
    note_md: str
    anchor_id: str
    start: int  # index into Document.turns


@dataclass
class Chapter:
    """A titled run of files. Carries the narrative between repos."""

    title: str
    note_md: str
    anchor_id: str
    start: int  # index into Document.files where this chapter begins


@dataclass
class AnnotatedFile:
    diff: FileDiff
    title: str = ""
    note_md: str = ""
    collapsed: bool = False
    sections: list[Section] = field(default_factory=list)
    notes: list[SideNote] = field(default_factory=list)
    anchor_id: str = ""


@dataclass
class Document:
    title: str
    subtitle: str
    plot_md: str
    files: list[AnnotatedFile]
    anchors: dict[str, Anchor]
    meta: dict
    chapters: list[Chapter] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # name -> {label, color, short}; see `categories:` in the README.
    categories: dict[str, dict] = field(default_factory=dict)
    # The appendix: conversations collected separately, cited from the diff.
    threads: list[Thread] = field(default_factory=list)
    # Every thread's turns in one chronological stream. A side conversation
    # opened to think something through belongs where it happened, not in a
    # section of its own.
    turns: list[Turn] = field(default_factory=list)
    appendix_chapters: list[AppendixChapter] = field(default_factory=list)
    appendix: dict = field(default_factory=dict)


_slug_bad = re.compile(r"[^a-zA-Z0-9._-]+")


def slug(s: str) -> str:
    return _slug_bad.sub("-", s).strip("-")


def load_annotations(path: str | None) -> dict:
    if not path:
        return {}
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise AnnotationError(f"{path}: top level must be a mapping")
    return data


def matches(file: FileDiff, pattern: str) -> bool:
    """Match a sidecar pattern against one file.

    A pattern naming a source (`actions:ecs-build/**`) is matched against the
    qualified key. A bare pattern (`**/dist/**`) is matched against the path
    inside every source, so single-repo sidecars keep working unchanged and a
    path glob means the same thing in each repo.
    """
    if ":" in pattern:
        return fnmatch.fnmatch(file.key, pattern)
    return fnmatch.fnmatch(file.path, pattern)


def _matches_any(file: FileDiff, patterns: list[str]) -> bool:
    return any(matches(file, p) for p in patterns)


def _take(
    remaining: list[FileDiff], patterns: list, warnings: list[str], label: str
) -> tuple[list[FileDiff], int | None]:
    """Pull the files matching `patterns` out of `remaining`, in pattern order.

    Returns the picked files and the position of a `*` wildcard, if one appeared.
    """
    picked: list[FileDiff] = []
    star_at: int | None = None
    for pat in patterns or []:
        if pat == "*":
            star_at = len(picked)
            continue
        hits = [f for f in remaining if matches(f, pat)]
        if not hits:
            warnings.append(f"{label}: no file matched {pat!r}")
        for f in hits:
            remaining.remove(f)
            picked.append(f)
    return picked, star_at


def order_files(files: list[FileDiff], spec: dict, warnings: list[str]) -> list[FileDiff]:
    """Apply `hide` and `order`. Files not named by `order` land at the `*` slot."""
    ordered, _ = order_and_chapter(files, spec, warnings)
    return ordered


def order_and_chapter(
    files: list[FileDiff], spec: dict, warnings: list[str]
) -> tuple[list[FileDiff], list[dict]]:
    """Order the files, and report where each chapter starts.

    `chapters` and `order` are alternatives: chapters are an order list cut into
    titled, annotated runs. When both are given, chapters win and `order` is
    reported as ignored.
    """
    hide = spec.get("hide") or []
    remaining = [f for f in files if not _matches_any(f, hide)]

    chapters = spec.get("chapters")
    if chapters and spec.get("order"):
        warnings.append("both `chapters` and `order` are set; ignoring `order`")

    if not chapters:
        picked, star_at = _take(remaining, spec.get("order") or [], warnings, "order")
        if not spec.get("order"):
            return remaining, []
        if star_at is None:
            picked.extend(remaining)
        else:
            picked[star_at:star_at] = remaining
        return picked, []

    result: list[FileDiff] = []
    marks: list[dict] = []
    leftovers_at: tuple[int, int] | None = None  # (chapter position, file position)

    for ci, chapter in enumerate(chapters):
        if not isinstance(chapter, dict):
            raise AnnotationError("each entry of `chapters` must be a mapping")
        picked, star_at = _take(
            remaining, chapter.get("files") or [], warnings, f"chapters[{ci}]"
        )
        marks.append(
            {
                "title": chapter.get("title", ""),
                "note": chapter.get("note", "") or "",
                "id": chapter.get("id"),
                "start": len(result),
            }
        )
        if star_at is not None:
            leftovers_at = (ci, len(result) + star_at)
        result.extend(picked)

    if remaining:
        if leftovers_at is None:
            # Nothing claimed the remainder, so it becomes a closing untitled run.
            marks.append({"title": "", "note": "", "id": None, "start": len(result)})
            result.extend(remaining)
        else:
            owner, at = leftovers_at
            result[at:at] = remaining
            # Only chapters *after* the one whose `*` absorbed the remainder move;
            # the owning chapter starts at the wildcard, so its own start holds.
            for mi, mark in enumerate(marks):
                if mi > owner:
                    mark["start"] += len(remaining)
    return result, marks


# --- anchor resolution -------------------------------------------------------


def resolve_anchor(file: FileDiff, spec: dict | str, warnings: list[str]) -> Anchor:
    """Resolve an `at`/`span`/`through` spec to a row range in `file`."""
    if isinstance(spec, str):
        spec = {"at": spec}
    at = spec.get("at")
    if at is None:
        raise AnnotationError(f"{file.key}: annotation is missing `at`")

    start = _find_row(file, at, int(spec.get("nth", 1)), warnings)
    end = start

    through = spec.get("through")
    span = spec.get("span")
    if through is not None:
        end = _find_row(file, through, 1, warnings, from_index=start)
    elif span is not None:
        end = min(start + int(span) - 1, len(file.lines) - 1)

    if end < start:
        end = start
    return Anchor(file=file, start=start, end=end, anchor_id="")


def _find_row(
    file: FileDiff,
    at,
    nth: int,
    warnings: list[str],
    from_index: int = 0,
) -> int:
    """Locate a diff row. Supports substring, /regex/, +N, -N, and @N forms."""
    rows = file.lines
    if not rows:
        raise AnnotationError(f"{file.key}: file has no diff rows to anchor to")

    if isinstance(at, int):
        return _clamp(at, rows)

    at = str(at)

    if at.startswith("@"):
        return _clamp(int(at[1:]), rows)

    if (at.startswith("+") or at.startswith("-")) and at[1:].isdigit():
        want = int(at[1:])
        side = "new_no" if at[0] == "+" else "old_no"
        for i, line in enumerate(rows[from_index:], start=from_index):
            if getattr(line, side) == want:
                return i
        warnings.append(f"{file.key}: no line {at}; anchoring at start")
        return from_index

    if len(at) > 1 and at.startswith("/") and at.endswith("/"):
        pat = re.compile(at[1:-1])
        test = lambda s: pat.search(s) is not None  # noqa: E731
    else:
        test = lambda s: at in s  # noqa: E731

    hits = [
        i
        for i, line in enumerate(rows[from_index:], start=from_index)
        if line.kind != "message" and test(line.text)
    ]
    if len(hits) >= nth:
        # An anchor that matches more than once is only pinned by accident: a
        # later commit adding an earlier match -- a comment quoting the code is
        # the usual way -- silently moves it. Say so while the choice is still
        # the intended one.
        # `nth: 1` is the default restated, not evidence the author counted the
        # matches; only nth >= 2 shows a deliberate choice among them.
        if len(hits) > 1 and nth == 1:
            where = rows[hits[0]].new_no or rows[hits[0]].old_no
            place = f"line {where}" if where else f"row {hits[0]}"
            warnings.append(
                f"{file.key}: {at!r} matches {len(hits)} rows; using the first "
                f"({place}). Narrow the pattern or set `nth` to pin it."
            )
        return hits[nth - 1]

    warnings.append(
        f"{file.key}: no match for {at!r}"
        + (f" (occurrence {nth}, {len(hits)} found)" if nth > 1 else "")
        + "; anchoring at start"
    )
    return from_index


def _clamp(i: int, rows: list[Line]) -> int:
    return max(0, min(i, len(rows) - 1))


# --- categories --------------------------------------------------------------


def normalize_categories(raw, warnings: list[str]) -> dict[str, dict]:
    """`categories:` may give each entry as a label string or a mapping.

    The result is keyed by the slug used in `{category: name}` markers and
    `ldc:` flags. `color` is optional; the renderer fills it from a
    colour-blind-safe palette in declaration order.
    """
    out: dict[str, dict] = {}
    if raw is None:
        return out
    if not isinstance(raw, dict):
        raise AnnotationError("`categories` must be a mapping of name -> label or settings")
    for name, conf in raw.items():
        if conf is None:
            conf = {}
        elif isinstance(conf, str):
            conf = {"label": conf}
        elif not isinstance(conf, dict):
            raise AnnotationError(f"categories.{name}: expected a label or a mapping")
        key = slug(str(name))
        if key in out:
            warnings.append(f"categories: {name!r} is declared twice")
        out[key] = {
            "label": str(conf.get("label") or name),
            "color": conf.get("color"),
            "short": str(conf.get("short") or ""),
        }
    return out


# --- assembly ----------------------------------------------------------------


def attach_threads(
    threads: list[Thread],
    spec: dict,
    anchors: dict[str, Anchor],
    warnings: list[str],
) -> None:
    """Bind `threads:` and `turns:` annotations, and register turn anchors.

    Every message is addressable whether or not it is annotated, so the plot can
    quote a turn with `ldq:` without the turn needing a sidecar entry first.
    """
    per_thread = spec.get("threads") or {}
    per_turn = spec.get("turns") or {}
    seen: set[str] = set()

    for thread in threads:
        conf = per_thread.get(thread.id) or {}
        thread.title = conf.get("title") or thread.title
        thread.note_md = conf.get("note", "") or ""

        for turn in thread.turns:
            key = f"{thread.id}:{turn.id}"
            tconf = per_turn.get(key)
            if tconf is None:
                tconf = per_turn.get(turn.id) if turn.id in per_turn else None
                if tconf is not None:
                    seen.add(turn.id)
            else:
                seen.add(key)
            tconf = tconf or {}

            base = slug(tconf.get("id")) if tconf.get("id") else slug(f"turn-{key}")
            turn.anchor_id = base
            turn.thread_title = thread.title
            turn.note_md = tconf.get("note", "") or ""

            whole = Anchor(file=turn.prompt, start=0, end=len(turn.prompt.lines) - 1,
                           anchor_id=base)
            if base in anchors:
                warnings.append(f"duplicate id {base!r}; later definition wins")
            anchors[base] = whole

            for side, body in (("prompt", turn.prompt), ("response", turn.response)):
                if body is None:
                    if tconf.get(side):
                        warnings.append(f"{key}: no {side} to anchor `{side}:` to")
                    continue
                spec = tconf.get(side)
                specs = spec if isinstance(spec, list) else [spec] if spec else []
                if specs:
                    found = [resolve_anchor(body, one, warnings) for one in specs]
                    ranges = sorted((a.start, a.end) for a in found)
                    if side == "prompt":
                        turn.prompt_ranges = ranges
                    else:
                        turn.response_ranges = ranges
                else:
                    found = [
                        Anchor(file=body, start=0, end=len(body.lines) - 1, anchor_id="")
                    ]
                # The first passage answers to `-prompt`/`-response`; a second
                # or third is `-prompt2`, `-prompt3`, so each is quotable.
                for n, anchor in enumerate(found, start=1):
                    aid = f"{base}-{side}" + ("" if n == 1 else str(n))
                    anchor.anchor_id = aid
                    anchors[aid] = anchor

            for extra in tconf.get("anchors") or []:
                if not extra.get("id"):
                    warnings.append(f"{key}: `anchors` entry without an id is a no-op")
                    continue
                side = extra.get("in", "prompt")
                body = turn.prompt if side == "prompt" else turn.response
                if body is None:
                    warnings.append(f"{key}: anchor {extra['id']!r} names a missing {side}")
                    continue
                anchor = resolve_anchor(body, extra, warnings)
                aid = slug(extra["id"])
                if aid in anchors:
                    warnings.append(f"duplicate id {aid!r}; later definition wins")
                anchor.anchor_id = aid
                anchors[aid] = anchor

    for key in per_turn:
        if key not in seen:
            warnings.append(f"turns: {key!r} is not in the transcript")
    known = {t.id for t in threads}
    for key in per_thread:
        if key not in known:
            warnings.append(f"threads: {key!r} is not in the transcript")


def build_stream(
    threads: list[Thread], spec: dict, anchors: dict, warnings: list[str]
) -> tuple[list[Turn], list[AppendixChapter]]:
    """One chronological stream across every thread, cut into titled runs.

    Turns without a timestamp keep the order they were collected in, after
    everything that has one, rather than sorting to the front.
    """
    turns = [t for thread in threads for t in thread.turns]
    turns.sort(key=lambda t: (t.at == "", t.at))

    where = {f"{t.thread}:{t.id}": i for i, t in enumerate(turns)}
    conf = spec.get("appendix") or {}
    chapters: list[AppendixChapter] = []
    for ci, raw in enumerate(conf.get("chapters") or []):
        at = raw.get("at")
        if at is None:
            warnings.append("appendix chapter is missing `at`")
            continue
        if at not in where:
            warnings.append(f"appendix chapter starts at {at!r}, which is not in the transcript")
            continue
        cid = slug(raw["id"]) if raw.get("id") else f"ac{ci}"
        chapters.append(
            AppendixChapter(
                title=raw.get("title", "") or "",
                note_md=raw.get("note", "") or "",
                anchor_id=cid,
                start=where[at],
            )
        )
    chapters.sort(key=lambda c: c.start)
    for chapter in chapters:
        aid = f"ac-{chapter.anchor_id}"
        if aid not in anchors:
            anchors[aid] = anchors.get(turns[chapter.start].anchor_id)
    return turns, chapters


def build_document(files: list[FileDiff], spec: dict, meta: dict) -> Document:
    warnings: list[str] = []
    ordered, chapter_marks = order_and_chapter(files, spec, warnings)
    categories = normalize_categories(spec.get("categories"), warnings)
    collapse_globs = spec.get("collapse") or []
    per_file = spec.get("files") or {}

    # A `files:` key addresses a file by its qualified key, or by bare path when
    # that is unambiguous across sources.
    by_key: dict[str, FileDiff] = {}
    for f in ordered:
        by_key[f.key] = f
    bare: dict[str, list[FileDiff]] = {}
    for f in ordered:
        bare.setdefault(f.path, []).append(f)

    def lookup(name: str) -> FileDiff | None:
        if name in by_key:
            return by_key[name]
        hits = bare.get(name) or []
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            warnings.append(
                f"files: {name!r} is ambiguous across sources "
                f"({', '.join(sorted(h.key for h in hits))}); qualify it"
            )
        return None

    for name in per_file:
        if lookup(name) is None and not any(h for h in (bare.get(name) or [])):
            warnings.append(f"files: {name!r} is not in the diff (or was hidden)")

    conf_for = {}
    for name, conf in per_file.items():
        f = lookup(name)
        if f is not None:
            conf_for[id(f)] = conf

    anchors: dict[str, Anchor] = {}
    out: list[AnnotatedFile] = []

    def register(anchor: Anchor, requested: str | None, fallback: str) -> str:
        aid = slug(requested) if requested else fallback
        if aid in anchors:
            warnings.append(f"duplicate id {aid!r}; later definition wins")
        anchor.anchor_id = aid
        anchors[aid] = anchor
        return aid

    for fi, fd in enumerate(ordered):
        conf = conf_for.get(id(fd)) or {}
        af = AnnotatedFile(
            diff=fd,
            title=conf.get("title", ""),
            note_md=conf.get("note", "") or "",
            collapsed=bool(conf.get("collapsed", _matches_any(fd, collapse_globs))),
            anchor_id=f"f{fi}",
        )
        whole = Anchor(file=fd, start=0, end=max(0, len(fd.lines) - 1), anchor_id=af.anchor_id)
        anchors[af.anchor_id] = whole
        # Keyed by source, so two repos with the same path do not collide.
        auto = slug("file:" + fd.key)
        if auto in anchors:
            warnings.append(f"two files share the automatic id {auto!r}")
        anchors[auto] = whole

        for si, s in enumerate(conf.get("sections") or []):
            anchor = resolve_anchor(fd, s, warnings)
            aid = register(anchor, s.get("id"), f"f{fi}s{si}")
            af.sections.append(
                Section(
                    title=s.get("title", ""),
                    note_md=s.get("note", "") or "",
                    anchor=anchor,
                    anchor_id=aid,
                )
            )

        for ni, note in enumerate(conf.get("notes") or []):
            anchor = resolve_anchor(fd, note, warnings)
            aid = register(anchor, note.get("id"), f"f{fi}n{ni}")
            af.notes.append(
                SideNote(text_md=note.get("text", "") or "", anchor=anchor, anchor_id=aid)
            )

        for a in conf.get("anchors") or []:
            anchor = resolve_anchor(fd, a, warnings)
            if not a.get("id"):
                warnings.append(f"{fd.key}: `anchors` entry without an id is a no-op")
                continue
            register(anchor, a["id"], "")

        out.append(af)

    chapters: list[Chapter] = []
    for ci, mark in enumerate(chapter_marks):
        cid = slug(mark["id"]) if mark["id"] else f"c{ci}"
        chapters.append(
            Chapter(
                title=mark["title"],
                note_md=mark["note"],
                anchor_id=cid,
                start=mark["start"],
            )
        )
        if mark["start"] < len(out):
            anchors[cid] = anchors[f"f{mark['start']}"]

    threads: list[Thread] = []
    turns: list[Turn] = []
    appendix_chapters: list[AppendixChapter] = []
    if meta.get("transcript"):
        threads = load_transcript(meta["transcript"], warnings)
        attach_threads(threads, spec, anchors, warnings)
        turns, appendix_chapters = build_stream(threads, spec, anchors, warnings)
    elif spec.get("turns") or spec.get("threads"):
        warnings.append("`turns:`/`threads:` need a `transcript:` to bind to")

    return Document(
        title=spec.get("title") or meta.get("title") or "Literate diff",
        subtitle=spec.get("subtitle", "") or "",
        plot_md=spec.get("plot", "") or "",
        files=out,
        anchors=anchors,
        meta=meta,
        chapters=chapters,
        warnings=warnings,
        categories=categories,
        threads=threads,
        turns=turns,
        appendix_chapters=appendix_chapters,
        appendix=spec.get("appendix") or {},
    )
