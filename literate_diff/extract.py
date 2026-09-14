"""`literate-diff extract`: read a built page back.

The page embeds its sidecar and every source's copy of record in a JSON data
block. That makes three things possible without the repositories: print a
layer as markdown with its quotes resolved, list every claim with its
evidence, and write the inputs to a directory the page can be rebuilt from.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from .model import Document
from .render import DATA_ID

# The header comment mentions the block's tag, so require the JSON to follow.
BLOCK_RE = re.compile(
    r'<script type="application/json" id="' + DATA_ID + r'">(\{.*?)</script>', re.S
)
COMMENT_RE = re.compile(r"<!--(.*?)-->", re.S)
MD_REF_RE = re.compile(r"\[([^\]]*)\]\((ld|ldq|ldc):#([^)]+)\)")


def read_data(path: str) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    m = BLOCK_RE.search(text)
    if not m:
        raise SystemExit(f"{path}: no #{DATA_ID} block; was it built with --no-embed?")
    return json.loads(m.group(1))


def read_about(path: str) -> str:
    text = Path(path).read_text(encoding="utf-8", errors="replace")[:20000]
    m = COMMENT_RE.search(text)
    return m.group(1).strip() if m else ""


def rebuild(data: dict) -> Document:
    """The document, from the embedded sidecar and sources alone."""
    from .render import render_document
    from .sidecar import build, parse_sidecar

    if not data.get("sidecar") and not data.get("sources"):
        raise SystemExit("this page was built with --no-embed; nothing to rebuild from")
    spec = parse_sidecar(data.get("sidecar") or "", "embedded sidecar")
    sources = dict(spec.get("sources") or {})
    for name, s in (data.get("sources") or {}).items():
        conf = dict(sources.get(name) or {})
        conf["type"] = s.get("type", "diff")
        conf.setdefault("label", s.get("label") or name)
        conf.setdefault("range", s.get("range") or "")
        files = s.get("files") or {}
        if files:
            fname, text = next(iter(files.items()))
            conf["text"] = text
            conf["file"] = fname
            conf.pop("diff", None)
            conf.pop("repo", None)
        sources[name] = conf
    spec["sources"] = sources
    spec.pop("transcript", None)
    doc = build(spec, base_dir=Path("."), cwd=Path("."), embed=False)
    render_document(doc, embed=False)
    return doc


def resolve_markdown(doc: Document, md: str) -> str:
    """Markdown with `ldq:` quotes expanded to the rows they name, and `ld:`
    and `ldc:` references left as bracketed ids a reader can follow."""

    def sub(m: re.Match) -> str:
        label, scheme, target = m.group(1), m.group(2), m.group(3)
        if scheme == "ldc":
            return f"{label} [flags {target}]".strip()
        if target.startswith("cat-"):
            claim = next((c for c in getattr(doc, "claims", []) if c["id"] == target[4:]), None)
            if claim is not None:
                head = " ".join(claim["text"].split())[:80]
                return f"{label} [claim {target[4:]}: {head}…]".strip()
        anchor = doc.anchors.get(target)
        if anchor is None:
            return f"{label} [{target}: unknown id]".strip()
        if scheme == "ld":
            return f"{label} [see {target}]".strip() if label else f"[see {target}]"
        rows = anchor.file.lines[anchor.start : anchor.end + 1]
        quoted = "\n".join("> " + (r.text or "") for r in rows if r.kind != "hunk")
        head = f"> — {anchor.file.path}" + (f" ({anchor.file.kind})" if anchor.file.kind else "")
        return (f"{label}\n\n" if label else "\n\n") + head + "\n" + quoted + "\n\n"

    return MD_REF_RE.sub(sub, md)


def extract_main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="literate-diff extract",
                                description="Read a built page's layers, claims and sources back out.")
    p.add_argument("page", help="the built HTML file")
    what = p.add_mutually_exclusive_group()
    what.add_argument("--about", action="store_true", help="what the file is (the header comment)")
    what.add_argument("--layers", action="store_true", help="list the layers")
    what.add_argument("--layer", metavar="ID", help="one layer as markdown, quotes resolved")
    what.add_argument("--claims", action="store_true", help="every claim, as JSON lines")
    what.add_argument("--claim", metavar="ID", help="one claim and what it cites")
    what.add_argument("--sidecar", action="store_true", help="the annotation YAML")
    what.add_argument("--source", metavar="NAME", help="one source's copy of record")
    what.add_argument("--to", metavar="DIR", help="write sidecar and sources to a directory")
    args = p.parse_args(argv)

    if args.about:
        print(read_about(args.page))
        return 0
    data = read_data(args.page)

    if args.layers or not any((args.layer, args.claims, args.claim, args.sidecar, args.source, args.to)):
        for l in data.get("layers") or []:
            meta = " · ".join(x for x in (l.get("audience"), l.get("budget")) if x)
            print(f"{l['id']:<16} {l['kind']:<7} {l.get('title') or ''}" + (f"  ({meta})" if meta else ""))
        return 0

    if args.sidecar:
        sys.stdout.write(data.get("sidecar") or "")
        return 0

    if args.source:
        s = (data.get("sources") or {}).get(args.source)
        if s is None:
            raise SystemExit(f"no source {args.source!r}; have: {', '.join(data.get('sources') or {})}")
        for text in (s.get("files") or {}).values():
            sys.stdout.write(text)
        return 0

    if args.claims:
        for c in data.get("claims") or []:
            print(json.dumps(c, ensure_ascii=False))
        return 0

    if args.to:
        return write_inputs(data, Path(args.to))

    doc = rebuild(data)
    if args.layer:
        layer = next((l for l in doc.layers if l.id == args.layer), None)
        if layer is None:
            raise SystemExit(f"no layer {args.layer!r}; have: {', '.join(l.id for l in doc.layers)}")
        if layer.is_prose:
            print(resolve_markdown(doc, layer.text_md))
        else:
            print(f"# {layer.title or layer.id}\n")
            for chapter in layer.chapters:
                print(f"## {chapter.title}\n")
                if chapter.note_md.strip():
                    print(resolve_markdown(doc, chapter.note_md) + "\n")
            for it in layer.items:
                head = it.title or it.unit.path
                print(f"- {it.key}" + (f": {head}" if head and head != it.key else ""))
                if it.note_md.strip():
                    print("  " + resolve_markdown(doc, it.note_md).replace("\n", "\n  "))
        return 0

    if args.claim:
        claim = next((c for c in data.get("claims") or [] if c["id"] == args.claim), None)
        if claim is None:
            raise SystemExit(f"no claim {args.claim!r}")
        print(json.dumps({k: v for k, v in claim.items() if k != "cites"}, ensure_ascii=False, indent=2))
        for target in claim.get("cites") or []:
            print(f"\n## cites {target}\n")
            print(resolve_markdown(doc, f"[](ldq:#{target})"))
        return 0
    return 0


def write_inputs(data: dict, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    (out / "sidecar.yaml").write_text(data.get("sidecar") or "", encoding="utf-8")
    spec = yaml.safe_load(data.get("sidecar") or "") or {}
    sources = dict(spec.get("sources") or {})
    src_dir = out / "sources"
    for name, s in (data.get("sources") or {}).items():
        conf = dict(sources.get(name) or {})
        conf["type"] = s.get("type", "diff")
        conf["label"] = s.get("label") or name
        if s.get("range"):
            conf["range"] = s["range"]
        for fname, text in (s.get("files") or {}).items():
            src_dir.mkdir(exist_ok=True)
            (src_dir / fname).write_text(text, encoding="utf-8")
            rel = f"sources/{fname}"
            if conf["type"] == "diff":
                conf.pop("repo", None)
                conf.pop("pathspec", None)
                conf["diff"] = rel
            else:
                conf["file"] = rel
        sources[name] = conf
    spec["sources"] = sources
    spec.pop("transcript", None)
    (out / "build.yaml").write_text(
        "# Rebuild: literate-diff -a build.yaml -o page.html  (run from this directory)\n"
        + yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=88),
        encoding="utf-8",
    )
    print(f"wrote {out}/sidecar.yaml, {out}/build.yaml and {len(list(src_dir.glob('*')) if src_dir.exists() else [])} source files",
          file=sys.stderr)
    return 0
