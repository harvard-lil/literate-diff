"""Conversations as an appendix: rows, highlights, and references into them."""

import json
import re

import pytest

from literate_diff.annotate import build_document
from literate_diff.parse import parse_diff
from literate_diff.render import render_document
from literate_diff.transcript import load_transcript, split_rows

DIFF = """\
diff --git a/first.py b/first.py
--- a/first.py
+++ b/first.py
@@ -1,2 +1,2 @@
-SECRET = "<hardcoded>"
+SECRET = os.environ["SECRET"]
"""

TRANSCRIPT = """\
collected: 2026-03-04T12:00:00Z
threads:
  - id: registry
    title: Registry auth
    sessions: [aaaa1111]
    turns:
      - id: t0304-1500
        at: 2026-03-04T15:00:00Z
        prompt: |-
          Can we put the registry behind SSO? I do like losing the surface area.
          Or not, I dunno.
        response: |-
          No, and the reason is the CLI. Docker login cannot do a browser flow.
        work: {seconds: 204, tokens: 33741}
        tools: {Bash: 29, WebSearch: 2}
        attachments: ["settings.py"]
        narration:
          - |-
            I'll look at how it is set up first.
      - id: t0304-1600
        at: 2026-03-04T16:00:00Z
        prompt: |-
          Then delete it.
"""


@pytest.fixture
def transcript(tmp_path):
    path = tmp_path / "conversations.yaml"
    path.write_text(TRANSCRIPT)
    return str(path)


def build(spec, transcript=None):
    meta = {"transcript": transcript} if transcript else {}
    return render_document(build_document(parse_diff(DIFF), spec, meta))


def body(page: str) -> str:
    """The rendered document alone. The inlined stylesheet and client script
    mention every class name, so a bare `in page` proves nothing."""
    return page.split("</style>", 1)[1].split("<script>", 1)[0]


# --- rows ---------------------------------------------------------------------


def test_prose_is_split_into_sentences_so_a_highlight_can_be_one():
    rows = split_rows("First one. Second one! Third?")
    assert [r.text for r in rows] == ["First one.", "Second one!", "Third?"]


def test_abbreviations_do_not_end_a_sentence():
    rows = split_rows("Use ECR, e.g. the private one. Not GHCR.")
    assert [r.text for r in rows] == ["Use ECR, e.g. the private one.", "Not GHCR."]


def test_fenced_code_stays_line_by_line():
    rows = split_rows("Look:\n```\nFROM base AS prod\nFROM prod AS test\n```\nSee?")
    kinds = [(r.kind, r.text) for r in rows]
    assert ("code", "FROM base AS prod") in kinds
    assert ("code", "FROM prod AS test") in kinds
    assert kinds[-1] == ("prose", "See?")


def test_blank_lines_are_kept_as_paragraph_breaks_but_not_trailing():
    rows = split_rows("One.\n\nTwo.\n\n\n")
    assert [r.kind for r in rows] == ["prose", "blank", "prose"]


# --- loading ------------------------------------------------------------------


def test_a_turn_without_a_reply_still_loads(transcript):
    warnings = []
    threads = load_transcript(transcript, warnings)
    assert [t.id for t in threads[0].turns] == ["t0304-1500", "t0304-1600"]
    assert threads[0].turns[1].response is None
    assert not warnings


def test_the_work_band_summarises_rather_than_reproduces(transcript):
    thread = load_transcript(transcript, [])[0]
    work = thread.turns[0].work
    assert work.tool_count == 31
    assert "3 min" in work.summary()
    assert "33.7k tokens" in work.summary()
    assert "Bash ×29" in work.summary()


# --- rendering ----------------------------------------------------------------


def test_the_appendix_renders_every_turn(transcript):
    page = build({}, transcript)
    assert page.count('class="ld-turn"') == 2
    assert "Registry auth" in page
    assert "31 tool calls" in page
    assert "settings.py" in page
    # The narration is a label on the band, not a message of its own.
    assert "I&#x27;ll look at how it is set up first." in page


