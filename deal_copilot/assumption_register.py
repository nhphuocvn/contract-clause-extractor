"""Assumption Register (§5) — the single list of every model input, classified
by type (contract_fact / market_data / policy_number / strategic_judgment) and
carrying the OWNER who confirms it.

Pure: builds `RegisterEntry` rows from a `DealAssumptions` + its provenance map,
plus the deal's contract terms and any warrant judgment inputs. The register is
the accountability view (its own Excel tab) and the source the Assumption Gap
Report (§9.6) draws from: every row typed market_data or strategic_judgment, or
carrying a placeholder provenance, becomes a gap line addressed to its owner.

Type/owner come from the assumption's provenance when present (the library
tags them); a default map fills any input whose provenance is untagged so the
register is never silently blank on accountability.
"""

from __future__ import annotations

from typing import Any

from deal_copilot import driver_mapper as dm
from deal_copilot.schemas import (
    AssumptionProvenance,
    AssumptionType,
    DealAssumptions,
    ProvenanceClass,
    RegisterEntry,
    TermType,
    WarrantTerms,
)

# Fallback (type, owner) for scalar assumption fields whose provenance is untagged.
_DEFAULT_OWNER_TYPE: dict[str, tuple[AssumptionType, str]] = {
    "unit_cogs_usd": (AssumptionType.MARKET_DATA, "cost accounting"),
    "opex_allocation_pct": (AssumptionType.STRATEGIC_JUDGMENT, "FP&A"),
    "discount_rate_wacc": (AssumptionType.POLICY_NUMBER, "Treasury"),
    "tax_rate": (AssumptionType.POLICY_NUMBER, "Tax / Treasury"),
    "supplier_payment_dpo_days": (AssumptionType.POLICY_NUMBER, "Treasury / Procurement"),
    "inventory_lead_months": (AssumptionType.STRATEGIC_JUDGMENT, "Operations / Supply Chain"),
    "current_stock_price_usd": (AssumptionType.MARKET_DATA, "Capital Markets (refresh before use)"),
    "assumed_volatility": (AssumptionType.MARKET_DATA, "Capital Markets"),
    "shares_outstanding": (AssumptionType.MARKET_DATA, "Capital Markets (latest 10-Q)"),
}

# Scalar assumption fields registered, in display order.
_SCALAR_FIELDS = list(_DEFAULT_OWNER_TYPE.keys())

_LABELS = {
    "unit_cogs_usd": "Unit COGS",
    "opex_allocation_pct": "Opex allocation %",
    "discount_rate_wacc": "WACC (discount rate)",
    "tax_rate": "Tax rate",
    "supplier_payment_dpo_days": "Supplier payment terms (DPO)",
    "inventory_lead_months": "Inventory lead (months)",
    "current_stock_price_usd": "Stock price (warrant measurement)",
    "assumed_volatility": "Assumed volatility",
    "shares_outstanding": "Shares outstanding",
}


def _type_and_owner(name: str, prov: AssumptionProvenance | None) -> tuple[AssumptionType, str]:
    default_type, default_owner = _DEFAULT_OWNER_TYPE.get(
        name, (AssumptionType.STRATEGIC_JUDGMENT, "deal team")
    )
    atype = prov.assumption_type if (prov and prov.assumption_type) else default_type
    owner = prov.owner if (prov and prov.owner) else default_owner
    return atype, owner


def _contract_fact_rows(terms) -> list[RegisterEntry]:
    """A few headline contract facts so the register shows the contract side too."""
    rows: list[RegisterEntry] = []

    def add(term_type: TermType, key: str, label: str) -> None:
        t = next((x for x in terms if x.term_type == term_type), None)
        if t is None:
            return
        rows.append(RegisterEntry(
            field_path=f"terms[{term_type.value}].{key}",
            label=label,
            value=t.parameters.get(key),
            assumption_type=AssumptionType.CONTRACT_FACT,
            basis=ProvenanceClass.CONTRACT,
            owner=f"contract §{t.source_section}",
            note=f"Extracted from {t.source_document} §{t.source_section}.",
        ))

    add(TermType.PRICING, "base_asp_usd", "Base ASP")
    add(TermType.PAYMENT_TERMS, "net_days", "Payment terms (net days)")
    add(TermType.TAKE_OR_PAY, "annual_minimum_pct_of_committed", "Take-or-pay floor %")
    add(TermType.PREPAYMENT, "amount_usd", "Prepayment amount")
    return rows


def _warrant_judgment_rows(assumptions: DealAssumptions, warrant: WarrantTerms | None) -> list[RegisterEntry]:
    if warrant is None:
        return []
    rows: list[RegisterEntry] = []
    price = assumptions.warrant_measurement_price_usd
    rows.append(RegisterEntry(
        field_path="assumptions.warrant_measurement_price_usd",
        label="Warrant measurement stock price",
        value=price if price is not None else assumptions.current_stock_price_usd,
        assumption_type=AssumptionType.STRATEGIC_JUDGMENT,
        basis=ProvenanceClass.PLACEHOLDER,
        owner="deal team",
        note="Strategic estimate — confirm with deal team.",
    ))
    for i, p in enumerate(assumptions.tranche_vest_probabilities):
        rows.append(RegisterEntry(
            field_path=f"assumptions.tranche_vest_probabilities[{i}]",
            label=f"Tranche {i + 1} vest probability",
            value=p,
            assumption_type=AssumptionType.STRATEGIC_JUDGMENT,
            basis=ProvenanceClass.PLACEHOLDER,
            owner="deal team",
            note="Strategic estimate — confirm with deal team.",
        ))
    return rows


def build_register(
    assumptions: DealAssumptions,
    provenance: dict[str, AssumptionProvenance] | None = None,
    *,
    terms: list | None = None,
    warrant_terms: WarrantTerms | None = None,
) -> list[RegisterEntry]:
    """Build the Assumption Register for one deal version. Pure."""
    provenance = provenance or assumptions.assumption_provenance or {}
    rows: list[RegisterEntry] = []

    for name in _SCALAR_FIELDS:
        value: Any = getattr(assumptions, name, None)
        prov = provenance.get(name)
        atype, owner = _type_and_owner(name, prov)
        rows.append(RegisterEntry(
            field_path=f"assumptions.{name}",
            label=_LABELS.get(name, name),
            value=value,
            assumption_type=atype,
            basis=prov.basis if prov else ProvenanceClass.LIBRARY_DEFAULT,
            owner=owner,
            note=prov.note if prov else "",
        ))

    rows.extend(_warrant_judgment_rows(assumptions, warrant_terms))
    if terms:
        rows.extend(_contract_fact_rows(terms))
    return rows


__all__ = ["build_register"]
