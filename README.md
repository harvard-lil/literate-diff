# literate-diff

Turns a git diff plus a YAML annotation sidecar into a single, self-contained
HTML file: a diff arranged and annotated as a narrative rather than as a list of
changed files.

```bash
uv run literate-diff --repo ../some-repo --range prod...main \
    -a notes.yaml -o review.html
```

Or, without cloning this repository:

```bash
uvx --from git+https://github.com/harvard-lil/literate-diff literate-diff \
    --repo ../some-repo --range prod...main -a notes.yaml -o review.html
```

The output has no external requests — CSS and JS are inlined — so it can be
emailed, dropped in a bucket, or attached to a ticket.

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

## More than one repository

A change often spans repos: h2o pins `harvard-lil/lil-actions/…@main`, so an
action change reaches it with no commit in h2o at all, and the registry it
deploys into is defined in lil-terraform. Reading any one diff alone hides most
of the story.

Declare the repos as named sources and address files as `source:path`:

```yaml
sources:
  actions: {repo: ../lil-actions, range: 48b57bb...e626b6e}
  tf:
    repo: ../lil-terraform
    range: f6b5a5e...9fadc90
    pathspec: [h2o/aws, legacy/primary/us-east-1/ecr]
  h2o: {repo: ../h2o, range: prod...main}
```

A source may also take `label:` (display name), `diff:` (a patch file instead of
a repo and range), and its own `context:`. Sources can be added from the command
line too, repeatably: `--source actions=../lil-actions@48b57bb...e626b6e`.

With sources declared, `order:`, `hide:`, `collapse:` and the keys under
`files:` all accept qualified keys. A pattern **with** a `source:` prefix matches
that repo only; a **bare** pattern matches the path inside every repo, so
`hide: ["**/node_modules/**"]` means the same thing everywhere and single-repo
sidecars keep working. A bare key under `files:` is fine when it is unambiguous;
when two repos share the path, it is reported rather than guessed at.

References need nothing new — ids are document-global, so `ld:` and `ldq:` cross
repositories exactly as they cross files, arrows included. Automatic file ids
include the source (`#file-actions-ecs-build-action.yml`), so two repos with the
same path do not collide.

### Chapters

Across several repos the reader needs to be told why the document just moved
from one to another. `chapters:` replaces `order:` and cuts it into titled,
annotated runs:

```yaml
chapters:
  - id: mechanism
    title: "1. A way to tag an image without rebuilding it"
    note: |
      Promotion needs an operation that marks an existing image as deployed.
      That operation did not exist yet.
    files:
      - actions:ecr-tag-image/action.yml
      - actions:ecs-build/action.yml

  - title: "2. A registry that will accept it"
    files:
      - "tf:**/ecr/**"

  - title: "Everything else"
    files: ["*"]
```

`*` may appear inside any chapter's `files:` and takes the remainder there;
without one, unclaimed files become a closing untitled run. A chapter's `id`
makes it linkable as `ld:#ch-<id>`. Setting both `chapters:` and `order:` warns
and uses chapters.

### Categories

A plot that lists what a batch achieved -- by kind of win: security,
performance, cost -- wants a way to point from each claim to the lines that
deliver it, and back. `categories:` declares the kinds; a list in any
annotation is bound to one by a `{category: name}` marker on the line before it,
and any annotation can then cite an item with an `ldc:` flag.

```yaml
categories:
  security: Security
  cost: {label: Cost, color: "#882255", short: "$"}

plot: |
  ## Security

  {category: security}
  1. {#build-role} Builds publish under a role that cannot deploy.
  2. Deploy roles trust one GitHub environment each, not every branch.

files:
  tf:h2o/aws/iam/iam_role.tf:
    note: |
      The build role [](ldc:#build-role) is this resource.
```

Items are numbered by position and coloured by category. The colours come from
Paul Tol's muted scheme, which stays distinguishable under the common forms of
colour-vision deficiency; `color:` overrides one, and `short:` prefixes the
number (`$1`) where colour alone should not carry the distinction. An item may
carry an id in `{#id}`; without one it is addressable as `name-N`.

A flag `[](ldc:#build-role)` renders as the item's coloured number. Hovering it
shows the item's text; clicking it goes to the item. Each item in turn lists the
places that flag it, with the usual direction arrows, so the plot doubles as an
index into the evidence. A label inside the brackets is kept after the badge.

Flags may cite items defined anywhere in the document; the renderer makes two
passes. An unknown item, or an undeclared category, is reported on stderr. Nested
ordered lists inside a category list are not supported.

## Updating a document as the branch moves

Annotations are written against a diff that is still changing. The workflow is
to keep the sidecar next to the branch, rebuild with the new range, and read
stderr:

```bash
uv run literate-diff --repo ../h2o --range prod...main -a notes.yaml -o out/review.html
```

Content anchors are chosen so most of them survive: they follow the line they
name rather than a line number, so unrelated commits above them cost nothing.
Three things do change, and each reports itself.

**An anchor that no longer matches** warns and falls back to the top of its
file, so the build still produces something readable rather than failing at the
last step before you share it.

**An anchor that now matches more than once** warns too, and this is the case
worth understanding. It is not that the anchor breaks — it keeps working and
starts meaning something else. The usual cause is a commit adding a comment
that quotes the code, which lands *above* the line you meant:

```
w.yml: 'secrets: inherit' matches 2 rows; using the first (line 11).
       Narrow the pattern or set `nth` to pin it.
```

Fix it by narrowing the pattern, or by setting `nth` if you want a later match.
`nth: 1` does not silence this — restating the default is not evidence you
counted the matches, and the whole point is to be told when the count changes.

**New files** land wherever `*` sits, unannotated, and appear in the table of
contents. Files that leave the diff are reported as `files:` keys that no
longer match anything.

Re-running `--outline` against the new range prints the current file list, which
is a quick way to see what arrived.

## Layout notes

Sidenotes are positioned in the right margin against their anchor line, pushed
down as needed so they never overlap; below 62rem they fold into the diff table
underneath the line they annotate. Both light and dark themes follow the
reader's system setting.

## Example

[`examples/feature-tour/`](examples/feature-tour/) is a small invented
change, an app repository and an infrastructure repository as two patch
files, annotated with every feature: sources, categories and flags, chapters,
hiding and folding, sections, sidenotes, quotes, and each anchor form. The
rendered output is committed beside it as
[`feature-tour.html`](examples/feature-tour/feature-tour.html). Rebuild it
from the repository root, since `diff:` paths resolve from the current
directory:

```bash
uv run literate-diff -a examples/feature-tour/notes.yaml \
    -o examples/feature-tour/feature-tour.html
```

The test suite builds it and fails on any warning.

## Writing one

[`.agents/skills/literate-diff/SKILL.md`](.agents/skills/literate-diff/SKILL.md)
is the working order for producing a document: choosing ranges and sources,
reading the diff and the record behind it, writing the plot and its category
lists, cutting chapters, annotating, and iterating on the build's warnings.
It is written for an agent and reads as a checklist for a person.

## Development

```bash
uv sync
uv run pytest
```

The tests cover the diff parser (renames, binary payloads, quoted paths,
missing-newline markers, per-side line numbering), anchor resolution in all of
its forms, ordering and glob handling, and the rendered output — reference
direction, quoting, escaping, and the anchor map handed to the client script.
