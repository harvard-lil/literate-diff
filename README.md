# literate-diff

Builds a **debrief**: one self-contained HTML file, from a YAML sidecar and
a set of sources (a git diff across one or more repositories, the agent
conversations behind it, notes, reference documents, a glossary). A debrief
has three parts. A *summary* says what the author wants each reader to
know. A *synthesis* says why the author believes it, every claim citing its
evidence, with the ones that cite nothing marked. The *evidence* is the
record itself, embedded whole. The file says how to read itself, so it can
be dragged into Slack or attached to a ticket and still be queried by a
script or handed to an agent as a knowledge base. `DESIGN.md` has the
vocabulary; a literate diff is the code block of a debrief.

```bash
uv run literate-diff -a notes.yaml -o review.html
```

Or, without cloning this repository:

```bash
uvx --from git+https://github.com/harvard-lil/literate-diff literate-diff \
    -a notes.yaml -o review.html
```

[`.agents/skills/literate-diff/SKILL.md`](.agents/skills/literate-diff/SKILL.md)
is the working order for writing one; [`DESIGN.md`](DESIGN.md) is the
architecture. This file is the reference for every key.

## Authoring a team debrief

[Writing a work debrief](docs/debrief-authoring.md) defines success: colleagues
can understand the result, act on it and choose where to review more closely.
It covers evidence status, corrections and reversals, optional system models,
role summaries, navigation copy and cold reads. Read it with the
[authoring skill](.agents/skills/literate-diff/SKILL.md); a clean build verifies
links and structure, not the truth or completeness of the account.


## The shape of a document

```yaml
title: "One image, dev to prod"
subtitle: "h2o's deploy overhaul, 31 August to 4 September"

brief:            # not rendered: who this is for and why (see the skill)
  readers: [...]

sources:          # the evidence, each with a type
  h2o:     {repo: ../h2o, range: 63da32f3...origin/main}
  chat:    {type: transcript, file: conversations.yaml}
  said:    {type: notes, items: [...]}
  terms:   {type: terms, items: [...]}

categories:       # kinds of claim, for the numbered lists
  security: {label: Security, short: S}

layers:           # the debrief, top to bottom
  - id: summary
    group: summary
    title: Executive summary
    subtitle: What changed, and what still needs checking.
    audience: anyone
    budget: 1 minute
    claims: required
    text: |
      {claims}
      - Deploys no longer take the site down by default [](ldc:#window-when-needed).
  - id: developers
    group: summary
    row: 2
    title: Developers
    text: ...
  - id: improvements
    group: synthesis
    title: Improvements
    subtitle: Changes to reliability, security, development, and cost.
    text: |
      {category: security}
      1. {#oidc-scope} Before, ... Now, ...
  - id: code
    kind: stream
    group: evidence
    title: Code
    sources: [h2o]
    chapters: [...]
  - id: conversation
    kind: stream
    group: evidence
    title: Conversation
    sources: [chat]
    chapters: [...]

files:            # per-file annotations for diff sources
  Dockerfile: {title: ..., note: ..., sections: [...], notes: [...]}
turns:            # per-turn annotations for transcript sources
  main:t0901-0913: {id: q-widen, prompt: {at: "..."}}
```

Every key is optional. With no sidecar at all, `--repo` and `--range` give
a plain readable diff.

### The v1 shape still works

A sidecar with `plot:`, `chapters:`/`order:`, `hide:`, `collapse:`,
`files:`, `transcript:`, `appendix:`, `threads:` and `turns:` and no
`layers:` is read as three layers: one prose layer from the plot, one stream
of the diff sources, one stream of the transcript. It renders as it did
before, without layer headers or the map. Move to `layers:` when the
document is next edited.

## Layers

A layer is prose (`text:`) or a stream (`kind: stream`, `sources:`). It
belongs to a `group` (`summary`, `synthesis` or `evidence`; prose defaults
to synthesis, streams to evidence) and a `row` within the group. Its
`title` names the subject or question; an optional `subtitle` clarifies what the block
contains and where it came from; those two render in the header and on the
map. `audience` and `budget` are metadata for the brief, the lint and the
cold read, shown on hover in the map.

The map draws the groups as rows of boxes, each group wider than the one
above, full size after the header as the top-level contents and again as a
postage stamp in the margin with the box in view marked.

