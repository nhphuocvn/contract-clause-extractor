"""Phase 2 extraction orchestrator.

`extract_deal` is the public entry point: takes loaded documents → returns an
`ExtractionResult` with a fully-assembled `DealPackage`, validation issues,
review queue, and an extraction log.

Per-document cache: sha256 + prompt_version. A cache hit skips every LLM call
for that document. Cache invalidation is by `EXTRACTION_PROMPT_VERSION` bump
in `prompts.py`.

Dispatch is per-document — small inputs (term sheets, pasted text) go to the
whole-text path; longer inputs go to RAG. Warrant documents get a single
WarrantTerms call (strict schema) plus a CROSS_REFERENCE pass for any
back-references to the purchase agreement.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from deal_copilot.extraction_cache import read_cache, write_cache
from deal_copilot.extraction_payloads import (
    ExtractedDictTerm,
    ExtractedRebate,
    ExtractedTakeOrPay,
    ExtractedVolumeCommitment,
)
from deal_copilot.intake import LoadedDoc, dispatch
from deal_copilot.prompts import (
    EXTRACTION_PROMPT_VERSION,
    SYSTEM_PROMPT,
    TERM_EXTRACTION_PROMPTS,
    TERM_QUERIES,
    WARRANT_EXTRACTION_PROMPT,
    build_user_message,
)
from deal_copilot.retrieval import DealCorpus
from deal_copilot.review_queue import ReviewItem, build_review_queue
from deal_copilot.schemas import (
    CommercialTerm,
    DealPackage,
    DocumentRef,
    TermType,
    TermVariant,
    WarrantTerms,
)
from deal_copilot.validators import ValidationIssue, validate_package


# Default model — single source of truth so a swap is one line.
DEFAULT_MODEL = "gpt-4o-mini"

# Top-K chunks retrieved per RAG query.
RAG_TOP_K = 5


# ---------------------------------------------------------------------------
# Public output
# ---------------------------------------------------------------------------


class ExtractionResult(BaseModel):
    """Output of `extract_deal` — package + validation + review + log."""
    model_config = ConfigDict(extra="forbid")

    package: DealPackage
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    review_queue: list[ReviewItem] = Field(default_factory=list)
    extraction_log: list[str] = Field(
        default_factory=list,
        description="Per-LLM-call traces — model, prompt version, tokens, retries, cache hit/miss.",
    )


# ---------------------------------------------------------------------------
# Per-document-type → list of TermTypes to attempt
# ---------------------------------------------------------------------------


# Commercial term types extracted from a non-warrant document.
_COMMERCIAL_TERMS_FOR_NON_WARRANT: tuple[TermType, ...] = (
    TermType.PRICING,
    TermType.VOLUME_COMMITMENT,
    TermType.REBATE,
    TermType.TAKE_OR_PAY,
    TermType.PREPAYMENT,
    TermType.PAYMENT_TERMS,
    TermType.PRICE_PROTECTION_MFN,
    TermType.TERMINATION,
    TermType.LIABILITY,
    TermType.SUPPLY_COMMITMENT,
    TermType.WARRANT_EQUITY,
    TermType.CROSS_REFERENCE,
)

# From a warrant document, we extract only cross-references back. The
# warrant's own terms are extracted separately into a WarrantTerms object.
_COMMERCIAL_TERMS_FOR_WARRANT: tuple[TermType, ...] = (
    TermType.CROSS_REFERENCE,
)


_STRICT_WRAPPER: dict[TermType, type[BaseModel]] = {
    TermType.REBATE: ExtractedRebate,
    TermType.VOLUME_COMMITMENT: ExtractedVolumeCommitment,
    TermType.TAKE_OR_PAY: ExtractedTakeOrPay,
}


# ---------------------------------------------------------------------------
# Per-document extraction
# ---------------------------------------------------------------------------


def _term_id(source_document: str, term_type: TermType, source_section: str) -> str:
    """Stable hash-derived id. Same (doc, type, section) → same id across runs."""
    raw = f"{source_document}::{term_type.value}::{source_section}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


def _build_context(doc: LoadedDoc, corpus: DealCorpus | None, query: str) -> str:
    """Return the contract text to wrap and feed into the LLM call.

    RAG path: top-K chunks for the query, joined with separators. Whole-text
    path: the entire document text.
    """
    if corpus is None:
        return doc.text
    chunks = corpus.search(query, top_k=RAG_TOP_K)
    if not chunks:
        return doc.text  # fallback if retrieval failed
    return "\n\n---\n\n".join(
        f"[§{c.section_number} {c.section_title}]\n{c.text}" for c in chunks
    )


def _strip_money_to_float(value: Any) -> Any:
    """Best-effort: convert "$25,000" or "25_000" or "25,000.00" → 25000.0."""
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        cleaned = re.sub(r"[\$,_\s]", "", value)
        try:
            return float(cleaned) if "." in cleaned else int(cleaned)
        except ValueError:
            return value
    return value


def _extract_one_term(
    client: OpenAI,
    doc: LoadedDoc,
    term_type: TermType,
    corpus: DealCorpus | None,
    log: list[str],
) -> CommercialTerm | None:
    """Run one LLM extraction call for one (document, term_type) pair.

    Returns None if `not_found` is set on the response, otherwise a fully
    populated `CommercialTerm`.
    """
    query = TERM_QUERIES[term_type]
    extraction_guide = TERM_EXTRACTION_PROMPTS[term_type]
    context = _build_context(doc, corpus, query)

    user_msg, nonce = build_user_message(
        term_query_label=f"{term_type.value} term ({extraction_guide.splitlines()[0]})",
        retrieved_or_full_text=context,
    )

    if term_type in _STRICT_WRAPPER:
        format_hint = (
            "Populate `payload` with the strict schema fields per the guidance. "
            "Set `parameters_json` to '{}' is not applicable here — leave it at "
            "its default."
        )
    else:
        format_hint = (
            "Populate `parameters_json` with a JSON-ENCODED STRING containing "
            "a dict of the keys named in PARAMETER GUIDANCE. Example: "
            '`"parameters_json": "{\\"net_days\\": 90, \\"currency\\": \\"USD\\"}"`. '
            "Do NOT output a literal JSON object — output a STRING that contains JSON."
        )

    variants_hint = (
        "If the clause is materially ambiguous AND you can articulate alternative "
        "readings, populate `variants_json` with a JSON-encoded STRING that decodes "
        "to a list of objects each shaped "
        "{\"label\": \"short reading name\", \"parameters\": \"<JSON-encoded params for this reading>\", \"note\": \"why this reading\"}. "
        "Default `variants_json` is '[]'. Only populate when alternative readings "
        "would materially change the financial model."
    )

    full_user = (
        f"{user_msg}\n\n"
        f"PARAMETER GUIDANCE:\n{extraction_guide}\n\n"
        f"FORMAT GUIDANCE:\n{format_hint}\n\n"
        f"VARIANTS GUIDANCE:\n{variants_hint}\n\n"
        f"If this term type is not present in the data block, set "
        f"`not_found=true` and leave other fields at their defaults."
    )

    wrapper_cls = _STRICT_WRAPPER.get(term_type, ExtractedDictTerm)

    response = None
    retries = 0
    try:
        completion = client.chat.completions.parse(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": full_user},
            ],
            response_format=wrapper_cls,
            temperature=0,
        )
        response = completion.choices[0].message.parsed
        tokens = completion.usage.total_tokens if completion.usage else 0
    except (ValidationError, ValueError) as exc:
        # One retry with the error appended.
        retries = 1
        retry_user = (
            f"{full_user}\n\n"
            f"Your previous response failed schema validation: {exc}. "
            f"Try again, conforming exactly to the schema. Pay close attention "
            f"to field types."
        )
        try:
            completion = client.chat.completions.parse(
                model=DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": retry_user},
                ],
                response_format=wrapper_cls,
                temperature=0,
            )
            response = completion.choices[0].message.parsed
            tokens = completion.usage.total_tokens if completion.usage else 0
        except (ValidationError, ValueError) as exc2:
            log.append(
                f"  [FAIL] {doc.filename} {term_type.value}: schema validation failed twice "
                f"({type(exc2).__name__}: {exc2})"
            )
            return None

    log.append(
        f"  [ok ] {doc.filename} {term_type.value}: nonce={nonce[:8]} tokens={tokens} "
        f"retries={retries} not_found={getattr(response, 'not_found', False)}"
    )

    if response is None or getattr(response, "not_found", False):
        return None

    # Convert wrapper response → CommercialTerm.
    source_section = (response.source_section or "").strip() or "unknown"
    term_id = _term_id(doc.filename, term_type, source_section)

    if term_type in _STRICT_WRAPPER:
        payload = response.payload  # type: ignore[attr-defined]
        if payload is None:
            log.append(f"  [WARN] {doc.filename} {term_type.value}: strict wrapper missing payload — skipping")
            return None
        parameters: dict[str, Any] = payload.model_dump()
    else:
        # Dict-shape path. Decode the JSON-encoded parameters and normalize
        # money-shaped strings.
        try:
            raw_params = json.loads(response.parameters_json or "{}")  # type: ignore[attr-defined]
            if not isinstance(raw_params, dict):
                raw_params = {}
        except json.JSONDecodeError:
            log.append(f"  [WARN] {doc.filename} {term_type.value}: parameters_json not valid JSON; defaulting to empty")
            raw_params = {}
        parameters = {k: _strip_money_to_float(v) for k, v in raw_params.items()}

    variants = _decode_variants(response.variants_json, log, doc.filename, term_type)

    try:
        return CommercialTerm(
            term_id=term_id,
            term_type=term_type,
            raw_text=response.raw_text,
            source_document=doc.filename,
            source_section=source_section,
            parameters=parameters,
            confidence=response.confidence,
            ambiguity_flag=response.ambiguity_flag,
            ambiguity_note=response.ambiguity_note,
            variants=variants,
        )
    except ValidationError as exc:
        # Most common: ambiguity_flag=True with empty ambiguity_note, or variants
        # populated without ambiguity_flag=True. Soft-fix by aligning flags.
        log.append(f"  [WARN] {doc.filename} {term_type.value}: CommercialTerm validation: {exc}")
        note = response.ambiguity_note or "Extractor flagged ambiguity without specifics."
        try:
            return CommercialTerm(
                term_id=term_id,
                term_type=term_type,
                raw_text=response.raw_text,
                source_document=doc.filename,
                source_section=source_section,
                parameters=parameters,
                confidence=response.confidence,
                ambiguity_flag=bool(variants) or response.ambiguity_flag,
                ambiguity_note=note if (bool(variants) or response.ambiguity_flag) else "",
                variants=variants,
            )
        except ValidationError:
            return None


def _decode_variants(
    variants_json: str,
    log: list[str],
    filename: str,
    term_type: TermType,
) -> list[TermVariant]:
    """Decode the JSON-encoded variants list. Each variant has 'label', 'note',
    and 'parameters' (also a JSON-encoded string, since OpenAI strict mode
    rejects arbitrary dicts)."""
    if not variants_json or variants_json.strip() == "[]":
        return []
    try:
        raw = json.loads(variants_json)
    except json.JSONDecodeError:
        log.append(f"  [WARN] {filename} {term_type.value}: variants_json not valid JSON; dropping")
        return []
    if not isinstance(raw, list):
        return []
    out: list[TermVariant] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label", "")).strip()
        if not label:
            continue
        params_raw = entry.get("parameters", {})
        if isinstance(params_raw, str):
            try:
                params = json.loads(params_raw)
                if not isinstance(params, dict):
                    params = {}
            except json.JSONDecodeError:
                params = {}
        elif isinstance(params_raw, dict):
            params = params_raw
        else:
            params = {}
        out.append(TermVariant(
            label=label,
            parameters={k: _strip_money_to_float(v) for k, v in params.items()},
            note=str(entry.get("note", "")),
        ))
    return out


# ---------------------------------------------------------------------------
# Warrant extraction
# ---------------------------------------------------------------------------


def _extract_warrant(
    client: OpenAI,
    doc: LoadedDoc,
    log: list[str],
) -> WarrantTerms | None:
    """Run a single WarrantTerms extraction call against a warrant document."""
    user_msg, nonce = build_user_message(
        term_query_label="warrant terms (shares, exercise price, tranches, expiration)",
        retrieved_or_full_text=doc.text,
    )
    full_user = f"{user_msg}\n\nDETAILED GUIDANCE:\n{WARRANT_EXTRACTION_PROMPT}"

    try:
        completion = client.chat.completions.parse(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": full_user},
            ],
            response_format=WarrantTerms,
            temperature=0,
        )
        warrant = completion.choices[0].message.parsed
        tokens = completion.usage.total_tokens if completion.usage else 0
        log.append(f"  [ok ] {doc.filename} WARRANT: nonce={nonce[:8]} tokens={tokens}")
        return warrant
    except (ValidationError, ValueError) as exc:
        log.append(f"  [FAIL] {doc.filename} WARRANT: {type(exc).__name__}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Cross-reference resolution
# ---------------------------------------------------------------------------


def _stem(filename: str) -> str:
    return Path(filename).stem.lower()


def _first_meaningful_line(text: str, max_chars: int = 500) -> str:
    """Return the first non-empty line of the document's title block."""
    for line in text[:max_chars].splitlines():
        if line.strip():
            return line.strip().lower()
    return ""


