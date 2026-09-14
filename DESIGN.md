# literate-diff 2: design

## Vocabulary

A **debrief** is the artifact: one author's account of a closed episode of
work, for several readers who were not there, checkable against the record
without the author present. It has an accountable author, stated motives
(the `brief:`), a date, and explicit limits on the evidence. The reviewed
sources are embedded with several reading paths. Their collection scope and
redactions must be stated; embedding does not guarantee a complete record.
Corrections preserve the episode's endpoint and identify later review findings,
rather than silently changing the historical account to match current state. A **literate
diff** is the code block of a debrief; the tool keeps that name.

A debrief has three **groups**, in reading order, each answering one
question a reader brings. The build checks structural requirements; authoring
and review establish whether the account answers those questions accurately:

| Group | Reader posture | Question | Validity rule | Enforced by |
| --- | --- | --- | --- | --- |
| Summary | orientation | what does the author want me to know? | every affected reader has a block, in budget, in their vocabulary | manifest audiences, budget lint, terms |
| Synthesis | verification | why does the author believe it? | every claim cites evidence and its kind is visible; each block is complete over its facet | unsupported mark, evidence kinds, completeness lint |
| Evidence | investigation | what actually happened? | the record is whole and embedded, not curated | copy of record, keep-all rule, `extract` |

Summary is two rows: the executive summary, then one block per reader
role. Synthesis is one row of blocks, each a comprehensive extraction of
one facet of the evidence: an optional system model, the work narrative, improvements
by category, regressions and mistakes, future work, vocabulary. Evidence is
one row: code, conversation, statements, documents. The **map** draws this
shape, full size as the top-level contents and as a postage stamp in the
margin.

