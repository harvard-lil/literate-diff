"""The Codex collector: rollout JSONL to turns."""

import json

import yaml

from literate_diff.codex import read_rollout
from literate_diff.collect import collect, to_yaml
from literate_diff.transcript import load_transcript

PROJECT = "/work/proj"


def rec(ts, kind, **payload):
    return json.dumps({"timestamp": ts, "type": kind, "payload": payload})


def meta(sid, cwd=PROJECT, source="vscode", ts="2026-09-11T17:00:00.000Z"):
    return rec(ts, "session_meta", id=sid, cwd=cwd, originator="Codex Desktop", source=source)


def user(ts, *texts, images=0):
    content = [{"type": "input_text", "text": t} for t in texts]
    content += [{"type": "input_image", "image_url": "data:"} for _ in range(images)]
    return rec(ts, "response_item", type="message", role="user", content=content)


def say(ts, text, phase="final_answer"):
    return rec(ts, "response_item", type="message", role="assistant", phase=phase,
               content=[{"type": "output_text", "text": text}])


def call(ts, name, kind="function_call"):
    return rec(ts, "response_item", type=kind, name=name, call_id="c")


def tokens(ts, total, out):
    return rec(ts, "event_msg", type="token_count",
               info={"total_token_usage": {"total_tokens": total},
                     "last_token_usage": {"output_tokens": out}})


def write_rollout(home, sid, records, day="2026/09/11"):
    directory = home / ".codex" / "sessions" / day
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"rollout-2026-09-11T13-00-00-{sid}.jsonl"
    path.write_text("\n".join(records) + "\n")
    return path


CONTEXT = [
    "# AGENTS.md instructions for /work/proj\n\n<INSTRUCTIONS>\nBe brief.\n</INSTRUCTIONS>",
    "<environment_context>\n  <cwd>/work/proj</cwd>\n</environment_context>",
]


def session(sid="01a0916a-0000-7000-8000-000000000001"):
    return [
        meta(sid),
        user("2026-09-11T17:03:23.900Z", *CONTEXT),
        user(
            "2026-09-11T17:03:24.000Z",
            "\n# Files mentioned by the user:\n\n## shot.png: /var/folders/x/shot.png\n\n"
            "## My request for Codex:\nWhy does the build fail?\n",
            '<image name=[Image #1] path="/var/folders/x/shot.png">',
            "</image>",
            images=1,
        ),
        rec("2026-09-11T17:03:25.000Z", "response_item", type="reasoning", summary=[],
            encrypted_content="xxx"),
        say("2026-09-11T17:03:30.000Z", "Reading the build script first.", phase="commentary"),
        call("2026-09-11T17:03:31.000Z", "exec", kind="custom_tool_call"),
        call("2026-09-11T17:03:32.000Z", "exec", kind="custom_tool_call"),
        rec("2026-09-11T17:03:33.000Z", "response_item", type="web_search_call", status="completed"),
        tokens("2026-09-11T17:03:34.000Z", 1000, 40),
        tokens("2026-09-11T17:03:34.100Z", 1000, 40),  # repeated report, same totals
        say("2026-09-11T17:05:24.000Z", "The lockfile is stale."),
        tokens("2026-09-11T17:05:25.000Z", 2000, 60),
        user("2026-09-11T17:06:00.000Z", "Fix it"),
        call("2026-09-11T17:06:01.000Z", "apply_patch", kind="custom_tool_call"),
        user("2026-09-11T17:06:02.000Z", "<subagent_notification>done</subagent_notification>"),
        rec("2026-09-11T17:06:03.000Z", "event_msg", type="turn_aborted", reason="interrupted"),
        user(
            "2026-09-11T17:07:00.000Z",
            "<turn_aborted>\nThe user interrupted the previous turn on purpose.\n</turn_aborted>",
        ),
        user("2026-09-11T17:07:01.000Z", "Stop, use the other lockfile"),
        rec("2026-09-11T17:07:30.000Z", "compacted", message="", replacement_history=[]),
        say("2026-09-11T17:08:00.000Z", "Done."),
    ]


def test_a_turn_is_what_the_person_typed_and_the_work_after_it(tmp_path):
    path = write_rollout(tmp_path, "01a0916a-0000-7000-8000-000000000001", session())
    info, turns = read_rollout(path)
    assert info["cwd"] == PROJECT
    assert [t.prompt for t in turns] == [
        "Why does the build fail?", "Fix it", "Stop, use the other lockfile",
    ]
    first, second, third = turns
    assert first.attachments == ["shot.png"]
    assert first.images == 1
    assert first.narration == ["Reading the build script first."]
    assert first.response == "The lockfile is stale."
    assert first.tools == {"exec": 2, "web_search": 1}
    assert first.out_tokens == 100
    assert first.seconds == 120
    assert second.tools == {"apply_patch": 1}
    assert second.events == 1
    assert second.interrupted is True
    assert second.response == ""
    assert third.compacted is True
    assert third.response == "Done."