def test_turns_are_addressable_without_being_annotated(transcript):
    page = build({}, transcript)
    anchors = json.loads(re.search(r"window\.LD_ANCHORS = (\{.*?\});", page, re.S).group(1))
    assert anchors["turn-registry-t0304-1500"]["body"] == "t0p"
    assert anchors["turn-registry-t0304-1500-response"]["body"] == "t0q"


def test_a_highlight_is_what_shows_and_the_rest_is_one_click_away(transcript):
    spec = {
        "turns": {
            "registry:t0304-1500": {
                "id": "q-sso",
                "prompt": {"at": "losing the surface area"},
            }
        }
    }
    page = build(spec, transcript)
    # Row 1 is the highlight; row 0 and row 2 are present but folded.
    assert '<span class="ld-prow ld-pprose" id="t0p-r1">' in page
    assert '<span class="ld-prow ld-pprose ld-elided" id="t0p-r0">' in page
    assert "show all (3 lines)" in page
    assert "ld-gap" in page


def test_without_a_highlight_short_messages_show_whole(transcript):
    page = build({}, transcript)
    assert 'id="t1p-r0"' in page
    # Everything here is under the lead budget, so nothing is folded.
    assert "show all" not in body(page)
    assert "ld-elided" not in body(page)


def _long(tmp_path, paragraphs: int, sentences: int = 10):
    path = tmp_path / "long.yaml"
    text = "\n\n".join(
        " ".join(f"Sentence number {i} runs on for a while." for i in range(sentences))
        for _ in range(paragraphs)
    )
    body_lines = "\n".join("          " + ln for ln in text.split("\n"))
    path.write_text(
        "threads:\n  - id: t\n    title: T\n    turns:\n      - id: t1\n"
        "        at: 2026-03-04T15:00:00Z\n        prompt: |-\n" + body_lines + "\n"
    )
    return str(path)


def test_without_a_highlight_a_long_message_leads_with_its_opening(tmp_path):
    page = body(build({}, _long(tmp_path, paragraphs=4)))
    assert "ld-elided" in page
    # The fold lands on a paragraph boundary, not between two sentences.
    assert '<span class="ld-prow ld-pprose" id="t0p-r9">' in page
    assert '<span class="ld-prow ld-pprose ld-elided" id="t0p-r11">' in page


def test_a_paragraph_with_no_break_in_it_still_folds(tmp_path):
    # No boundary to stop on, so the budget gives way rather than showing
    # a five-thousand-character paste whole.
    page = body(build({}, _long(tmp_path, paragraphs=1, sentences=60)))
    assert "ld-elided" in page


def test_a_short_tail_is_shown_rather_than_folded(tmp_path):
    page = body(build({}, _long(tmp_path, paragraphs=2, sentences=5)))
    assert "ld-elided" not in page
    assert "show all" not in page


def test_the_narrative_can_quote_a_message(transcript):
    spec = {
        "turns": {"registry:t0304-1500": {"id": "q-sso"}},
        "plot": "He asked [about SSO](ldq:#q-sso-prompt).",
    }
    page = body(build(spec, transcript))
    assert "ld-quote-said" in page
    assert "Registry auth — said" in page
    assert "Can we put the registry behind SSO?" in page
    # Quoting prose shows no diff signs or line numbers.
    assert "ld-qsign" not in page


def test_a_reference_into_the_appendix_points_forward(transcript):
    spec = {
        "turns": {"registry:t0304-1500": {"id": "q-sso"}},
        "plot": "See [the exchange](ld:#q-sso).",
    }
    page = build(spec, transcript)
    assert re.search(r'class="ld-ref ld-ref-forward"[^>]*data-ld-target="q-sso"', page)


