"""`--outline`: a starter sidecar for the sources a document has."""

from __future__ import annotations

from .model import Document


def make_outline(doc: Document) -> str:
    plugins = getattr(doc, "plugins", {})
    named = [n for n in doc.sources if n]
    multi = bool(named)

    lines = [
        f"title: {doc.title}",
        'subtitle: ""',
        "",
        "# The pyramid: layers written for different readers, over the sources.",
        "# Every layer names its audience and time budget; a prose layer's claims",
        "# cite the evidence with ld:/ldq:/ldc: links. See DESIGN.md and the skill.",
        "layers:",
        "  - id: summary",
        "    title: What changed",
        "    audience: anyone",
        "    budget: 1 minute",
        "    goal: what is different now, for someone who uses the system",
        "    claims: required",
        "    text: |",
        "      {claims}",
        "      - ",
        "",
        "  - id: story",
        "    title: The story",
        "    audience: a colleague in another role",
        "    budget: 10 minutes",
        "    text: |",
        "      ",
        "",
    ]
    for name in doc.sources:
        info = doc.sources[name]
        plugin = plugins.get(name)
        if plugin is None:
            continue
        lid = name or "code"
        lines += [
            f"  - id: {lid}",
            f"    kind: stream",
            f"    title: \"{info.label}\"",
            f"    sources: [{name or '\"\"'}]",
            "    audience: someone reviewing the change",
        ]
        if plugin.natural_order:
            lines += [
                "    chapters:",
                "      - at: <source-key of the item the chapter opens at>",
                '        title: ""',
                "        note: |",
                "          ",
                "",
            ]
        else:
            lines += [
                "    hide: []",
                "    collapse: []",
                "    chapters:",
                '      - title: ""',
                "        note: |",
                "          ",
                "        files:",
            ]
            for it in [it for layer in doc.layers for it in layer.items if it.source == name]:
                lines.append(f"          - {_key(it.key)}")
            lines += ["          - '*'", ""]

    if multi:
        lines.append("# Files are addressed as `source:path`.")
        lines.append("sources:")
        for name, info in doc.sources.items():
            lines.append(f"  {name}:")
            lines.append(f"    type: {info.type}")
            if info.repo:
                lines.append(f"    repo: {info.repo}")
            if info.range:
                lines.append(f"    range: {info.range}")
        lines.append("")

    lines.append("files:")
    for name in doc.sources:
        plugin = plugins.get(name)
        items = [it for layer in doc.layers for it in layer.items if it.source == name]
        if plugin is not None:
            lines += plugin.outline(items, doc.sources[name])
    return "\n".join(lines)


def _key(path: str) -> str:
    return f'"{path}"' if any(c in path for c in ":#{}[],") else path
