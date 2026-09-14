"""The document model: sources, units, rows, anchors, layers.

A document is a stack of layers over a set of sources. A source is loaded by
a plugin into units; a unit is rows; an anchor is a row range in a unit.
Layers are prose (markdown for a reader) or streams (a run of items from one
or more sources, cut into chapters). Nothing here knows what a diff or a
conversation is: those are plugins in `literate_diff.sources`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class AnnotationError(Exception):
    pass


_slug_bad = re.compile(r"[^a-zA-Z0-9._-]+")


def slug(s: str) -> str:
    return _slug_bad.sub("-", s).strip("-")


@dataclass
class Row:
    """One addressable row of a unit.

    `kind` is plugin-defined (a diff has context/add/del/hunk/message; prose
    has prose/code/heading/bullet/...). `old_no`/`new_no` exist so the diff
    plugin's `+N`/`-N` anchor forms have something to address; other plugins
    leave them None.
    """

    kind: str
    text: str
    old_no: int | None = None
    new_no: int | None = None
    index: int = 0
    dom_id: str = ""
    marks: list = field(default_factory=list)


@dataclass(kw_only=True)
class Unit:
    """An anchorable body: a file's diff, one message, one document."""

    key: str  # how the sidecar addresses it (`source:path`, or bare)
    path: str  # display path or name
    source: str = ""  # source name
    lines: list = field(default_factory=list)  # rows; plugins may subclass Row
    kind: str = ""  # plugin-defined
    label: str = ""

    @property
    def is_prose(self) -> bool:
        return False

    def find_extra(self, at: str, from_index: int) -> int | None:
        """A plugin's own anchor forms. Return a row index, -1 for "this form
        is mine but nothing matched", or None for "not my form"."""
        return None


@dataclass
class Anchor:
    """A resolved row range within one unit."""

    file: Unit  # historical name: the unit the range is in
    start: int
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


@dataclass(kw_only=True)
class Item:
    """One entry of a stream: a file, a turn, a note, a term, a document.

    `payload` is the plugin's own object (a FileDiff, a Turn); `bodies` are the
    anchorable units it contains (a file is its own body; a turn has a prompt
    and maybe a reply). Core annotation keys bind here; a plugin binds its own
    (a turn's highlights) in `bind`.
    """

    key: str
    source: str
    plugin: str
    payload: object
    bodies: list[Unit]
    anchor_id: str = ""
    title: str = ""
    note_md: str = ""
    collapsed: bool = False
    sections: list[Section] = field(default_factory=list)
    notes: list[SideNote] = field(default_factory=list)
    # Filled by the renderer: the item's index in the document's item order.
    index: int = -1

    @property
    def unit(self) -> Unit:
        return self.bodies[0]

    @property
    def diff(self):
        """v1 name for a file item's payload."""
        return self.payload


@dataclass
class Chapter:
    """A titled run of items inside a stream layer."""

    title: str
    note_md: str
    anchor_id: str
    start: int  # index into the layer's items where this chapter begins


@dataclass(kw_only=True)
class Layer:
    id: str
    kind: str  # "prose" | "stream"
    title: str = ""
    audience: str = ""
    budget: str = ""
    goal: str = ""
    subtitle: str = ""  # what the block contains and where it came from
    # summary | synthesis | evidence: which part of the debrief this is
    group: str = ""
    row: int = 1  # rows within a group, top to bottom
    note_md: str = ""  # stream: rendered under the title
    text_md: str = ""  # prose: the layer itself
    sources: list[str] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    chapters: list[Chapter] = field(default_factory=list)
    claims: str = ""  # "" | "required"
    # Synthesised from a v1 sidecar (`plot:`, the file list, `appendix:`),
    # which renders the way v1 did rather than with a layer header.
    implicit: bool = False
    # Automatically added to hold sources no layer placed.
    automatic: bool = False
    # The plugin whose head renders above the stream, when every source in
    # the layer is of one type.
    plugin: str = ""
    index: int = -1

    @property
    def is_prose(self) -> bool:
        return self.kind == "prose"


@dataclass
class SourceInfo:
    """What the page says about a source, and what the file embeds of it."""

    name: str
    type: str
    label: str
    range: str = ""
    repo: str = ""
    # Copy of record, for the embedded data block: filename -> text.
    embed: dict[str, str] = field(default_factory=dict)
    counts: dict = field(default_factory=dict)


@dataclass
class Document:
    title: str
    subtitle: str
    layers: list[Layer]
    anchors: dict[str, Anchor]
    meta: dict
    sources: dict[str, SourceInfo] = field(default_factory=dict)
    categories: dict[str, dict] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    brief: dict = field(default_factory=dict)
    sidecar_text: str = ""
    # Terms: name -> {id, text, aliases}, from every `terms` source.
    terms: dict[str, dict] = field(default_factory=dict)

    # --- v1 views, kept for callers and tests that know the old shape ------

    @property
    def files(self) -> list[Item]:
        return [it for layer in self.layers for it in layer.items if it.plugin == "diff"]

    @property
    def turns(self) -> list:
        return [it.payload for layer in self.layers for it in layer.items if it.plugin == "transcript"]

    @property
    def threads(self) -> list:
        return list(self.meta.get("_threads") or [])

    @property
    def chapters(self) -> list[Chapter]:
        for layer in self.layers:
            if layer.kind == "stream" and layer.plugin == "diff":
                return layer.chapters
        return []

    @property
    def appendix_chapters(self) -> list[Chapter]:
        for layer in self.layers:
            if layer.kind == "stream" and layer.plugin == "transcript":
                return layer.chapters
        return []

    @property
    def plot_md(self) -> str:
        return "\n\n".join(l.text_md for l in self.layers if l.is_prose and l.text_md.strip())

    def items(self) -> list[Item]:
        return [it for layer in self.layers for it in layer.items]