def test_annotations_that_name_a_missing_turn_are_reported(transcript):
    doc = build_document(
        parse_diff(DIFF),
        {"turns": {"registry:t9999-9999": {"id": "x"}}, "threads": {"absent": {}}},
        {"transcript": transcript},
    )
    assert any("is not in the transcript" in w for w in doc.warnings)
    assert any("threads: 'absent'" in w for w in doc.warnings)


def test_turn_annotations_without_a_transcript_are_reported():
    doc = build_document(parse_diff(DIFF), {"turns": {"a:b": {}}}, {})
    assert any("need a `transcript:`" in w for w in doc.warnings)


def test_a_document_with_no_transcript_renders_no_appendix():
    page = body(build({}))
    assert "ld-appendix" not in page
    assert "Appendix" not in page


# --- markdown -----------------------------------------------------------------


def test_sentence_splitting_leaves_labels_and_markup_alone():
    rows = split_rows("**A. Keycloak OIDC** — days to weeks. Poor ratio.")
    assert [r.text for r in rows] == [
        "**A. Keycloak OIDC** — days to weeks.",
        "Poor ratio.",
    ]


def test_blocks_are_rebuilt_around_the_rows():
    from literate_diff.message import render_message

    rows = split_rows(
        "## Options\n\nText with **bold**. More text.\n\n"
        "- One `item`. Second sentence.\n- Two\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n```\ncode line\n```\n"
    )
    out = render_message(rows, "t0p", [(0, len(rows) - 1)])
    assert '<h4 class="ld-pheadingline"' in out
    assert "<strong>bold</strong>" in out
    assert '<ul class="ld-plist"' in out and out.count('<li class="ld-pitem') == 2
    assert "<code>item</code>" in out
    assert '<table class="ld-ptableblock"' in out and out.count("<td>") == 4
    assert '<pre class="ld-pcodeblock"' in out and "code line" in out


def test_rows_carry_a_real_space_so_the_page_can_be_copied():
    from literate_diff.message import render_message

    rows = split_rows("One sentence. Two sentences.")
    out = render_message(rows, "t0p", [(0, 1)])
    # Not a CSS ::after: generated content does not reach the clipboard.
    assert "One sentence. </span>" in out


def test_every_content_row_keeps_an_id_even_where_it_is_not_shown():
    from literate_diff.message import render_message

    rows = split_rows("| a | b |\n|---|---|\n| 1 | 2 |")
    out = render_message(rows, "t0p", [(0, 0)])
    # Rows 0 and 2 are the table's content; row 1 is its `|---|` punctuation,
    # which is not rendered and has nothing to anchor to.
    assert 'id="t0p-r0"' in out and 'id="t0p-r2"' in out
    assert 'id="t0p-r1"' not in out


def test_row_numbering_survives_the_rows_that_are_not_rendered():
    from literate_diff.message import render_message

    rows = split_rows("One.\n\nTwo.\n\nThree.")
    out = render_message(rows, "t0p", [(0, len(rows) - 1)])
    # Indices count blanks; the DOM does not carry them.
    assert 'id="t0p-r0">One.' in out and 'id="t0p-r4">Three.' in out
    assert 'id="t0p-r1"' not in out


# --- more than one passage ----------------------------------------------------


def test_a_highlight_may_be_several_passages(transcript):
    spec = {
        "turns": {
            "registry:t0304-1500": {
                "id": "q-sso",
                "response": [
                    {"at": "No, and the reason is the CLI"},
                    {"at": "Docker login cannot do a browser flow"},
                ],
            }
        }
    }
    doc = build_document(
        parse_diff(DIFF), spec, {"transcript": transcript}
    )
    turn = doc.turns[0]
    assert turn.response_ranges == [(0, 0), (1, 1)]
    # Each passage is quotable on its own.
    assert "q-sso-response" in doc.anchors and "q-sso-response2" in doc.anchors
    assert not doc.warnings


# --- one stream ---------------------------------------------------------------

