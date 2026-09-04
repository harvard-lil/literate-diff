"""Sources, chapters, and the qualified-key addressing they need."""

import re

import pytest

from literate_diff.annotate import build_document, matches, order_and_chapter
from literate_diff.parse import parse_diff
from literate_diff.render import render_document

# Both repos carry a .github/workflows/main.yml -- the collision case.
ACTIONS = """\
diff --git a/ecs-build/action.yml b/ecs-build/action.yml
--- a/ecs-build/action.yml
+++ b/ecs-build/action.yml
@@ -1,2 +1,3 @@
 name: ecs-build
+  sha-tag-only: true
diff --git a/.github/workflows/main.yml b/.github/workflows/main.yml
--- a/.github/workflows/main.yml
+++ b/.github/workflows/main.yml
@@ -1 +1 @@
-on: [push]
+on: [push, pull_request]
"""

H2O = """\
diff --git a/.github/workflows/main.yml b/.github/workflows/main.yml
--- a/.github/workflows/main.yml
+++ b/.github/workflows/main.yml
@@ -1 +1 @@
-      uses: ./old
+      uses: harvard-lil/lil-actions/ecr-tag-image@main
diff --git a/web/gen/bundle.js b/web/gen/bundle.js
--- a/web/gen/bundle.js
+++ b/web/gen/bundle.js
@@ -1 +1 @@
-x
+y
"""


@pytest.fixture
def files():
    return parse_diff(ACTIONS, source="actions") + parse_diff(H2O, source="h2o")


META = {
    "sources": [
        {"name": "actions", "label": "lil-actions", "range": "a...b"},
        {"name": "h2o", "label": "h2o", "range": "c...d"},
    ]
}


def test_key_is_qualified_by_source(files):
    assert files[0].key == "actions:ecs-build/action.yml"
    assert [f.key for f in files if f.path.endswith("main.yml")] == [
        "actions:.github/workflows/main.yml",
        "h2o:.github/workflows/main.yml",
    ]


def test_same_path_in_two_repos_gets_distinct_auto_ids(files):
    doc = build_document(files, {}, META)
    assert "file-actions-.github-workflows-main.yml" in doc.anchors
    assert "file-h2o-.github-workflows-main.yml" in doc.anchors
    assert not any("share the automatic id" in w for w in doc.warnings)


def test_qualified_pattern_matches_one_source_only(files):
    workflows = [f for f in files if matches(f, "actions:.github/**")]
    assert [f.key for f in workflows] == ["actions:.github/workflows/main.yml"]


def test_bare_pattern_applies_inside_every_source(files):
    both = [f for f in files if matches(f, ".github/workflows/*.yml")]
    assert len(both) == 2


def test_hide_with_a_bare_glob_still_works_across_sources(files):
    doc = build_document(files, {"hide": ["web/gen/**"]}, META)
    assert all("bundle.js" not in f.diff.path for f in doc.files)


def test_files_key_may_be_qualified_or_unambiguously_bare(files):
    spec = {
        "files": {
            "actions:.github/workflows/main.yml": {"title": "qualified"},
            "ecs-build/action.yml": {"title": "bare but unique"},
        }
    }
    doc = build_document(files, spec, META)
    titles = {f.diff.key: f.title for f in doc.files}
    assert titles["actions:.github/workflows/main.yml"] == "qualified"
    assert titles["actions:ecs-build/action.yml"] == "bare but unique"
    assert doc.warnings == []


def test_ambiguous_bare_key_warns_rather_than_guessing(files):
    doc = build_document(files, {"files": {".github/workflows/main.yml": {"title": "x"}}}, META)
    assert any("ambiguous across sources" in w for w in doc.warnings)
    # Neither file silently picks up the annotation.
    assert all(f.title == "" for f in doc.files)


# --- chapters ---------------------------------------------------------------


CHAPTERS = {
    "chapters": [
        {
            "title": "1. Make tagging possible",
            "note": "Nothing downstream works until this lands.",
            "id": "possible",
            "files": ["actions:ecs-build/action.yml"],
        },
        {"title": "2. Consume it", "files": ["h2o:.github/workflows/main.yml"]},
    ]
}


def test_chapters_order_files_and_record_their_boundaries(files):
    ordered, marks = order_and_chapter(files, CHAPTERS, [])
    assert [f.key for f in ordered][:2] == [
        "actions:ecs-build/action.yml",
        "h2o:.github/workflows/main.yml",
    ]
    assert [m["start"] for m in marks] == [0, 1, 2]
    # The unclaimed remainder becomes a closing untitled run.
    assert marks[-1]["title"] == ""


def test_a_star_inside_a_chapter_claims_the_remainder(files):
    spec = {
        "chapters": [
            {"title": "Everything else", "files": ["*"]},
            {"title": "Last", "files": ["h2o:.github/workflows/main.yml"]},
        ]
    }
    ordered, marks = order_and_chapter(files, spec, [])
    assert ordered[-1].key == "h2o:.github/workflows/main.yml"
    assert [m["title"] for m in marks] == ["Everything else", "Last"]
    # The second chapter's start moved past the files the wildcard absorbed.
    assert marks[1]["start"] == len(ordered) - 1


def test_chapters_and_order_together_warn_and_chapters_win(files):
    warnings = []
    spec = dict(CHAPTERS, order=["h2o:web/gen/bundle.js", "*"])
    ordered, marks = order_and_chapter(files, spec, warnings)
    assert any("ignoring `order`" in w for w in warnings)
    assert ordered[0].key == "actions:ecs-build/action.yml"


def test_chapter_headings_and_ids_render(files):
    doc = build_document(files, CHAPTERS, META)
    html = render_document(doc)
    assert '<section class="ld-chapter" id="ch-possible">' in html
    assert "<h2 class=\"ld-chapter-title\">1. Make tagging possible</h2>" in html
    # An untitled trailing chapter contributes no heading.
    assert html.count('class="ld-chapter"') == 2


def test_source_badges_appear_in_the_header_and_on_files(files):
    html = render_document(build_document(files, CHAPTERS, META))
    assert '<div class="ld-sources">' in html
    assert html.count('class="ld-src"') >= 4
    assert 'data-ld-src="actions"' in html


def test_cross_repo_reference_resolves_and_gets_a_direction(files):
    spec = dict(
        CHAPTERS,
        files={
            "h2o:.github/workflows/main.yml": {
                "note": "Needs [the action change](ld:#file-actions-ecs-build-action.yml)."
            }
        },
    )
    doc = build_document(files, spec, META)
    html = render_document(doc)
    assert "ld-ref-back" in html
    assert not doc.warnings, doc.warnings


def test_a_star_in_a_middle_chapter_shifts_only_later_chapters(files):
    spec = {
        "chapters": [
            {"title": "First", "files": ["actions:ecs-build/action.yml"]},
            {"title": "Middle", "files": ["*", "h2o:.github/workflows/main.yml"]},
            {"title": "Last", "files": ["h2o:web/gen/bundle.js"]},
        ]
    }
    ordered, marks = order_and_chapter(files, spec, [])
    starts = {m["title"]: m["start"] for m in marks}
    # Each chapter heading must land on the file it actually introduces.
    assert ordered[starts["First"]].key == "actions:ecs-build/action.yml"
    assert ordered[starts["Middle"]].key == "actions:.github/workflows/main.yml"
    assert ordered[starts["Last"]].key == "h2o:web/gen/bundle.js"
