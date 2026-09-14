"""Checks on the prose of a document that a build cannot make from anchors
alone: writing that describes the document instead of the subject, layers
over their budget, claims with nothing behind them.

Run at build time (the findings join the warnings) and as
`literate-diff lint notes.yaml`.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .model import Document

# Sentences whose subject is the document rather than the work. A document
# that says "this section traces how the work happened" has spent its first
# sentence on itself.
SELF_REFERENCE = [
    re.compile(r"^\s*This\s+(?:section|document|page|write-?up|report|appendix|chapter|summary|list)\b", re.I),
    re.compile(r"^\s*(?:In|For)\s+this\s+(?:section|document|draft)\b", re.I),
    re.compile(r"\b(?:since|from|in)\s+the\s+(?:last|previous|earlier)\s+draft\b", re.I),
    re.compile(r"^\s*(?:Below|Above)\b", re.I),
    re.compile(r"\bthe reader\b", re.I),
    re.compile(r"\b(?:see|described|listed|discussed)\s+(?:below|above)\b", re.I),
]

WORDS_PER_MINUTE = 200
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
FENCE = re.compile(r"```.*?```", re.S)
MARKER = re.compile(r"^\s*\{[^}]*\}\s*$", re.M)


def budget_words(budget: str) -> int | None:
    """`400 words` or `5 minutes` -> a word count; None if unreadable."""
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(\w+)", budget or "")
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2).lower()
    if unit.startswith("word"):
        return int(n)
    if unit.startswith("min"):
        return int(n * WORDS_PER_MINUTE)
    if unit.startswith(("hour", "hr")):
        return int(n * 60 * WORDS_PER_MINUTE)
    if unit.startswith("sec"):
        return int(n / 60 * WORDS_PER_MINUTE)
    return None


def prose_sentences(text: str) -> list[str]:
    text = FENCE.sub("", text)
    text = MARKER.sub("", text)
    out = []
    for para in re.split(r"\n\s*\n", text):
        para = re.sub(r"^\s*(?:#+|[-*]|\d+\.)\s*", "", para.strip(), flags=re.M)
        para = " ".join(line.strip() for line in para.split("\n"))
        for s in SENTENCE_END.split(para):
            s = s.strip()
            if s:
                out.append(s)
    return out


def word_count(text: str) -> int:
    text = FENCE.sub("", text)
    return len(re.findall(r"\b\w[\w'-]*\b", text))


def lint_document(doc: Document) -> list[str]:
    """Findings, also appended to `doc.warnings`."""
    found: list[str] = []
    for layer in doc.layers:
        if not layer.is_prose or not layer.text_md.strip():
            continue
        label = f"layer {layer.id!r}"
        for s in prose_sentences(layer.text_md):
            for pat in SELF_REFERENCE:
                if pat.search(s):
                    excerpt = s if len(s) <= 90 else s[:87].rstrip() + "…"
                    found.append(f"{label}: writes about the document rather than the work: \"{excerpt}\"")
                    break
        limit = budget_words(layer.budget)
        if limit:
            n = word_count(layer.text_md)
            if n > limit:
                found.append(f"{label}: {n} words against a budget of {layer.budget} (~{limit} words)")
    found += completeness(doc)
    doc.warnings.extend(found)
    return found


def completeness(doc: Document) -> list[str]:
    """A synthesis block is a comprehensive extraction of one facet. Two
    checks that fall out of that: a declared category with no items, and a
    defined term that no layer uses."""
    found: list[str] = []
    prose = "\n".join(l.text_md for l in doc.layers if l.is_prose)
    for cat in doc.categories:
        if not re.search(r"\{category:\s*" + re.escape(cat) + r"\s*\}", prose):
            found.append(f"category {cat!r} is declared but no list uses it")
    names: dict[str, str] = {}
    used: set[str] = set()
    for word, term in doc.terms.items():
        names[term["id"]] = term.get("term") or word
        if re.search(r"\b" + re.escape(word) + r"\b", prose, re.IGNORECASE):
            used.add(term["id"])
    for tid in sorted(set(names) - used):
        found.append(f"term {names[tid]!r} is defined but no prose layer uses it")
    return found


def lint_main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="literate-diff lint",
                                description="Check a sidecar's prose and claims without writing a page.")
    p.add_argument("annotations", help="annotation YAML sidecar")
    p.add_argument("--strict", action="store_true", help="exit 1 on any finding")
    args = p.parse_args(argv)

    from .render import render_document
    from .sidecar import build, load_annotations

    spec = load_annotations(args.annotations)
    doc = build(spec, base_dir=Path(args.annotations).parent, cwd=Path("."), embed=False)
    render_document(doc, embed=False)  # resolves references and claims
    lint_document(doc)
    for w in doc.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if not doc.warnings:
        print("clean", file=sys.stderr)
    return 1 if (args.strict and doc.warnings) else 0
