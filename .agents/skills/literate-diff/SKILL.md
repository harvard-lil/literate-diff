---
name: literate-diff
description: Build a debrief with literate-diff -- summary, synthesis and evidence blocks written for named readers over the record (a git diff across one or more repos, the agent conversations behind it, notes, reference docs, terms), compiled to one self-describing HTML file. Use when asked to write up, review, explain, hand over, or tell the story of a change, a branch, a release, a week of agent-assisted work, or any complex piece of work someone else has to understand and take responsibility for; or to produce a "litdiff".
---

# Build a debrief

First read [docs/debrief-authoring.md](../../../docs/debrief-authoring.md).
It defines the acceptance criteria and the evidence and editorial checks used
throughout this workflow.

A debrief is one author's account of a closed episode of work, for readers
who were not there, checkable against the record without the author
present. It has three groups of blocks. The **summary** says what the
author wants each reader to know: an executive summary, then one block per
reader role. The **synthesis** says why the author believes it, one block
per facet: an optional system model, work narrative, improvements, regressions and
mistakes, future work, vocabulary. The **evidence** is the record itself:
code, conversation, statements, documents. Every claim links to what it
rests on and the build reports the ones that do not. The output is one HTML
file that carries its sources and says how to read itself, so a person can
open it and an agent can query it. `DESIGN.md` has the vocabulary.

The tool is `literate-diff` in this repository. `README.md` is the reference
for every key; `DESIGN.md` is the architecture. This file is the working
order: what to do, in what sequence, and what each step has to produce
before the next starts. Each kind of source has its own instructions in
`sources/`, consulted at the steps marked **(per source)**.

```bash
uv run literate-diff -a notes.yaml -o out/review.html     # build
uv run literate-diff lint notes.yaml                      # prose and claims
uv run literate-diff extract out/review.html --layers     # read one back
```

Or without a checkout: `uvx --from git+https://github.com/harvard-lil/literate-diff literate-diff …`.

## Why the order matters

The layers a reader sees first are written last. A summary is selective,
and selection needs two things the raw material does not contain: what the
author was trying to do, and what each reader already knows and will do
next. Written first, a summary is a list of what the diff contains. Written
last, against a brief and a reader roster, it is a list of what changed for
someone. So the order is: brief and readers, then evidence, then ledgers,
then the evidence blocks, then the synthesis, then the summary, then the checks.

## 1. Brief: use the author's context and fill material gaps

The author's motives are the one input that cannot be reliably derived from
the diff or the transcript, and the transcript is a slow way to get them.
Use answers already supplied in the conversation. Ask only what is still
materially missing, and put the brief under `brief:` in the sidecar, in the
author's words where possible:

1. **What were you trying to do, and what constrained you?** The goal, the
   deadline or season, the thing that made this urgent, the thing you were
   not allowed to touch.
2. **What did you learn?** What you believed at the start that turned out
   wrong; what you would tell yourself a week ago.
3. **What happened outside the record?** Account actions, console clicks,
   Slack messages, decisions made in a meeting: anything the diff and the
   transcript do not show. Each of these becomes a note (see
   `sources/notes.md`).

Then write the **reader roster**: for each reader the document is for,
`who`, `knows` (their vocabulary and what they can take for granted),
`does` (what they will do with the document on Monday), and `asks` (the
two or three questions they would put to the author). Derive readers from
the work, not from an org chart: who has to change a habit, who will field
a question, who is about to build the next thing, who owns something this
touched. Four is typical. Users of the product are a reader only if they
have to know something; usually they do not.