```yaml
layers:
  - id: builders
    group: summary
    row: 2
    title: Deploy builders
    subtitle: What to reuse, and the habit to drop, when setting up a deploy elsewhere.
    audience: someone about to build the next deploy
    budget: 3 minutes          # or "600 words"; the lint reports overruns
    claims: required           # an unsupported claim is a warning, not just a mark
    text: |
      Markdown.
  - id: code
    kind: stream
    group: evidence
    title: Code
    subtitle: The annotated diff, in dependency order.
    sources: [h2o, actions]    # one or more sources of one ordering kind
    hide: ["**/dist/**"]
    collapse: ["**/package-lock.json"]
    chapters:
      - id: mechanism
        title: "1. A way to tag an image without rebuilding it"
        note: |
          Why the reader has moved here.
        files: [actions:ecr-tag-image/action.yml, "actions:ecs-build/**"]
      - title: Housekeeping
        files: ["*"]
    items:                     # per-item annotations; same as top-level `files:`
      actions:ecr-tag-image/action.yml: {title: ..., note: ...}
```

A stream of sources that order themselves (a transcript, by time) takes
chapters fixed at an item: `- {at: main:t0902-0951, title: ...}`. A stream
of sources the author arranges (diffs, documents) takes chapters that list
items, with `*` for the remainder. The two kinds cannot share a layer.

Sources no layer places are rendered in an automatic closing layer, so every
citation has somewhere to land.

## Sources

Each entry under `sources:` has a `type:` (default `diff`) and `label:`
(display name). Files and other items are addressed as `source:path`; a bare
path works when only one source has it.

### diff

```yaml
h2o:
  repo: ../h2o
  range: 63da32f3...origin/main
  pathspec: [".", ":!web/static/dist"]   # optional
  context: 3                              # optional
actions:
  diff: changes.patch                     # a patch file instead of a repo
```

`--repo`/`--range`/`--diff`/`--pathspec` on the command line are the
single-source form; `--source name=repo@range` adds one. Prefer
`origin/main` to a local branch when the checkout may lag.

### transcript

```yaml
chat:
  type: transcript
  file: conversations.yaml      # relative to the sidecar
```

Collected separately, because session logs are local and eventually
deleted:

```bash
uv run literate-diff collect --repo ../h2o \
    --title "Harbor registry Keycloak" --merge-by-title \
    -o conversations.yaml
```

`--repo` names the project whose sessions to read. `--tool` says whose logs:
`claude-code` (the default; JSONL under `~/.claude/projects`) or `codex`
(rollouts under `~/.codex/sessions` and `~/.codex/archived_sessions`, from
the Codex CLI, IDE extension or desktop app, matched on the directory the
thread ran in). Give both to collect one piece of work done in each into one
file; every thread records its `tool:`, and the page names the agent beside
each thread's counts. `--title` keeps sessions whose title contains it and
is repeatable; `--session` takes ids or prefixes; `--since` drops earlier
turns. `--merge-by-title` treats sessions sharing a title as one thread in
timestamp order, dropping the turns a resumed session repeats.
`--timezone` sets the clock times are shown on and turn ids are derived
from; it defaults to the collecting machine's and is written into the file.

The output is plain YAML meant to be read and cut before it is shared:
prompts and replies quote whatever was on screen. Nothing regenerates it.

A turn keeps the prompt verbatim minus what the harness injected; the
reply, meaning the last text block before the next prompt, with earlier
blocks kept as narration for the band below; and the work between them as
counts only (time, tokens, tool calls by name, attachments). Turn ids
derive from when the turn happened, so re-collecting does not renumber.

For Codex, what the harness injected is the environment and AGENTS.md
context, skill bodies, browser state and the file lists the desktop app puts
above "My request"; the files are kept as attachment names. Codex names
threads in `~/.codex/session_index.jsonl`; an unnamed thread is titled by
its first message, as Codex lists it. Threads Codex spawned as subagents are
not collected. Codex stores reasoning encrypted, so its turns have no
thinking count.

### notes

Primary sources a layer introduces itself: a statement with who said it,
when, where, and a URL if there is one.

```yaml
said:
  type: notes
  items:
    - id: rebecca-slack
      by: Rebecca
      on: 2026-09-01
      where: "#h2o in Slack"
      text: dev and prod images that are closer together would help
    - id: cdn-drain
      by: Cloudflare
      text: A 524 is returned when the origin has not answered in 100 seconds.
      url: https://developers.cloudflare.com/…
```

`file:` reads the same list from a YAML file. Cite with `ld:#rebecca-slack`;
quote with `ldq:`. A note with a URL is evidence of kind *reference*;
without, *attestation*.

### terms

```yaml
glossary:
  type: terms
  items:
    - term: digest
      aliases: [digests]
      text: The hash of an image's manifest; names exactly one set of bytes.
```

The first use of a term or alias in each prose layer becomes a link to the
definition, with the definition on hover. Matching is on word boundaries
outside code, links and headings. A mapping of `term: text` works for the
simple case.

### doc

```yaml
standards:
  type: doc
  files:
    - ../lil-engineering/docs/standards/deploys.md
    - {path: notes/design.md, title: The design note this started from}
```

