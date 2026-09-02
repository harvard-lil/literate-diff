from literate_diff.parse import parse_diff

MODIFY = """\
diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -3,4 +3,5 @@ def handler():
 context one
-old line
+new line
+extra line
 context two
"""


def test_modified_file_line_numbering():
    (f,) = parse_diff(MODIFY)
    assert f.path == "app.py"
    assert f.status == "modified"
    assert (f.additions, f.deletions) == (2, 1)

    kinds = [line.kind for line in f.lines]
    assert kinds == ["hunk", "context", "del", "add", "add", "context"]

    hunk, ctx1, dele, add1, add2, ctx2 = f.lines
    assert hunk.text == "def handler():"
    # Old and new sides advance independently.
    assert (ctx1.old_no, ctx1.new_no) == (3, 3)
    assert (dele.old_no, dele.new_no) == (4, None)
    assert (add1.old_no, add1.new_no) == (None, 4)
    assert (add2.old_no, add2.new_no) == (None, 5)
    assert (ctx2.old_no, ctx2.new_no) == (5, 6)


def test_row_index_is_position_within_the_file():
    (f,) = parse_diff(MODIFY)
    assert [line.index for line in f.lines] == list(range(6))


def test_added_and_deleted_files():
    text = """\
diff --git a/new.py b/new.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/new.py
@@ -0,0 +1 @@
+hello
diff --git a/gone.py b/gone.py
deleted file mode 100644
index 4444444..0000000
--- a/gone.py
+++ /dev/null
@@ -1 +0,0 @@
-goodbye
"""
    new, gone = parse_diff(text)
    assert (new.path, new.status) == ("new.py", "added")
    assert (gone.path, gone.status) == ("gone.py", "deleted")
    # A deleted file is addressed by the path it had.
    assert gone.old_path == "gone.py"


def test_rename_reports_both_paths():
    text = """\
diff --git a/old/name.py b/new/name.py
similarity index 92%
rename from old/name.py
rename to new/name.py
index 5555555..6666666 100644
--- a/old/name.py
+++ b/new/name.py
@@ -1 +1 @@
-a
+b
"""
    (f,) = parse_diff(text)
    assert f.status == "renamed"
    assert f.old_path == "old/name.py"
    # The display path follows the file to where it now lives.
    assert f.path == "new/name.py"


def test_binary_payload_is_summarised_not_parsed():
    text = """\
diff --git a/logo.png b/logo.png
index 7777777..8888888 100644
GIT binary patch
literal 12
zcmZQzU|?_ppQ
literal 0
HcmV?d00001

diff --git a/after.py b/after.py
index 9999999..aaaaaaa 100644
--- a/after.py
+++ b/after.py
@@ -1 +1 @@
-x
+y
"""
    logo, after = parse_diff(text)
    assert logo.binary is True
    assert [line.kind for line in logo.lines] == ["message"]
    # The payload must not leak into the next file.
    assert after.path == "after.py"
    assert (after.additions, after.deletions) == (1, 1)


def test_quoted_paths_with_spaces():
    text = """\
diff --git "a/dir/some file.py" "b/dir/some file.py"
index bbbbbbb..ccccccc 100644
--- "a/dir/some file.py"
+++ "b/dir/some file.py"
@@ -1 +1 @@
-a
+b
"""
    (f,) = parse_diff(text)
    assert f.path == "dir/some file.py"


def test_no_newline_marker_becomes_a_message_row():
    text = """\
diff --git a/f.txt b/f.txt
index ddddddd..eeeeeee 100644
--- a/f.txt
+++ b/f.txt
@@ -1 +1 @@
-a
\\ No newline at end of file
+b
"""
    (f,) = parse_diff(text)
    kinds = [line.kind for line in f.lines]
    assert kinds == ["hunk", "del", "message", "add"]
    assert f.lines[2].text == "No newline at end of file"
    # The marker is not counted as a change.
    assert (f.additions, f.deletions) == (1, 1)


def test_preamble_before_the_first_file_is_ignored():
    text = "commit abc123\nAuthor: Someone\n\n    A message\n\n" + MODIFY
    (f,) = parse_diff(text)
    assert f.path == "app.py"


def test_single_hunk_shorthand_counts():
    # `@@ -1 +1 @@` omits the length, which defaults to 1.
    text = """\
diff --git a/f.py b/f.py
--- a/f.py
+++ b/f.py
@@ -7 +7 @@
-a
+b
"""
    (f,) = parse_diff(text)
    assert f.lines[1].old_no == 7
    assert f.lines[2].new_no == 7
