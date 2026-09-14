"""Serialization and browser-decoder contract for data-driven pages."""
import html
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from literate_diff.extract import BLOCK_RE, read_data, rebuild
from literate_diff.presentation import decode_presentation, encode_presentation
from literate_diff.render import json_for_html, render_document
from literate_diff.sidecar import build, parse_sidecar


def test_source_slices_and_markup_dictionary_round_trip_in_javascript():
    text = '🙂 café </script> & "quotes" ' + 'source content with Unicode and escaping; ' * 20
    data = {'sidecar': text, 'sources': {}}
    markup = '<p>' + html.escape(text) + '</p>'
    original = {'html': markup * 4, 'rows': {'f0': {'rows': [['a', 0, 1, text, '']]}},
                'anchors': {'example': {'body': 'f0', 'start': 0, 'end': 0}}}
    data['presentation'] = encode_presentation(data, original)
    decoded = decode_presentation(data)
    assert decoded['html'] == original['html']
    assert decoded['rows'] == original['rows']
    assert '$text' in json.dumps(data['presentation'])
    assert len(json.dumps(data['presentation'])) < len(json.dumps(original))
    # No literal HTML closing tag can end the JSON script early.
    assert '</script>' not in json_for_html(data)
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is needed to exercise the browser decoder')
    script = Path('literate_diff/assets/presentation.js').read_text()
    harness = '''const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const root = {};
const context = {window: {}, document: {getElementById: id =>
  id === 'ld-data' ? {textContent: JSON.stringify(input.data)} : root}};
vm.runInNewContext(input.script, context);
process.stdout.write(JSON.stringify({html: root.innerHTML, view: context.window.LD.presentation}));'''
    result = subprocess.run([node, '-e', harness], input=json.dumps({'data': data, 'script': script}),
                            text=True, capture_output=True, check=True)
    browser = json.loads(result.stdout)
    assert browser['html'] == original['html']
    assert browser['view']['rows'] == original['rows']
    assert browser['view']['anchors'] == original['anchors']


@pytest.mark.parametrize('embed', [True, False])
def test_page_renders_from_one_data_block_and_preserves_extraction(tmp_path, embed):
    text = 'Unique source sentence for checking the standalone extraction contract. ' * 5
    spec = parse_sidecar('''title: Example
sources:
  report:
    type: notes
    items:
      - id: observation
        text: ''' + text + '\nlayers:\n  - id: evidence\n    kind: stream\n    sources: [report]\n')
    doc = build(spec, base_dir=tmp_path, cwd=tmp_path, embed=embed)
    page = render_document(doc, embed=embed)
    path = tmp_path / 'page.html'
    path.write_text(page)
    data = read_data(str(path))
    assert len(BLOCK_RE.findall(page)) == 1
    shell = BLOCK_RE.sub('', page)
    assert '<main class="ld-main">' not in shell
    assert 'window.LD_ROWS =' not in shell and 'window.LD_ANCHORS =' not in shell
    assert text not in shell
    assert 'requires JavaScript' in shell
    assert decode_presentation(data)['html'].count(text.split('. ')[0]) == 5
    if embed:
        assert data['sidecar'] == doc.sidecar_text
        assert rebuild(data).title == doc.title
    else:
        assert data['sidecar'] == ''
        assert all(not source['files'] for source in data['sources'].values())
        assert data['presentation']['text_sources'] == []


def test_legacy_record_still_extracts(tmp_path):
    data = {'format': 'literate-diff', 'version': 2, 'sidecar': 'title: Original\n', 'sources': {}}
    path = tmp_path / 'old.html'
    path.write_text('<script type="application/json" id="ld-data">' + json_for_html(data) + '</script>')
    assert read_data(str(path)) == data
