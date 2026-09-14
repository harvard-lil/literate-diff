# HTML data and rendering

The standalone page mounts its UI from the `script#ld-data` JSON block. There
is no parallel static document body or separate `LD_ROWS` / `LD_ANCHORS` payload.
The page contains inline CSS and JavaScript and makes no requests to render.
JavaScript is required for display; `noscript` explains how to extract the record.

The v2 record fields (`sidecar`, `sources`, `brief`, `layers`, `claims`) remain
ordinary JSON. Existing `jq` queries and `literate-diff extract` work without
running the page. Older HTML files without `presentation` remain extractable.
Rebuilding uses the sidecar and source records, not the presentation.

## Compiled presentation

Python still resolves Markdown, references, categories and source annotations.
It adds a `presentation` object with its own version number, currently `1`:

- `html`: an ordered list of literal fragments, text-copy objects, and integer
  indexes into `markup`.
- `markup`: a dictionary of repeated HTML tags, stored once.
- `anchors`: the anchor-to-row map used for navigation.
- `rows`: deferred diff rows and section bands, materialized when opened.
- `text_sources`: paths into the record, each with an `escape` flag.

A text-copy object is `{"$text": ["literal", [source, start, end], ...]}`. The
three integers select a slice of a `text_sources` entry. Offsets count Unicode
code points, with an exclusive end. When `escape` is true, offsets apply after
Python-compatible HTML escaping (`&`, `<`, `>`, double quote, single quote).
JavaScript must not apply UTF-16 offsets directly to these strings.

Copy objects can occur in presentation strings, including deferred rows and
section bands. They reference the embedded record rather than repeat matching
passages. Short strings and text transformed by Markdown can remain literal;
this is not a guarantee that every word occurs only once. The source records
are retained verbatim for extraction, including their original formatting.
With `--no-embed`, copies of record are absent and presentation text is literal.

`presentation.py` compiles and decodes this representation in Python.
`assets/presentation.js` decodes it in the browser and mounts `#ld-root` before
`app.js` installs navigation, folding and note placement. `window.LD.data()`
returns the original record; `window.LD.presentation` contains the decoded view.

Changes to this contract should preserve extraction/rebuild tests and compare
Python and JavaScript decoding, including non-BMP Unicode and HTML escaping.
Layout tests inspect decoded markup; browser checks cover mounting, initial
hash navigation, folded diffs, transcript expansion and quotes. Update the
presentation version when making an incompatible representation change.