TWO_THREADS = """\
threads:
  - id: main
    title: Main
    turns:
      - {id: a, at: 2026-03-04T09:00:00Z, prompt: First.}
      - {id: c, at: 2026-03-04T11:00:00Z, prompt: Third.}
  - id: aside
    title: Aside
    turns:
      - {id: b, at: 2026-03-04T10:00:00Z, prompt: Second.}
"""


@pytest.fixture
def two_threads(tmp_path):
    path = tmp_path / "two.yaml"
    path.write_text(TWO_THREADS)
    return str(path)


def test_threads_interleave_by_time(two_threads):
    doc = build_document(parse_diff(DIFF), {}, {"transcript": two_threads})
    assert [t.id for t in doc.turns] == ["a", "b", "c"]


def test_a_badge_marks_only_where_the_stream_changes_session(two_threads, transcript):
    page = body(render_document(build_document(parse_diff(DIFF), {}, {"transcript": two_threads})))
    # Three turns, three crossings: main -> aside -> main.
    assert page.count("ld-turn-thread") == 3
    one = body(render_document(build_document(parse_diff(DIFF), {}, {"transcript": transcript})))
    assert "ld-turn-thread" not in one


def test_appendix_chapters_cut_the_stream(two_threads):
    spec = {
        "appendix": {
            "chapters": [
                {"at": "aside:b", "id": "second", "title": "The aside", "note": "Why."},
                {"at": "main:a", "id": "first", "title": "The opening"},
            ]
        }
    }
    doc = build_document(parse_diff(DIFF), spec, {"transcript": two_threads})
    # Declared out of order; they follow the stream.
    assert [(c.anchor_id, c.start) for c in doc.appendix_chapters] == [("first", 0), ("second", 1)]
    page = body(render_document(doc))
    assert 'id="ac-first"' in page and "The aside" in page
    assert not doc.warnings


def test_a_chapter_at_a_turn_that_is_not_there_is_reported(two_threads):
    doc = build_document(
        parse_diff(DIFF),
        {"appendix": {"chapters": [{"at": "main:zzz", "title": "x"}]}},
        {"transcript": two_threads},
    )
    assert any("not in the transcript" in w for w in doc.warnings)


# --- clocks -------------------------------------------------------------------


def test_times_are_shown_on_the_transcripts_clock(tmp_path):
    from literate_diff.transcript import format_span, format_when

    # The logs stamp UTC; the reader wants the clock the work happened on.
    assert format_when("2026-09-01T20:06:00Z", "America/New_York") == (
        "Tuesday, Sept. 1 4:06PM"
    )
    assert format_when("2026-12-02T21:06:00Z", "America/New_York") == (
        "Wednesday, Dec. 2 4:06PM"
    )
    # Noon and midnight are the two the 12-hour clock gets wrong.
    assert format_when("2026-07-04T16:00:00Z", "America/New_York").endswith("12:00PM")
    assert format_when("2026-07-04T04:00:00Z", "America/New_York").endswith("12:00AM")
    assert format_span(
        "2026-08-31T14:19:00Z", "2026-09-04T23:34:00Z", "America/New_York"
    ) == "Aug. 31 – Sept. 4, 2026"
    assert format_span(
        "2026-09-04T14:00:00Z", "2026-09-04T18:00:00Z", "America/New_York"
    ) == "Sept. 4, 2026"


def test_an_unreadable_zone_falls_back_and_says_so(tmp_path):
    path = tmp_path / "t.yaml"
    path.write_text(
        "timezone: Mars/Olympus\nthreads:\n  - id: t\n    title: T\n    turns:\n"
        "      - {id: t1, at: 2026-09-01T20:06:00Z, prompt: Hi.}\n"
    )
    warnings = []
    threads = load_transcript(str(path), warnings)
    assert threads[0].zone == "UTC"
    assert any("is not a zone" in w for w in warnings)


