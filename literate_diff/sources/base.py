"""The source plugin contract.

A plugin owns one kind of evidence end to end: producing its copy of record,
loading that into items with anchorable rows, any anchor forms and annotation
keys of its own, and rendering its items, quotes and table-of-contents
entries. The core owns everything between: the sidecar, layers, ids and
references, categories and claims, the page.

The test for a layer violation: the core never imports a plugin's types, and
a plugin never reads another plugin's items.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..model import Anchor, Chapter, Item, Layer, SourceInfo, Unit


@dataclass
class LoadContext:
    """What a plugin gets to load a source with."""

    name: str
    conf: dict
    base_dir: Path  # the sidecar's directory; relative paths resolve from here
    cwd: Path  # where the build was run; `repo:` and `diff:` resolve from here
    warnings: list[str]
    cli: dict = field(default_factory=dict)  # command-line overrides
    embed: bool = True

    def warn(self, message: str) -> None:
        self.warnings.append(message)


class SourcePlugin:
    """Subclass per source type. Attributes and methods a plugin may override
    are listed here with the default behaviour; only `type` and `load` are
    required."""

    #: the `type:` value in `sources:`
    type: str = ""
    #: how the evidence is described on a claim that cites it
    evidence: str = ""
    #: True when the source orders its own items (a transcript by time) and a
    #: chapter is fixed by `at:`; False when the author lists items and a
    #: chapter takes a wildcard.
    natural_order: bool = False
    #: sidecar keys this plugin binds on an item beyond the core ones
    item_keys: tuple[str, ...] = ()
    #: the top-level sidecar key that holds this plugin's per-item
    #: annotations in a v1 sidecar (`files:`, `turns:`), if any
    v1_items_key: str = ""

    # --- loading ---------------------------------------------------------

    def load(self, ctx: LoadContext) -> tuple[list[Item], SourceInfo]:
        raise NotImplementedError

    # --- binding -----------------------------------------------------------

    def match(self, item: Item, pattern: str) -> bool:
        """Does a sidecar pattern (`hide:`, a chapter's list) name this item?"""
        return pattern in (item.key, item.unit.path)

    def bind(self, item: Item, conf: dict, resolve: Callable, warnings: list[str],
             register: Callable) -> None:
        """Bind plugin-specific annotation keys. `resolve(unit, spec)` gives an
        Anchor; `register(anchor, id)` makes it addressable."""

    def item_anchor_id(self, item: Item, n: int) -> str:
        """The automatic id of an item (`f3`, `t12`)."""
        return f"u{n}"

    def auto_ids(self, item: Item) -> list[str]:
        """Extra automatic ids for an item (`file-<path>`)."""
        return []

    def body_dom(self, item: Item, unit: Unit, n: int) -> str:
        """DOM id prefix for a body's rows: `<prefix>-r<i>`."""
        return f"u{n}"

    def sort_key(self, item: Item):
        """For natural-order sources: how items sort across sources."""
        return 0

    # --- rendering ---------------------------------------------------------

    def render_item(self, r, layer: Layer, item: Item, show_source: bool) -> str:
        raise NotImplementedError

    def render_head(self, r, layer: Layer) -> str:
        """Above the stream: counts, sessions, whatever the reader needs to
        judge what they are looking at."""
        return ""

    def quote(self, r, anchor: Anchor, target: str, label: str) -> str:
        raise NotImplementedError

    def toc_item(self, r, item: Item) -> str:
        raise NotImplementedError

    def chapter_landmark(self) -> str:
        """Prefix for chapter ids in this plugin's streams."""
        return "ch-"

    def metaline(self, r, layer: Layer) -> list[str]:
        """Bits for the header's meta line."""
        return []

    # --- extract / outline / skill -------------------------------------------

    def outline(self, items: list[Item], info: SourceInfo) -> list[str]:
        return []

    def skill_fragment(self) -> str:
        return ""