The review norm the artifact supports: the reader chooses the posture. Old
code review required every reviewer to take the third posture on
everything; a debrief makes all three available from one object, and the
norm becomes a rule about which posture a change requires. The practice
words: **spot-check** (verify a sample of a block's citations), **cold read**
(a reader with no context reads one block and reports what they would do
and what they did not understand), **zone of understanding** (what the team
must understand to take responsibility for what it ships).

The problem class: understanding transfer across a large investment gap.
One author has spent far more time on a closed episode than any reader
will; several readers in different roles each need a role-specific
understanding; the organisation needs that understanding checkable against
the record. Drop any one condition and a cheaper form serves: a PR
description for one reader, a wiki page for an open subject, a memo where
nobody needs to verify. A debrief is the wrong form for a subject still
moving, for operating a system (a runbook), or for a discussion in
progress. Agent-assisted work is why the class is suddenly common.

Lineage, by part: the assurance case (Goal Structuring Notation) and
Toulmin's claim/grounds/warrant for the validity rules; RO-Crate and
in-toto attestations for the self-contained package with provenance; the
archival finding aid and the intelligence product graded by level for the
layered description over a whole record; the trial bundle for citing by
page; Knuth's literate programming, the glossed page and Nelson's
transclusion for narrative interleaved with the source; IBIS for the
narrative of decisions; Pirolli and Card's sensemaking loop and Star and
Griesemer's boundary object for the class itself. Two collisions to know:
"evidence pyramid" ranks study designs in medicine, and `litdoc` is an npm
package. "Casebook" is held in reserve for LIL-internal use.

## Architecture

A literate diff is one kind of document this tool builds. The general form is
a **pyramid**: a stack of layers, each written for a named audience with a
stated time budget, over a set of **sources** that are the evidence. Every
layer may cite any source and any lower layer; the build reports claims that
cite nothing. The whole thing compiles to one HTML file that carries its own
sources and instructions for reading them.

This document is the architecture. The README is the reference for keys and
the skill is the working order. [Writing a work debrief](docs/debrief-authoring.md)
defines the reader and evidence acceptance criteria.

## Vocabulary

- **Source.** Evidence, declared under `sources:` with a `type:`. A source
  is loaded by a plugin into **units**.
- **Unit.** One addressable body: a file's diff, one message of a
  conversation, one reference document, one attestation, one term. A unit
  has a `key` the sidecar addresses it by and `rows` the anchor grammar
  resolves against.
- **Row.** The smallest addressable thing. A diff line, a sentence of a
  message, a paragraph of a document. Every row has an id in the page.
- **Anchor.** A resolved row range in a unit. The grammar (`at:`, `nth:`,
  `span:`, `through:`; substring, `/regex/`, `@N`) is core. A plugin may add
  forms (`+N`/`-N` for diffs).
- **Layer.** One block of the debrief, declared under `layers:`. A layer is
  either **prose** (markdown for a reader) or a **stream** (a run of units
  from one or more sources, cut into chapters). It has a `group` and a
  `row`, a `title` naming a subject or question, an optional navigation `subtitle`, and
  `audience` and `budget` as metadata; the map, the header and the lint
  read them.
- **Claim.** A list item in a prose layer inside a `{category: x}` or
  `{claims}` list. A claim is **supported** when it cites something with
  `ld:`/`ldq:`/`ldc:` or something flags it with `ldc:`; the kinds of
  evidence it rests on (diff, conversation, document, attestation) are
  computed from what it cites, not authored. A claim that cites nothing
  renders marked and is reported.
- **Category.** A named kind of claim with a colour and a short label.
  Unchanged from v1.

## Sources are plugins; the pyramid is not

The plugin boundary is the source. A plugin owns:

1. `collect`: producing the copy of record from a volatile origin, when
   one is needed. A git range is reproducible, so the diff plugin's collect
   is optional and writes a `.patch`; session logs are not, so the
   transcript plugin's collect writes a transcript YAML. Collection is a
   separate command, because the copy of record is what gets reviewed and
   redacted before it goes anywhere.
2. `load`: the copy of record (or the live origin) to units with rows.
3. Anchor forms beyond the core grammar.
4. Annotation keys beyond the core ones, and how they bind. Core keys on a
   unit are `title`, `note`, `sections`, `notes`, `anchors`, `collapsed`.
   The transcript plugin adds `prompt:`/`response:` highlights.
5. Rendering a unit's body, its quote form (`ldq:`), and its table of
   contents entry. The diff plugin's lazy folded rows live here.
6. The unit's natural order, when the source has one. A transcript is
   ordered by time and chapters are cut at a turn; a diff has no natural
   order, so the author lists files and chapters take a wildcard.
7. A skill fragment: what an author has to do to choose, collect, read and
   annotate this kind of source.
8. An outline fragment for `--outline`.

What the core owns: the sidecar, the layer manifest, anchor resolution,
ids and references, categories and claims, chapters, the page, the embedded
source block, `extract`, `lint`.

The test for a layer violation: the core never imports a plugin's types,
and a plugin never reads another plugin's units. The generic skill consults
each plugin's fragment at the steps that touch its source, and says so.

Plugins in this release: `diff`, `transcript`, `notes` (attestations and
external references: a statement with who said it, when, and a URL if
there is one), `terms`, `doc` (a markdown or text file, one unit per file,
one row per paragraph).

## Layers and the default pyramid

```yaml
layers:
  - id: summary
    kind: prose
    title: What changed
    audience: anyone
    budget: 1 minute
    goal: what is different now, in the vocabulary of someone who uses the system
    text: |
      ...
  - id: story
    kind: prose
    ...
  - id: code
    kind: stream
    title: The code
    sources: [h2o, actions, tf]
    audience: someone reviewing the change
    chapters: [...]
  - id: conversation
    kind: stream
    sources: [chat]
    chapters: [...]
```

A v1 sidecar has no `layers:`. It is read as: one prose layer from `plot:`,
one stream from the diff sources with `chapters:`/`order:`, one stream from
`transcript:` with `appendix:`. Every v1 key keeps its meaning, so the h2o
document builds unchanged and moves to `layers:` when it is edited.

The `budget:` is words or a time; the lint reports a prose layer over it.
`audience:` and `goal:` render in the layer header and the map. A layer
may set `claims: required`, which makes an unsupported claim a warning
rather than a mark.

## Primary sources at any layer

Any layer may introduce evidence: a thing a colleague said in Slack, a
pattern the author knows from elsewhere, a document. That evidence is a
`notes` source, declared like any other:

```yaml
sources:
  said:
    type: notes
    items:
      - id: rebecca-slack
        by: Rebecca
        on: 2026-09-01
        where: "#h2o in Slack"
        text: dev and prod images that are closer together would help
      - id: assets-cdn-pattern
        by: Jack
        text: hashed assets on a CDN kept across deploys is the common shape
        url: https://...
```

A claim that cites `ld:#rebecca-slack` is supported, with evidence of kind
*attestation*; the rendering shows the kind, so a reader can tell a claim
resting on the diff from one resting on the author's word. A claim that
cites nothing is marked `[unsupported]` in the page. The author's choice
is therefore: cite, introduce, or leave the mark. The tool never judges
the evidence; it only says whether there is any.

## Terms

`type: terms` is a source whose units are definitions. The first use of a
term in each prose layer is linked to its definition, with the definition
on hover, so a layer stays readable where it sits without repeating the
glossary. Terms are matched on word boundaries outside code and links;
`aliases:` widen the match.

## The file documents itself

The output begins with an HTML comment that says what the file is, which
tool and version built it, the layers with their audiences and ids, the
sources, and how to get the data out. The sidecar and every source's copy
of record are embedded as a JSON **data island**,
`<script type="application/json" id="ld-data">`, with every `<` written
as `\u003c` so the block is safe inside a script element (the WHATWG
tokenizer scans raw bytes for `</script` regardless of JSON string
context). JSON rather than YAML because `pup`, `htmlq`, `xidel` and `jq`
already know the shape, and because the page's own script can read it
(`window.LD.data()`); the sidecar and transcript are carried inside it
verbatim as strings, so comments and formatting survive a round trip.

```bash
pup 'script#ld-data text{}' < page.html | jq '.claims[] | select(.supported|not)'
literate-diff extract page.html --to dir/     # sidecar and sources, rebuildable
literate-diff extract page.html --layer summary
literate-diff extract page.html --claims       # every claim, its evidence, its kinds
literate-diff extract page.html --claim oidc-scope
```

The comment also gives the `pup`/`htmlq` forms and a one-line Python
fallback for a reader with no tool. There is no JavaScript API beyond the
parsed island; the data is the interface. A visible "About this file"
section at the foot says the same for a person.

`--no-embed` leaves the sources out for a document that must be small. The
h2o document grows from 4.0 MB to 5.9 MB with its patches and transcript
embedded.

## Lint

`literate-diff lint notes.yaml` (also run at build; `--strict` fails):

- a claim with no evidence;
- a category item nothing flags;
- a prose layer over its budget;
- a sentence in a prose layer whose subject is the document ("this
  section", "this document", "the reader", "below", "above", "in this
  draft");
- a term used in a prose layer that is defined nowhere, when a terms
  source exists and the identifier is in code font;
- everything v1 reported: unmatched and ambiguous anchors, unknown ids,
  keys that name nothing.

## Brief

`brief:` is a non-rendered key the skill writes before any prose and the
lint and QA read: the author's motives and constraints, the readers (who,
what they know, what they will do, the questions they would ask), and the
beats the summary must contain. It is embedded with the sidecar so an
agent interrogating the file can see who it was written for.

## What is kept from v1 without change

Anchor resolution and its warnings. The rebuild loop and the outline. Lazy
rows for folded files. Sidenote placement. References, arrows and quotes.
Categories, flags and the two-pass render. The transcript row model and the
default highlight. Collection.

## Layout

```
literate_diff/
  model.py        Row, Unit, Item, Anchor, Layer, Document
  sidecar.py      sidecar -> sources -> layers of bound items; v1 synthesis
  anchors.py      at:/nth:/span:/through: over any unit; Unit.find_extra for plugin forms
  render.py       the page: layers, references, categories, claims, terms, map, data island
  extract.py      read a page back; rebuild from its island
  lint.py         prose about the document, budgets; run at build and as a command
  outline.py      --outline from the loaded sources
  sources/
    base.py       SourcePlugin, LoadContext
    diff.py       git range or patch; +N/-N; the diff table and lazy rows
    transcript.py collected conversations; highlights; the work band
    notes.py      attestations and references
    terms.py      definitions, linked on first use per layer
    doc.py        reference documents, one unit per file
  parse.py, transcript.py, message.py, collect.py   the diff and transcript machinery
  annotate.py     v1 names
.agents/skills/literate-diff/
  SKILL.md        the working order
  sources/*.md    one fragment per source type, consulted at the (per source) steps
```

## State, 9 September 2026

Built on the `v2` branch in a worktree. Groups, rows and subtitles, the
grid map, the completeness lint, the debrief copy and the readers' note
landed on 9 September; the feature-tour and h2o sidecars use nouns and
groups. Steps 1 to 8 of the original order of work are done: the port builds every v1 sidecar unchanged (the h2o
document renders with the same counts of files, turns, flags, quotes and
references as the v1 build); layers, claims and evidence kinds, the notes,
terms and doc sources, the data island, `extract`, `lint`, the skill with
per-source fragments, and the h2o document in the v2 shape all exist and
the suite covers them.

On 14 September `collect` gained `--tool codex`, which reads Codex rollout
files into the same transcript shape, with the agent recorded per thread;
and doc files gained front matter for provenance, so a Google Doc exported
to markdown through the Drive connector shows its origin, URL and dates.
ChatGPT conversations outside Codex keep no local log and are not collected.

Not done, and worth doing next:

- Record cold-read coverage for each generated debrief; results for one
  document do not establish the quality of later generations.
- Sidenotes and sections are bound for every plugin but only the diff
  plugin renders them; a doc or note with a sidenote drops it silently.
- `--outline` writes a v2 skeleton but does not yet emit `items:` for
  transcript or doc sources.
- Terms are linked in prose layers only, not in chapter notes or item
  notes inside streams.
- A claim citing a claim is followed one level; deeper chains report only
  the direct citation's kinds.

## HTML rendering contract

The browser mounts the document from `ld-data.presentation`. Embedded source
records remain directly readable and sufficient for rebuilding. Presentation
strings can reference slices of those records; repeated HTML tags share a
dictionary. The standalone page requires JavaScript for display. The format and
compatibility rules are in [HTML data and rendering](docs/html-data.md).
