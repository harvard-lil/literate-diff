# Source: terms

Definitions. Each item is a `term:`, an optional `aliases:` list, and a
one-paragraph `text:`. The first use of a term (or alias) in each prose
layer is linked to its definition, with the definition on hover, so a
layer stays readable where it sits.

## Which terms

Take the reader roster's `knows` lines and list every word in the top
layers that is not covered by any of them. The test is a reader in another
role at the same organisation: "digest", "OIDC", "task definition",
"referrer" need entries; "Django" and "pull request" usually do not.
Shorthand that grew up during the work ("the window", "the switch",
"promotion") needs an entry or, better, a rewrite.

## Write

```yaml
sources:
  glossary:
    type: terms
    items:
      - term: digest
        aliases: [digests]
        text: |
          The hash of an image's manifest. It names exactly one set of
          bytes, where a tag is a movable name.
```

One paragraph, for the reader the document is for, saying what the thing
is and why it matters here. Matching is on word boundaries outside code,
links and headings; list plurals and verb forms as aliases.

A terms source does not replace defining a term in the sentence where an
entry depends on it. Prefer the clause ("the switch: the load balancer in
front of the site could be told to serve a static page instead of the
application") where a beat turns on the word; use the terms source for the
words that recur.