One item per file, rows by sentence, rendered as the markdown it was
written in. Paths resolve from the build's working directory. Cite with
`ld:#doc-<filename>`; quote a passage through an `anchors:` entry on the
item.

A copy exported from elsewhere, such as a Google Doc downloaded as markdown,
records where it came from in YAML front matter:

```markdown
---
title: Deploy standard
origin: Google Docs
url: https://docs.google.com/document/d/…/edit
modified: 2026-08-14T17:36:37Z
retrieved: 2026-09-14
---
```

The page shows `title` beside the filename and the other keys as a line
under it (a link to the original, the last-modified and retrieved dates).
Rows and anchors start after the front matter; the embedded copy keeps it.
The same keys on a `files:` entry override the file's.

## Annotating items

Under top-level `files:` (diffs), `turns:` (transcripts), or a stream
layer's `items:`:

```yaml
files:
  Dockerfile:
    title: one build graph       # shown beside the path
    collapsed: false
    note: |                      # introduces the item, in the story
      Markdown, rendered above the diff.
    sections:                    # a band inside the diff
      - at: "FROM prod AS test"
        id: dockerfile-test
        title: "test — what CI runs the suite against"
        note: "Markdown."
    notes:                       # a sidenote in the right margin
      - at: "ENV H2O_SETTINGS_MODULE"
        span: 1
        id: settings-env
        text: "Markdown."
    anchors:                     # named ranges with no visible output
      - {id: uwsgi-build, at: "CPUCOUNT=1", span: 5}

turns:
  promotion:t0302-0914:
    id: q-promotion              # what `ld:` and `ldq:` address
    note: Markdown, rendered above the turn.
    prompt: {at: "How hard is it to test one image"}
    response:                    # the highlight: one passage, or several
      - {at: "Promotion is a tag, not a copy"}
      - {at: "The work is in the two things", through: "before you need it"}
    anchors:
      - {id: q-why, at: "the lifecycle policy", in: response}
```

### Anchoring

`at:` locates a row. Ordering is by position, so an anchor is stable against
changes elsewhere.

| form | meaning |
| --- | --- |
| `"some text"` | first row containing that substring |
| `/regex/` | first row matching the regex |
| `@37` | the 37th row, counting from 0 |
| `+412` | diffs only: the row that is line 412 on the new side |
| `-88` | diffs only: the row that is line 88 on the old side |

`nth: 2` takes the second match. A range extends with `span: 5` (five rows)
or `through: "other text"` (up to the next match). An unmatched anchor
warns and falls back to the top of the item; an anchor that matches more
than once warns too, because a later commit can silently move it (`nth: 1`
does not silence this).

In a message, rows are sentences rather than lines, since the part of a
prompt worth quoting is a sentence of it; code, tables and headings stay
whole. Without a highlight a message shows its opening and its closing
passage, the close being what the next turn answers.

### References and quotes

Inside any markdown, a link with the `ld:` scheme points at an id anywhere
in the document:

```markdown
See [the settings switch](ld:#settings-switch) for where this value comes from.
```

The arrow (`↑` back, `↓` forward) is computed from position in the rendered
page. Clicking opens a folded item, scrolls, and highlights the rows. A
reference with no label, `[](ld:#id)`, renders as a small citation marker.

`ldq:` quotes instead of linking: a diff's lines with signs and numbers, a
message's or note's words with attribution, each with a link through to
context. `[a label](ldq:#id)` is a control the reader opens; `[](ldq:#id)`
renders the quoted words in place.

Every item also gets an automatic id: `#file-<source>-<path>` for a file,
`#turn-<thread>-<turn>` for a turn (`-prompt`, `-response`, `-prompt2`… for
its passages), a note's own id, `#term-<term>`, `#doc-<filename>`.

## Categories, claims and evidence

`categories:` declares kinds of claim; `{category: name}` on the line
before an ordered list binds the list; each item is numbered and coloured
(Paul Tol's muted scheme, distinguishable under colour-vision deficiency;
`color:` overrides, `short:` prefixes the number). `{#id}` at the start of
an item names it; otherwise it is `name-N`.

```yaml
categories:
  security: {label: Security, short: S}
layers:
  - id: wins
    text: |
      {category: security}
      1. {#build-role} Before, builds published under the deploy role. Now under one that cannot deploy.
files:
  tf:h2o/aws/iam/iam_role.tf:
    note: The build role [](ldc:#build-role) is this resource.
```

A flag `[](ldc:#build-role)` renders as the item's coloured number, shows
the item on hover, and links to it; the item lists every place that flags
it. `ld:#cat-build-role` links to an item in prose.

