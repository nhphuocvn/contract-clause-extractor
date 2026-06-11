"""Deterministic sanity checks on an assembled `DealPackage`.

Runs after extraction and after cross-reference resolution. NEVER crashes —
every rule catches its own exceptions and emits a `ValidationIssue` instead.
Issues at severity "error" route a term to the review queue and block policy
PASS; "warning" lets the deal proceed but flags it; "info" is purely advisory.

Each rule is a small standalone function so it's trivial to test, extend, or
reorder. Rules live in `_RULES`; `validate_package` is the single entry point.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from deal_copilot.schemas import (
    CommercialTerm,
    DealPackage,
    TermType,
)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


Severity = Literal["error", "warning", "info"]


class ValidationIssue(BaseModel):
    """One issue raised by a validator rule. Routed to the review queue and
    aggregated into the CRB memo / policy verdict."""
    model_config = ConfigDict(extra="forbid")

    term_id: str | None = Field(
        default=None,
        description="The CommercialTerm.term_id this issue applies to, when applicable. "
                    "None for package-level issues (e.g., unresolved cross-references).",
    )
    severity: Severity
    rule_id: str = Field(description="Stable rule identifier, e.g. 'volume_ramp_sums_to_total'.")
    message: str
    suggested_action: str = Field(default="")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _terms_of(pkg: DealPackage, term_type: TermType) -> list[CommercialTerm]:
    return [t for t in pkg.terms if t.term_type == term_type]


def _param(term: CommercialTerm, key: str, default: Any = None) -> Any:
    """Defensive parameter accessor — never raises on missing keys."""
    if not isinstance(term.parameters, dict):
        return default
    return term.parameters.get(key, default)


_DATE_FIELDS = {"effective_date", "expiration_date", "signing_date", "issue_date"}


def _looks_like_date(value: Any) -> bool:
    """Heuristic: a string that contains a 4-digit year is plausibly a date."""
    if not isinstance(value, str):
        return False
    return bool(re.search(r"\b(19|20)\d{2}\b", value))


# ---------------------------------------------------------------------------
# Rules (each: pkg -> list[ValidationIssue], never raises)
# ---------------------------------------------------------------------------


def volume_ramp_sums_to_total(pkg: DealPackage) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for term in _terms_of(pkg, TermType.VOLUME_COMMITMENT):
        total = _param(term, "total_units")
        sched = _param(term, "quarterly_schedule_units", [])
        if not isinstance(sched, list) or not sched:
            continue
        try:
            ssum = sum(int(x) for x in sched)
        except (TypeError, ValueError):
            issues.append(ValidationIssue(
                term_id=term.term_id, severity="error",
                rule_id="volume_ramp_sums_to_total",
                message=f"quarterly_schedule_units contains non-numeric entries: {sched!r}",
                suggested_action="Re-extract the quarterly schedule; values must be integers.",
            ))
            continue
        if not isinstance(total, (int, float)):
            issues.append(ValidationIssue(
                term_id=term.term_id, severity="error",
                rule_id="volume_ramp_sums_to_total",
                message=f"total_units missing or non-numeric (got {total!r})",
                suggested_action="Re-extract total_units.",
            ))
            continue
        if ssum != int(total):
            issues.append(ValidationIssue(
                term_id=term.term_id, severity="error",
                rule_id="volume_ramp_sums_to_total",
                message=(
                    f"Quarterly schedule sums to {ssum} but total_units is {int(total)}. "
                    f"Difference: {ssum - int(total):+d}."
                ),
                suggested_action="Re-check the schedule for missing or duplicate quarters.",
            ))
    return issues


def rebate_tiers_monotonic(pkg: DealPackage) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for term in _terms_of(pkg, TermType.REBATE):
        tiers = _param(term, "tiers", [])
        if not isinstance(tiers, list) or len(tiers) < 2:
            continue  # 0 or 1 tier — nothing to check for monotonicity
        thresholds: list[float] = []
        pcts: list[float] = []
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            t = tier.get("threshold_cumulative_units")
            p = tier.get("pct_off_base_asp")
            if isinstance(t, (int, float)):
                thresholds.append(float(t))
            if isinstance(p, (int, float)):
                pcts.append(float(p))
        if thresholds and thresholds != sorted(thresholds):
            issues.append(ValidationIssue(
                term_id=term.term_id, severity="error",
                rule_id="rebate_tiers_monotonic",
                message=f"Rebate tier thresholds not strictly increasing: {thresholds}",
                suggested_action="Re-extract tiers; verify ordering in the contract clause.",
            ))
        if pcts and pcts != sorted(pcts):
            issues.append(ValidationIssue(
                term_id=term.term_id, severity="warning",
                rule_id="rebate_tiers_monotonic",
                message=f"Rebate percentages not strictly increasing across tiers: {pcts}",
                suggested_action="Confirm with the deal team — unusual but legal in some structures.",
            ))
    return issues


def take_or_pay_pct_in_range(pkg: DealPackage) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for term in _terms_of(pkg, TermType.TAKE_OR_PAY):
        pct = _param(term, "annual_minimum_pct_of_committed")
        if pct is None:
            issues.append(ValidationIssue(
                term_id=term.term_id, severity="warning",
                rule_id="take_or_pay_pct_in_range",
                message="TAKE_OR_PAY term missing annual_minimum_pct_of_committed.",
                suggested_action="Re-extract; the floor percentage is mandatory for downside modeling.",
            ))
            continue
        try:
            pct_f = float(pct)
        except (TypeError, ValueError):
            issues.append(ValidationIssue(
                term_id=term.term_id, severity="error",
                rule_id="take_or_pay_pct_in_range",
                message=f"annual_minimum_pct_of_committed is non-numeric: {pct!r}",
                suggested_action="Re-extract as a decimal in (0, 1].",
            ))
            continue
        if not (0.0 < pct_f <= 1.0):
            issues.append(ValidationIssue(
                term_id=term.term_id, severity="error",
                rule_id="take_or_pay_pct_in_range",
                message=f"annual_minimum_pct_of_committed = {pct_f} is outside (0, 1].",
                suggested_action="Check whether the value should be a decimal (e.g., 0.80) rather than a percent (80).",
            ))
    return issues


def payment_terms_recognized(pkg: DealPackage) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for term in _terms_of(pkg, TermType.PAYMENT_TERMS):
        net_days = _param(term, "net_days")
        if net_days is None:
            issues.append(ValidationIssue(
                term_id=term.term_id, severity="warning",
                rule_id="payment_terms_recognized",
                message="PAYMENT_TERMS missing net_days; DSO assumption cannot be derived.",
                suggested_action="Re-extract net_days, or set explicitly in assumptions.",
            ))
            continue
        try:
            nd = int(net_days)
        except (TypeError, ValueError):
            issues.append(ValidationIssue(
                term_id=term.term_id, severity="error",
                rule_id="payment_terms_recognized",
                message=f"net_days is non-numeric: {net_days!r}",
                suggested_action="Re-extract as an integer count of days.",
            ))
            continue
        if not (0 <= nd <= 365):
            issues.append(ValidationIssue(
                term_id=term.term_id, severity="warning",
                rule_id="payment_terms_recognized",
                message=f"net_days = {nd} is outside the expected [0, 365] range.",
                suggested_action="Confirm with the deal team.",
            ))
    return issues


def dates_parse(pkg: DealPackage) -> list[ValidationIssue]:
    """Best-effort check: any parameter key smelling like a date should look like one."""
    issues: list[ValidationIssue] = []
    for term in pkg.terms:
        if not isinstance(term.parameters, dict):
            continue
        for k, v in term.parameters.items():
            if k.lower() in _DATE_FIELDS and v not in (None, ""):
                if not _looks_like_date(v):
                    issues.append(ValidationIssue(
                        term_id=term.term_id, severity="warning",
                        rule_id="dates_parse",
                        message=f"Parameter '{k}' on {term.term_type.value} term does not look like a date: {v!r}",
                        suggested_action="Re-extract or correct the date.",
                    ))
    return issues


def rebate_pct_out_of_range(pkg: DealPackage) -> list[ValidationIssue]:
    """Defense Layer 3: bounds-check rebate percentages even on the dict-shape path."""
    issues: list[ValidationIssue] = []
    for term in _terms_of(pkg, TermType.REBATE):
        tiers = _param(term, "tiers", [])
        if not isinstance(tiers, list):
            continue
        for i, tier in enumerate(tiers):
            if not isinstance(tier, dict):
                continue
            p = tier.get("pct_off_base_asp")
            if isinstance(p, (int, float)) and not (0.0 <= p <= 0.5):
                issues.append(ValidationIssue(
                    term_id=term.term_id, severity="error",
                    rule_id="rebate_pct_out_of_range",
                    message=f"Tier {i} pct_off_base_asp = {p} is outside the plausible [0, 0.5] range.",
                    suggested_action="A >50% rebate is implausible — likely a misextraction (e.g., 50 vs 0.50).",
                ))
    return issues


def cross_references_resolved(pkg: DealPackage) -> list[ValidationIssue]:
    if not pkg.unresolved_cross_references:
        return []
    return [
        ValidationIssue(
            term_id=None, severity="warning",
            rule_id="unresolved_cross_reference",
            message=(
                f"This deal references a document that was not uploaded: {label}. "
                f"Economics are incomplete until the referenced document is provided."
            ),
            suggested_action="Upload the missing document and re-extract.",
        )
        for label in pkg.unresolved_cross_references
    ]


def liability_cap_present_for_supply_deal(pkg: DealPackage) -> list[ValidationIssue]:
    """Informational: a deal with WARRANT_EQUITY should usually carry a LIABILITY cap.
    Flag if not, so the deal team can confirm rather than discover the gap in CRB."""
    has_warrant_equity = any(t.term_type == TermType.WARRANT_EQUITY for t in pkg.terms)
    has_liability = any(t.term_type == TermType.LIABILITY for t in pkg.terms)
    if has_warrant_equity and not has_liability:
        return [ValidationIssue(
            term_id=None, severity="info",
            rule_id="liability_cap_missing_for_supply_deal",
            message="Deal includes a customer warrant but no LIABILITY cap term was extracted. "
                    "Typical supply deals of this size include a liability cap.",
            suggested_action="Confirm with Legal whether the contract has a liability cap that was missed.",
        )]
    return []


def warrant_tranche_consistency(pkg: DealPackage) -> list[ValidationIssue]:
    """WarrantTerms enforces tranche-sum at construction. If construction failed
    earlier (graceful degradation), `warrant_terms` will be None even when a
    WARRANT_EQUITY term is present. Surface that as an issue."""
    has_warrant_equity = any(t.term_type == TermType.WARRANT_EQUITY for t in pkg.terms)
    if has_warrant_equity and pkg.warrant_terms is None:
        return [ValidationIssue(
            term_id=None, severity="error",
            rule_id="warrant_terms_missing",
            message="Deal references a warrant (via WARRANT_EQUITY term) but warrant_terms "
                    "could not be parsed. Warrant economics cannot be computed.",
            suggested_action="Upload the warrant document and re-extract, or check the extraction log "
                             "for a tranche-sum validation failure.",
        )]
    return []


# Order matters only for output readability — rules are otherwise independent.
_RULES: list[Callable[[DealPackage], list[ValidationIssue]]] = [
    volume_ramp_sums_to_total,
    rebate_tiers_monotonic,
    rebate_pct_out_of_range,
    take_or_pay_pct_in_range,
    payment_terms_recognized,
    dates_parse,
    cross_references_resolved,
    warrant_tranche_consistency,
    liability_cap_present_for_supply_deal,
]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def validate_package(pkg: DealPackage) -> list[ValidationIssue]:
    """Run every validator rule against the package and collect issues.

    Never raises. A buggy rule cannot crash the extractor — we catch and log
    its failure as a separate `validator_internal_error` info issue.
    """
    all_issues: list[ValidationIssue] = []
    for rule in _RULES:
        try:
            all_issues.extend(rule(pkg))
        except Exception as exc:  # defensive: never let extraction crash on a validator bug
            all_issues.append(ValidationIssue(
                term_id=None, severity="info",
                rule_id="validator_internal_error",
                message=f"Validator {rule.__name__!r} raised {type(exc).__name__}: {exc}. "
                        f"Other rules ran normally.",
                suggested_action="Report this as a bug; the extraction itself is unaffected.",
            ))
    return all_issues


__all__ = [
    "Severity",
    "ValidationIssue",
    "validate_package",
    # Individual rules exported for unit testing
    "volume_ramp_sums_to_total",
    "rebate_tiers_monotonic",
    "rebate_pct_out_of_range",
    "take_or_pay_pct_in_range",
    "payment_terms_recognized",
    "dates_parse",
    "cross_references_resolved",
    "warrant_tranche_consistency",
    "liability_cap_present_for_supply_deal",
]
