"""Load the annotation sidecar and bind it to parsed diff lines."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field

import yaml

from .parse import FileDiff, Line


class AnnotationError(Exception):
    pass


@dataclass
class Anchor:
    """A resolved range of diff rows within one file."""

    file: FileDiff
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
    warnings: list[str] = field(default_factory=list)


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


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, p) for p in patterns)


def order_files(files: list[FileDiff], spec: dict, warnings: list[str]) -> list[FileDiff]:
    """Apply `hide` and `order`. Files not named by `order` land at the `*` slot."""
    hide = spec.get("hide") or []
    kept = [f for f in files if not _matches_any(f.path, hide)]

    order = spec.get("order")
    if not order:
        return kept

    remaining = list(kept)
    result: list[FileDiff] = []
    star_at: int | None = None
    for pat in order:
        if pat == "*":
            star_at = len(result)
            continue
        picked = [f for f in remaining if fnmatch.fnmatch(f.path, pat)]
        if not picked:
            warnings.append(f"order: no file matched {pat!r}")
        for f in picked:
            remaining.remove(f)
            result.append(f)
    if star_at is None:
        result.extend(remaining)
    else:
        result[star_at:star_at] = remaining
    return result


# --- anchor resolution -------------------------------------------------------


def resolve_anchor(file: FileDiff, spec: dict | str, warnings: list[str]) -> Anchor:
    """Resolve an `at`/`span`/`through` spec to a row range in `file`."""
    if isinstance(spec, str):
        spec = {"at": spec}
    at = spec.get("at")
    if at is None:
        raise AnnotationError(f"{file.path}: annotation is missing `at`")

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
    file: FileDiff, at, nth: int, warnings: list[str], from_index: int = 0
) -> int:
    """Locate a diff row. Supports substring, /regex/, +N, -N, and @N forms."""
    rows = file.lines
    if not rows:
        raise AnnotationError(f"{file.path}: file has no diff rows to anchor to")

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
        warnings.append(f"{file.path}: no line {at}; anchoring at start")
        return from_index

    if len(at) > 1 and at.startswith("/") and at.endswith("/"):
        pat = re.compile(at[1:-1])
        test = lambda s: pat.search(s) is not None  # noqa: E731
    else:
        test = lambda s: at in s  # noqa: E731

    hits = 0
    for i, line in enumerate(rows[from_index:], start=from_index):
        if line.kind in ("add", "del", "context", "hunk") and test(line.text):
            hits += 1
            if hits >= nth:
                return i
    warnings.append(
        f"{file.path}: no match for {at!r}"
        + (f" (occurrence {nth})" if nth > 1 else "")
        + "; anchoring at start"
    )
    return from_index


def _clamp(i: int, rows: list[Line]) -> int:
    return max(0, min(i, len(rows) - 1))


# --- assembly ----------------------------------------------------------------


def build_document(files: list[FileDiff], spec: dict, meta: dict) -> Document:
    warnings: list[str] = []
    ordered = order_files(files, spec, warnings)
    collapse_globs = spec.get("collapse") or []
    per_file = spec.get("files") or {}

    for name in per_file:
        if not any(f.path == name for f in ordered):
            warnings.append(f"files: {name!r} is not in the diff (or was hidden)")

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
        conf = per_file.get(fd.path) or {}
        af = AnnotatedFile(
            diff=fd,
            title=conf.get("title", ""),
            note_md=conf.get("note", "") or "",
            collapsed=bool(conf.get("collapsed", _matches_any(fd.path, collapse_globs))),
            anchor_id=f"f{fi}",
        )
        whole = Anchor(file=fd, start=0, end=max(0, len(fd.lines) - 1), anchor_id=af.anchor_id)
        anchors[af.anchor_id] = whole
        anchors[slug("file:" + fd.path)] = whole

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
                warnings.append(f"{fd.path}: `anchors` entry without an id is a no-op")
                continue
            register(anchor, a["id"], "")

        out.append(af)

    return Document(
        title=spec.get("title") or meta.get("title") or "Literate diff",
        subtitle=spec.get("subtitle", "") or "",
        plot_md=spec.get("plot", "") or "",
        files=out,
        anchors=anchors,
        meta=meta,
        warnings=warnings,
    )
