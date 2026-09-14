"""The diff source: a git range or a patch file, as files of rows.

Owns what is particular to code: reading `git diff`, the `+N`/`-N` anchor
forms (on `FileDiff` itself), the diff table with its lazily built folded
rows, the sidenote gutter, and the quote form with signs and line numbers.
"""

from __future__ import annotations

import html
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

from ..model import Anchor, Item, Layer, SourceInfo, slug
from ..parse import FileDiff, parse_diff
from .base import LoadContext, SourcePlugin


def git_diff(repo: str, rev_range: str, context: int, pathspec) -> str:
    cmd = [
        "git", "-C", repo, "diff", f"--unified={context}", "--no-color",
        "--no-ext-diff", rev_range,
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
        capture_output=True, text=True,
    ).stdout.strip()
    return Path(top).name if top else Path(repo).resolve().name


def read_patch(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8", errors="replace")


class DiffSource(SourcePlugin):
    type = "diff"
    evidence = "diff"
    natural_order = False
    v1_items_key = "files"

    # --- loading ---------------------------------------------------------

    def load(self, ctx: LoadContext) -> tuple[list[Item], SourceInfo]:
        conf = ctx.conf
        name = ctx.name
        if conf.get("text") is not None:
            # Already-parsed text handed over by a caller (tests, `extract`).
            text = conf["text"]
            label = conf.get("label") or name
            rev_range = conf.get("range", "")
            repo = conf.get("repo", "")
        elif conf.get("diff"):
            text = read_patch(str(ctx.cwd / conf["diff"]) if conf["diff"] != "-" else "-")
            label = conf.get("label") or name or conf["diff"]
            rev_range = conf.get("range", "")
            repo = conf.get("diff", "")
        else:
            if not conf.get("repo") or not conf.get("range"):
                raise SystemExit(f"sources.{name} needs `repo` and `range` (or `diff`)")
            repo_path = str(ctx.cwd / conf["repo"])
            text = git_diff(
                repo_path, conf["range"],
                int(conf.get("context", ctx.cli.get("context", 3))),
                conf.get("pathspec", ctx.cli.get("pathspec")),
            )
            label = conf.get("label") or repo_name(repo_path)
            rev_range = conf["range"]
            repo = conf["repo"]
        files = parse_diff(text, source=name)
        if not files:
            ctx.warn(f"source {name or label!r} contributed no files")
        items = [
            Item(key=f.key, source=name, plugin=self.type, payload=f, bodies=[f])
            for f in files
        ]
        info = SourceInfo(name=name, type=self.type, label=label, range=rev_range, repo=repo)
        if ctx.embed:
            info.embed[f"{name or 'diff'}.patch"] = text
        info.counts = {
            "files": len(files),
            "additions": sum(f.additions for f in files),
            "deletions": sum(f.deletions for f in files),
        }
        return items, info

    # --- binding -----------------------------------------------------------

    def match(self, item: Item, pattern: str) -> bool:
        """A pattern naming a source (`actions:ecs-build/**`) is matched against
        the qualified key; a bare pattern (`**/dist/**`) against the path inside
        every source, so a path glob means the same thing in each repo."""
        f: FileDiff = item.payload
        if ":" in pattern:
            return fnmatch(f.key, pattern)
        return fnmatch(f.path, pattern)

    def item_anchor_id(self, item: Item, n: int) -> str:
        return f"f{n}"

    def auto_ids(self, item: Item) -> list[str]:
        return [slug("file:" + item.payload.key)]

    def body_dom(self, item: Item, unit, n: int) -> str:
        return f"f{n}"

    # --- rendering ---------------------------------------------------------

    def _owner(self, item: Item) -> str:
        return item.payload.path.split("/")[-1]

    def _row_data(self, r, item: Item):
        """A file's diff as rows and section headers, for the client to build.

        A collapsed file is markup nobody has asked to see: 145 bytes of table
        scaffolding per line for about 47 bytes of code. Handing over the rows
        instead costs the text and little else, and nothing is lost that worked
        before -- a folded `<details>` is already invisible to find-in-page.
        """
        sections_at: dict[int, list] = {}
        for sec in item.sections:
            sections_at.setdefault(sec.anchor.start, []).append(sec)
        marked: dict[int, list[str]] = {}
        for note in item.notes:
            for i in range(note.anchor.start, note.anchor.end + 1):
                marked.setdefault(i, []).append(note.anchor_id)
        rows = [
            [line.kind[0], line.old_no or 0, line.new_no or 0, line.text,
             ",".join(marked.get(line.index, ()))]
            for line in item.payload.lines
        ]
        sections = {
            str(at): "".join(self._section_row(r, item, sec) for sec in secs)
            for at, secs in sections_at.items()
        }
        return {"rows": rows, "sections": sections}

    def _section_row(self, r, item: Item, sec) -> str:
        owner = sec.title or self._owner(item)
        note = (
            f'<div class="ld-section-note">'
            f"{r.md(sec.note_md, r.here(item, sec.anchor.start), owner)}</div>"
            if sec.note_md.strip() else ""
        )
        title = f'<h3 class="ld-section-title">{html.escape(sec.title)}</h3>' if sec.title else ""
        return (
            f'<tr class="ld-sectionrow" id="{html.escape(sec.anchor_id)}">'
            f'<td colspan="3"><div class="ld-section">{title}{note}</div></td></tr>'
        )

    def _table(self, r, item: Item, dom: str) -> str:
        if item.collapsed:
            r.lazy[dom] = self._row_data(r, item)
            return '<table class="ld-diff"><tbody></tbody></table>'

        sections_at: dict[int, list] = {}
        for s in item.sections:
            sections_at.setdefault(s.anchor.start, []).append(s)
        marked: dict[int, list[str]] = {}
        for note in item.notes:
            for i in range(note.anchor.start, note.anchor.end + 1):
                marked.setdefault(i, []).append(note.anchor_id)

        parts = ['<table class="ld-diff"><tbody>']
        for line in item.payload.lines:
            for s in sections_at.get(line.index, []):
                parts.append(self._section_row(r, item, s))
            rid = f"{dom}-r{line.index}"
            if line.kind == "hunk":
                parts.append(
                    f'<tr class="ld-row ld-hunk" id="{rid}"><td class="ld-no"></td>'
                    f'<td class="ld-no"></td><td class="ld-text">{html.escape(line.text) or "&nbsp;"}</td></tr>'
                )
                continue
            if line.kind == "message":
                parts.append(
                    f'<tr class="ld-row ld-message" id="{rid}"><td class="ld-no"></td>'
                    f'<td class="ld-no"></td><td class="ld-text">{html.escape(line.text)}</td></tr>'
                )
                continue
            cls = f"ld-row ld-{line.kind}"
            note_ids = marked.get(line.index)
            if note_ids:
                cls += " ld-marked"
            sign = {"add": "+", "del": "-"}.get(line.kind, " ")
            parts.append(
                f'<tr class="{cls}" id="{rid}"'
                + (f' data-ld-notes="{html.escape(",".join(note_ids))}"' if note_ids else "")
                + f'><td class="ld-no">{line.old_no or ""}</td>'
                f'<td class="ld-no">{line.new_no or ""}</td>'
                f'<td class="ld-text"><span class="ld-sign">{sign}</span>'
                f'{html.escape(line.text) or "&nbsp;"}</td></tr>'
            )
        parts.append("</tbody></table>")
        return "".join(parts)

    def _gutter(self, r, item: Item, dom: str) -> str:
        out = []
        for note in item.notes:
            out.append(
                f'<aside class="ld-note" id="{html.escape(note.anchor_id)}"'
                f' data-ld-row="{dom}-r{note.anchor.start}">'
                f"{r.md(note.text_md, r.here(item, note.anchor.start), self._owner(item))}</aside>"
            )
        return "".join(out)

    def render_item(self, r, layer: Layer, item: Item, show_source: bool) -> str:
        d: FileDiff = item.payload
        dom = r.body_dom[id(d)]
        badge = {
            "added": '<span class="ld-badge ld-badge-add">added</span>',
            "deleted": '<span class="ld-badge ld-badge-del">deleted</span>',
            "renamed": '<span class="ld-badge ld-badge-ren">renamed</span>',
        }.get(d.status, "")
        rename = ""
        if d.status == "renamed" and d.old_path and d.old_path != d.path:
            rename = f'<span class="ld-rename">from <code>{html.escape(d.old_path)}</code></span>'
        title = f'<span class="ld-filetitle">{html.escape(item.title)}</span>' if item.title else ""
        src = (
            f'<span class="ld-src" data-ld-src="{html.escape(d.source)}">'
            f"{html.escape(r.source_label(d.source))}</span>"
            if d.source else ""
        )
        note = (
            f'<div class="ld-filenote">{r.md(item.note_md, r.here(item, 0), self._owner(item))}</div>'
            if item.note_md.strip() else ""
        )
        stats = (
            f'<span class="ld-stat ld-stat-add">+{d.additions}</span>'
            f'<span class="ld-stat ld-stat-del">−{d.deletions}</span>'
        )
        open_attr = "" if item.collapsed else " open"
        lazy = f' data-ld-lazy="{dom}"' if item.collapsed else ""
        return (
            f'<section class="ld-file" id="{dom}" data-ld-path="{html.escape(d.path)}">'
            f"{note}"
            f'<details class="ld-fileblock"{open_attr}{lazy}>'
            f'<summary class="ld-filehead">'
            f'<span class="ld-chev" aria-hidden="true">▸</span>'
            f"{src}"
            f'<code class="ld-path">{html.escape(d.path)}</code>'
            f"{badge}{rename}{title}"
            f'<span class="ld-spacer"></span>{stats}</summary>'
            f'<div class="ld-body"><div class="ld-diffwrap">{self._table(r, item, dom)}</div>'
            f'<div class="ld-gutter">{self._gutter(r, item, dom)}</div></div>'
            f"</details></section>"
        )

    def quote(self, r, anchor: Anchor, target: str, label: str) -> str:
        rows = []
        for line in anchor.file.lines[anchor.start : anchor.end + 1]:
            if line.kind == "hunk":
                continue
            sign = {"add": "+", "del": "-"}.get(line.kind, " ")
            no = line.new_no or line.old_no or ""
            rows.append(
                f'<span class="ld-qrow ld-{line.kind}">'
                f'<span class="ld-qno">{no}</span>'
                f'<span class="ld-qsign">{sign}</span>'
                f'<span class="ld-qtext">{html.escape(line.text) or "&nbsp;"}</span>'
                "</span>"
            )
        body = "".join(rows)
        path = html.escape(anchor.file.path)
        if anchor.file.source:
            path = (
                f'<span class="ld-src">{html.escape(r.source_label(anchor.file.source))}'
                f"</span> {path}"
            )
        return (
            '<span class="ld-quote">'
            f'<button type="button" class="ld-quote-btn" aria-expanded="false"'
            f' data-ld-target="{html.escape(target)}">{label}</button>'
            f'<span class="ld-quote-body" hidden>'
            f'<span class="ld-qhead"><code>{path}</code>'
            f'<a class="ld-qjump" href="#{html.escape(target)}"'
            f' data-ld-target="{html.escape(target)}">go to context ↦</a></span>'
            f"{body}</span></span>"
        )

    def toc_item(self, r, item: Item) -> str:
        d: FileDiff = item.payload
        dom = r.body_dom[id(d)]
        subs = "".join(
            f'<li><a href="#{html.escape(s.anchor_id)}" data-ld-target="{html.escape(s.anchor_id)}">'
            f"{html.escape(s.title)}</a></li>"
            for s in item.sections if s.title
        )
        label = item.title or self._owner(item)
        src = (
            f'<span class="ld-toc-src">{html.escape(r.source_label(d.source))}</span>'
            if d.source else ""
        )
        return (
            f'<li class="ld-toc-file"><a href="#{dom}" data-ld-target="{dom}">'
            f'<span class="ld-toc-name">{html.escape(label)}</span>'
            f'<span class="ld-toc-path">{src}{html.escape(d.path)}</span></a>'
            + (f'<ul class="ld-toc-sub">{subs}</ul>' if subs else "")
            + "</li>"
        )

    def metaline(self, r, layer: Layer) -> list[str]:
        files = [it.payload for it in layer.items]
        adds = sum(f.additions for f in files)
        dels = sum(f.deletions for f in files)
        return [
            f"{len(files)} files",
            f'<span class="ld-stat-add">+{adds}</span>',
            f'<span class="ld-stat-del">−{dels}</span>',
        ]

    # --- outline -----------------------------------------------------------

    def outline(self, items: list[Item], info: SourceInfo) -> list[str]:
        out = []
        for it in items:
            f: FileDiff = it.payload
            out += [
                f"  {yaml_key(f.key)}:",
                f"    # {f.status}, +{f.additions} -{f.deletions}",
                "    note: |",
                "      ",
                "    sections: []",
                "    notes: []",
                "",
            ]
        return out

    def skill_fragment(self) -> str:
        return "diff.md"


def yaml_key(path: str) -> str:
    return f'"{path}"' if any(c in path for c in ":#{}[],") else path