`{claims}` before a plain list makes each item a claim without a category.
For every claim, in either kind of list, the page computes what it **rests
on**: the kinds of source it cites (`ld:`/`ldq:` to a row: *diff*,
*conversation*, *attestation*, *reference*, *document*) and the kinds of
place that flag it. A claim that cites another claim (`ldc:#x`,
`ld:#cat-x`) rests on what that claim rests on. The kinds show beside the
claim; a claim with none is marked *unsupported*, and in a layer with
`claims: required` it is a warning. The tool never judges the evidence; it
says whether there is any.

## The file describes itself

The page begins with an HTML comment saying what it is, its layers and
sources, and how to get the data out, and the header tells a person that an
agent given the file will find those instructions.  A JSON data block,
`<script type="application/json" id="ld-data">`, holds the sidecar, each
source's copy of record (the patches, the transcript, the notes), the
brief, and every claim with its evidence, with `<` written as `\u003c` so
the block is safe inside a script element.

```bash
pup 'script#ld-data text{}' < page.html | jq '.claims[] | select(.supported|not)'
htmlq -t '#ld-data' -f page.html | jq -r .sidecar
```

```bash
literate-diff extract page.html --about        # the header comment
literate-diff extract page.html --layers       # ids, kinds, audiences
literate-diff extract page.html --layer summary  # markdown, quotes resolved
literate-diff extract page.html --claims       # JSON lines
literate-diff extract page.html --claim oidc-scope
literate-diff extract page.html --sidecar
literate-diff extract page.html --source chat
literate-diff extract page.html --to dir/      # sidecar + sources; rebuild from dir/
```

`--to` writes a `build.yaml` whose sources point at the extracted files, so
the page rebuilds without the repositories. In the page, `window.LD.data()`
returns the same object. `--no-embed` at build time leaves the inputs out.

The browser renders from this data block, including a compiled `presentation`
with shared markup and references into source text. It requires JavaScript to
display; extraction does not. See [the HTML data contract](docs/html-data.md)
for the representation and compatibility rules.

## Lint

```bash
uv run literate-diff lint notes.yaml
```

Also run at build; `--strict` fails the build on any warning. Beyond the
anchor and id checks, the lint reports a prose layer over its `budget:`, a
claim that cites nothing in a `claims: required` layer, a sentence whose
subject is the document rather than the work ("This section traces…", "the
reader", "Below,", "since the last draft"), and two completeness checks
that follow from a synthesis block being a comprehensive extraction of one
facet: a declared category no list uses, and a defined term no prose layer
uses.

## Output

One file, no external requests: CSS and JS inlined, sources embedded. Every
diff row and every sentence of the conversation carries an id, which is
what lets `ld:` land on one line. Files that render folded shut ship as
rows in `ld-data.presentation.rows` and are built the first time they are
opened. Repeated markup uses a dictionary, and matching presentation text
references the embedded source record. HTTP compression can reduce transfer
size further; the standalone file also works from disk.

Sidenotes sit in the right margin against their line, pushed down as needed
so they never overlap; below 62rem they fold into the table under the line
they annotate. Light and dark follow the reader's system setting. The map
in the margin shows the blocks as a grid and marks the one in view.

## Updating as the branch moves

While drafting, keep the sidecar beside the sources and update its intended
range explicitly. Freeze commit endpoints when publishing a dated account.
For a scope change, rebuild with the new range and read
stderr: an anchor that no longer matches falls back to the top of its file
and warns; an anchor that now matches more than once warns (the usual cause
is a commit adding a comment that quotes the code, above the line you
meant); new files land at `*` unannotated; keys that name nothing are
reported. `--outline` against the new range prints the current file list.

## Example

[`examples/feature-tour/`](examples/feature-tour/) is a small invented
change across an app repository and an infrastructure repository, with a
two-session transcript, a reference document, two notes and three terms,
annotated with every feature. [`notes.yaml`](examples/feature-tour/notes.yaml)
is the v2 shape, eleven blocks in three groups; [`notes-v1.yaml`](examples/feature-tour/notes-v1.yaml)
the same document in the v1 shape. Rebuild from the repository root, since
`diff:` and document paths resolve from the current directory:

```bash
uv run literate-diff -a examples/feature-tour/notes.yaml \
    -o examples/feature-tour/feature-tour.html
```

The test suite builds both and fails on any warning.

## Development

```bash
uv sync
uv run pytest
```

`literate_diff/model.py` is the document model; `sidecar.py` reads the
sidecar into layers of bound items; `anchors.py` resolves `at:` specs;
`render.py` composes the page; `extract.py`, `lint.py`, `outline.py` and
`cli.py` are what they say. `sources/` holds one plugin per source type
behind the contract in `sources/base.py`; `parse.py`, `transcript.py`,
`message.py` and `collect.py` are the diff and transcript plugins'
machinery. `annotate.py` keeps the v1 names for callers that used them.
