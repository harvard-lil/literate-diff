---
name: literate-diff
description: Turn a git diff (one repo or several), and optionally the agent conversations behind it, into an annotated, single-file HTML narrative with literate-diff. Use when asked to write up, review, explain, or tell the story of a change, a branch, a release, or a week of work across repositories, or to produce a "litdiff".
---

# Make a literate diff

A literate diff is a diff arranged as a story: a plot at the top that says why
the batch exists and what it achieved, chapters that put files in the order a
reader needs rather than alphabetical order, notes on the lines that carry the
argument, and — when the work was done with agents — an appendix of the
conversation the narrative can quote. The tool is `literate-diff` in this repository; the README is
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

## 2. Collect the conversation, if there is one

Do this before writing, not after: the transcript is what step 3 is written
from, and it is also a separate artifact that has to be reviewed.

```bash
uv run literate-diff collect --repo ../h2o \
    --title "<session title>" --merge-by-title -o conversations.yaml
```

Collection reads local session logs, which are neither shared nor permanent,
so the output file is the copy of record and belongs beside the sidecar.
**Read it before it goes anywhere** — prompts and replies quote whatever was
on screen, including printed environment, absolute paths and error output; cut
what should not be shared. Nothing regenerates the file, so a rebuild will not
undo an edit.

Keep the rest. The appendix is comprehensive, not selected: it is read by
someone following how a decision was reached, who needs the turns in order,
and by someone deciding how hard to review the diff, for whom the thin turns
are the evidence. Cutting to the turns where the answer was good produces a
third thing, and it reads like one.

## 3. Read the whole diff before writing

Read every file that will be annotated, not the outline. Anchors are
substrings of diff rows, and the notes have to say what the lines do. Read the
record behind the work too — the collected transcript, a ticket, a thread:
decisions, rejected alternatives, measurements and incidents are what a diff
cannot show, and they are what the plot is made of. For a long thread, digest
it in chunks before writing.

## 4. Write the plot

The plot is markdown at the top. In order:

- **What changed**: the executive summary. See below.
- **What to take from this**: what each audience should do differently. See
  below.
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
- **How it happened**, if there is a transcript: the order the decisions
  actually arrived in. See below.

### What changed

The first thing on the page, for the reader who will read only this. A short
list of outcomes in the second person, in the vocabulary of someone using the
system rather than building it.

Each bullet leads with what is different, says what it was before, and gives
the number if there is one -- "deploys got roughly 2-3x faster, from 11-14
minutes to about 5", not "optimised the deploy pipeline". Name the command
someone would type. Where a bullet needs a mechanism to be believable, put it
in a sub-bullet rather than in the sentence.