def resolve_cross_references(pkg: DealPackage, loaded_docs: list[LoadedDoc]) -> None:
    """Match each CROSS_REFERENCE term's referenced document label against the
    documents in the package; unmatched labels populate
    `unresolved_cross_references`. Case-insensitive substring matching.
    """
    known_labels: set[str] = set()
    text_by_filename = {d.filename: d.text for d in loaded_docs}
    for doc_ref in pkg.documents:
        known_labels.add(_stem(doc_ref.filename))
        known_labels.add(doc_ref.document_type.replace("_", " ").lower())
        text = text_by_filename.get(doc_ref.filename, "")
        if text:
            known_labels.add(_first_meaningful_line(text))

    unresolved: list[str] = []
    seen: set[str] = set()

    for term in pkg.terms:
        if term.term_type != TermType.CROSS_REFERENCE:
            continue
        label = str(term.parameters.get("referenced_document_label", "")).strip()
        if not label:
            continue
        label_norm = label.lower()
        matched = any(label_norm in k or (k and k in label_norm) for k in known_labels if k)
        if not matched and label not in seen:
            seen.add(label)
            unresolved.append(label)

    pkg.unresolved_cross_references = unresolved


# ---------------------------------------------------------------------------
# Per-document extraction (cached)
# ---------------------------------------------------------------------------


