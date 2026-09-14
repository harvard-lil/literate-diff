"""v2: layers, claims and their evidence, notes, terms, documents, the data
block, extract, lint."""

import json
import re
from pathlib import Path

import pytest

from literate_diff.cli import main
from literate_diff.extract import BLOCK_RE, rebuild, resolve_markdown, write_inputs
from literate_diff.lint import budget_words, lint_document
from rendered import render_document, presentation
from literate_diff.sidecar import build, parse_sidecar

DIFF = """\
diff --git a/deploy.yml b/deploy.yml
--- a/deploy.yml
+++ b/deploy.yml
@@ -1,2 +1,2 @@
-      aws-access-key-id: ${{ secrets.KEY }}
+      role-to-assume: ${{ vars.ROLE }}
"""

TRANSCRIPT = """\
collected: 2026-03-04T12:00:00Z
threads:
  - id: keys
    title: Keys
    turns:
      - id: t0304-1500
        at: 2026-03-04T15:00:00Z
        prompt: |-
          The workflow has AWS keys in it. Can it assume a role instead?
        response: |-
          Yes. The trust policy names one environment. Nothing else changes.
"""

SIDECAR = """\
title: Keys out
sources:
  app: {{diff: {diff}, label: app}}
  chat: {{type: transcript, file: {transcript}}}
  said:
    type: notes
    items:
      - id: audit
        by: Sam
        on: 2026-03-01
        where: the audit
        text: The keys in the workflow are from 2022 and have never rotated.
      - id: gh-docs
        by: GitHub
        text: A job that names an environment presents environment:NAME as its subject.
        url: https://docs.github.com/actions/oidc
  glossary:
    type: terms
    items:
      - term: OIDC
        text: A signed token a CI job presents in place of a stored key.
      - term: trust policy
        aliases: [trust policies]
        text: The part of a role that says who may assume it.
categories:
  security: {{label: Security, short: S}}
layers:
  - id: summary
    title: What changed
    audience: anyone
    budget: 1 minute
    claims: required
    text: |
      {{claims}}
      - No keys in the workflow; it assumes a role over OIDC [](ld:#q-keys).
      - The keys were old [](ld:#audit).
      - The role trusts one environment [](ldc:#one-env).
      - Deploys are faster.
  - id: wins
    title: Wins
    audience: a reviewer
    text: |
      OIDC again, and a trust policy, and trust policies plural.

      {{category: security}}
      1. {{#one-env}} Before, any branch could assume the role. Now one environment can [](ld:#gh-docs).
  - id: code
    kind: stream
    title: The code
    audience: a reviewer
    sources: [app]
  - id: talk
    kind: stream
    title: The conversation
    sources: [chat]
files:
  deploy.yml:
    note: The role [](ldc:#one-env).
turns:
  keys:t0304-1500:
    id: q-keys
"""


@pytest.fixture
def page(tmp_path):
    (tmp_path / "changes.patch").write_text(DIFF)
    (tmp_path / "conversations.yaml").write_text(TRANSCRIPT)
    text = SIDECAR.format(diff=str(tmp_path / "changes.patch"), transcript="conversations.yaml")
    spec = parse_sidecar(text)
    doc = build(spec, base_dir=tmp_path, cwd=tmp_path)
    html = render_document(doc)
    lint_document(doc)
    return doc, html


def body(page: str) -> str:
    return page.split("</style>", 1)[1].split('<script type="application/json"', 1)[0]


# --- layers ---------------------------------------------------------------------


def test_layers_render_in_order_with_their_audiences(page):
    doc, html = page
    b = body(html)
    assert [l.id for l in doc.layers] == ["summary", "wins", "code", "talk", "sources"]
    assert b.index('id="summary"') < b.index('id="wins"') < b.index('id="code"') < b.index('id="talk"')
    assert "for anyone" in b and "1 minute" in b
    # Sources no layer placed get a closing layer so citations have a target.
    assert doc.layers[-1].automatic and set(doc.layers[-1].sources) == {"said", "glossary"}


def test_the_map_lists_every_declared_layer_twice(page):
    doc, html = page
    b = body(html)
    # Once in the margin (postage stamp), once full size after the header,
    # grouped: prose defaults to synthesis, streams to evidence.
    full = b[b.index('class="ld-map ld-map-full"'):]
    blocks = re.findall(r'data-ld-layer="([^"]+)"', full)
    assert blocks == ["summary", "wins", "code", "talk", "sources"]
    assert [l.group for l in doc.layers] == ["synthesis", "synthesis", "evidence", "evidence", "evidence"]
    mini = b[b.index('class="ld-map ld-map-mini"'):b.index('class="ld-map ld-map-full"')]
    assert re.findall(r'data-ld-layer="([^"]+)"', mini) == blocks
    assert 'data-ld-group="Synthesis"' in full and 'data-ld-group="Evidence"' in full


