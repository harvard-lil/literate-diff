"""The feature-tour example builds without warnings and uses every feature,
in both the v2 shape (layers) and the v1 shape (plot, chapters, appendix)."""

import re
from pathlib import Path

from literate_diff.cli import main
from rendered import materialize, presentation

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "feature-tour"


def test_feature_tour_builds_cleanly(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(EXAMPLE.parent.parent)
    out = tmp_path / "feature-tour.html"
    assert main(["-a", str(EXAMPLE / "notes.yaml"), "-o", str(out)]) == 0
    stderr = capsys.readouterr().err
    assert "warning:" not in stderr, stderr

    html = materialize(out.read_text())
    body = html[html.index('<main class="ld-main">'):].split('<script type="application/json"', 1)[0]
    # Two sources, chapters, categories, flags, quotes, and no broken refs.
    assert 'data-ld-src="app"' in body and 'data-ld-src="infra"' in body
    assert body.count('<section class="ld-chapter"') >= 3
    assert len(re.findall(r'<ol class="ld-cat-list"', body)) >= 3
    assert len(re.findall(r'<a class="ld-cat-flag"', body)) >= 6
    assert 'class="ld-quote-btn"' in body
    assert 'ld-ref-broken' not in body
    # Renames, binary files and the missing-newline marker render.
    assert "ld-badge-ren" in body
    assert "Binary file not shown" in str(presentation(html)["rows"])
    # The conversation appendix: turns, a folded message, a work band, and a
    # quote of a prompt from inside the narrative.
    assert body.count('<article class="ld-turn"') == 4
    assert "ld-quote-said" in body
    assert "ld-elided" in body
    assert "tool calls" in body
    # Two sessions interleaved by time, cut into subject chapters, with
    # markdown rendered inside the messages.
    assert body.index('id="t1p-r0"') < body.index('id="t2p-r0"')
    assert body.count("ld-turn-thread") == 3
    assert body.count('class="ld-chapter ld-achapter"') == 2
    assert '<table class="ld-ptableblock"' in body
    # The work narrative: quotes shown in place, and bare citations.
    assert "Work narrative" in body
    assert "ld-quote-open" in body and "ld-cite" in body
    # Summary blocks before synthesis before evidence.
    assert body.index('id="summary"') < body.index('id="builders"') < body.index('id="overview"')
    assert body.index('id="vocabulary"') < body.index('id="code"')
    # v2: layers with audiences, the map, claims with evidence, notes, terms,
    # a reference document, and the embedded inputs.
    assert body.count('<section class="ld-layer') == 11
    assert html.count('data-ld-layer="') == 2 * 11
    assert 'data-ld-group="Summary"' in body
    assert '<ul class="ld-claims">' in body and "ld-unsupported" not in body
    assert 'data-ld-evidence="attestation,diff"' in body
    assert body.count('<a class="ld-term"') >= 6
    assert body.count('class="ld-note-item"') == 2 and body.count('class="ld-term-item"') == 3
    assert '<section class="ld-doc"' in body
    assert '<script type="application/json" id="ld-data">' in html
    assert html.startswith("<!doctype html>\n<!--\nDebrief: Promote, do not rebuild")


def test_the_v1_shape_of_the_example_still_builds_cleanly(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(EXAMPLE.parent.parent)
    out = tmp_path / "feature-tour-v1.html"
    assert main(["-a", str(EXAMPLE / "notes-v1.yaml"), "-o", str(out)]) == 0
    stderr = capsys.readouterr().err
    assert "warning:" not in stderr, stderr
    html = materialize(out.read_text())
    body = html[html.index('<main class="ld-main">'):].split('<script type="application/json"', 1)[0]
    assert '<div class="ld-plot" id="plot">' in body
    assert body.count('<article class="ld-turn"') == 4
    assert body.count('<section class="ld-chapter"') >= 3
    assert 'data-ld-layer="' not in html
