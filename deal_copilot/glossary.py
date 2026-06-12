"""Glossary loader (§9.7).

Reads `data/glossary.json` — every finance term and abbreviation used anywhere
in the UI or outputs mapped to a one-sentence plain-English explanation. The UI
shows hover/expander definitions; the README includes the full table. This is a
thin I/O loader (cached per path); lookups are pure.

No unexplained jargon anywhere in the product is the design bar; the glossary is
the single source of those definitions.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DEFAULT_GLOSSARY_PATH = Path("data/glossary.json")


def load_glossary(path: str | Path = DEFAULT_GLOSSARY_PATH) -> dict[str, str]:
    """Return the term → definition map. Cached per resolved path. Returns an
    empty dict if the file is absent (graceful degradation — the UI simply shows
    no definitions rather than crashing)."""
    resolved = str(Path(path).resolve())
    try:
        return _load_cached(resolved)
    except FileNotFoundError:
        return {}


@lru_cache(maxsize=8)
def _load_cached(resolved_path: str) -> dict[str, str]:
    with open(resolved_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return dict(data.get("terms", {}))


def lookup(term: str, path: str | Path = DEFAULT_GLOSSARY_PATH) -> str | None:
    """Definition for a term (exact match, then case-insensitive); None if absent."""
    terms = load_glossary(path)
    if term in terms:
        return terms[term]
    lower = {k.lower(): v for k, v in terms.items()}
    return lower.get(term.lower())


__all__ = ["DEFAULT_GLOSSARY_PATH", "load_glossary", "lookup"]
