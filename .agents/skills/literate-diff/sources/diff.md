# Source: diff

A git range in one repository, or a patch file. Files are the items; rows
are diff lines; `+N`/`-N` address a line by new-side or old-side number.

## Choose the range

Ask what the reader should compare: usually "before this work" to "now".
For one repository, `repo:` and `range: base...tip`. For work that spans
repositories, one source per repository, and address files as
`source:path`. Include a repository the change reaches without a commit in
the primary one: a shared action referenced at `@main`, the Terraform
behind a workflow. Resolve the reviewed endpoints to full commit IDs for a dated account.
Remote-tracking refs can also lag and should not silently move the record.
Use `pathspec:` to document exclusions. Fetching or modifying git state still
requires the user's authorization.

Print the file list first, and again whenever the branch moves:

```bash
uv run literate-diff -a notes.yaml --outline
```

## Copy of record

A range with fixed commit endpoints is reproducible from the repository; the build reads `git diff` and embeds the patch in the page.
For a repository that is not to hand, `diff: changes.patch` reads a patch
file instead.

## Read

Read every file that will be annotated, not the outline. Anchors are
substrings of diff rows, and a note has to say what the lines do. Note for
the change ledger which outcome each file serves; a file that serves none
is housekeeping.

## Annotate

Files go in a stream layer with `chapters:`. Put files in dependency
order: what had to exist before the next thing could use it, which is
rarely merge order or alphabetical order. Each chapter gets a title and a
short note saying why the reader has moved. Put `*` in a closing
"Housekeeping" chapter. `hide:` lock files and generated output;
`collapse:` files that are present for completeness (provider blocks,
outputs, renames, formatting).

For each file that carries part of the story, under `files:` (or the
layer's `items:`):

- `title:` a phrase shown beside the path, for the table of contents.
- `note:` what the file's change is in the story, with `[](ldc:#id)` flags
  for the items it delivers and `ld:` links to related anchors.
- `sections:` a band across the diff at a row (`at:`), with an `id` other
  notes can link to.
- `notes:` sidenotes on a row or span (`at:` plus `span:` or `through:`).
- `ldq:` to quote another anchor's lines inline where the reader needs them
  without jumping.

Prefer a distinctive substring from a comment or a unique token as an
anchor, because those survive unrelated commits above them. When one string
appears in both tiers or both stages, pick another string or pin with
`nth`. An anchor that matches twice warns; `nth: 1` does not silence it,
because restating the default is not evidence the matches were counted.

## When the draft scope changes

Rebuild with the new range and read stderr: an anchor that no longer
matches, an anchor that now matches more than once (a comment quoting the
code, added above the line), new files landing at `*` unannotated, and
`files:` keys that name nothing. Merged branches that were separate sources
stop contributing files; fold their annotations into the main source.

Keep the endpoints of a completed episode fixed. Later corrections should
identify their review date and preserve the originally observed state.