def _extract_one_document(
    client: OpenAI,
    doc: LoadedDoc,
    cache_dir: Path | None,
    log: list[str],
) -> tuple[list[CommercialTerm], WarrantTerms | None]:
    """Extract every relevant term + (if warrant) the WarrantTerms for one doc.

    Cached by (doc.sha256, EXTRACTION_PROMPT_VERSION).
    """
    if cache_dir is not None:
        cached = read_cache(cache_dir, doc.sha256, EXTRACTION_PROMPT_VERSION)
        if cached is not None:
            log.append(
                f"  [cache hit] {doc.filename} sha={doc.sha256[:8]} prompt={EXTRACTION_PROMPT_VERSION}"
            )
            terms = [CommercialTerm.model_validate(t) for t in cached.get("terms", [])]
            warrant_dict = cached.get("warrant_terms")
            warrant = WarrantTerms.model_validate(warrant_dict) if warrant_dict else None
            return terms, warrant

    log.append(f"  [extract ] {doc.filename} ({doc.document_type}, {len(doc.text)} chars)")

    dispatch_mode = dispatch(doc)
    corpus: DealCorpus | None = None
    if dispatch_mode == "rag":
        corpus = DealCorpus(client, [doc])
        log.append(f"  [corpus  ] {doc.filename}: {corpus.chunk_count} chunks indexed")

    # Pick the TermType set to extract based on document type.
    if doc.document_type == "warrant":
        term_types = _COMMERCIAL_TERMS_FOR_WARRANT
    else:
        term_types = _COMMERCIAL_TERMS_FOR_NON_WARRANT

    terms: list[CommercialTerm] = []
    for tt in term_types:
        term = _extract_one_term(client, doc, tt, corpus, log)
        if term is not None:
            terms.append(term)

    # Warrant-specific extraction.
    warrant: WarrantTerms | None = None
    if doc.document_type == "warrant":
        warrant = _extract_warrant(client, doc, log)

    if cache_dir is not None:
        payload = {
            "doc_sha256": doc.sha256,
            "prompt_version": EXTRACTION_PROMPT_VERSION,
            "model": DEFAULT_MODEL,
            "filename": doc.filename,
            "document_type": doc.document_type,
            "terms": [t.model_dump() for t in terms],
            "warrant_terms": warrant.model_dump() if warrant else None,
        }
        write_cache(cache_dir, doc.sha256, EXTRACTION_PROMPT_VERSION, payload)

    return terms, warrant


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract_deal(
    client: OpenAI,
    loaded_docs: list[LoadedDoc],
    *,
    deal_name: str,
    deal_id: str = "",
    counterparty: str = "",
    cache_dir: Path | None = Path("cache/extraction"),
) -> ExtractionResult:
    """End-to-end extraction for a deal package.

    Args:
        client: an authenticated OpenAI client.
        loaded_docs: documents already loaded via `intake.load_documents` /
            `intake.load_pasted_text`.
        deal_name, deal_id, counterparty: passed through to the DealPackage.
        cache_dir: per-document JSON cache directory. None disables caching.
    """
    log: list[str] = [
        f"extract_deal: deal_name={deal_name!r} deal_id={deal_id!r} "
        f"prompt_version={EXTRACTION_PROMPT_VERSION} model={DEFAULT_MODEL} "
        f"docs={len(loaded_docs)}"
    ]

    all_terms: list[CommercialTerm] = []
    warrant_terms: WarrantTerms | None = None

    for doc in loaded_docs:
        terms, warrant = _extract_one_document(client, doc, cache_dir, log)
        all_terms.extend(terms)
        if warrant is not None and warrant_terms is None:
            warrant_terms = warrant
        elif warrant is not None:
            log.append(f"  [warn] multiple warrant docs detected; using the first")

    document_refs = [
        DocumentRef(
            filename=d.filename,
            document_type=d.document_type if d.document_type != "unknown" else "other",
            sha256=d.sha256,
        )
        for d in loaded_docs
    ]

    package = DealPackage(
        deal_name=deal_name,
        deal_id=deal_id,
        counterparty=counterparty,
        documents=document_refs,
        terms=all_terms,
        warrant_terms=warrant_terms,
    )

    resolve_cross_references(package, loaded_docs)

    issues = validate_package(package)
    queue = build_review_queue(package, issues)

    log.append(
        f"extract_deal done: {len(all_terms)} terms, "
        f"warrant={'yes' if warrant_terms else 'no'}, "
        f"unresolved={len(package.unresolved_cross_references)}, "
        f"issues={len(issues)}, queue={len(queue)}"
    )

    return ExtractionResult(
        package=package,
        validation_issues=issues,
        review_queue=queue,
        extraction_log=log,
    )


__all__ = [
    "DEFAULT_MODEL",
    "RAG_TOP_K",
    "ExtractionResult",
    "extract_deal",
    "resolve_cross_references",
]
