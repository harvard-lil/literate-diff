# literate-diff

Turns a git diff plus a YAML annotation sidecar into a single, self-contained
HTML file: a diff arranged and annotated as a narrative rather than as a list of
changed files.

```bash
uv run literate-diff --repo ../some-repo --range prod...main \
    -a notes.yaml -o review.html
```

The output has no external requests — CSS and JS are inlined — so it can be
emailed, dropped in a bucket, or attached to a ticket.

## Why not annotate GitHub's page

GitHub's compare view renders its diffs client-side. A saved copy of
`/compare/prod...main` contains the commit list and page chrome but none of the
diff text, so there is nothing to inject annotations into. "Save as web page,
complete" captures only what the virtualized DOM had rendered at save time.
Generating the page is also what makes file reordering and mid-file section
bands possible at all.

## Input

Either a repo and a range:

```bash
literate-diff --repo path/to/repo --range prod...main
```

or a diff that already exists, which is useful when the repo is not to hand:

```bash
git diff prod...main > changes.patch
literate-diff --diff changes.patch
# or: git diff prod...main | literate-diff --diff -
```

`--pathspec` limits the diff, `-U/--context` sets context lines.

To start a sidecar, `--outline` prints a YAML skeleton listing every file in the
diff:

```bash
literate-diff --repo path/to/repo --range prod...main --outline > notes.yaml
```

## The annotation file

Every key is optional; with no sidecar you get a plain readable diff.

```yaml
title: "One build graph"
subtitle: "Making CI test the artifact that ships"

# The Plot: why this batch exists, and what the reader is about to see.
plot: |
  Markdown. Rendered at the top, above every file.

# Files render in this order; '*' is everything not named above. Globs work.
order:
  - web/config/settings/__init__.py
  - Dockerfile
  - "*"

hide:                        # dropped entirely
  - "web/static/dist/**"
collapse:                    # rendered, but folded shut
  - "web/package-lock.json"

files:
  Dockerfile:
    title: one build graph   # shown next to the path
    collapsed: false
    note: |                  # File-level: introduces the file, in the story
      Markdown, rendered above the diff.

    sections:                # File-section-level: a band inside the diff
      - at: "FROM prod AS test"
        id: dockerfile-test
        title: "test — what CI runs the suite against"
        note: "Markdown."

    notes:                   # Line-level: a sidenote in the right margin
      - at: "ENV H2O_SETTINGS_MODULE"
        span: 1
        id: settings-env
        text: "Markdown. A footnote, not part of the story."

    anchors:                 # Named ranges with no visible output, for linking
      - id: uwsgi-build
        at: "CPUCOUNT=1"
        span: 5
```

### Anchoring

`at:` locates a row in that file's diff. Ordering is by position in the diff, so
an anchor is stable against changes elsewhere in the batch.

| form | meaning |
| --- | --- |
| `"some text"` | first diff row containing that substring |
| `/regex/` | first row matching the regex |
| `+412` | the row that is line 412 on the new side |
| `-88` | the row that is line 88 on the old side |
| `@37` | the 37th row of this file's diff, counting from 0 |

`nth: 2` takes the second match rather than the first. A range extends with
either `span: 5` (five rows) or `through: "other text"` (up to the next match).

An unmatched anchor is a warning on stderr, not an error: it falls back to the
top of the file so the build still produces something readable.

### References and quotes

Inside any annotation, a markdown link with the `ld:` scheme points at an `id`
elsewhere in the document:

```markdown
See [the settings switch](ld:#settings-switch) for where this value comes from.
```

The arrow (`↑` back, `↓` forward) is computed from position in the rendered
document, so reordering files cannot leave a "see below" pointing upward.
Clicking opens the target's file if it is collapsed, scrolls to it, and
highlights the anchored lines.

The `ldq:` scheme quotes instead of linking: it renders the target's diff lines
inline as a collapsed block, with a link through to their context. Useful for
referring to a span of a file that had to appear early.

```markdown
The value being overridden is [set here](ldq:#dockerfile-settings-env).
```

Every file also gets an automatic id, `#file-<path with non-word chars
hyphenated>` — e.g. `ld:#file-web-frontend_assets.py`.

## Layout notes

Sidenotes are positioned in the right margin against their anchor line, pushed
down as needed so they never overlap; below 62rem they fold into the diff table
underneath the line they annotate. Both light and dark themes follow the
reader's system setting.

## Example

`examples/h2o-prod-to-main.yaml` annotates harvard-lil/h2o `prod...main`
(88 files, 13 commits) and exercises every feature. Run it from a workspace
where `h2o` is checked out alongside this repo:

```bash
uv run literate-diff --repo ../h2o --range b10e1336...1e774212 \
    -a examples/h2o-prod-to-main.yaml -o out/h2o.html
```

## Development

```bash
uv sync
uv run pytest
```

The tests cover the diff parser (renames, binary payloads, quoted paths,
missing-newline markers, per-side line numbering), anchor resolution in all of
its forms, ordering and glob handling, and the rendered output — reference
direction, quoting, escaping, and the anchor map handed to the client script.
