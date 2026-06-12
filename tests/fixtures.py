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