def test_turn_ids_follow_the_same_clock_as_the_times_beside_them(tmp_path):
    from literate_diff.collect import Thread as CThread
    from literate_diff.collect import Turn as CTurn
    from literate_diff.collect import turn_id

    turn = CTurn(at="2026-09-01T20:06:00Z", prompt="Hi")
    assert turn_id(turn, set(), "America/New_York") == "t0901-1606"
    assert turn_id(turn, set(), "UTC") == "t0901-2006"


def test_the_control_sits_inside_the_message_it_opens(tmp_path):
    page = body(build({}, _long(tmp_path, paragraphs=4)))
    block = page[page.index('class="ld-msg-body"') :]
    # Inside the tinted body, not floating under it.
    assert block.index("ld-msg-more") < block.index("</div></div>")


def test_the_closing_passage_is_kept_because_the_next_turn_answers_it(tmp_path):
    path = tmp_path / "close.yaml"
    middle = "\n\n".join(
        " ".join(f"Middle sentence {i} of paragraph {j}." for i in range(8))
        for j in range(6)
    )
    text = (
        "Opening paragraph that sets out the problem at hand.\n\n"
        + middle
        + "\n\nSo: shall I go ahead and apply it?"
    )
    lines = "\n".join("          " + ln for ln in text.split("\n"))
    path.write_text(
        "threads:\n  - id: t\n    title: T\n    turns:\n      - id: t1\n"
        "        at: 2026-09-01T20:06:00Z\n        prompt: |-\n" + lines + "\n"
    )
    page = body(build({}, str(path)))
    assert "Opening paragraph that sets out the problem" in page
    assert "ld-elided" in page
    # The question the next turn answers is not behind the control.
    closing = page[page.index("shall I go ahead and apply it") - 200 :]
    assert "ld-elided" not in closing.split("shall I go ahead")[0][-120:]


def test_the_closing_passage_opens_at_the_top_of_its_block(tmp_path):
    """A close landing inside a list starts at the heading above it, not at
    whichever bullet the budget happened to reach."""
    path = tmp_path / "list.yaml"
    filler = "\n\n".join(
        " ".join(f"Filler sentence {i} of paragraph {j}." for i in range(8))
        for j in range(6)
    )
    text = (
        "Opening paragraph stating the problem.\n\n"
        + filler
        + "\n\n## What I'd do\n\n"
        + "\n".join(f"- Step {i}, which is a reasonably long line of its own." for i in range(6))
        + "\n\nShall I take these in that order?"
    )
    lines = "\n".join("          " + ln for ln in text.split("\n"))
    path.write_text(
        "threads:\n  - id: t\n    title: T\n    turns:\n      - id: t1\n"
        "        at: 2026-09-01T20:06:00Z\n        prompt: |-\n" + lines + "\n"
    )
    page = body(build({}, str(path)))
    head = page.index("What I'd do")
    assert "ld-elided" not in page[head - 60 : head]
    assert "ld-elided" not in page[head : page.index("Shall I take these")]


def test_an_unlabelled_citation_is_a_marker_and_an_unlabelled_quote_is_shown(transcript):
    spec = {
        "turns": {"registry:t0304-1500": {"id": "q-sso"}},
        "plot": "It was settled [](ld:#q-sso), like this: [](ldq:#q-sso-response)",
    }
    page = body(build(spec, transcript))
    # The bare reference renders as a citation marker, not a naked arrow.
    assert "ld-cite" in page
    # The bare quote shows its words rather than hiding them behind a control.
    assert "ld-quote-open" in page
    assert "No, and the reason is the CLI" in page
    assert "ld-quote-btn" not in page


def test_a_labelled_quote_stays_a_control(transcript):
    spec = {
        "turns": {"registry:t0304-1500": {"id": "q-sso"}},
        "plot": "He asked [about SSO](ldq:#q-sso-prompt).",
    }
    page = body(build(spec, transcript))
    assert "ld-quote-btn" in page and "ld-quote-open" not in page
