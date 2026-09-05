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
# The skill in `.agents/skills/literate-diff/` sets out the sections it
# usually wants -- an executive summary, what each audience should take from
# the work, the story, terms, wins by kind, and how the decisions arrived.
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

## The conversation appendix

A batch built with agents has a second record beside the diff: what was asked
for, and what came back. `literate-diff` can carry that as an appendix the
narrative cites, so a claim in the plot can point at the sentence that prompted
it.

### Collecting is a separate phase

A git range is reproducible from the repository. Session logs are not: they are
local, mutable, and eventually deleted. So the transcript is collected once into
a file that lives beside the sidecar, the way a `.patch` file does, and builds
read that file rather than the logs.

```bash
uv run literate-diff collect --repo ../h2o \
    --title "Harbor registry Keycloak" --merge-by-title \
    -o conversations.yaml
```

`--repo` names the project whose sessions to read (Claude CLI JSONL under
`~/.claude/projects`). `--title` keeps sessions whose title contains it and is
repeatable; `--session` takes ids or id prefixes; `--since` drops earlier turns.
`--merge-by-title` treats sessions sharing a title as one thread in timestamp
order, dropping the turns a resumed session repeats from the one it continued.

Logs are stamped UTC, which is the wrong clock for a document about someone's
week — an evening turn reads as the next morning. `--timezone` sets the clock
times are shown on and turn ids are derived from; it defaults to the collecting
machine's and is written into the transcript, so a rebuild elsewhere does not
change what the document says.

The separation is also where redaction belongs. The output is plain YAML meant
to be read and cut before it is shared — prompts and replies quote whatever was
on screen, which includes printed environment, paths, and error output. Trim it
by hand; nothing regenerates it behind you.

### What a turn keeps

A turn is one prompt and everything that followed it, up to the next prompt.

- **The prompt**, verbatim, minus what the harness injected — system reminders,
  slash-command echoes, background-task notifications, interrupt markers.
- **The reply**: the last text block before the next prompt. Earlier text blocks
  are narration wrapped around tool calls ("Let me check X"), and are kept
  separately as a label for the band below.
- **The work between them**, as counts only: elapsed time, output tokens, tool
  calls by name, attachments by filename, thinking characters. It does not
  expand, and that is deliberate — the outcome of the work is the diff, and the
  transcript of it would be an order of magnitude larger than everything else
  here put together.

```yaml
threads:
  - id: promotion
    title: "Promoting an image instead of rebuilding it"
    sessions: [aaaa1111, bbbb2222]
    turns:
      - id: t0302-0914
        at: 2026-03-02T09:14:00Z
        prompt: |-
          Every deploy rebuilds from source on the prod branch, so what ships
          has never been tested.
        response: |-
          Not hard, and no service is needed. Promotion is a tag, not a copy.
        work: {seconds: 214, tokens: 4120}
        tools: {Bash: 12, Read: 4}
        narration:
          - |-
            Reading the workflow and the registry configuration first.
```

Turn ids are derived from when the turn happened, not from its position, so
collecting again after an earlier session turns up does not renumber the ids the
sidecar refers to.

### One stream, cut into chapters

Every thread's turns render as a single chronological stream. A side session
opened to think one thing through belongs where it was asked, not in a section
of its own, and a badge marks the turns where the stream crosses from one
session to another.

That leaves the chapters to be about the subject rather than the session, and
because the stream is chronological a chapter is fixed by the turn it opens at:

```yaml
appendix:
  title: "Appendix: the conversation"
  note: |
    Markdown, rendered above the stream.
  chapters:
    - id: sizing
      at: promotion:t0302-0914
      title: "Sizing one question, and getting a different answer"
      note: |
        Markdown, rendered where the chapter starts.
    - id: runtime
      at: aside:t0303-0900
      title: "One image for every tier"
```

Chapters may be declared in any order; they follow the stream. `ac-<id>` links
one.

### Annotating a turn

Point the sidecar at the file and annotate turns the way files are annotated.

```yaml
transcript: conversations.yaml

threads:
  promotion:
    title: "Promoting an image"   # overrides the collected title
    note: |
      Markdown, shown against this session in the appendix header.

turns:
  promotion:t0302-0914:
    id: q-promotion               # what `ld:` and `ldq:` address
    note: |
      Markdown, rendered above the turn.
    prompt: {at: "How hard is it to test one image"}
    response:                     # one passage, or several
      - {at: "Promotion is a tag, not a copy"}
      - {at: "The work is in the two things", through: "before you need it"}
    anchors:
      - {id: q-why, at: "the lifecycle policy", in: response}
```

