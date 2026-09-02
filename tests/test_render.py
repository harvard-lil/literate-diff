import json
import re

import pytest

from literate_diff.annotate import build_document
from literate_diff.parse import parse_diff
from literate_diff.render import render_document

DIFF = """\
diff --git a/first.py b/first.py
--- a/first.py
+++ b/first.py
@@ -1,2 +1,2 @@
-SECRET = "<hardcoded>"
+SECRET = os.environ["SECRET"]
diff --git a/second.py b/second.py
--- a/second.py
+++ b/second.py
@@ -1 +1 @@
-import first
+import first as f
"""


def build(spec):
    return render_document(build_document(parse_diff(DIFF), spec, {}))


@pytest.fixture
def doc_and_html():
    spec = {
        "title": "T",
        "files": {
            "first.py": {
                "anchors": [{"id": "secret", "at": "os.environ", "span": 1}],
                "note": 'Points [down](ld:#later) and quotes [it](ldq:#secret).',
            },
            "second.py": {
                "notes": [
                    {"at": "import first as f", "id": "later",
                     "text": "Points [up](ld:#secret)."}
                ]
            },
        },
    }
    doc = build_document(parse_diff(DIFF), spec, {})
    return doc, render_document(doc)


def test_reference_direction_follows_document_order(doc_and_html):
    _, html = doc_and_html
    # first.py -> second.py is forward; the return trip is backward.
    down = re.search(r'<a class="ld-ref ld-ref-(\w+)"[^>]*href="#later"', html)
    up = re.search(r'<a class="ld-ref ld-ref-(\w+)"[^>]*href="#secret"', html)
    assert down.group(1) == "forward"
    assert up.group(1) == "back"
    assert "↓" in html and "↑" in html


def test_reordering_flips_the_arrow():
    spec = {
        "order": ["second.py", "first.py"],
        "files": {
            "first.py": {"note": "See [it](ld:#later)."},
            "second.py": {"notes": [{"at": "import", "id": "later", "text": "x"}]},
        },
    }
    html = build(spec)
    assert re.search(r'ld-ref-back"[^>]*href="#later"', html)


def test_quote_embeds_the_target_lines(doc_and_html):
    _, html = doc_and_html
    body = re.search(r'<span class="ld-quote-body" hidden>(.*?)</span></span>', html, re.S)
    assert body and "os.environ" in body.group(1)
    # The quoted row keeps its add/del colouring and offers a jump to context.
    assert 'ld-qrow ld-add' in body.group(1)
    assert 'href="#secret"' in body.group(1)


def test_unknown_reference_is_flagged_not_linked():
    doc = build_document(parse_diff(DIFF), {"files": {"first.py": {"note": "[x](ld:#nope)"}}}, {})
    html = render_document(doc)
    assert 'ld-ref-broken' in html
    assert 'href="ld:#nope"' not in html
    assert any("nope" in w for w in doc.warnings)


def test_diff_content_is_html_escaped():
    html = build({})
    assert '&lt;hardcoded&gt;' in html
    assert '<hardcoded>' not in html


def test_anchor_map_is_emitted_for_the_client():
    spec = {"files": {"first.py": {"anchors": [{"id": "secret", "at": "os.environ", "span": 1}]}}}
    page = build(spec)
    payload = re.search(r"window\.LD_ANCHORS = (\{.*?\});", page, re.S).group(1)
    anchors = json.loads(payload)
    # Row 0 is the hunk header, row 1 the deletion, row 2 the addition matched here.
    assert anchors["secret"] == {"file": 0, "start": 2, "end": 2}
    # Files are addressable too, by index and by path.
    assert anchors["f1"]["file"] == 1
    assert "file-second.py" in anchors


def test_output_is_self_contained():
    html = build({})
    assert "<style>" in html and "<script>" in html
    assert "src=" not in html and 'rel="stylesheet"' not in html


def test_section_band_spans_the_table():
    html = build({"files": {"first.py": {"sections": [{"at": "os.environ", "title": "S"}]}}})
    assert '<tr class="ld-sectionrow"' in html
    assert '<td colspan="3">' in html
    assert "<h3 class=\"ld-section-title\">S</h3>" in html


def test_marked_rows_name_their_notes():
    html = build({"files": {"first.py": {"notes": [
        {"at": "SECRET", "span": 2, "id": "n", "text": "t"}]}}})
    # Both rows of the span are marked and point at the note.
    assert html.count('data-ld-notes="n"') == 2
    assert '<aside class="ld-note" id="n" data-ld-row="f0-r1">' in html


def test_cli_creates_missing_output_directories(tmp_path):
    from literate_diff.cli import main

    diff = tmp_path / "d.patch"
    diff.write_text(DIFF, encoding="utf-8")
    out = tmp_path / "nested" / "deeper" / "page.html"
    assert main(["--diff", str(diff), "-o", str(out)]) == 0
    assert out.exists() and "<style>" in out.read_text(encoding="utf-8")
