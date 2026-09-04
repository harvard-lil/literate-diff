"""The feature-tour example builds without warnings and uses every feature."""

import re
from pathlib import Path

from literate_diff.cli import main

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "feature-tour"


def test_feature_tour_builds_cleanly(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(EXAMPLE.parent.parent)
    out = tmp_path / "feature-tour.html"
    assert main(["-a", str(EXAMPLE / "notes.yaml"), "-o", str(out)]) == 0
    stderr = capsys.readouterr().err
    assert "warning:" not in stderr, stderr

    html = out.read_text()
    body = html[html.index('<main class="ld-main">'):]
    # Two sources, chapters, categories, flags, quotes, and no broken refs.
    assert 'data-ld-src="app"' in body and 'data-ld-src="infra"' in body
    assert body.count('<section class="ld-chapter"') >= 3
    assert len(re.findall(r'<ol class="ld-cat-list"', body)) >= 3
    assert len(re.findall(r'<a class="ld-cat-flag"', body)) >= 6
    assert 'class="ld-quote-btn"' in body
    assert 'ld-ref-broken' not in body
    # Renames, binary files and the missing-newline marker render.
    assert "ld-badge-ren" in body
    assert "Binary file not shown" in body
