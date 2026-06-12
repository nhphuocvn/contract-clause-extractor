"""Shared test fixtures: the synthetic AMD–Meta deal as an in-memory
`DealPackage`, built directly from the ground-truth parameters (no LLM call).

Mirrors `data/sample_contracts/ground_truth.json` so the engine tests assert
against the same numbers the extraction eval uses.
"""

from __future__ import annotations

from datetime import datetime

from deal_copilot.assumptions_library import build_default_assumptions, load_library
from deal_copilot.schemas import (
    CommercialTerm,
    DealAssumptions,
    DealPackage,
    DocumentRef,
    TermType,
    WarrantTerms,
    WarrantTranche,
)

QUARTERLY_SCHEDULE = [7000, 9000, 12000, 15000, 18000, 20000, 18000, 16000, 13000, 11000, 7000, 4000]
YEAR_TOTALS = [43000, 72000, 35000]
TOTAL_UNITS = 150000
BASE_ASP = 25000.0
AS_OF = datetime(2026, 6, 11)


def _term(term_type: TermType, section: str, params: dict, *, ambiguity=False, note="") -> CommercialTerm:
    return CommercialTerm(
        term_id=f"{term_type.value.lower()}-{section}",
        term_type=term_type,
        raw_text=f"(synthetic excerpt for {term_type.value} §{section})",
        source_document="gpu_purchase_agreement",
        source_section=section,
        parameters=params,
        ambiguity_flag=ambiguity,
        ambiguity_note=note,
    )


def synthetic_package() -> DealPackage:
    """The synthetic GPU purchase agreement as a populated DealPackage."""
    terms = [
        _term(TermType.PRICING, "4", {"base_asp_usd": 25000, "currency": "USD", "firm_for_initial_term": True}),
        _term(TermType.VOLUME_COMMITMENT, "3", {
            "total_units": TOTAL_UNITS,
            "term_years": 3,
            "quarterly_schedule_units": QUARTERLY_SCHEDULE,
            "year_totals_units": YEAR_TOTALS,
        }),
        _term(TermType.REBATE, "5", {
            "tiers": [
                {"threshold_cumulative_units": 30000, "pct_off_base_asp": 0.03},
                {"threshold_cumulative_units": 75000, "pct_off_base_asp": 0.05},
                {"threshold_cumulative_units": 120000, "pct_off_base_asp": 0.07},
            ],
            "measurement_basis": "cumulative_since_effective_date",
            "settlement_cadence": "annual_in_arrears",
            "settlement_window_days": 45,
        }, ambiguity=True, note="Tier-crossing retroactivity within a Year is unspecified."),
        _term(TermType.TAKE_OR_PAY, "6", {
            "annual_minimum_pct_of_committed": 0.80,
            "shortfall_basis": "pct_of_committed",
            "measurement_period": "annual",
            "shortfall_payment_per_unit_usd": 25000,
            "shortfall_payment_due_days": 60,
            "banked_units_eligible_for_carryforward": True,
            "banked_units_forfeit_at_term_end": True,
        }),
        _term(TermType.PREPAYMENT, "7", {
            "amount_usd": 500000000,
            "paid_at": "effective_date",
            "refundable": False,
            "drawdown_method": "applied_against_invoices",
            "default_drawdown_pct_of_invoice": 0.20,
        }),
        _term(TermType.PAYMENT_TERMS, "8", {"net_days": 90, "currency": "USD"}),
        _term(TermType.PRICE_PROTECTION_MFN, "9", {"trigger": "lower_price_to_comparable_volume_customer", "application": "prospective_only"}),
        _term(TermType.LIABILITY, "12", {"cap_basis": "amounts_paid_or_payable_trailing_12_months", "cap_months_of_fees": 12, "ip_indemnification_uncapped": True}),
        _term(TermType.WARRANT_EQUITY, "13", {"instrument": "warrant_to_purchase_common_stock", "referenced_document_filename": "warrant_agreement"}),
    ]
    return DealPackage(
        deal_name="AMD-Meta MI355X (synthetic)",
        deal_id="DEAL-SYNTH-001",
        counterparty="Meta Platforms, Inc.",
        documents=[DocumentRef(filename="gpu_purchase_agreement.pdf", document_type="purchase_agreement")],
        terms=terms,
    )


def default_assumptions() -> DealAssumptions:
    """DealAssumptions populated from the library (unit_cogs $15k, WACC 10%)."""
    assumptions, _ = build_default_assumptions(load_library(), AS_OF)
    return assumptions


def synthetic_warrant_terms() -> WarrantTerms:
    """The ground-truth warrant: 12,000,000 shares @ $0.01, four 3,000,000-share
    tranches at deployment milestones 30k/75k/120k/150k with VWAP hurdles."""
    return WarrantTerms(
        total_shares=12_000_000,
        exercise_price_usd=0.01,
        expiration_years=6,
        tranches=[
            WarrantTranche(share_count=3_000_000, deployment_milestone_units=30_000, stock_price_hurdle_usd=180.0),
            WarrantTranche(share_count=3_000_000, deployment_milestone_units=75_000, stock_price_hurdle_usd=230.0),
            WarrantTranche(share_count=3_000_000, deployment_milestone_units=120_000, stock_price_hurdle_usd=300.0),
            WarrantTranche(share_count=3_000_000, deployment_milestone_units=150_000, stock_price_hurdle_usd=400.0),
        ],
    )


def synthetic_package_with_warrant() -> DealPackage:
    """The synthetic package plus the warrant terms attached, with the four
    base-case vest probabilities set (so validate_assumptions_against_warrant
    passes). Kept separate from `synthetic_package()` so Phase 3's warrant-free
    hand-calcs stay stable."""
    pkg = synthetic_package()
    pkg.warrant_terms = synthetic_warrant_terms()
    return pkg


def warrant_assumptions() -> DealAssumptions:
    """Default assumptions with AMD spot $470 and the base vest-probability set
    [0.9, 0.7, 0.5, 0.3] (length matches the 4 tranches)."""
    a = default_assumptions()
    return a.model_copy(update={
        "current_stock_price_usd": 470.0,
        "tranche_vest_probabilities": [0.9, 0.7, 0.5, 0.3],
    })