def test_groups_rows_and_subtitles_come_from_the_sidecar(tmp_path):
    (tmp_path / "c.patch").write_text(DIFF)
    spec = parse_sidecar(f"""
sources:
  app: {{diff: {tmp_path / 'c.patch'}}}
layers:
  - id: exec
    group: summary
    title: Executive summary
    subtitle: What changed, for anyone.
    text: Keys are gone.
  - id: ops
    group: summary
    row: 2
    title: Ops
    text: Nothing to do.
  - id: code
    kind: stream
    sources: [app]
    group: nowhere
""")
    doc = build(spec, base_dir=tmp_path, cwd=tmp_path)
    assert [(l.group, l.row) for l in doc.layers] == [("summary", 1), ("summary", 2), ("synthesis", 1)]
    assert any("group 'nowhere'" in w for w in doc.warnings)
    html = render_document(doc)
    b = body(html)
    assert '<p class="ld-layer-subtitle">What changed, for anyone.</p>' in b
    assert "ld-layer-audience" not in b
    assert 'class="ld-map-row ld-map-row-2"' in b


def test_a_v1_sidecar_is_read_as_three_implicit_layers(tmp_path):
    (tmp_path / "c.patch").write_text(DIFF)
    (tmp_path / "conversations.yaml").write_text(TRANSCRIPT)
    spec = parse_sidecar(f"""
plot: |
  ## Summary
  Keys are gone.
sources:
  app: {{diff: {tmp_path / 'c.patch'}}}
transcript: conversations.yaml
""")
    doc = build(spec, base_dir=tmp_path, cwd=tmp_path)
    assert [(l.id, l.kind, l.implicit) for l in doc.layers] == [
        ("plot", "prose", True), ("code", "stream", True), ("appendix", "stream", True)
    ]
    html = render_document(doc)
    assert '<div class="ld-plot" id="plot">' in html
    assert '<section class="ld-appendix" id="appendix">' in html
    assert "ld-map-block" not in body(html)


# --- claims ---------------------------------------------------------------------


def test_claims_show_what_they_rest_on(page):
    doc, html = page
    b = body(html)
    assert 'data-ld-evidence="conversation"' in b
    assert 'data-ld-evidence="attestation"' in b
    # A claim that flags a category item rests on what that item rests on:
    # the item is flagged from the diff and cites a reference.
    m = re.search(r'<li id="cat-claim-3"[^>]*data-ld-evidence="([^"]+)"', b)
    assert m and set(m.group(1).split(",")) == {"diff", "reference"}


def test_an_unsupported_claim_is_marked_and_reported(page):
    doc, html = page
    b = body(html)
    assert b.count("ld-unsupported") == 1
    assert 'id="cat-claim-4"' in b
    assert any("claim 'claim-4' in layer 'summary' cites nothing" in w for w in doc.warnings)


def test_claims_are_listed_in_the_data_block(page):
    _, html = page
    data = json.loads(BLOCK_RE.search(html).group(1))
    claims = {c["id"]: c for c in data["claims"]}
    assert claims["claim-1"]["evidence"] == ["conversation"] and claims["claim-1"]["supported"]
    assert claims["claim-4"]["supported"] is False
    assert claims["one-env"]["category"] == "security"
    assert "deploy.yml" in claims["one-env"]["flagged_from"]


# --- notes and terms ------------------------------------------------------------


def test_a_note_is_cited_by_its_own_id_and_says_who_said_it(page):
    doc, html = page
    b = body(html)
    assert 'id="audit"' in b and "Sam" in b and "the audit" in b
    assert "ld-note-kind\">attestation" in b
    assert "ld-note-kind\">reference" in b
    assert 'href="https://docs.github.com/actions/oidc"' in b


def test_terms_link_their_first_use_in_each_layer(page):
    _, html = page
    b = body(html)
    links = re.findall(r'<a class="ld-term"[^>]*data-ld-target="([^"]+)"', b)
    # Once per layer for OIDC (summary, wins); the alias once in wins.
    assert links.count("term-OIDC") == 2
    assert links.count("term-trust-policy") == 1
    assert 'title="The part of a role' in b


