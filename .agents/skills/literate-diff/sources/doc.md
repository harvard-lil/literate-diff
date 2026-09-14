# Source: doc

Reference documents: a standard the work follows, a runbook it changed,
the design note it started from, a page from a vendor's documentation.
Each file is an item; rows are sentences, so a claim can quote the
paragraph it rests on.

```yaml
sources:
  standards:
    type: doc
    files:
      - ../lil-engineering/docs/standards/deploys.md
      - path: notes/design.md
        title: The design note this started from
```

Paths resolve from the directory the build runs in, like `diff:`. The file
is embedded as its copy of record, so a document that later changes still
reads as it did when it was cited. Cite with `ld:#doc-<filename>`; quote a
passage by giving the file an `anchors:` entry with an `at:` substring.

## Google Docs

Export the doc as markdown through the Google Drive connector and save it
beside the sidecar with front matter saying where it came from. No
credentials or API setup is involved beyond the connector.

1. Find the file id: it is the path segment after `/document/d/` in the
   doc's URL, or `search_files` with `title contains '…'` and
   `mimeType = 'application/vnd.google-apps.document'`.
2. `get_file_metadata` with `excludeContentSnippets: true` for `title`,
   `viewUrl` and `modifiedTime`.
3. `download_file_content` with `exportMimeType: text/markdown`. The
   content comes back base64-encoded. Decode it with `base64 -d`, never by
   reading it: if the harness saved the result to a file, decode from that
   file (`jq -r .content saved.json | base64 -d > design.md`); otherwise
   write the string to `design.md.b64` and decode that. Check the result is
   UTF-8 text whose first heading matches the doc, then delete the `.b64`.
4. Prepend front matter:

   ```markdown
   ---
   title: The design note
   origin: Google Docs
   url: https://docs.google.com/document/d/<id>/edit
   modified: 2026-08-14T17:36:37Z   # modifiedTime
   retrieved: 2026-09-14            # the day of the export
   ---
   ```

   Drop the `usp=` and `ouid=` query parameters from `viewUrl`; the second
   identifies the account that ran the export.

5. Read the file before it goes anywhere, as for a transcript. The export
   carries the doc's text only: comments are not in it. When a comment
   thread is evidence, `read_file_content` with `includeComments: true`
   returns the comments inline; quote the ones a claim rests on as `notes`
   items (who, when, `where: comment on <doc title>`, the doc URL). Google's
   markdown escapes punctuation (`\.`, `\[ \]`); the page renders those
   correctly, so leave them.

The export is a snapshot. When the doc changes after the episode, keep the
copy that was cited and say so in the brief rather than re-exporting.

## Which documents

Ones a top-layer claim rests on, and ones a reader in the roster will be
sent to next. A standard the work introduced or changed is usually also in
a diff source; include it here only if the reader needs to read it whole
rather than see what changed.