Last, list the **beats**: the five to eight things the summary must
contain for the roster's questions to be answered. Write them as outcomes
("deploys can omit maintenance; the automatic decision still needs a live check"), not as work ("refactored the
deploy pipeline").

```yaml
brief:
  author: |
    Prove the deploy shape on h2o before applying it to Perma; classes
    start this week, so h2o must not go down while it is done.
  learned: |
    Promotion needs no service; the registry already holds an image by digest.
  outside_the_record:
    - A console change the author observed, with its date and evidence
  readers:
    - who: someone who develops h2o
      knows: Django, docker compose; not ECS or Terraform
      does: runs the new local setup; opens the next PR to staging
      asks: what do I type now? will my deploy take the site down?
  beats:
    - conditional maintenance is implemented; a live decision check remains
```

The brief is not rendered. It is embedded with the sidecar so the lint and
any agent interrogating the file can see who it was written for, and it is
what step 8 checks the summary against.

## 2. Sources: decide what the evidence is, and collect it

Declare each source under `sources:` with a `type:`. **(per source)** Read
`sources/<type>.md` for how to choose its range, produce its copy of
record, and review it before it goes anywhere. The usual set for a week of
agent-assisted work:

- `diff` -- one per repository the work reached, including a repository the
  change reaches without a commit in the primary one.
- `transcript` -- the agent conversations (Claude Code, Codex, or both),
  collected into a file.
- `notes` -- what the brief turned up outside the record, and anything the
  author knows from elsewhere that a claim will rest on.
- `terms` -- the words a reader outside the daily work will meet.
- `doc` -- a standard the work follows, a runbook it changed, the design
  note it started from, including a Google Doc exported to markdown.

Collection is a separate phase because the copy of record is what gets
reviewed and redacted. Do it before writing, not after.

## 3. Read all of it

Read every file that will be annotated, and the whole transcript, before
writing a sentence of prose. **(per source)** The fragments say what to
read for. Digest a long transcript in chunks into a scratch file; do not
try to hold it in your head.

## 4. Ledgers before prose

Two working documents, kept in scratch rather than in the sidecar. They are
what the prose is written from, and they are what makes a missing beat
visible.

**Change ledger.** One line per file: what changed, and which outcome it
serves. Files that serve no outcome are housekeeping, and say so.

**Turn ledger.** One line per prompt in the transcript: what was asked,
what came back, who challenged it, its later correction or reversal, and
what was different afterwards. Mark proposed/implemented/applied/deployed/observed
separately. Then mark the turns that
pass the test *the outcome would be surprising without this turn*. Those
are the beats of the work narrative; the rest is effort, and effort is not
plot.

Cross-check the two. Every category item should trace to a turn or be
marked incidental; every marked turn should have produced at least one
item. An item with no turn is often a missing beat; a turn with no item is
often a decision that was reversed, which belongs in the story anyway.

## 5. Write the bottom layers

Streams first: they are the evidence, and every prose claim will point into
them.

- **(per source)** Annotate each stream: chapters in the order a reader
  needs, titles and notes on the items that carry the story, sections and
  sidenotes on the rows that carry the argument, highlights on the turns
  the decisions turned on. Give ids to anything prose will cite.
- **Improvements, by kind.** Declare `categories:`; write one `{category: name}`
  list per kind. Every item states what was true before and what is true
  now. A mechanism is not a win; a bug the work itself introduced and fixed
  is not a win but belongs in its own category, since it explains code that
  looks over-cautious. Flag each item with `[](ldc:#id)` where it is
  delivered.
- **The other side.** Regressions and trade-offs; mistakes and what they
  taught; future work, each item saying what would trigger it.

## 6. Write the synthesis

Each synthesis block is a comprehensive extraction of one facet. The test
of a block is completeness over its facet, and the lint checks the two it
can: a category no list uses, a term no block uses.

**Optional system model.** Include it when a shared explanation of components,
order and ownership helps readers understand the result. Name the subject,
such as “Deployment model.” Omit a generic Overview that repeats the summary
and chronology.

**Work narrative.** Use the decision ledger to explain the actual sequence:
scope changes, constraints, rejected proposals, operator overrides, corrected
claims and later reversals. A final diff's dependency order is not the history
of the work. Separate concurrent strands and distinguish a mechanism test from
its integration and use in each environment. There is no fixed beat count or
required paragraph formula. Avoid closing every entry with an italic moral.
Cite a turn where it supports the account; quote only when the wording matters,
and include the correction if the quoted reply was later overturned. Attribute
motives to the author and inferences to their source.

## 7. Write the summary, last

**One block per reader role**, the second row of the summary. For each
reader in the roster who would act differently: what exists now that did not (named, linked), the habit to
drop (as an instruction), the belief that was wrong, and the corrections
to this work itself, which are what make the other three credible. A
reader with nothing to say is left out, not padded. Point at where each
lesson now lives in a repository; the layer is the notice, the repository
is the record.

**Executive summary.** Written as answers to the roster's `asks`, in the
vocabulary of the roster's `knows`. Each bullet leads with what is
different, says what it was before, and gives the number where there is
one. Name the command someone would type. State the limit inside the claim
where there is one. Write it as the person who did the work. Ten bullets is
plenty, and it does not have to cover everything the wins layer covers.
Mark the list `{claims}` and set `claims: required`, so a bullet that
cites nothing is reported.

Check both against `brief.beats`: every beat appears, and nothing appears
that is not a beat or a direct answer to an `asks`.

**Titles and subtitles help readers choose.** Use a concise subject or question.
A subtitle should clarify the section's usefulness in ordinary language, such
as “How the scope and design changed over the week.” Do not reproduce the
writing rubric (“motives, turning points, from transcript and code”) or promise
exhaustiveness (“every win”). Omit a redundant subtitle. Audience metadata helps
the brief and cold read; it is not a reason to remove useful audience cues from
navigation. Set `group:` and `row:` to place blocks deliberately.

## 8. Claims, terms and evidence

Every claim in a top layer does one of three things: **cites** evidence
(`ld:`/`ldq:` to a row, `ldc:` to an item that is itself flagged),
**introduces** it (a `notes` item with who, when, where, and a URL if there
is one), or **stays marked** unsupported for the reader to see. The tool
never judges the evidence; it says whether there is any and of what kind,
and the page shows the kind beside the claim. Choose deliberately: a claim
resting on the author's word is fine when it says so.

Any term a reader in the roster does not `know` gets a `terms` item, and
the first use in each layer links to it. A `## Terms` section is not a
substitute: an entry has to be readable where it sits.

## 9. Build, lint, and read the warnings

```bash
uv run literate-diff -a notes.yaml -o out/review.html
uv run literate-diff lint notes.yaml
```

Every warning names a fix. Anchors that no longer match or match twice;
ids nothing defines; keys that name nothing; items nothing flags; claims
that cite nothing in a `claims: required` layer; a layer over its budget;
and a sentence whose subject is the document. That last one is the
symptom of writing to the instructions instead of to the reader: "this
section traces how the work happened" spends the first sentence on
itself. Delete the sentence; the layer's `goal:` says what the layer is
for, and the reader does not need it repeated. Revision notes ("changed
since the last draft") go in chat or a changelog, never in the text.

A clean build checks structure. Follow consequential claims to their sources
and search for later corrections. Code comments, generated docs and an agent's
“verified” reply are claims to check, not independent proof. Separate new
findings from the historical work and preserve important limitations in the
summary. Use the authoring guide's evidence table and examples.


## 10. Cold read

The author agent has the jargon; a reader agent with no context is the
jargon detector. For each reader in the roster, start a fresh session and
give it only that reader's layer (`literate-diff extract out/review.html
--layer summary`) and the reader's `who`/`knows` line. Ask three things:
what would you do on Monday; what did you not understand; what do you
suspect is missing. Fix what comes back, rebuild, and repeat until the
answers match the roster's `does` and `asks`.

## 11. Ship

Send the HTML. The review norm it supports: the reader chooses the posture
(take the author's word, check the reasoning, go to the record), so say
which posture the change calls for and **spot-check** a sample of the
citations in the blocks that matter. Keep the sidecar, the collected transcript and any notes
beside it in the repository or the ticket; the page embeds them, but the
files are what the next revision edits. During drafting, update the intended range explicitly and rebuild when scope
changes. Freeze reviewed commit endpoints for the dated account; record later
corrections without silently including later code or deployment state.

## Writing

The document is read by people who did not watch the work, in roles the
author does not have. The rules that follow from that:

- Lead each note with what the lines do, then why.
- Say what was true before and what is true now. A sentence that could be
  true of any change ("improved reliability") has not said anything.
- Give numbers their basis: a run log, a thread, a list price. Say what was
  not verified.
- No words the roster does not know without a definition in the sentence
  or a terms entry. Shorthand that grew up during the work ("the switch",
  "the window", "referrers") is the commonest way a beat becomes
  unreadable; when a beat sounds important and a reader in another role
  could not say what it means, it is shorthand.
- Emphasis, escalation and metaphor are a budget spent against unmarked
  prose. Most paragraphs spend nothing.
- Remove prose that merely recites a section's purpose. Keep useful scope,
  observation dates and evidence limits. Editorial revision history belongs
  in metadata; findings added later must be distinguished from the episode.
