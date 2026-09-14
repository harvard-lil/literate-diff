"""Compile presentation strings to slices of the embedded copies of record.

The record remains ordinary JSON, readable with jq and older extractors. Only
presentation strings use copy instructions: {$text: [literal, [source, start,
end], ...]}. Offsets count Unicode code points in the optionally HTML-escaped
source. Literal fragments hold layout and text not present verbatim in a source.
This is a serialization step, not a second Markdown or source parser.
"""
from __future__ import annotations

import html
import re
from collections import Counter

SEED = 24
STRIDE = 8
MIN_COPY = 48


def encode_presentation(data: dict, presentation: dict) -> dict:
    # Repeated table/paragraph scaffolding is a shared dictionary, not a full
    # second HTML document. Tokenization is lossless; it does not parse HTML.
    tokens = re.split(r"(<[^>]*>)", presentation["html"])
    counts = Counter(tokens)
    markup = [t for t, count in counts.items() if t.startswith("<") and count > 1]
    ids = {text: i for i, text in enumerate(markup)}
    fragments, literal = [], []
    for token in tokens:
        if token in ids:
            if literal:
                fragments.append("".join(literal))
                literal = []
            fragments.append(ids[token])
        else:
            literal.append(token)
    if literal:
        fragments.append("".join(literal))
    presentation = {**presentation, "html": fragments, "markup": markup}
    paths = [["sidecar"]] if data.get("sidecar") else []
    paths += [["sources", name, "files", filename]
              for name, source in data["sources"].items()
              for filename in source["files"]]
    sources, texts, index = [], [], {}
    for path in paths:
        value = data
        for key in path:
            value = value[key]
        for escaped in (False, True):
            text = html.escape(value) if escaped else value
            if escaped and text == value:
                continue
            source = len(texts)
            sources.append({"path": path, "escape": escaped})
            texts.append(text)
            for pos in range(0, len(text) - SEED + 1, STRIDE):
                # One deterministic candidate bounds both memory and work even
                # for large sources containing repetitive generated lines.
                index.setdefault(text[pos:pos + SEED], (source, pos))

    def encode(value):
        if isinstance(value, dict):
            return {k: encode(v) for k, v in value.items()}
        if isinstance(value, list):
            return [encode(v) for v in value]
        if not isinstance(value, str) or len(value) < MIN_COPY:
            return value
        parts, pos, literal = [], 0, 0
        while pos <= len(value) - MIN_COPY:
            candidate = index.get(value[pos:pos + SEED])
            if candidate is None:
                pos += 1
                continue
            source, start = candidate
            text = texts[source]
            size = SEED
            while (pos + size < len(value) and start + size < len(text)
                   and value[pos + size] == text[start + size]):
                size += 1
            if size < MIN_COPY:
                pos += 1
                continue
            if literal < pos:
                parts.append(value[literal:pos])
            parts.append([source, start, start + size])
            pos += size
            literal = pos
        if not parts:
            return value
        if literal < len(value):
            parts.append(value[literal:])
        return {"$text": parts}

    return {"version": 1, "text_sources": sources, **encode(presentation)}


def decode_presentation(data: dict) -> dict:
    """Materialize the compiled view for non-browser consumers and tests."""
    presentation = data["presentation"]
    if presentation["version"] != 1:
        raise ValueError("unsupported presentation version")
    texts = []
    for source in presentation["text_sources"]:
        value = data
        for key in source["path"]:
            value = value[key]
        texts.append(html.escape(value) if source["escape"] else value)

    def decode(value):
        if isinstance(value, dict):
            if "$text" in value:
                return "".join(p if isinstance(p, str) else texts[p[0]][p[1]:p[2]]
                               for p in value["$text"])
            return {k: decode(v) for k, v in value.items()}
        if isinstance(value, list):
            return [decode(v) for v in value]
        return value

    result = decode(presentation)
    result["html"] = "".join(result["markup"][part] if isinstance(part, int) else part
                             for part in result["html"])
    return result
