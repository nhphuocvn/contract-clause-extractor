"""sha256-keyed JSON cache for extraction outputs.

Cache key = `(doc_sha256, prompt_version)`. Bumping `EXTRACTION_PROMPT_VERSION`
in `prompts.py` invalidates every prior cache entry at the same filename — the
file name embeds the version, so old entries simply stop being matched.

Cached entries are JSON; consumers know how to round-trip their own Pydantic
models via `model_dump_json` / `model_validate_json`. This module just owns
the storage layer.
"""

from __future__ import annotations

import json
from pathlib import Path


def _cache_path(cache_dir: Path, doc_sha256: str, prompt_version: str) -> Path:
    return cache_dir / f"{doc_sha256}__{prompt_version}.json"


def read_cache(
    cache_dir: Path,
    doc_sha256: str,
    prompt_version: str,
) -> dict | None:
    """Return the cached dict if hit, else None. Never raises on missing dir."""
    if not cache_dir.exists():
        return None
    path = _cache_path(cache_dir, doc_sha256, prompt_version)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Corrupt cache entry — silently miss rather than fail extraction.
        return None


def write_cache(
    cache_dir: Path,
    doc_sha256: str,
    prompt_version: str,
    payload: dict,
) -> None:
    """Persist a JSON-serializable dict. Best-effort: errors are swallowed
    (cache failures must never break extraction)."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = _cache_path(cache_dir, doc_sha256, prompt_version)
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    except OSError:
        pass


__all__ = ["read_cache", "write_cache"]
