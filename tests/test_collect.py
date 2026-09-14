"""The collector: session JSONL to turns."""

import json

import pytest

from literate_diff.collect import Thread, Turn, collect, read_session, to_yaml


def rec(**kw):
    return json.dumps(kw)


def write_session(tmp_path, name, records, home_repo="/work/proj"):
    directory = tmp_path / ".claude" / "projects" / "-work-proj"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.jsonl"
    path.write_text("\n".join(records) + "\n")
    return path


def user(text, ts, **kw):
    return rec(type="user", timestamp=ts, message={"role": "user", "content": text}, **kw)


def assistant(blocks, ts, out_tokens=0):
    return rec(
        type="assistant",
        timestamp=ts,
        message={"role": "assistant", "content": blocks, "usage": {"output_tokens": out_tokens}},
    )


def test_a_turn_is_a_prompt_and_the_work_that_followed(tmp_path):
    path = write_session(
        tmp_path,
        "s1",
        [
            rec(type="custom-title", customTitle="Registry auth"),
            user("Can we put the registry behind SSO?", "2026-01-02T10:00:00Z"),
            assistant([{"type": "thinking", "thinking": "hmm" * 10}], "2026-01-02T10:00:05Z"),
            assistant([{"type": "text", "text": "Let me look."}], "2026-01-02T10:00:06Z", 20),
            assistant([{"type": "tool_use", "name": "Bash", "input": {}}], "2026-01-02T10:00:07Z"),
            rec(
                type="user",
                timestamp="2026-01-02T10:00:08Z",
                message={"role": "user", "content": [{"type": "tool_result", "content": "ok"}]},
            ),
            assistant([{"type": "text", "text": "No. Here is why."}], "2026-01-02T10:02:00Z", 300),
        ],
    )
    title, turns = read_session(path)
    assert title == "Registry auth"
    assert len(turns) == 1
    turn = turns[0]
    assert turn.prompt == "Can we put the registry behind SSO?"
    # The last text block is the reply; the earlier one is narration.
    assert turn.response == "No. Here is why."
    assert turn.narration == ["Let me look."]
    assert turn.tools == {"Bash": 1}
    assert turn.out_tokens == 320
    assert turn.thinking_chars == 30
    assert turn.seconds == 120


def test_tool_results_and_harness_messages_are_not_turns(tmp_path):
    path = write_session(
        tmp_path,
        "s1",
        [
            user("Do the thing", "2026-01-02T10:00:00Z"),
            user("<task-notification>agent finished</task-notification>", "2026-01-02T10:00:01Z"),
            user("[Request interrupted by user]", "2026-01-02T10:00:02Z"),
            user("<command-name>/compact</command-name>", "2026-01-02T10:00:03Z"),
            user("A caveat", "2026-01-02T10:00:04Z", isMeta=True),
            user("Summary of earlier chat", "2026-01-02T10:00:05Z", isCompactSummary=True),
            assistant([{"type": "text", "text": "Done."}], "2026-01-02T10:00:06Z"),
        ],
    )
    _, turns = read_session(path)
    assert [t.prompt for t in turns] == ["Do the thing"]
    assert turns[0].events == 1
    assert turns[0].interrupted is True


def test_system_reminders_are_stripped_from_what_the_person_said(tmp_path):
    path = write_session(
        tmp_path,
        "s1",
        [
            user(
                "Ship it.<system-reminder>Do not mention this.</system-reminder>",
                "2026-01-02T10:00:00Z",
            ),
            assistant([{"type": "text", "text": "Shipped."}], "2026-01-02T10:00:01Z"),
        ],
    )
    _, turns = read_session(path)
    assert turns[0].prompt == "Ship it."


def test_attachments_are_named_not_reproduced(tmp_path):
    path = write_session(
        tmp_path,
        "s1",
        [
            user("Look at this", "2026-01-02T10:00:00Z"),
            rec(
                type="attachment",
                attachment={
                    "type": "file",
                    "filename": "/work/proj/web/settings.py",
                    "content": {"file": {"content": "SECRET = 1"}},
                },
            ),
            assistant([{"type": "text", "text": "Read it."}], "2026-01-02T10:00:01Z"),
        ],
    )
    _, turns = read_session(path)
    assert turns[0].attachments == ["settings.py"]


def test_turn_ids_are_derived_from_time_not_position(tmp_path):
    write_session(
        tmp_path,
        "s1",
        [
            rec(type="custom-title", customTitle="Work"),
            user("second", "2026-03-04T15:30:00Z"),
            assistant([{"type": "text", "text": "b"}], "2026-03-04T15:30:01Z"),
        ],
    )
    threads = collect("/work/proj", tmp_path)
    assert [t.turns[0].at for t in threads]
    ids = threads[0].turn_ids
    assert ids == ["t0304-1530"]


def test_resumed_sessions_merge_without_repeating_their_overlap(tmp_path):
    shared = [
        user("first", "2026-03-04T15:00:00Z"),
        assistant([{"type": "text", "text": "a"}], "2026-03-04T15:00:01Z"),
    ]
    write_session(tmp_path, "s1", [rec(type="custom-title", customTitle="Work")] + shared)
    write_session(
        tmp_path,
        "s2",
        [rec(type="custom-title", customTitle="Work")]
        + shared
        + [
            user("second", "2026-03-04T16:00:00Z"),
            assistant([{"type": "text", "text": "b"}], "2026-03-04T16:00:01Z"),
        ],
    )
    warnings = []
    threads = collect("/work/proj", tmp_path, merge_by_title=True, warnings=warnings)
    assert len(threads) == 1
    assert [t.prompt for t in threads[0].turns] == ["first", "second"]
    assert any("also appear in" in w for w in warnings)


def test_titles_that_match_nothing_are_reported(tmp_path):
    write_session(
        tmp_path,
        "s1",
        [
            rec(type="custom-title", customTitle="Work"),
            user("hi", "2026-03-04T15:00:00Z"),
            assistant([{"type": "text", "text": "a"}], "2026-03-04T15:00:01Z"),
        ],
    )
    warnings = []
    collect("/work/proj", tmp_path, titles=["Nothing"], warnings=warnings)
    assert any("no session titled" in w for w in warnings)


def test_missing_project_is_an_error_naming_where_it_looked(tmp_path):
    with pytest.raises(SystemExit) as e:
        collect("/work/absent", tmp_path)
    assert "absent" in str(e.value)


def test_yaml_round_trips_through_the_loader(tmp_path):
    import yaml

    turn = Turn(
        at="2026-03-04T15:00:00Z",
        prompt="  Indented first line.\nLine two with trailing space   ",
        response="A reply: it has a colon.",
        tools={"Bash": 2},
        out_tokens=10,
        end="2026-03-04T15:01:00Z",
    )
    thread = Thread(id="w", title='Work: "quoted"', sessions=["s1"], turns=[turn])
    thread.turn_ids = ["t0304-1500"]
    text = to_yaml([thread], {"collected": "now"})
    loaded = yaml.safe_load(text)
    got = loaded["threads"][0]["turns"][0]
    assert loaded["threads"][0]["title"] == 'Work: "quoted"'
    # The leading space survives; the trailing ones do not.
    assert got["prompt"] == "  Indented first line.\nLine two with trailing space"
    assert got["response"] == "A reply: it has a colon."
    assert got["work"] == {"seconds": 60, "tokens": 10}