def test_collects_named_threads_for_the_project_only(tmp_path):
    sid = "01a0916a-0000-7000-8000-000000000001"
    write_rollout(tmp_path, sid, session(sid))
    write_rollout(tmp_path, "01a0916a-0000-7000-8000-00000000000e",
                  [meta("01a0916a-0000-7000-8000-00000000000e", cwd="/elsewhere"),
                   user("2026-09-11T18:00:00.000Z", "Not this one")])
    write_rollout(tmp_path, "01a0916a-0000-7000-8000-00000000000s",
                  [meta("01a0916a-0000-7000-8000-00000000000s",
                        source={"subagent": {"thread_spawn": {"parent_thread_id": sid}}}),
                   user("2026-09-11T18:00:00.000Z", "Subagent task")])
    index = tmp_path / ".codex" / "session_index.jsonl"
    index.write_text(
        json.dumps({"id": sid, "thread_name": "Build fix draft"}) + "\n"
        + json.dumps({"id": sid, "thread_name": "Build fix"}) + "\n"
    )
    threads = collect(PROJECT, tmp_path, tools=["codex"], zone="America/New_York")
    assert [(t.title, t.tool) for t in threads] == [("Build fix", "codex")]
    assert threads[0].turn_ids == ["t0911-1303", "t0911-1306", "t0911-1307"]


def test_an_unnamed_thread_is_titled_by_its_first_message(tmp_path):
    sid = "01a0916a-0000-7000-8000-000000000002"
    write_rollout(tmp_path, sid, [meta(sid), user("2026-09-11T17:00:01.000Z", "Look at the deploy"),
                                   say("2026-09-11T17:00:02.000Z", "Looking.")])
    threads = collect(PROJECT, tmp_path, tools=["codex"])
    assert threads[0].title == "Look at the deploy"


def test_claude_and_codex_threads_collect_into_one_transcript(tmp_path):
    sid = "01a0916a-0000-7000-8000-000000000001"
    write_rollout(tmp_path, sid, session(sid))
    claude = tmp_path / ".claude" / "projects" / "-work-proj"
    claude.mkdir(parents=True)
    (claude / "s1.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"type": "custom-title", "customTitle": "Build fix"},
        {"type": "user", "timestamp": "2026-09-10T12:00:00Z",
         "message": {"role": "user", "content": "Plan the build fix"}},
        {"type": "assistant", "timestamp": "2026-09-10T12:01:00Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "Plan."}]}},
    ]) + "\n")
    (tmp_path / ".codex" / "session_index.jsonl").write_text(
        json.dumps({"id": sid, "thread_name": "Build fix"}) + "\n")

    threads = collect(PROJECT, tmp_path, tools=["claude-code", "codex"], merge_by_title=True)
    # Same title, different agents: two threads, in the order the work happened.
    assert [t.tool for t in threads] == ["claude-code", "codex"]

    text = to_yaml(threads, {"collected": "now", "timezone": "UTC"})
    assert [t["tool"] for t in yaml.safe_load(text)["threads"]] == ["claude-code", "codex"]
    loaded = load_transcript(text, [])
    assert [t.tool for t in loaded] == ["claude-code", "codex"]


def test_a_missing_store_for_one_tool_is_not_an_error_when_another_has_one(tmp_path):
    sid = "01a0916a-0000-7000-8000-000000000002"
    write_rollout(tmp_path, sid, [meta(sid), user("2026-09-11T17:00:01.000Z", "hi"),
                                   say("2026-09-11T17:00:02.000Z", "hello")])
    threads = collect(PROJECT, tmp_path, tools=["claude-code", "codex"])
    assert len(threads) == 1


def test_older_transcripts_name_their_tool_at_the_top():
    text = (
        "collected: now\ntool: claude-code\nthreads:\n"
        "  - id: w\n    title: Work\n    turns:\n"
        "      - id: t1\n        at: 2026-01-01T00:00:00Z\n        prompt: hi\n"
    )
    assert load_transcript(text, [])[0].tool == "claude-code"


def test_a_resumed_thread_does_not_stretch_the_turn_before_it(tmp_path):
    sid = "01a0916a-0000-7000-8000-000000000003"
    path = write_rollout(tmp_path, sid, [
        meta(sid),
        user("2026-09-11T17:00:00.000Z", "Start"),
        say("2026-09-11T17:01:00.000Z", "Started."),
        rec("2026-09-11T20:00:00.000Z", "response_item", type="message", role="developer",
            content=[{"type": "input_text", "text": "<permissions instructions>"}]),
        user("2026-09-11T20:00:00.100Z", *CONTEXT),
        user("2026-09-11T20:00:01.000Z", "Continue"),
    ])
    _, turns = read_rollout(path)
    assert turns[0].seconds == 60


def test_terminal_colour_codes_do_not_break_the_transcript(tmp_path):
    sid = "01a0916a-0000-7000-8000-000000000004"
    write_rollout(tmp_path, sid, [
        meta(sid),
        user("2026-09-11T17:00:00.000Z", "It printed \x1b[31mFAILED\x1b[0m and a bell\x07"),
        say("2026-09-11T17:01:00.000Z", "Fixed."),
    ])
    threads = collect(PROJECT, tmp_path, tools=["codex"])
    assert threads[0].turns[0].prompt == "It printed FAILED and a bell"
    yaml.safe_load(to_yaml(threads, {"collected": "now"}))
