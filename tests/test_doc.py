"""The doc source: reference documents, and the provenance of exported ones."""

from literate_diff.sidecar import build, parse_sidecar
from literate_diff.sources.doc import split_front_matter
from rendered import render_document

EXPORTED = """\
---
title: Day 3 worksheet
origin: Google Docs
url: https://docs.google.com/document/d/abc/edit
modified: 2026-08-14T17:36:37.037Z
retrieved: 2026-09-14
---
# Day 3 \\— Worksheet

Pick one teammate to be the driver\\. Switch roles at any time.
"""

SIDECAR = """\
title: Docs
sources:
  docs:
    type: doc
    files:
      - {path}
      - path: {plain}
        title: A plain file
        url: https://example.org/plain
layers:
  - id: summary
    title: Summary
    text: |
      The worksheet says so [](ldq:#driver).
  - id: docs
    kind: stream
    title: Documents
    sources: [docs]
    items:
      docs:worksheet.md:
        anchors:
          - id: driver
            at: Pick one teammate
"""


def build_page(tmp_path):
    (tmp_path / "worksheet.md").write_text(EXPORTED)
    (tmp_path / "plain.md").write_text("Just text.\n")
    spec = parse_sidecar(SIDECAR.format(path="worksheet.md", plain="plain.md"))
    doc = build(spec, base_dir=tmp_path, cwd=tmp_path)
    return doc, render_document(doc)


def test_front_matter_is_provenance_not_text(tmp_path):
    doc, page = build_page(tmp_path)
    item = next(it for it in doc.layers[1].items if it.key == "docs:worksheet.md")
    assert item.title == "Day 3 worksheet"
    assert item.payload.lines[0].kind == "heading"
    assert not any("origin:" in row.text for row in item.payload.lines)
    assert '<a href="https://docs.google.com/document/d/abc/edit">Google Docs</a>' in page
    assert "last modified Aug. 14, 2026" in page
    assert "retrieved Sept. 14, 2026" in page
    assert not [w for w in doc.warnings if "driver" in w]


def test_the_copy_of_record_keeps_its_front_matter(tmp_path):
    doc, _ = build_page(tmp_path)
    info = doc.sources["docs"]
    assert info.embed["worksheet.md"].startswith("---\ntitle: Day 3 worksheet")


def test_sidecar_keys_describe_a_file_without_front_matter(tmp_path):
    _, page = build_page(tmp_path)
    assert '<a href="https://example.org/plain">original</a>' in page


def test_text_without_a_mapping_between_rules_has_no_front_matter():
    assert split_front_matter("---\n\nA rule, then prose.\n") == ({}, "---\n\nA rule, then prose.\n")
    assert split_front_matter("No front matter.\n") == ({}, "No front matter.\n")
