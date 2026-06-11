"""Document intake: load files or pasted text into uniform `LoadedDoc`s,
infer each document's type via lightweight heuristics, and decide whether the
extractor should run RAG-style or read the document whole.

Three entry points:
- `load_documents(sources)`  : take Paths or file-like objects → list[LoadedDoc].
- `load_pasted_text(text)`   : wrap an inline string as a `LoadedDoc`.
- `dispatch(loaded)`         : returns "rag" or "whole_text".

The unit of analysis is the deal package: callers pass everything (purchase
agreement + warrant + side letters + pasted emails) and get back one list of
`LoadedDoc`s, ready for the term extractor.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from extract import read_contract_bytes


# ---------------------------------------------------------------------------
# Dispatch threshold
# ---------------------------------------------------------------------------


# Whole-text path for short inputs (term sheets, pasted emails); RAG path for
# larger contracts. Tuned against the Phase 1 docs:
#   purchase agreement = ~29k chars  → RAG
#   warrant            = ~15k chars  → RAG
#   a typical term sheet / pasted email ≈ 2-6k chars → whole_text
WHOLE_TEXT_CHAR_LIMIT = 8000


DocumentType = Literal[
    "purchase_agreement",
    "warrant",
    "amendment",
    "term_sheet",
    "paste",
    "unknown",
]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class LoadedDoc(BaseModel):
    """A single document loaded into memory and classified by type.

    Carries everything the extractor needs to make per-document decisions
    (RAG vs whole-text dispatch, term-type relevance filtering, source-doc
    tagging) without re-reading the file.
    """
    model_config = ConfigDict(extra="forbid")

    filename: str
    document_type: DocumentType
    text: str
    sha256: str = Field(description="Hex digest of the raw bytes (or text.encode for paste).")
    parent_filename_hint: str | None = Field(
        default=None,
        description="When document_type='amendment', best-effort name of the agreement being amended. "
                    "None if unidentifiable.",
    )


# Duck-typed file-like inputs (matches Streamlit UploadedFile: .name + .getvalue()).
class FileLike(Protocol):
    name: str
    def getvalue(self) -> bytes: ...


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------


# Filename signals — checked first; cheap and usually decisive.
_FILENAME_SIGNALS: list[tuple[re.Pattern[str], DocumentType]] = [
    (re.compile(r"(?i)amend(ment)?"), "amendment"),
    (re.compile(r"(?i)warrant"), "warrant"),
    (re.compile(r"(?i)(term[\s_-]?sheet|ts[._\-])"), "term_sheet"),
    (re.compile(r"(?i)(purchase|supply|master[\s_-]?(services|agreement)|msa)"), "purchase_agreement"),
]


# Content signals — fall back when filename is uninformative.
_CONTENT_SIGNALS: list[tuple[re.Pattern[str], DocumentType]] = [
    (re.compile(r"(?im)^\s*amendment\s+(no\.?|#)\s*\d+\b"), "amendment"),
    (re.compile(r"(?i)\bThis Amendment\b"), "amendment"),
    (re.compile(r"(?i)amends?\s+that\s+certain\b"), "amendment"),
    (re.compile(r"(?i)warrant\s+to\s+purchase\s+shares"), "warrant"),
    (re.compile(r"(?i)\bproduct\s+purchase\s+agreement\b"), "purchase_agreement"),
    (re.compile(r"(?i)\bpurchase\s+agreement\b"), "purchase_agreement"),
    (re.compile(r"(?i)\bsupply\s+agreement\b"), "purchase_agreement"),
    (re.compile(r"(?i)\bterm\s+sheet\b"), "term_sheet"),
]


# Amendment parent-document phrasing: "amends that certain X Agreement dated ..."
_AMENDMENT_PARENT_RE = re.compile(
    r"(?i)amends?\s+that\s+certain\s+([A-Z][A-Za-z\s\-/&]+?Agreement)\s+(?:dated|by\s+and\s+between)",
)


def infer_document_type(filename: str, text: str) -> DocumentType:
    """Classify a document via filename then content signals."""
    head = text[:1500]  # first ~1500 chars usually contain title + preamble

    for pattern, dtype in _FILENAME_SIGNALS:
        if pattern.search(filename):
            return dtype

    for pattern, dtype in _CONTENT_SIGNALS:
        if pattern.search(head):
            return dtype

    # Short documents with no signal are most plausibly term sheets or summaries.
    if len(text) < 4000:
        return "term_sheet"

    return "unknown"


def find_amendment_parent_hint(text: str) -> str | None:
    """Best-effort extraction of the parent agreement's name from amendment text."""
    m = _AMENDMENT_PARENT_RE.search(text)
    if m:
        return m.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_one(source: Path | FileLike) -> LoadedDoc:
    """Read one input into a LoadedDoc. Accepts a Path or any file-like with
    .name and .getvalue() (Streamlit's UploadedFile fits)."""
    if isinstance(source, Path):
        data = source.read_bytes()
        filename = source.name
        suffix = source.suffix
    else:
        # Duck-typed file-like.
        data = source.getvalue()
        filename = source.name
        suffix = Path(filename).suffix

    text = read_contract_bytes(data, suffix)
    dtype = infer_document_type(filename, text)
    parent_hint = find_amendment_parent_hint(text) if dtype == "amendment" else None

    return LoadedDoc(
        filename=filename,
        document_type=dtype,
        text=text,
        sha256=_sha256_bytes(data),
        parent_filename_hint=parent_hint,
    )


def load_documents(sources: list[Path | FileLike] | tuple[Path | FileLike, ...]) -> list[LoadedDoc]:
    """Load and classify a list of documents into a uniform LoadedDoc list."""
    return [_load_one(s) for s in sources]


def load_pasted_text(text: str, hint_label: str = "pasted") -> LoadedDoc:
    """Wrap an inline string (e.g., an email summary) as a LoadedDoc."""
    data = text.encode("utf-8")
    return LoadedDoc(
        filename=f"{hint_label}.txt",
        document_type="paste",
        text=text,
        sha256=_sha256_bytes(data),
    )


def dispatch(loaded: LoadedDoc) -> Literal["rag", "whole_text"]:
    """Decide whether a document should be retrieval-extracted or read whole.

    Whole-text path for short inputs (term sheets, pastes, brief side letters);
    RAG path for everything longer. The threshold lives in `WHOLE_TEXT_CHAR_LIMIT`.
    """
    if loaded.document_type in ("paste", "term_sheet"):
        return "whole_text"
    if len(loaded.text) <= WHOLE_TEXT_CHAR_LIMIT:
        return "whole_text"
    return "rag"


__all__ = [
    "DocumentType",
    "LoadedDoc",
    "FileLike",
    "WHOLE_TEXT_CHAR_LIMIT",
    "infer_document_type",
    "find_amendment_parent_hint",
    "load_documents",
    "load_pasted_text",
    "dispatch",
]
