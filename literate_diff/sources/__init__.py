"""Source plugins, by `type:`."""

from __future__ import annotations

from .base import LoadContext, SourcePlugin

_REGISTRY: dict[str, type[SourcePlugin]] = {}


def register(cls: type[SourcePlugin]) -> type[SourcePlugin]:
    _REGISTRY[cls.type] = cls
    return cls


def plugin_for(type_name: str) -> SourcePlugin:
    """A fresh plugin instance for a source type. Instances are per source,
    so a plugin may keep what it loaded (a transcript's threads)."""
    _load_builtins()
    cls = _REGISTRY.get(type_name)
    if cls is None:
        raise SystemExit(
            f"unknown source type {type_name!r}; known: {', '.join(sorted(_REGISTRY))}"
        )
    return cls()


def types() -> list[str]:
    _load_builtins()
    return sorted(_REGISTRY)


def _load_builtins() -> None:
    if _REGISTRY:
        return
    from . import diff, doc, notes, terms, transcript

    register(diff.DiffSource)
    register(transcript.TranscriptSource)
    register(notes.NotesSource)
    register(terms.TermsSource)
    register(doc.DocSource)


__all__ = ["LoadContext", "SourcePlugin", "plugin_for", "register", "types"]
