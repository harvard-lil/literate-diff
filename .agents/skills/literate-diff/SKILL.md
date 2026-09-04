---
name: literate-diff
description: Turn a git diff (one repo or several) into an annotated, single-file HTML narrative with literate-diff. Use when asked to write up, review, explain, or tell the story of a change, a branch, a release, or a week of work across repositories, or to produce a "litdiff".
---

# Make a literate diff

A literate diff is a diff arranged as a story: a plot at the top that says why
the batch exists and what it achieved, chapters that put files in the order a
reader needs rather than alphabetical order, and notes on the lines that carry
the argument. The tool is `literate-diff` in this repository; the README is
the reference for every key. This skill is the working order.

Run it from a checkout of this repository, with the repositories being
described checked out beside it:

```bash
uv run literate-diff -a notes.yaml -o out/review.html
```

or without a checkout:

```bash
uvx --from git+https://github.com/harvard-lil/literate-diff literate-diff -a notes.yaml -o out/review.html
```

## 1. Decide the range and the sources

Ask what the reader should compare: usually "before this work" to "now". For
one repository that is `--repo ../repo --range base...tip`. For work that
spans repositories, declare each as a named source in the sidecar and address
files as `source:path`; include a repository the change reaches without a
commit in the primary one (a shared action referenced at `@main`, the
Terraform behind a workflow). Use `origin/main` rather than a local branch
when the checkout may lag, and `pathspec:` to keep unrelated changes in the
same range out.

Print the file list first:

```bash
uv run literate-diff -a notes.yaml --outline
```

## 2. Read the whole diff before writing

Read every file that will be annotated, not the outline. Anchors are
substrings of diff rows, and the notes have to say what the lines do. If the
work happened in a thread or a ticket, read that too: decisions, rejected
alternatives, measurements and incidents are what a diff cannot show, and
they are what the plot is made of. For a long thread, digest it in chunks
before writing.

## 3. Write the plot

The plot is markdown at the top. In order:

- **The story** in a few paragraphs: what was true before, what is true now,
  and the property the whole batch is organised around. Say where things
  stood when the document was written if the work is still moving.
- **Terms**, if the audience will meet concepts outside their daily work.
  Define each in one line, for the reader the document is for.
- **Wins, by kind**, as category lists. Declare the categories under
  `categories:` (label, optional `short:` letter and `color:`), then in the
  plot put `{category: name}` on the line before an ordered list. Give items
  ids with `{#id}` so flags survive reordering. Every item states what was
  true before and what is true now; a mechanism, or a bug the work itself
  introduced and fixed, is not a win.
- **The other side**: regressions and trade-offs, then bugs introduced and
  fixed during the work (their own category, since they explain code that
  looks over-cautious), then future work.

Flag each item where it is delivered with `[](ldc:#id)` in a file, section
or line note. The renderer numbers and colours the flag, shows the item on
hover, and lists on the item every place it is flagged. Link to an item in
prose with `ld:#cat-id`.

## 4. Cut the diff into chapters

`chapters:` replaces `order:`. Put files in dependency order: what had to
exist before the next thing could use it, which is rarely merge order or
alphabetical order. Each chapter gets a title and a short note saying why the
reader has moved. Put `*` in a closing "Housekeeping" chapter. `hide:` lock
files and generated output; `collapse:` files that are present for
completeness (provider blocks, outputs, renames, formatting).

## 5. Annotate files

For each file that carries part of the story:

- `title:` a phrase shown beside the path, for the table of contents.
- `note:` what the file's change is in the story, with flags for the items it
  delivers and `ld:` links to related anchors elsewhere.
- `sections:` for a band across the diff at a row (`at:`), with an `id` other
  notes can link to.
- `notes:` for sidenotes on a row or span (`at:` plus `span:` or `through:`).
- `ldq:` to quote another anchor's lines inline where the reader needs them
  without jumping.

Anchors are substrings by default; a regex (`/…/`), a new-side line (`+N`),
an old-side line (`-N`) or a row index (`@N`) also work. Prefer a distinctive
substring from a comment or a unique token, because those survive unrelated
commits above them. When one string appears in both tiers or both stages,
pick another string or pin with `nth`.

## 6. Build, read stderr, repeat

```bash
uv run literate-diff -a notes.yaml -o out/review.html
```

Every warning names a fix: an anchor that no longer matches, an anchor that
matches more than once (narrow it or set `nth`; `nth: 1` does not silence
it), a `files:` key not in the diff, a reference to an unknown id, a flag to
an undeclared category item. A clean build has none. Check the rendered
page for broken references (`ld-ref-broken`) and that every category item is
flagged somewhere; an unflagged win usually means the annotation for its
file is missing.

When the branch moves, re-run `--outline` to see what arrived, rebuild, and
fix the warnings. Merged branches that were separate sources stop
contributing files; fold their annotations into the main source.

## Writing

The document is read by people who did not watch the work. Lead each note
with what the lines do, then why. Quote measurements with their basis (a
run log, a thread, a list price). Keep the plot's claims to what the diff
and the record support; say what was not verified.
