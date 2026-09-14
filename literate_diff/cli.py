"""Command line entry point: build, collect, extract, lint."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .collect import TOOLS, collect, local_zone, to_yaml
from .model import AnnotationError
from .render import render_document
from .sidecar import build, load_annotations
from .sources.diff import repo_name


def parse_source_flag(value: str) -> tuple[str, dict]:
    """`name=path/to/repo@range` -> (name, {repo, range})."""
    if "=" not in value:
        raise SystemExit(f"--source must look like name=repo@range (got {value!r})")
    name, spec = value.split("=", 1)
    if "@" not in spec:
        raise SystemExit(f"--source {name} is missing @range (got {spec!r})")
    repo, rev_range = spec.rsplit("@", 1)
    return name.strip(), {"repo": repo, "range": rev_range, "type": "diff"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="literate-diff",
        description="Build a layered, self-describing HTML document over a git "
        "diff, a conversation and other evidence, from a YAML sidecar.",
    )
    src = p.add_argument_group("input")
    src.add_argument("--repo", default=".", help="git repo to diff (default: cwd)")
    src.add_argument("--range", help="git range, e.g. prod...main or abc123..def456")
    src.add_argument("--diff", help="read a unified diff from a file instead of git ('-' for stdin)")
    src.add_argument("--pathspec", nargs="*", default=None, help="limit git diff to these paths")
    src.add_argument("-U", "--context", type=int, default=3, help="context lines")
    src.add_argument(
        "--source", action="append", metavar="NAME=REPO@RANGE",
        help="add a named repo to a multi-repo document; repeatable. "
        "Sources may also be declared in the annotation file.",
    )
    p.add_argument("-a", "--annotations", help="annotation YAML sidecar")
    p.add_argument("-o", "--out", default="literate-diff.html", help="output HTML path")
    p.add_argument("--outline", action="store_true",
                   help="print a starter annotation YAML for this diff instead of HTML")
    p.add_argument("--title", help="override the document title")
    p.add_argument("--transcript",
                   help="collected conversation YAML (overrides the sidecar's `transcript:`)")
    p.add_argument("--no-embed", action="store_true",
                   help="leave the sidecar and sources out of the file")
    p.add_argument("--strict", action="store_true", help="exit 1 on any warning")
    return p


def build_from_args(args) -> tuple:
    try:
        spec = load_annotations(args.annotations)
    except AnnotationError as e:
        raise SystemExit(str(e))

    cli: dict = {"context": args.context, "pathspec": args.pathspec}
    sources = {}
    for flag in args.source or []:
        name, conf = parse_source_flag(flag)
        sources[name] = conf
    has_sources = bool(sources) or bool(spec.get("sources"))
    if not has_sources:
        if args.diff:
            sources[""] = {"type": "diff", "diff": args.diff, "label": args.diff}
        elif args.range:
            sources[""] = {
                "type": "diff", "repo": args.repo, "range": args.range,
                "label": repo_name(args.repo), "pathspec": args.pathspec,
            }
            cli["default_title"] = f"{repo_name(args.repo)} {args.range}"
        else:
            return None, spec, None
    cli["sources"] = sources
    if args.transcript:
        cli["transcript"] = str(Path(args.transcript).resolve())
    if args.title:
        cli["title"] = args.title
    base_dir = Path(args.annotations).parent if args.annotations else Path(".")
    doc = build(spec, base_dir=base_dir, cwd=Path("."), cli=cli, embed=not args.no_embed)
    return doc, spec, cli


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "collect":
        return collect_main(argv[1:])
    if argv and argv[0] == "extract":
        from .extract import extract_main
        return extract_main(argv[1:])
    if argv and argv[0] == "lint":
        from .lint import lint_main
        return lint_main(argv[1:])

    p = build_parser()
    args = p.parse_args(argv)
    doc, spec, cli = build_from_args(args)
    if doc is None:
        p.error("give --range, --diff, at least one --source, or a sidecar with `sources:`")

    if args.outline:
        from .outline import make_outline
        print(make_outline(doc))
        return 0

    html = render_document(doc, embed=not args.no_embed)
    from .lint import lint_document
    lint_document(doc)

    out = Path(args.out)
    if out.parent != Path(""):
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    for w in doc.warnings:
        print(f"warning: {w}", file=sys.stderr)
    kb = len(html.encode("utf-8")) / 1024
    files = len(doc.files)
    turns = len(doc.turns)
    threads = len(doc.threads)
    convo = f", {turns} turns in {threads} threads" if turns else ""
    print(f"wrote {args.out} — {files} files{convo}, {kb:,.0f} KB", file=sys.stderr)
    if args.strict and doc.warnings:
        return 1
    return 0


def collect_main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="literate-diff collect",
        description="Collect local agent sessions into a transcript file. "
        "Read the result before sharing it: it quotes whatever was on screen.",
    )
    p.add_argument("--repo", default=".", help="project whose sessions to read")
    p.add_argument("--tool", action="append", dest="tools", choices=TOOLS,
                   help="whose logs to read: claude-code (~/.claude/projects) or codex "
                   "(~/.codex/sessions); repeatable (default: claude-code)")
    p.add_argument("--title", action="append", dest="titles",
                   help="only sessions whose title contains this; repeatable")
    p.add_argument("--session", action="append", dest="sessions", help="session id (or prefix)")
    p.add_argument("--since", default="", help="drop turns before this ISO date")
    p.add_argument("--merge-by-title", action="store_true",
                   help="sessions sharing a title become one thread, in timestamp order")
    p.add_argument("--home", default=str(Path.home()), help="home directory to read")
    p.add_argument("--timezone", help="clock to show times on and derive turn ids from "
                   "(default: this machine's). Logs are stamped UTC.")
    p.add_argument("-o", "--out", required=True, help="transcript YAML to write")
    args = p.parse_args(argv)

    warnings: list[str] = []
    zone = args.timezone or local_zone()
    threads = collect(
        repo=args.repo, zone=zone, home=Path(args.home), titles=args.titles,
        sessions=args.sessions, since=args.since, merge_by_title=args.merge_by_title,
        warnings=warnings, tools=args.tools or ["claude-code"],
    )
    if not threads:
        raise SystemExit("no sessions matched")

    text = to_yaml(threads, {
        "collected": datetime.now().astimezone().isoformat(timespec="seconds"),
        "timezone": zone,
    })
    out = Path(args.out)
    if out.parent != Path(""):
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")

    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    turns = sum(len(t.turns) for t in threads)
    kb = len(text.encode("utf-8")) / 1024
    print(f"wrote {args.out} — {len(threads)} threads, {turns} turns, {kb:,.0f} KB", file=sys.stderr)
    return 0
