"""Read the sidecar and build the document: sources into items, items into
layers, annotations bound to rows.

A v1 sidecar (`plot:`, `chapters:`/`order:`, `files:`, `transcript:`,
`appendix:`, `turns:`) is read as a three-layer pyramid: one prose layer, one
stream of the diff sources, one stream of the transcript. Every v1 key keeps
its meaning; `layers:` is the v2 form and takes over when present.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .anchors import resolve_anchor
from .model import (
    Anchor, AnnotationError, Chapter, Document, Item, Layer, Section, SideNote,
    SourceInfo, slug,
)
from .sources import LoadContext, plugin_for
from .sources.base import SourcePlugin


def load_annotations(path: str | None) -> dict:
    if not path:
        return {}
    with open(path, encoding="utf-8") as fh:
        return parse_sidecar(fh.read(), path)


def parse_sidecar(text: str, label: str = "sidecar") -> dict:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise AnnotationError(f"{label}: top level must be a mapping")
    data["_text"] = text
    return data


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


# --- ordering ----------------------------------------------------------------


def _take(remaining: list[Item], patterns: list, plugins, warnings, label: str):
    """Pull the items matching `patterns` out of `remaining`, in pattern order.
    Returns the picked items and the position of a `*` wildcard, if any."""
    picked: list[Item] = []
    star_at: int | None = None
    for pat in patterns or []:
        if pat == "*":
            star_at = len(picked)
            continue
        hits = [it for it in remaining if plugins[it.source].match(it, pat)]
        if not hits:
            warnings.append(f"{label}: no file matched {pat!r}")
        for it in hits:
            remaining.remove(it)
            picked.append(it)
    return picked, star_at


def arrange(items: list[Item], conf: dict, plugins, warnings) -> tuple[list[Item], list[dict]]:
    """Order the items of an arranged stream and report where each chapter
    starts. `chapters` and `order` are alternatives: chapters are an order
    list cut into titled, annotated runs. When both are given, chapters win
    and `order` is reported as ignored."""
    remaining = list(items)
    chapters = conf.get("chapters")
    if chapters and conf.get("order"):
        warnings.append("both `chapters` and `order` are set; ignoring `order`")

    if not chapters:
        picked, star_at = _take(remaining, conf.get("order") or [], plugins, warnings, "order")
        if not conf.get("order"):
            return remaining, []
        if star_at is None:
            picked.extend(remaining)
        else:
            picked[star_at:star_at] = remaining
        return picked, []

    result: list[Item] = []
    marks: list[dict] = []
    leftovers_at: tuple[int, int] | None = None
    for ci, chapter in enumerate(chapters):
        if not isinstance(chapter, dict):
            raise AnnotationError("each entry of `chapters` must be a mapping")
        patterns = chapter.get("files") or chapter.get("items") or []
        picked, star_at = _take(remaining, patterns, plugins, warnings, f"chapters[{ci}]")
        marks.append({
            "title": chapter.get("title", ""),
            "note": chapter.get("note", "") or "",
            "id": chapter.get("id"),
            "start": len(result),
        })
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
            # Only chapters *after* the one whose `*` absorbed the remainder
            # move; the owning chapter starts at the wildcard, so its start holds.
            for mi, mark in enumerate(marks):
                if mi > owner:
                    mark["start"] += len(remaining)
    return result, marks


def natural(items: list[Item], conf: dict, plugins, warnings) -> tuple[list[Item], list[dict]]:
    """Order a natural stream by the plugins' sort keys and fix chapters at
    the items they name."""
    ordered = sorted(items, key=lambda it: plugins[it.source].sort_key(it))
    marks: list[dict] = []
    for ci, raw in enumerate(conf.get("chapters") or []):
        if not isinstance(raw, dict):
            raise AnnotationError("each entry of `chapters` must be a mapping")
        at = raw.get("at")
        if at is None:
            warnings.append("appendix chapter is missing `at`")
            continue
        where = next(
            (i for i, it in enumerate(ordered) if plugins[it.source].match(it, str(at))), None
        )
        if where is None:
            warnings.append(f"appendix chapter starts at {at!r}, which is not in the transcript")
            continue
        marks.append({
            "title": raw.get("title", "") or "",
            "note": raw.get("note", "") or "",
            "id": raw.get("id") or f"ac{ci}",
            "start": where,
        })
    marks.sort(key=lambda m: m["start"])
    return ordered, marks


# --- layers ------------------------------------------------------------------

# The three parts of a debrief, in reading order: what the author wants the
# reader to know, why the author believes it, and what actually happened.
GROUPS = ("summary", "synthesis", "evidence")


def _v1_layers(spec: dict, by_type: dict[str, list[str]]) -> list[dict]:
    """The pyramid a v1 sidecar describes."""
    layers: list[dict] = []
    if (spec.get("plot") or "").strip():
        layers.append({"id": "plot", "kind": "prose", "text": spec["plot"], "_implicit": True,
                       "group": "summary"})
    diff_sources = by_type.get("diff") or []
    if diff_sources:
        layers.append({
            "id": "code", "kind": "stream", "sources": diff_sources, "_implicit": True,
            "chapters": spec.get("chapters"), "order": spec.get("order"),
            "hide": spec.get("hide"), "collapse": spec.get("collapse"),
        })
    chats = by_type.get("transcript") or []
    if chats:
        appendix = spec.get("appendix") or {}
        layers.append({
            "id": "appendix", "kind": "stream", "sources": chats, "_implicit": True,
            "title": appendix.get("title") or "Appendix: the conversation",
            "note": appendix.get("note", "") or "",
            "chapters": appendix.get("chapters"),
        })
    return layers


@dataclass
class _Build:
    spec: dict
    warnings: list[str] = field(default_factory=list)
    anchors: dict[str, Anchor] = field(default_factory=dict)
    plugins: dict[str, SourcePlugin] = field(default_factory=dict)
    sources: dict[str, SourceInfo] = field(default_factory=dict)
    items_by_source: dict[str, list[Item]] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)

    def register(self, anchor: Anchor, requested: str | None, fallback: str = "", quiet=False) -> str:
        aid = slug(requested) if requested else fallback
        if aid in self.anchors and not quiet:
            self.warnings.append(f"duplicate id {aid!r}; later definition wins")
        anchor.anchor_id = aid
        self.anchors[aid] = anchor
        return aid


def build(
    spec: dict,
    *,
    base_dir: Path | str = ".",
    cwd: Path | str = ".",
    cli: dict | None = None,
    embed: bool = True,
    preloaded: dict | None = None,
) -> Document:
    """Build a document from a sidecar mapping.

    `cli` carries command-line overrides (`sources`, `transcript`, `title`,
    `context`, `pathspec`). `preloaded` maps a source name to already-parsed
    items, for callers that have them (the v1 `build_document` shim).
    """
    cli = dict(cli or {})
    base_dir = Path(base_dir)
    cwd = Path(cwd)
    b = _Build(spec=spec)
    warnings = b.warnings

    # --- sources -----------------------------------------------------------
    sources: dict[str, dict] = {}
    for name, conf in (spec.get("sources") or {}).items():
        if not isinstance(conf, dict):
            raise SystemExit(f"sources.{name} must be a mapping")
        sources[str(name)] = dict(conf)
    for name, conf in (cli.get("sources") or {}).items():
        sources[name] = dict(conf)
    # A v1 `transcript:` is a transcript source named after the key.
    transcript = cli.get("transcript") or spec.get("transcript")
    if transcript and not any(c.get("type") == "transcript" for c in sources.values()):
        name = "transcript" if "transcript" not in sources else "chat"
        sources[name] = {"type": "transcript", "file": str(transcript), "_from_v1": True}
    elif (spec.get("turns") or spec.get("threads")) and not any(
        c.get("type") == "transcript" for c in sources.values()
    ):
        warnings.append("`turns:`/`threads:` need a `transcript:` to bind to")
    for name, conf in list(sources.items()):
        conf.setdefault("type", "diff")
        if preloaded and name in preloaded:
            conf["_items"] = preloaded[name]

    by_type: dict[str, list[str]] = {}
    for name, conf in sources.items():
        plugin = plugin_for(conf["type"])
        ctx = LoadContext(name=name, conf=conf, base_dir=base_dir, cwd=cwd,
                          warnings=warnings, cli=cli, embed=embed)
        if conf.get("_items") is not None:
            items = list(conf["_items"])
            info = SourceInfo(name=name, type=conf["type"], label=conf.get("label") or name,
                              range=conf.get("range", ""))
        else:
            items, info = plugin.load(ctx)
        b.plugins[name] = plugin
        b.sources[name] = info
        b.items_by_source[name] = items
        by_type.setdefault(conf["type"], []).append(name)
        if hasattr(plugin, "bind_source"):
            plugin.bind_source(spec, warnings)

    # --- layers ------------------------------------------------------------
    raw_layers = spec.get("layers")
    if not raw_layers:
        raw_layers = _v1_layers(spec, by_type)
    layers: list[Layer] = []
    placed: set[str] = set()
    for li, raw in enumerate(raw_layers):
        if not isinstance(raw, dict):
            raise AnnotationError("each entry of `layers` must be a mapping")
        kind = raw.get("kind") or ("prose" if raw.get("text") is not None else "stream")
        group = str(raw.get("group") or ("evidence" if kind == "stream" else "synthesis"))
        if group not in GROUPS:
            warnings.append(f"layer {raw.get('id')!r}: group {group!r} is not one of {', '.join(GROUPS)}")
            group = "synthesis"
        layer = Layer(
            id=slug(str(raw.get("id") or f"layer{li}")),
            kind=kind,
            title=raw.get("title", "") or "",
            audience=raw.get("audience", "") or "",
            budget=str(raw.get("budget", "") or ""),
            goal=raw.get("goal", "") or "",
            subtitle=raw.get("subtitle", "") or "",
            group=group,
            row=int(raw.get("row") or 1),
            note_md=raw.get("note", "") or "",
            text_md=raw.get("text", "") or "",
            claims=str(raw.get("claims", "") or ""),
            implicit=bool(raw.get("_implicit")),
        )
        if kind == "stream":
            names = raw.get("sources")
            if names is None:
                names = [n for n in sources if n not in placed] or list(sources)
            if isinstance(names, str):
                names = [names]
            unknown = [n for n in names if n not in sources]
            if unknown:
                warnings.append(f"layer {layer.id!r} names unknown sources: {', '.join(unknown)}")
            layer.sources = [n for n in names if n in sources]
            placed.update(layer.sources)
            _fill_stream(b, layer, raw)
        layers.append(layer)

    # Sources no layer placed get a closing layer of their own, so that every
    # citation has somewhere to land.
    leftovers = [n for n in sources if n not in placed]
    if leftovers:
        layer = Layer(id="sources", kind="stream", title="Sources", automatic=True, group="evidence")
        layer.sources = leftovers
        _fill_stream(b, layer, {})
        layers.append(layer)

    for li, layer in enumerate(layers):
        layer.index = li
        kinds = {b.plugins[n].type for n in layer.sources}
        layer.plugin = kinds.pop() if len(kinds) == 1 else ""

    # --- the rest ------------------------------------------------------------
    categories = normalize_categories(spec.get("categories"), warnings)
    title = cli.get("title") or spec.get("title") or cli.get("default_title") or "Literate diff"
    meta = dict(cli.get("meta") or {})
    meta["_threads"] = [
        t for n in by_type.get("transcript", []) for t in getattr(b.plugins[n], "threads", [])
    ]
    doc = Document(
        title=title,
        subtitle=spec.get("subtitle", "") or "",
        layers=layers,
        anchors=b.anchors,
        meta=meta,
        sources=b.sources,
        categories=categories,
        warnings=warnings,
        brief=spec.get("brief") or {},
        sidecar_text=spec.get("_text", ""),
    )
    doc.plugins = b.plugins  # type: ignore[attr-defined]
    for n in by_type.get("terms", []):
        for it in b.items_by_source[n]:
            for alias in [it.title] + list(getattr(it.payload, "aliases", [])):
                if alias:
                    doc.terms[alias] = {"id": it.anchor_id, "text": it.payload.text,
                                        "term": it.payload.term}
    return doc


def _fill_stream(b: _Build, layer: Layer, raw: dict) -> None:
    plugins = b.plugins
    warnings = b.warnings
    spec = b.spec
    items = [it for n in layer.sources for it in b.items_by_source[n]]

    hide = raw.get("hide") or []
    if hide:
        items = [it for it in items if not any(plugins[it.source].match(it, p) for p in hide)]
    collapse = raw.get("collapse") or []

    natural_kinds = {plugins[n].natural_order for n in layer.sources}
    if len(natural_kinds) > 1:
        raise AnnotationError(
            f"layer {layer.id!r} mixes sources that order themselves with ones that "
            "are arranged; give each its own layer"
        )
    if natural_kinds == {True}:
        ordered, marks = natural(items, raw, plugins, warnings)
    else:
        ordered, marks = arrange(items, raw, plugins, warnings)

    # Per-item annotations: `items:` in v2, or the plugin's own key (`files:`,
    # `turns:`) at the top level. A key addresses an item by its qualified key
    # or by bare path when that is unambiguous.
    per_item: dict[str, dict] = {}
    for n in layer.sources:
        key = plugins[n].v1_items_key
        if key and isinstance(spec.get(key), dict):
            per_item.update(spec[key])
    if isinstance(raw.get("items"), dict):
        per_item.update(raw["items"])

    by_key = {it.key: it for it in ordered}
    bare: dict[str, list[Item]] = {}
    for it in ordered:
        bare.setdefault(it.unit.path, []).append(it)

    def lookup(name: str) -> Item | None:
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

    conf_for: dict[int, dict] = {}
    for name, conf in per_item.items():
        it = lookup(str(name))
        if it is None:
            if not bare.get(str(name)):
                what = "transcript" if layer.plugin == "transcript" or all(
                    plugins[n].natural_order for n in layer.sources) else "diff"
                if what == "transcript":
                    warnings.append(f"turns: {name!r} is not in the transcript")
                else:
                    warnings.append(f"files: {name!r} is not in the diff (or was hidden)")
            continue
        conf_for[id(it)] = conf or {}

    def resolve(unit, spec_):
        return resolve_anchor(unit, spec_, warnings)

    for it in ordered:
        plugin = plugins[it.source]
        n = b.counters.get(plugin.type, 0)
        b.counters[plugin.type] = n + 1
        conf = conf_for.get(id(it)) or {}
        it.title = conf.get("title", "") or it.title
        it.note_md = conf.get("note", "") or ""
        it.collapsed = bool(conf.get(
            "collapsed", any(plugin.match(it, p) for p in collapse)
        ))
        it.anchor_id = slug(conf["id"]) if conf.get("id") else plugin.item_anchor_id(it, n)
        for bi, body in enumerate(it.bodies):
            body.dom_id = plugin.body_dom(it, body, n)
        first = it.bodies[0]
        whole = Anchor(file=first, start=0, end=max(0, len(first.lines) - 1), anchor_id=it.anchor_id)
        if it.anchor_id in b.anchors:
            warnings.append(f"duplicate id {it.anchor_id!r}; later definition wins")
        b.anchors[it.anchor_id] = whole
        for auto in plugin.auto_ids(it):
            if auto in b.anchors:
                warnings.append(f"two files share the automatic id {auto!r}")
            b.anchors[auto] = whole

        unit = it.unit
        for si, s in enumerate(conf.get("sections") or []):
            anchor = resolve(unit, s)
            aid = b.register(anchor, s.get("id"), f"{it.anchor_id}s{si}")
            it.sections.append(Section(title=s.get("title", ""), note_md=s.get("note", "") or "",
                                       anchor=anchor, anchor_id=aid))
        for ni, note in enumerate(conf.get("notes") or []):
            anchor = resolve(unit, note)
            aid = b.register(anchor, note.get("id"), f"{it.anchor_id}n{ni}")
            it.notes.append(SideNote(text_md=note.get("text", "") or "", anchor=anchor, anchor_id=aid))
        if not plugin.item_keys or "anchors" not in plugin.item_keys:
            for a in conf.get("anchors") or []:
                anchor = resolve(unit, a)
                if not a.get("id"):
                    warnings.append(f"{it.key}: `anchors` entry without an id is a no-op")
                    continue
                b.register(anchor, a["id"])
        plugin.bind(it, conf, resolve, warnings, b.register)

    layer.items = ordered
    landmark = plugins[layer.sources[0]].chapter_landmark() if layer.sources else "ch-"
    for ci, mark in enumerate(marks):
        cid = slug(str(mark["id"])) if mark["id"] else f"c{ci}"
        layer.chapters.append(Chapter(title=mark["title"], note_md=mark["note"],
                                      anchor_id=cid, start=mark["start"]))
        if mark["start"] < len(ordered):
            target = ordered[mark["start"]].anchor_id
            if landmark == "ch-":
                if cid not in b.anchors:
                    b.anchors[cid] = b.anchors[target]
            else:
                b.anchors.setdefault(f"{landmark}{cid}", b.anchors[target])
