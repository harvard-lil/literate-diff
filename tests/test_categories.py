"""Categories: coloured, numbered plot lists and the `ldc:` flags that cite them."""

import re

from literate_diff.annotate import build_document
from literate_diff.parse import parse_diff
from literate_diff.render import PALETTE
from rendered import render_document, presentation

DIFF = """\
diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1 +1 @@
-x = 1
+x = 2
diff --git a/b.py b/b.py
--- a/b.py
+++ b/b.py
@@ -1 +1 @@
-y = 1
+y = 2
"""

PLOT = """\
## Security

{category: security}
1. {#least-priv} Builds cannot deploy.
2. Roles trust one environment.

## Cost

{category: cost}
1. {#alb} One load balancer fewer.
"""


def build(spec):
    doc = build_document(parse_diff(DIFF), spec, {})
    return doc, render_document(doc)


def spec(**over):
    base = {
        "categories": {"security": "Security", "cost": {"label": "Cost", "color": "#123456"}},
        "plot": PLOT,
        "files": {
            "a.py": {"note": "Done here: [](ldc:#least-priv) and [also](ldc:#alb)."},
            "b.py": {
                "notes": [{"at": "y = 2", "text": "Second place: [](ldc:#least-priv)."}]
            },
        },
    }
    base.update(over)
    return base


def test_list_items_are_numbered_and_addressable():
    _, html = build(spec())
    assert '<li id="cat-least-priv" data-ld-cat="security"' in html
    # The second item took no explicit id, so it gets category-number.
    assert '<li id="cat-security-2"' in html
    assert '<li id="cat-alb" data-ld-cat="cost"' in html
    # The `{#id}` marker itself is gone from the text.
    assert "{#least-priv}" not in html
    assert "{category:" not in html


def test_colours_come_from_the_palette_unless_given():
    _, html = build(spec())
    assert f'data-ld-cat="security" style="--cat:{PALETTE[0]};' in html
    assert 'data-ld-cat="cost" style="--cat:#123456;' in html


def test_flag_shows_the_item_number_and_text():
    _, html = build(spec())
    flags = re.findall(r'<a class="ld-cat-flag"[^>]*>', html)
    assert len(flags) == 3
    first = flags[0]
    assert 'href="#cat-least-priv"' in first
    assert 'title="Security 1: Builds cannot deploy."' in first
    assert re.search(r'<a class="ld-cat-flag"[^>]*href="#cat-least-priv"[^>]*>'
                     r'<span class="ld-cat-badge">1</span>', html)
    assert 'title="Cost 1: One load balancer fewer."' in html
    # A non-empty label is kept after the badge.
    assert '<span class="ld-cat-flag-label">also</span>' in html


def test_items_link_back_to_every_flag():
    _, html = build(spec())
    li = re.search(r'<li id="cat-least-priv".*?</li>', html, re.S).group(0)
    where = re.search(r'<span class="ld-cat-where">(.*)</span></li>', li, re.S).group(1)
    # Two flags: the a.py file note and the b.py sidenote, both below the plot.
    assert where.count("ld-ref-forward") == 2
    assert "a.py" in where and "b.py" in where
    assert 'href="#flag-least-priv-1"' in where and 'href="#flag-least-priv-2"' in where
    # And the flag elements carry those ids so the links land on them.
    assert 'id="flag-least-priv-1"' in html and 'id="flag-least-priv-2"' in html


def test_unknown_item_and_undeclared_category_warn():
    doc, html = build(spec(files={"a.py": {"note": "[](ldc:#nope)"}},
                            plot="{category: mystery}\n1. thing\n"))
    assert "flag ldc:#nope names no category item" in doc.warnings
    assert "{category: mystery} is not declared under `categories`" in doc.warnings
    assert 'class="ld-ref ld-ref-broken"' in html
    # Warnings are not doubled by the two-pass render.
    assert doc.warnings.count("flag ldc:#nope names no category item") == 1


def test_short_prefix_appears_on_badges_and_flags():
    s = spec(categories={"security": {"label": "Security", "short": "S"}, "cost": "Cost"})
    _, html = build(s)
    assert '>S1</span>' in html
    assert re.search(r'<a class="ld-cat-flag"[^>]*href="#cat-least-priv"[^>]*>'
                     r'<span class="ld-cat-badge">S1</span>', html)


def test_string_category_shorthand_and_slug_keys():
    doc, _ = build(spec(categories={"Support Window": "Support window"}))
    assert doc.categories == {
        "Support-Window": {"label": "Support window", "color": None, "short": ""}
    }


def test_plain_link_to_a_category_item():
    _, html = build(spec(files={"a.py": {"note": "See [the first win](ld:#cat-least-priv)."}}))
    assert re.search(r'<a class="ld-ref ld-ref-back" href="#cat-least-priv"[^>]*>'
                     r'<span class="ld-arrow" aria-hidden="true">↑</span>the first win</a>', html)