A message is rows the way a file's diff is rows, so `at:`, `nth:`, `span:` and
`through:` mean what they mean everywhere else. The rows are sentences rather
than lines, because a prompt is usually one long paragraph and the part worth
quoting is a sentence of it; code, table and heading lines stay whole, and a
split is declined where it would cut an abbreviation, a list label (`A.`) or a
run of `**bold**`. The `+412` and `-88` line-number forms have nothing to
address here, but `@N` does.

`prompt:` and `response:` are the **highlight**: the part that shows. Give a
list where one decision turned on two passages that are pages apart — the
options and the recommendation, say. The rest of the message is in the page
behind a "show all" control inside the message, and a reference into a folded
row opens it.

Without a highlight, a message shows its opening **and its closing passage**.
The close is doing more work than its length suggests: it is what the next turn
answers — the recommendation, the question back, or, in a long paste, the thing
the person actually wanted asked. The opening stops on a paragraph boundary
rather than mid-argument, gives way at twice the budget for a paste with no
blank line in it, keeps a heading with the paragraph under it, and shows a short
tail rather than folding it, since hiding two sentences costs the reader more
than showing them.

Messages render as the markdown they were written in — headings, lists, tables,
fenced code, links — while every row keeps its own id, so a reference can still
land on one sentence inside a rendered list.

Every turn is addressable whether or not it is annotated, so the narrative can
quote one before the sidecar has an entry for it:

- `#turn-<thread>-<turn id>` — the turn (`#q-promotion` when `id:` is set)
- `#turn-<thread>-<turn id>-prompt`, `-response` — the first highlighted passage
- `-prompt2`, `-response2`, … — the second and later passages

`ld:` links to a turn and `ldq:` quotes it inline, exactly as they do for a
diff; quoting a message shows the words with no signs or line numbers, and a
link through to where they were said. The label decides the form: `[a
label](ldq:#id)` is a control the reader opens, `[](ldq:#id)` renders the
quoted words in place for prose that is reciting them, and `[](ld:#id)` is a
small citation marker for a sentence that has already said the thing and only
needs to say where it came from. Because the appendix follows the files,
references from the narrative into it point forward.

Turns are not interleaved with the diff. The diff is the document's spine and
the conversation is the record behind it; a chapter about work that left no
trace in the diff cites the turns rather than embedding them.

### On keeping all of it

The appendix is worth more comprehensive than curated. Two people read it: one
following how a decision was reached, who needs the turns in order rather than
the good ones; and one deciding how hard to review the diff, for whom "ok go
ahead" next to a link to a failing run is the evidence, not the noise. A
selection of the turns where the answer was good is a third thing, and reads
like one.

Cut for confidentiality. Keep the rest, and let the highlights carry the
reading.

## Size

The output is one file with no external requests, so its size is the size of
the markup. Most of that is per-line addressing: every diff row and every
sentence of the conversation carries an id, which is what lets `ld:` and `ldq:`
land on one line.

Files that render folded shut are the exception. A collapsed file costs about
145 bytes of table scaffolding per line for about 47 bytes of code, for content
nobody has asked to see, so it ships as rows in `window.LD_ROWS` and the table
is built the first time the file is opened — by a click, or by a reference
pointing into it. Nothing is lost that worked before: a folded `<details>` is
already invisible to find-in-page, and the rows are still plain text in the
file. On a 178-file document that is about 0.4 MB.

Serving the file over HTTP makes most of this moot — it gzips to about a sixth.
The size matters when it is emailed or dropped in a bucket uncompressed.

## Layout notes

Sidenotes are positioned in the right margin against their anchor line, pushed
down as needed so they never overlap; below 62rem they fold into the diff table
underneath the line they annotate. Both light and dark themes follow the
reader's system setting.

## Example

[`examples/feature-tour/`](examples/feature-tour/) is a small invented
change, an app repository and an infrastructure repository as two patch
files, with an invented two-session transcript beside them, annotated with
every feature: sources, categories and flags, chapters, hiding and folding,
sections, sidenotes, quotes, each anchor form, and a conversation appendix —
interleaved, chaptered, with a two-passage highlight — that the plot cites. The
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
its forms, ordering and glob handling, the rendered output — reference
direction, quoting, escaping, and the anchor map handed to the client script —
and the conversation side: what the collector keeps and discards from a session
log, how resumed sessions merge, sentence splitting that declines to cut a
label or a bold run, markdown blocks rebuilt around addressable rows,
multi-passage highlights, interleaving, and appendix chapters.
