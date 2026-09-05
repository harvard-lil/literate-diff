"""Command line entry point."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .annotate import AnnotationError, build_document, load_annotations
from .collect import collect, local_zone, to_yaml
from .parse import parse_diff
from .render import render_document


def git_diff(repo: str, rev_range: str, context: int, pathspec) -> str:
    cmd = [
        "git",
        "-C",
        repo,
        "diff",
        f"--unified={context}",
        "--no-color",
        "--no-ext-diff",
        rev_range,
    ]
    if pathspec:
        cmd += ["--"] + list(pathspec)
    out = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if out.returncode != 0:
        raise SystemExit(f"git diff failed in {repo}:\n{out.stderr.strip()}")
    return out.stdout


def repo_name(repo: str) -> str:
    top = subprocess.run(
        ["git", "-C", repo, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return Path(top).name if top else Path(repo).resolve().name


def read_patch(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8", errors="replace")


def parse_source_flag(value: str) -> tuple[str, dict]:
    """`name=path/to/repo@range` -> (name, {repo, range})."""
    if "=" not in value:
        raise SystemExit(f"--source must look like name=repo@range (got {value!r})")
    name, spec = value.split("=", 1)
    if "@" not in spec:
        raise SystemExit(f"--source {name} is missing @range (got {spec!r})")
    repo, rev_range = spec.rsplit("@", 1)
    return name.strip(), {"repo": repo, "range": rev_range}


def collect_sources(args, spec: dict) -> tuple[list, dict]:
    """Parse every configured source into one ordered list of files."""
    sources = dict(spec.get("sources") or {})
    for flag in args.source or []:
        name, conf = parse_source_flag(flag)
        sources[name] = conf

    # No named sources: the single-repo form, where files keep bare paths.
    if not sources:
        if args.diff:
            text = read_patch(args.diff)
            return parse_diff(text), {"sources": [{"name": "", "label": args.diff}]}
        text = git_diff(args.repo, args.range, args.context, args.pathspec)
        return parse_diff(text), {
            "range": args.range,
            "repo": repo_name(args.repo),
            "sources": [
                {"name": "", "label": repo_name(args.repo), "range": args.range}
            ],
        }

    files = []
    described = []
    for name, conf in sources.items():
        if not isinstance(conf, dict):
            raise SystemExit(f"sources.{name} must be a mapping")
        if conf.get("diff"):
            text = read_patch(conf["diff"])
            label = conf.get("label") or name
            rev_range = conf.get("range", "")
        else:
            if not conf.get("repo") or not conf.get("range"):
                raise SystemExit(f"sources.{name} needs `repo` and `range` (or `diff`)")
            text = git_diff(
                conf["repo"],
                conf["range"],
                conf.get("context", args.context),
                conf.get("pathspec", args.pathspec),
            )
            label = conf.get("label") or repo_name(conf["repo"])
            rev_range = conf["range"]
        found = parse_diff(text, source=name)
        if not found:
            print(f"warning: source {name!r} contributed no files", file=sys.stderr)
        files.extend(found)
        described.append(
            {
                "name": name,
                "label": label,
                "range": rev_range,
                "repo": conf.get("repo", conf.get("diff", "")),
            }
        )

    return files, {"sources": described}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "collect":
        return collect_main(argv[1:])

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
    src.add_argument(
        "--source",
        action="append",
        metavar="NAME=REPO@RANGE",
        help="add a named repo to a multi-repo document; repeatable. "
        "Sources may also be declared in the annotation file.",
    )

    p.add_argument("-a", "--annotations", help="annotation YAML sidecar")
    p.add_argument("-o", "--out", default="literate-diff.html", help="output HTML path")
    p.add_argument(
        "--outline",
        action="store_true",
        help="print a starter annotation YAML for this diff instead of HTML",
    )
    p.add_argument("--title", help="override the document title")
    p.add_argument(
        "--transcript",
        help="collected conversation YAML for the appendix (overrides the "
        "sidecar's `transcript:`)",
    )

    args = p.parse_args(argv)

    try:
        spec = load_annotations(args.annotations)
    except AnnotationError as e:
        raise SystemExit(str(e))

    has_sources = bool(args.source) or bool(spec.get("sources"))
    if not has_sources and not args.diff and not args.range:
        p.error("give --range, --diff, or at least one --source")

    files, meta = collect_sources(args, spec)
    if not files:
        raise SystemExit("no files found in the diff")

    # A `transcript:` in the sidecar is relative to the sidecar, which is where
    # the collected file sits; one on the command line is relative to the cwd.
    transcript = args.transcript
    if not transcript and spec.get("transcript"):
        base = Path(args.annotations).parent if args.annotations else Path(".")
        transcript = str(base / spec["transcript"])
    if transcript:
        if not Path(transcript).is_file():
            raise SystemExit(f"transcript not found: {transcript}")
        meta["transcript"] = transcript

    if args.outline:
        print(make_outline(files, meta))
        return 0

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
    turns = sum(len(t.turns) for t in doc.threads)
    convo = f", {turns} turns in {len(doc.threads)} threads" if turns else ""
    print(
        f"wrote {args.out} — {len(doc.files)} files{convo}, {kb:,.0f} KB",
        file=sys.stderr,
    )
    return 0


def collect_main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="literate-diff collect",
        description="Collect local agent sessions into a transcript file. "
        "Read the result before sharing it: it quotes whatever was on screen.",
    )
    p.add_argument("--repo", default=".", help="project whose sessions to read")
    p.add_argument(
        "--title",
        action="append",
        dest="titles",
        help="only sessions whose title contains this; repeatable",
    )
    p.add_argument(
        "--session", action="append", dest="sessions", help="session id (or prefix)"
    )
    p.add_argument("--since", default="", help="drop turns before this ISO date")
    p.add_argument(
        "--merge-by-title",
        action="store_true",
        help="sessions sharing a title become one thread, in timestamp order",
    )
    p.add_argument("--home", default=str(Path.home()), help="home directory to read")
    p.add_argument(
        "--timezone",
        help="clock to show times on and derive turn ids from "
        "(default: this machine's). Logs are stamped UTC.",
    )
    p.add_argument("-o", "--out", required=True, help="transcript YAML to write")
    args = p.parse_args(argv)

    warnings: list[str] = []
    zone = args.timezone or local_zone()
    threads = collect(
        repo=args.repo,
        zone=zone,
        home=Path(args.home),
        titles=args.titles,
        sessions=args.sessions,
        since=args.since,
        merge_by_title=args.merge_by_title,
        warnings=warnings,
    )
    if not threads:
        raise SystemExit("no sessions matched")

    text = to_yaml(
        threads,
        {
            "collected": datetime.now().astimezone().isoformat(timespec="seconds"),
            "timezone": zone,
        },
    )
    out = Path(args.out)
    if out.parent != Path(""):
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")

    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    turns = sum(len(t.turns) for t in threads)
    kb = len(text.encode("utf-8")) / 1024
    print(
        f"wrote {args.out} — {len(threads)} threads, {turns} turns, {kb:,.0f} KB",
        file=sys.stderr,
    )
    return 0


def make_outline(files, meta) -> str:
    """Emit a YAML skeleton listing every file, ready to be filled in."""
    described = meta.get("sources") or []
    multi = len([d for d in described if d["name"]]) > 0

    lines = [
        f"title: {meta.get('repo', 'Changes')} {meta.get('range', '')}".rstrip(),
        'subtitle: ""',
        "",
        "plot: |",
        "  Why this batch of commits exists, and what the reader is about to see.",
        "",
    ]

    if multi:
        lines.append("# Files are addressed as `source:path`.")
        lines.append("sources:")
        for d in described:
            lines.append(f"  {d['name']}:")
            lines.append(f"    repo: {d.get('repo', '?')}")
            lines.append(f"    range: {d.get('range', '?')}")
        lines.append("")

    lines += [
        "# Globs work; use `hide` to drop generated files, `collapse` to fold them.",
        "hide: []",
        "collapse: []",
        "",
    ]

    if multi:
        lines += [
            "# Chapters cut the order into titled runs. '*' takes the remainder.",
            "chapters:",
            '  - title: ""',
            "    note: |",
            "      ",
            "    files:",
        ]
        for f in files:
            lines.append(f"      - {yaml_key(f.key)}")
        lines += ["      - '*'", ""]
    else:
        lines += [
            "# Files render in this order. '*' is everything not named above.",
            "order:",
        ]
        for f in files:
            lines.append(f"  - {yaml_key(f.key)}")
        lines += ["  - '*'", ""]

    lines.append("files:")
    for f in files:
        lines += [
            f"  {yaml_key(f.key)}:",
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
