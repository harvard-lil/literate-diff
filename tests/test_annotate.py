import pytest

from literate_diff.annotate import (
    AnnotationError,
    build_document,
    order_files,
    resolve_anchor,
)
from literate_diff.parse import parse_diff

DIFF = """\
diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -10,3 +10,4 @@ def outer():
 keep me
-drop me
+add me
+add me twice
diff --git a/b.py b/b.py
--- a/b.py
+++ b/b.py
@@ -1,2 +1,2 @@
-old b
+new b
diff --git a/gen/bundle.js b/gen/bundle.js
--- a/gen/bundle.js
+++ b/gen/bundle.js
@@ -1 +1 @@
-x
+y
"""


@pytest.fixture
def files():
    return parse_diff(DIFF)


# --- ordering ---------------------------------------------------------------


def test_order_places_unnamed_files_at_the_star(files):
    warnings = []
    spec = {"order": ["b.py", "*", "a.py"]}
    assert [f.path for f in order_files(files, spec, warnings)] == [
        "b.py",
        "gen/bundle.js",
        "a.py",
    ]
    assert warnings == []


def test_order_without_a_star_appends_the_remainder(files):
    got = order_files(files, {"order": ["b.py"]}, [])
    assert [f.path for f in got] == ["b.py", "a.py", "gen/bundle.js"]


def test_hide_accepts_globs_and_runs_before_order(files):
    got = order_files(files, {"hide": ["gen/**"], "order": ["*"]}, [])
    assert [f.path for f in got] == ["a.py", "b.py"]


def test_order_entry_matching_nothing_warns_without_failing(files):
    warnings = []
    got = order_files(files, {"order": ["nope.py", "*"]}, warnings)
    assert [f.path for f in got] == ["a.py", "b.py", "gen/bundle.js"]
    assert len(warnings) == 1 and "nope.py" in warnings[0]


# --- anchoring --------------------------------------------------------------


def test_substring_anchor_finds_the_first_match(files):
    a = resolve_anchor(files[0], {"at": "add me"}, [])
    assert files[0].lines[a.start].text == "add me"
    assert a.start == a.end


def test_nth_selects_a_later_occurrence(files):
    a = resolve_anchor(files[0], {"at": "add me", "nth": 2}, [])
    assert files[0].lines[a.start].text == "add me twice"


def test_regex_anchor(files):
    a = resolve_anchor(files[0], {"at": "/^drop/"}, [])
    assert files[0].lines[a.start].text == "drop me"


def test_side_qualified_line_number_anchors(files):
    # The hunk is `@@ -10,3 +10,4 @@`, so both sides start numbering at 10.
    lines = files[0].lines
    new_side = resolve_anchor(files[0], {"at": "+12"}, [])
    assert lines[new_side.start].text == "add me twice"
    old_side = resolve_anchor(files[0], {"at": "-11"}, [])
    assert lines[old_side.start].text == "drop me"


def test_line_number_on_the_wrong_side_warns_and_falls_back(files):
    # Line 11 exists on the old side only; asking for it on the new side is a miss.
    warnings = []
    a = resolve_anchor(files[0], {"at": "+99"}, warnings)
    assert a.start == 0
    assert len(warnings) == 1 and "+99" in warnings[0]


def test_raw_row_index_anchor(files):
    a = resolve_anchor(files[0], {"at": "@0"}, [])
    assert files[0].lines[a.start].kind == "hunk"


def test_span_and_through_define_a_range(files):
    span = resolve_anchor(files[0], {"at": "keep me", "span": 3}, [])
    assert (span.start, span.end) == (1, 3)
    through = resolve_anchor(files[0], {"at": "keep me", "through": "add me twice"}, [])
    assert (through.start, through.end) == (1, 4)


def test_span_is_clamped_to_the_end_of_the_file(files):
    a = resolve_anchor(files[0], {"at": "keep me", "span": 999}, [])
    assert a.end == len(files[0].lines) - 1


def test_a_bare_string_is_shorthand_for_at(files):
    assert resolve_anchor(files[0], "add me", []).start == 3


def test_unmatched_anchor_warns_and_falls_back(files):
    warnings = []
    a = resolve_anchor(files[0], {"at": "not present"}, warnings)
    assert a.start == 0
    assert len(warnings) == 1 and "not present" in warnings[0]


def test_anchor_without_at_is_an_error(files):
    with pytest.raises(AnnotationError):
        resolve_anchor(files[0], {"span": 2}, [])


# --- assembly ---------------------------------------------------------------


def test_build_document_registers_ids_and_auto_file_anchors(files):
    spec = {
        "order": ["b.py", "a.py", "*"],
        "files": {
            "a.py": {
                "notes": [{"at": "add me", "id": "the-note", "text": "hi"}],
                "anchors": [{"id": "invisible", "at": "keep me", "span": 2}],
            }
        },
    }
    doc = build_document(files, spec, {})
    assert [f.diff.path for f in doc.files] == ["b.py", "a.py", "gen/bundle.js"]

    # Explicit ids resolve, and every file gets one automatically.
    assert doc.anchors["the-note"].start == 3
    assert (doc.anchors["invisible"].start, doc.anchors["invisible"].end) == (1, 2)
    assert "file-a.py" in doc.anchors
    assert doc.anchors["f0"].file.path == "b.py"


def test_configuring_a_file_that_is_not_in_the_diff_warns(files):
    doc = build_document(files, {"files": {"absent.py": {"note": "x"}}}, {})
    assert any("absent.py" in w for w in doc.warnings)


def test_collapse_glob_marks_files_folded(files):
    doc = build_document(files, {"collapse": ["gen/**"]}, {})
    folded = {f.diff.path: f.collapsed for f in doc.files}
    assert folded == {"a.py": False, "b.py": False, "gen/bundle.js": True}
