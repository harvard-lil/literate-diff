"""v1 names, kept for callers that know the old shape.

`build_document(files, spec, meta)` builds from already-parsed diff files;
new code should call `literate_diff.sidecar.build` with a sidecar mapping.
"""

from __future__ import annotations

from pathlib import Path

from .model import (  # noqa: F401
    Anchor, AnnotationError, Chapter, Document, Item, Section, SideNote, slug,
)
from .anchors import resolve_anchor  # noqa: F401
from .sidecar import arrange, load_annotations, normalize_categories  # noqa: F401
from .sidecar import build as _build
from .sources import plugin_for

AnnotatedFile = Item
AppendixChapter = Chapter


def matches(file, pattern: str) -> bool:
    return plugin_for("diff").match(Item(key=file.key, source=file.source, plugin="diff",
                                         payload=file, bodies=[file]), pattern)


def order_and_chapter(files, spec: dict, warnings: list[str]):
    """v1: order parsed files and report chapter marks."""
    plugin = plugin_for("diff")
    items = [Item(key=f.key, source=f.source, plugin="diff", payload=f, bodies=[f]) for f in files]
    hide = spec.get("hide") or []
    items = [it for it in items if not any(plugin.match(it, p) for p in hide)]
    plugins = {it.source: plugin for it in items}
    plugins.setdefault("", plugin)
    ordered, marks = arrange(items, spec, plugins, warnings)
    return [it.payload for it in ordered], marks


def order_files(files, spec: dict, warnings: list[str]):
    ordered, _ = order_and_chapter(files, spec, warnings)
    return ordered


def build_document(files, spec: dict, meta: dict) -> Document:
    by_source: dict[str, list] = {}
    for f in files:
        by_source.setdefault(f.source, []).append(f)
    spec = dict(spec)
    sources = dict(spec.get("sources") or {})
    described = {d["name"]: d for d in (meta.get("sources") or []) if d.get("name")}
    preloaded = {}
    for name, fs in by_source.items():
        conf = dict(sources.get(name) or {})
        conf.setdefault("type", "diff")
        d = described.get(name) or {}
        conf.setdefault("label", d.get("label") or name)
        conf.setdefault("range", d.get("range") or "")
        sources[name] = conf
        preloaded[name] = [Item(key=f.key, source=name, plugin="diff", payload=f, bodies=[f]) for f in fs]
    spec["sources"] = sources
    cli = {"meta": meta}
    if meta.get("transcript"):
        cli["transcript"] = meta["transcript"]
    if meta.get("title"):
        cli["default_title"] = meta["title"]
    return _build(spec, base_dir=Path("."), cwd=Path("."), cli=cli, preloaded=preloaded)
