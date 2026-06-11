"""Derive the review queue from a `DealPackage` plus validation issues.

The queue is purely derived — never persisted. Clearing a queued item means
editing the underlying term (lower the ambiguity flag, raise the confidence,
fix the parameter, or upload a missing document). This Phase 2 implementation
stays simple; Phase 6+ may add "I've reviewed this" markers if the UX needs
them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from deal_copilot.schemas import DealPackage, TermType
from deal_copilot.validators import ValidationIssue


ReviewReason = Literal[
    "low_confidence",
    "validation_error",
    "validation_warning",
    "ambiguity_flagged",
    "missing_document",
]


class ReviewItem(BaseModel):
    """One entry on the human-review checklist."""
    model_config = ConfigDict(extra="forbid")

    term_id: str | None = Field(
        default=None,
        description="The CommercialTerm.term_id this item references; None for "
                    "package-level items (e.g., missing cross-referenced document).",
    )
    term_type: TermType | None = Field(
        default=None,
        description="The term's type, when applicable, for UI grouping.",
    )
    reason: ReviewReason
    detail: str = Field(description="Human-readable explanation of why review is needed.")
    rule_id: str | None = Field(
        default=None,
        description="The rule_id of the originating ValidationIssue, when applicable.",
    )


def build_review_queue(
    pkg: DealPackage,
    issues: list[ValidationIssue],
    confidence_threshold: float = 0.8,
) -> list[ReviewItem]:
    """Compose the review queue from low-confidence terms, ambiguous terms, and
    validation issues.

    Order in the returned list (preserved):
      1. Validation errors  (most actionable; block policy PASS).
      2. Missing-document warnings (unique reason — package-level).
      3. Other validation warnings.
      4. Ambiguity-flagged terms.
      5. Low-confidence terms.
    Items at the same level appear in the order they were encountered.
    """
    items: list[ReviewItem] = []

    # Index terms by id for O(1) lookup when annotating issue-derived items.
    by_id = {t.term_id: t for t in pkg.terms}

    # (1) errors, (3) warnings, (2) missing-document (separate bucket).
    errors: list[ReviewItem] = []
    missing_doc: list[ReviewItem] = []
    warnings: list[ReviewItem] = []
    for issue in issues:
        if issue.severity == "info":
            continue  # info-level issues don't gate review; surfaced elsewhere
        term = by_id.get(issue.term_id) if issue.term_id else None
        bucket = (
            ReviewItem(
                term_id=issue.term_id,
                term_type=term.term_type if term else None,
                reason="validation_error" if issue.severity == "error" else (
                    "missing_document" if issue.rule_id == "unresolved_cross_reference"
                    else "validation_warning"
                ),
                detail=issue.message + (
                    f" Suggested: {issue.suggested_action}" if issue.suggested_action else ""
                ),
                rule_id=issue.rule_id,
            )
        )
        if bucket.reason == "validation_error":
            errors.append(bucket)
        elif bucket.reason == "missing_document":
            missing_doc.append(bucket)
        else:
            warnings.append(bucket)

    # (4) ambiguity flags
    ambiguities = [
        ReviewItem(
            term_id=t.term_id,
            term_type=t.term_type,
            reason="ambiguity_flagged",
            detail=(t.ambiguity_note or "Ambiguous term — review required.")
                   + (f" ({len(t.variants)} alternative reading(s) modeled.)" if t.variants else ""),
        )
        for t in pkg.terms
        if t.ambiguity_flag
    ]

    # (5) low confidence
    low_conf = [
        ReviewItem(
            term_id=t.term_id,
            term_type=t.term_type,
            reason="low_confidence",
            detail=f"Extraction confidence {t.confidence:.2f} below threshold "
                   f"{confidence_threshold:.2f}. Verify against the source clause.",
        )
        for t in pkg.terms
        if t.confidence < confidence_threshold
    ]

    items.extend(errors)
    items.extend(missing_doc)
    items.extend(warnings)
    items.extend(ambiguities)
    items.extend(low_conf)
    return items


__all__ = ["ReviewReason", "ReviewItem", "build_review_queue"]
