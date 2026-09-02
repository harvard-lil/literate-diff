"""Command line entry point."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .annotate import AnnotationError, build_document, load_annotations
from .parse import parse_diff
from .render import render_document


def read_diff(args) -> tuple[str, dict]:
    """Return (diff text, metadata) from either --diff or a git range."""
    if args.diff:
        text = sys.stdin.read() if args.diff == "-" else Path(args.diff).read_text(
            encoding="utf-8", errors="replace"
        )
        return text, {"source": args.diff}

    cmd = [
        "git",
        "-C",
        args.repo,
        "diff",
        f"--unified={args.context}",
        "--no-color",
        "--no-ext-diff",
        args.range,
    ]
    if args.pathspec:
        cmd += ["--"] + args.pathspec
    out = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if out.returncode != 0:
        raise SystemExit(f"git diff failed:\n{out.stderr.strip()}")

    name = subprocess.run(
        ["git", "-C", args.repo, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return out.stdout, {"range": args.range, "repo": Path(name).name if name else ""}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="literate-diff",
        description="Turn a git diff plus a YAML annotation sidecar into a "
        "shareable single-file HTML narrative.",
    )
    src = p.add_argument_group("input")
    src.add_argument("--repo", default=".", help="git repo to diff (default: cwd)")
    src.add_argument(
        "--range", help="git range, e.g. prod...main or abc123..def456"
    )
    src.add_argument(
        "--diff", help="read a unified diff from a file instead of git ('-' for stdin)"
    )
    src.add_argument(
        "--pathspec", nargs="*", default=None, help="limit git diff to these paths"
    )
    src.add_argument("-U", "--context", type=int, default=3, help="context lines")

    p.add_argument("-a", "--annotations", help="annotation YAML sidecar")
    p.add_argument("-o", "--out", default="literate-diff.html", help="output HTML path")
    p.add_argument(
        "--outline",
        action="store_true",
        help="print a starter annotation YAML for this diff instead of HTML",
    )
    p.add_argument("--title", help="override the document title")

    args = p.parse_args(argv)
    if not args.diff and not args.range:
        p.error("give either --range or --diff")

    diff_text, meta = read_diff(args)
    files = parse_diff(diff_text)
    if not files:
        raise SystemExit("no files found in the diff")

    if args.outline:
        print(make_outline(files, meta))
        return 0

    try:
        spec = load_annotations(args.annotations)
    except AnnotationError as e:
        raise SystemExit(str(e))
    if args.title:
        spec["title"] = args.title

    doc = build_document(files, spec, meta)
    html = render_document(doc)
    out = Path(args.out)
    if out.parent != Path(""):
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    for w in doc.warnings:
        print(f"warning: {w}", file=sys.stderr)
    kb = len(html.encode("utf-8")) / 1024
    print(
        f"wrote {args.out} — {len(doc.files)} files, {kb:,.0f} KB",
        file=sys.stderr,
    )
    return 0


def make_outline(files, meta) -> str:
    """Emit a YAML skeleton listing every file, ready to be filled in."""
    lines = [
        f"title: {meta.get('repo', 'Changes')} {meta.get('range', '')}".rstrip(),
        "subtitle: \"\"",
        "",
        "plot: |",
        "  Why this batch of commits exists, and what the reader is about to see.",
        "",
        "# Files render in this order. '*' is everything not named above.",
        "# Globs work; use `hide` to drop generated files, `collapse` to fold them.",
        "hide: []",
        "collapse: []",
        "order:",
    ]
    for f in files:
        lines.append(f"  - {yaml_key(f.path)}")
    lines += ["  - '*'", "", "files:"]
    for f in files:
        lines += [
            f"  {yaml_key(f.path)}:",
            f"    # {f.status}, +{f.additions} -{f.deletions}",
            "    note: |",
            "      ",
            "    sections: []",
            "    notes: []",
            "",
        ]
    return "\n".join(lines)


def yaml_key(path: str) -> str:
    return f'"{path}"' if any(c in path for c in ":#{}[]," ) else path
