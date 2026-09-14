# Source: notes

Primary sources a layer introduces itself: a thing someone said outside
the record, an account action that left no diff, a pattern the author
knows from elsewhere, a page on the web. Each is an item with `text:` and,
as far as they are known, `by:`, `on:`, `where:` and `url:`. Items are
the units; rows are sentences.

A citation to a note is labelled with evidence of kind
*attestation* (someone's word) or *reference* (something a reader can
follow a link to). The page shows the kind beside the claim, so a reader
can distinguish code evidence from a reported observation. This label does
not establish that the observation is accurate or independently verified.

## What belongs

Relevant observations from the brief that are absent from the collected record: secrets deleted in a
console, a setting changed by hand, a decision taken in a meeting, a
message in Slack that changed the scope. Anything a top-layer claim rests
on that is not in a diff, a transcript or a document. Anything the author
would otherwise write as "as we discussed" or "which is the common
pattern".

Not: things the transcript already says (cite the turn), things a document
says (add the document as a `doc` source and cite it), or the author's
opinions about the work (those are the story, and take no citation).

## Write

```yaml
sources:
  said:
    type: notes
    items:
      - id: keys-deleted
        by: Jack
        on: 2026-09-03
        where: GitHub and the AWS console
        text: |
          32 repository secrets deleted from h2o and 13 IAM access keys
          deactivated, after the workflows moved to OIDC.
      - id: cdn-drain
        by: Cloudflare
        text: A 524 is returned when the origin has not answered in 100 seconds.
        url: https://developers.cloudflare.com/…/error-524/
```

Preserve who actually supplied the observation. An account change reported
by an agent in the transcript should cite that turn; do not convert it into
a note attributed to the operator. If an existing document retains a summary
note, label it as a summary of that report and link the original turn. Being
outside git is different from being outside the collected record.

Give each item an `id:` a claim can cite (`[](ld:#keys-deleted)`), one
statement per item, in the words of whoever said it where there are words.
Put the date on anything that could change. Put the URL on anything a
reader could check.

Notes need no layer of their own: sources no layer places go in an
automatic closing layer, so every citation has somewhere to land. Give
them a titled layer when there are enough to read as a list.
