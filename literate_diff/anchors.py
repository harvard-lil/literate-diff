"""Resolve `at:`/`nth:`/`span:`/`through:` specs to row ranges in a unit.

The grammar is the same for every kind of source: a substring, a `/regex/`,
or `@N` for a row index. A unit may add forms of its own through
`Unit.find_extra` (the diff plugin's `+N` and `-N` line numbers).
"""

from __future__ import annotations

import re

from .model import Anchor, AnnotationError, Unit


def resolve_anchor(unit: Unit, spec: dict | str, warnings: list[str]) -> Anchor:
    """Resolve an `at`/`span`/`through` spec to a row range in `unit`."""
    if isinstance(spec, str):
        spec = {"at": spec}
    at = spec.get("at")
    if at is None:
        raise AnnotationError(f"{unit.key}: annotation is missing `at`")

    start = find_row(unit, at, int(spec.get("nth", 1)), warnings)
    end = start

    through = spec.get("through")
    span = spec.get("span")
    if through is not None:
        end = find_row(unit, through, 1, warnings, from_index=start)
    elif span is not None:
        end = min(start + int(span) - 1, len(unit.lines) - 1)

    if end < start:
        end = start
    return Anchor(file=unit, start=start, end=end, anchor_id="")


def find_row(unit: Unit, at, nth: int, warnings: list[str], from_index: int = 0) -> int:
    rows = unit.lines
    if not rows:
        raise AnnotationError(f"{unit.key}: unit has no rows to anchor to")

    if isinstance(at, int):
        return _clamp(at, rows)

    at = str(at)

    if at.startswith("@"):
        return _clamp(int(at[1:]), rows)

    extra = unit.find_extra(at, from_index)
    if extra is not None:
        if extra >= 0:
            return extra
        warnings.append(f"{unit.key}: no line {at}; anchoring at start")
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
        # the intended one. `nth: 1` is the default restated, not evidence the
        # author counted the matches; only nth >= 2 shows a deliberate choice.
        if len(hits) > 1 and nth == 1:
            where = rows[hits[0]].new_no or rows[hits[0]].old_no
            place = f"line {where}" if where else f"row {hits[0]}"
            warnings.append(
                f"{unit.key}: {at!r} matches {len(hits)} rows; using the first "
                f"({place}). Narrow the pattern or set `nth` to pin it."
            )
        return hits[nth - 1]

    warnings.append(
        f"{unit.key}: no match for {at!r}"
        + (f" (occurrence {nth}, {len(hits)} found)" if nth > 1 else "")
        + "; anchoring at start"
    )
    return from_index


def _clamp(i: int, rows: list) -> int:
    return max(0, min(i, len(rows) - 1))