def test_a_document_source_renders_and_can_be_quoted(tmp_path):
    (tmp_path / "c.patch").write_text(DIFF)
    (tmp_path / "standard.md").write_text("# Standard\n\nNo long-lived keys. Roles only.\n")
    spec = parse_sidecar(f"""
sources:
  app: {{diff: {tmp_path / 'c.patch'}}}
  std: {{type: doc, files: [{tmp_path / 'standard.md'}]}}
layers:
  - id: summary
    title: Summary
    text: |
      The standard says [](ldq:#doc-standard.md).
  - id: code
    kind: stream
    sources: [app]
  - id: refs
    kind: stream
    title: References
    sources: [std]
""")
    doc = build(spec, base_dir=tmp_path, cwd=tmp_path)
    html = render_document(doc)
    b = body(html)
    assert doc.warnings == []
    assert '<section class="ld-doc" id="doc-standard.md">' in b
    assert "ld-quote-open" in b and "Roles only." in b


# --- the data block and extract -------------------------------------------------


def test_the_page_embeds_its_inputs_and_rebuilds_from_them(page, tmp_path):
    doc, html = page
    data = json.loads(BLOCK_RE.search(html).group(1))
    assert data["format"] == "literate-diff" and data["version"] == 2
    assert "title: Keys out" in data["sidecar"]
    assert "changes.patch" in data["sources"]["app"]["files"] or "app.patch" in data["sources"]["app"]["files"]
    assert "conversations.yaml" in data["sources"]["chat"]["files"]
    assert "<" not in BLOCK_RE.search(html).group(1)

    again = rebuild(data)
    assert [l.id for l in again.layers] == [l.id for l in doc.layers]
    assert set(again.anchors) == set(doc.anchors)

    out = tmp_path / "rt"
    write_inputs(data, out)
    assert (out / "build.yaml").exists() and (out / "sources" / "conversations.yaml").exists()


def test_extract_resolves_quotes_to_the_rows_they_name(page):
    doc, _ = page
    md = resolve_markdown(doc, "They said [](ldq:#audit) and see [here](ld:#q-keys).")
    assert "> The keys in the workflow are from 2022" in md
    assert "here [see q-keys]" in md


def test_no_embed_leaves_the_sources_out(tmp_path, capsys):
    (tmp_path / "c.patch").write_text(DIFF)
    out = tmp_path / "page.html"
    assert main(["--diff", str(tmp_path / "c.patch"), "-o", str(out), "--no-embed"]) == 0
    html = out.read_text()
    data = json.loads(BLOCK_RE.search(html).group(1))
    assert data["sources"][""]["files"] == {} and data["sidecar"] == ""


def test_the_file_begins_by_saying_what_it_is(page):
    _, html = page
    head = html[:3000]
    assert head.startswith("<!doctype html>\n<!--\nDebrief: Keys out")
    assert "designed to be read by people or by agents" in html
    assert "#summary" in head and "pup 'script#ld-data" in head


# --- lint -----------------------------------------------------------------------


def test_budgets_read_as_words_or_minutes():
    assert budget_words("400 words") == 400
    assert budget_words("2 minutes") == 400
    assert budget_words("") is None


def test_lint_reports_prose_about_the_document_and_layers_over_budget(tmp_path):
    (tmp_path / "c.patch").write_text(DIFF)
    spec = parse_sidecar(f"""
sources:
  app: {{diff: {tmp_path / 'c.patch'}}}
layers:
  - id: summary
    title: Summary
    budget: 5 words
    text: |
      This section traces how the work happened. The reader should note the keys. Below, more.
      One two three four five six seven.
""")
    doc = build(spec, base_dir=tmp_path, cwd=tmp_path)
    found = lint_document(doc)
    assert sum("writes about the document" in f for f in found) == 3
    assert any("against a budget of 5 words" in f for f in found)


def test_lint_reports_an_unused_category_and_an_unused_term(tmp_path):
    (tmp_path / "c.patch").write_text(DIFF)
    spec = parse_sidecar(f"""
sources:
  app: {{diff: {tmp_path / 'c.patch'}}}
  glossary:
    type: terms
    items:
      - {{term: OIDC, text: a token}}
      - {{term: digest, text: a hash}}
categories:
  security: Security
  cost: Cost
layers:
  - id: wins
    title: Improvements
    text: |
      OIDC is in.

      {{category: security}}
      1. Keys are gone.
""")
    doc = build(spec, base_dir=tmp_path, cwd=tmp_path)
    render_document(doc)
    found = lint_document(doc)
    assert any("category 'cost' is declared but no list uses it" in f for f in found)
    assert any("term 'digest' is defined but no prose layer uses it" in f for f in found)
    assert not any("'OIDC'" in f for f in found)
