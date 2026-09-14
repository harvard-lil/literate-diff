# Source: transcript

Agent conversations, collected from local session logs into a YAML file.
Turns are the items; rows are sentences of a prompt or reply, and lines of
code or table inside one.

## Collect, before writing

```bash
uv run literate-diff collect --repo ../h2o \
    --title "<session title>" --merge-by-title -o conversations.yaml
```

Session logs are local, mutable and eventually deleted, so the output file
is the copy of record and belongs beside the sidecar. `--title` keeps
sessions whose title contains it; `--merge-by-title` treats sessions
sharing a title as one thread and drops the turns a resumed session repeats.
`--timezone` sets the clock times are shown on and turn ids are derived
from; it defaults to the collecting machine's and is written into the file.

`--tool codex` reads Codex threads (CLI, IDE extension or desktop app)
instead of Claude sessions; `--tool claude-code --tool codex` reads both
into one file when the work moved between agents. Codex threads are matched
on the directory they ran in, so a thread started from a parent directory
(a metarepo checkout) needs `--repo` set to that directory, then `--title`
or `--session` to narrow it. Codex thread names are what the sidebar shows;
list them with `jq -r '.thread_name' ~/.codex/session_index.jsonl`.

**Read it before it goes anywhere.** Prompts and replies quote whatever was
on screen, including printed environment, absolute paths, tokens in error
output and other people's messages pasted in. Cut what should not be
shared. Nothing regenerates the file, so a rebuild will not undo an edit.

Keep the rest. The stream is comprehensive, not selected: it is read by
someone following how a decision was reached, who needs the turns in order,
and by someone deciding how hard to review the diff, for whom the thin
turns ("ok go ahead" next to a link to a failing run) are the evidence.
Cutting to the turns where the answer was good produces a third thing, and
it reads like one.

## Read

Read the whole transcript, in chunks, into the turn ledger: one line per
prompt, what was asked, what came back, what was different afterwards.
Decisions, rejected alternatives, measurements and incidents are what a diff
cannot show, and they are what the story is made of. Note where the author
was argued down and where the agent was wrong; those turns are worth more
to a reader judging the work than the turns where it was right.

## Annotate

Turns go in a stream layer of their own. Every session's turns render as
one chronological stream, so chapters are about the subject, not the
session: a chapter is fixed by the turn it opens at (`at: thread:turn-id`),
with a title and a note saying what the reader has moved to. Ten to fifteen
over a week of work.

Under `turns:` (or the layer's `items:`), choose **highlights** for the
turns that carry the argument: `prompt:` and `response:` take the same
anchor forms as a file, and a list, for a reply whose decisive parts are
pages apart -- the options and the recommendation.

Be generous. A highlight has to contain at least what the next prompt is
responding to, or the reader cannot follow the thread; usually that means a
section, not a sentence. A reply cut to its first line reads as an
assertion, and the point of showing it is to let someone judge the
reasoning. Setting a highlight replaces the default, which keeps a
message's opening *and* its closing passage; when the last paragraph is
what the next prompt answers, give a list and keep it.

Give each such turn an `id:`, then cite from prose: `ld:#id` to send the
reader to a turn, `ldq:#id-prompt` to quote the words inline where the
claim is made, `anchors:` with `in: response` for a sentence inside a
reply. Do not paraphrase a turn in a note and cite it as though it said
that. Quote it, or say what it settled in your own words without the
citation.

## Corrections and attribution

Track a recommendation through later challenges and reversals before citing it
as the explanation of the final code. Distinguish what an agent reports from
what a tool result or operator observation establishes. A confident reply is
evidence of that reply, not an independent test result. Record missing replies
and external investigations so completeness claims match the collected scope.
Account changes described here are outside git, not outside the record; do not
relabel them as independent operator testimony.
