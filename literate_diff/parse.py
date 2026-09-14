"""Parse unified git diff text into a structured model."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import Row, Unit

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")


class Line(Row):
    """One rendered row of a diff: a context/add/del line, or a hunk header."""


@dataclass(kw_only=True)
class FileDiff(Unit):
    """One file's diff. A unit, so anchors and references reach into it."""

    old_path: str | None = None
    new_path: str | None = None
    status: str = "modified"  # "modified" | "added" | "deleted" | "renamed"
    binary: bool = False
    additions: int = 0
    deletions: int = 0
    mode_note: str = ""
    key: str = ""

    def __post_init__(self):
        if not self.key:
            self.key = f"{self.source}:{self.path}" if self.source else self.path

    def find_extra(self, at: str, from_index: int) -> int | None:
        """`+N` is line N on the new side, `-N` line N on the old side."""
        if (at.startswith("+") or at.startswith("-")) and at[1:].isdigit():
            want = int(at[1:])
            side = "new_no" if at[0] == "+" else "old_no"
            for i, line in enumerate(self.lines[from_index:], start=from_index):
                if getattr(line, side) == want:
                    return i
            return -1
        return None


def _strip_prefix(p: str) -> str:
    if p.startswith(("a/", "b/")):
        return p[2:]
    return p


def parse_diff(text: str, source: str = "") -> list[FileDiff]:
    """Parse `git diff` output. Returns files in the order they appear."""
    files: list[FileDiff] = []
    cur: FileDiff | None = None
    old_no = new_no = 0

    lines = text.split("\n")
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]

        if raw.startswith("diff --git "):
            rest = raw[len("diff --git ") :]
            old_p, new_p = _split_git_paths(rest)
            cur = FileDiff(
                path=_strip_prefix(new_p or old_p or "?"),
                old_path=_strip_prefix(old_p) if old_p else None,
                new_path=_strip_prefix(new_p) if new_p else None,
                status="modified",
                source=source,
                kind="diff",
            )
            files.append(cur)
            old_no = new_no = 0
            i += 1
            continue

        if cur is None:
            # Preamble (e.g. commit headers from `git show`); skip.
            i += 1
            continue

        if raw.startswith("new file mode"):
            cur.status = "added"
        elif raw.startswith("deleted file mode"):
            cur.status = "deleted"
        elif raw.startswith("rename from "):
            cur.status = "renamed"
            cur.old_path = raw[len("rename from ") :]
        elif raw.startswith("rename to "):
            cur.status = "renamed"
            cur.new_path = raw[len("rename to ") :]
            cur.path = cur.new_path
            cur.key = f"{cur.source}:{cur.path}" if cur.source else cur.path
        elif raw.startswith("old mode ") or raw.startswith("new mode "):
            cur.mode_note = (cur.mode_note + " " + raw).strip()
        elif raw.startswith("Binary files ") or raw.startswith("GIT binary patch"):
            cur.binary = True
            cur.lines.append(Line("message", "Binary file not shown"))
            # Skip the binary payload until the next file.
            while i + 1 < n and not lines[i + 1].startswith("diff --git "):
                i += 1
        elif raw.startswith("--- ") or raw.startswith("+++ ") or raw.startswith("index "):
            pass
        elif raw.startswith("@@"):
            m = HUNK_RE.match(raw)
            if m:
                old_no = int(m.group(1))
                new_no = int(m.group(3))
                cur.lines.append(Line("hunk", m.group(5).rstrip()))
        elif raw.startswith("+"):
            cur.lines.append(Line("add", raw[1:], None, new_no))
            new_no += 1
            cur.additions += 1
        elif raw.startswith("-"):
            cur.lines.append(Line("del", raw[1:], old_no, None))
            old_no += 1
            cur.deletions += 1
        elif raw.startswith(" "):
            cur.lines.append(Line("context", raw[1:], old_no, new_no))
            old_no += 1
            new_no += 1
        elif raw.startswith("\\"):
            # "\ No newline at end of file"
            cur.lines.append(Line("message", raw[2:]))
        elif raw == "":
            pass
        i += 1

    for f in files:
        for idx, line in enumerate(f.lines):
            line.index = idx
    return files


def _split_git_paths(rest: str) -> tuple[str | None, str | None]:
    """Split the `a/x b/y` tail of a `diff --git` line, handling quoted paths."""
    if rest.startswith('"'):
        # Quoted paths: "a/x" "b/y"
        parts = re.findall(r'"((?:[^"\\]|\\.)*)"', rest)
        if len(parts) == 2:
            return parts[0], parts[1]
    # Unquoted. Paths may contain spaces, so find the split by trying each
    # position where a `b/` could begin and checking the halves agree.
    toks = rest.split(" ")
    for cut in range(1, len(toks)):
        left = " ".join(toks[:cut])
        right = " ".join(toks[cut:])
        if left.startswith("a/") and right.startswith("b/"):
            if left[2:] == right[2:] or cut == len(toks) - 1:
                return left, right
    half = len(toks) // 2
    return " ".join(toks[:half]), " ".join(toks[half:])