Two things keep it honest. State the limit inside the claim where there is one
("a window is now taken only when the code needs one -- which for now means,
if it has any migrations; this could be tighter"), rather than leaving it for
the trade-offs section. And write it as the person who did the work, not as a
report about them; "hoping not to use this one" about a rollback command tells
a reader more than a paragraph of assurance.

Ten bullets is plenty. It is not a summary of the diff, and it does not need
to cover everything the wins section covers.

### What to take from this

Then, for the reader who is not going to read the rest: what someone in each
affected position should now do differently, or now knows. This is the layer
between a talking-points summary and the full list of impacts, and it is
usually the part a document like this is missing.

**Derive the audiences from the work, not from an org chart.** Who has to
change a habit, who will field a question, who is about to build the next
thing, who owns something this touched. Four is typical: the people who work
on the project, the people who run or support it, the people who will build
something adjacent, and whoever owns a cross-cutting concern it turned up. If
users of the product need to know something, they are an audience too --
usually they do not.

**A section earns its place only if a reader in that role would act
differently.** An audience with nothing to say gets left out, not padded. This
is the section that decays into self-congratulation fastest, so keep it to
statements: what exists now that did not, what habit to drop, what was wrong
and is now known. Do not editorialise about learning.

Four kinds of content, and the last two are the ones people skip:

1. **New in the world.** A module, a command, a pattern that did not exist and
   now does -- named, with a link, so someone can find it when they need it.
2. **Do Y, not X.** A habit the work retired. State it as an instruction.
3. **A corrected misunderstanding.** Something the organisation believed that
   is not true, or a practice nobody had adopted. These are the highest-value
   items and the least comfortable to write.
4. **Corrections to this work itself.** A bug this batch introduced and found,
   a first answer that was wrong. Including them is what makes the other three
   credible.

**Point at where it lives.** A lesson that matters outlives the document, so
it belongs in a README, a comment, or an engineering-docs commit. Say where,
and link it. This section is the notice; the repository is the record.

### How it happened

Everything above is the outcome, arranged for a reader who wants to know what
the batch achieved. This section is the story: what was asked for, what came
back, and where the plan turned. It is the part colleagues tend to mean by
"the plot" -- the reason the code looks like this rather than some other way
-- and it is the only part of the document with reversals in it.

It is prose in the plot, not a feature. Entries cite the appendix with `ld:`
and quote it with `ldq:`, the same as any other annotation.

**What belongs.** One test: *a turn belongs if the outcome would be surprising
without it.* That is the highlight rule raised a level -- a highlight must
contain what the next prompt answers; an entry must contain what the next
entry assumes. Effort is not plot: forty turns of applying a decision already
made are one clause, or nothing.

In practice the turns that pass are of six kinds, and the last three are the
ones a sceptical reader weighs most:

1. The scope changed from outside -- a colleague, a ticket, an incident.
2. The frame changed: someone asked a different question about the same thing.
3. A constraint was discovered that ruled an option out.
4. A proposal was argued down, in either direction.
5. A recommendation was overruled.
6. A claim was checked and was wrong.

**Shape.** One short paragraph per entry: a bold title, when, what changed and
why, the citation or quote, and a closing italic sentence saying what was
different afterwards. Ten to twenty entries for a week of work; 1,500 words is
plenty. Write them in order and make them chain -- each should end where the
next begins. If you reach an entry whose premise came from nowhere, one is
missing.

**Write for someone in another role.** The reader may be at the same
organisation and work on nothing like this. Give sentences their nouns, and
define a term the first time an entry depends on it, in a clause rather than a
sentence: not "the switch" but "the switch: the load balancer in front of the
site could be told to serve a static page instead of the application". A
`## Terms` section above does not cover this -- an entry has to be readable
where it sits.

**Give the human stakes their weight.** What made the work urgent is usually
in the record and usually left out of summaries: a date, a season, a person
who has to get up at 4am, a number that is getting worse. Those are what make
the technical entries legible as a sequence rather than a list. Find the turn
where the stake was measured and give it an entry of its own.

**Quoting.** A quote that *is* the content takes no label -- `[](ldq:#id)`
renders the words in place, attributed, with a link through. A quote the prose
is not reciting takes a label and stays a control the reader can open. A
reference with no label, `[](ld:#id)`, renders as a small citation marker;
use it where the sentence has already said the thing and only needs to say
where it came from.

Flag each item where it is delivered with `[](ldc:#id)` in a file, section
or line note. The renderer numbers and colours the flag, shows the item on
hover, and lists on the item every place it is flagged. Link to an item in
prose with `ld:#cat-id`.

## 5. Cut the diff into chapters

`chapters:` replaces `order:`. Put files in dependency order: what had to
exist before the next thing could use it, which is rarely merge order or
alphabetical order. Each chapter gets a title and a short note saying why the
reader has moved. Put `*` in a closing "Housekeeping" chapter. `hide:` lock
files and generated output; `collapse:` files that are present for
completeness (provider blocks, outputs, renames, formatting).

## 6. Annotate files

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

## 7. Chapter the stream, and highlight the turns that carry it

Every session's turns render as one chronological stream, so `appendix:
chapters:` are about the subject, not the session. A chapter is fixed by the
turn it opens at (`at: thread:turn-id`); write a title and a note saying what
the reader has moved to, the way a diff chapter does. Ten to fifteen over a
week of work is about right.

Then, under `turns:`, choose **highlights** for the turns that carry the
argument. `prompt:` and `response:` take the same anchor forms as a file and
also take a list, for a reply whose decisive parts are pages apart -- the
options and the recommendation.

Be generous. A highlight has to contain at least what the next prompt is
responding to, or the reader cannot follow the thread; usually that means a
section, not a sentence. A reply cut to its first line reads as an assertion,
and the point of showing it is to let someone judge the reasoning.

Setting a highlight replaces the default, which keeps a message's opening *and*
its closing passage. So when you set one on a reply whose last paragraph is
what the next prompt answers, give a list and keep that paragraph -- otherwise
your highlight is worse than no highlight.

Give each such turn an `id:`, then cite from the diff side: `ld:#id` to send
the reader to a turn, `ldq:#id-prompt` to quote the words inline where the
claim is made. Cite where the record answers a question the diff raises -- why
this approach and not the obvious one, where a constraint came from, what was
tried and abandoned. A chapter whose work left no trace in the diff cites
turns rather than embedding them.

Do not paraphrase a turn in a note and cite it as though it said that. Quote
it, or say what it settled in your own words without the citation. Keep the
turns where the model was wrong or was argued down, and highlight those too:
they are worth more to a reader judging the work than the turns where it was
right.

## 8. Build, read stderr, repeat

```bash
uv run literate-diff -a notes.yaml -o out/review.html
```

Every warning names a fix: an anchor that no longer matches, an anchor that
matches more than once (narrow it or set `nth`; `nth: 1` does not silence
it), a `files:` key not in the diff, a `turns:` key not in the transcript, an
appendix chapter starting at a turn that is not there, a reference to an
unknown id, a flag to an undeclared category item. A clean build has none. Check the rendered
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
