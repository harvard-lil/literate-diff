"""Inspect the generated DOM separately from its serialized HTML container.

Browser integration tests exercise the JavaScript decoder. These helpers let
existing annotation/layout assertions inspect the equivalent decoded markup.
"""
import json
from literate_diff.extract import BLOCK_RE
from literate_diff.presentation import decode_presentation
from literate_diff.render import render_document as build_page


def presentation(page):
    return decode_presentation(json.loads(BLOCK_RE.search(page).group(1)))


def materialize(page):
    return page.replace('<div id="ld-root"></div>', presentation(page)['html'])


def render_document(*args, **kwargs):
    return materialize(build_page(*args, **kwargs))
