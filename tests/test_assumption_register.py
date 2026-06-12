"""Assumption Register (§5): every model input typed and owner-tagged. The
KICKOFF-mandated accountabilities must hold — COGS → cost accounting, WACC →
Treasury, vest probabilities → deal team — plus the new working-capital inputs."""

from __future__ import annotations

from deal_copilot.assumption_register import build_register
from deal_copilot.schemas import AssumptionType, ProvenanceClass
from tests.fixtures import (
    default_assumptions,
    synthetic_package,
    synthetic_package_with_warrant,
    warrant_assumptions,
)


def _by_path(rows):
    return {r.field_path: r for r in rows}


def test_scalar_inputs_typed_and_owned():
    rows = _by_path(build_register(default_assumptions()))
    cogs = rows["assumptions.unit_cogs_usd"]
    assert cogs.assumption_type == AssumptionType.MARKET_DATA
    assert cogs.owner == "cost accounting"

    wacc = rows["assumptions.discount_rate_wacc"]
    assert wacc.assumption_type == AssumptionType.POLICY_NUMBER
    assert wacc.owner == "Treasury"

    dpo = rows["assumptions.supplier_payment_dpo_days"]
    assert dpo.assumption_type == AssumptionType.POLICY_NUMBER
    assert dpo.owner == "Treasury / Procurement"

    inv = rows["assumptions.inventory_lead_months"]
    assert inv.assumption_type == AssumptionType.STRATEGIC_JUDGMENT
    assert inv.owner == "Operations / Supply Chain"


def test_register_covers_all_scalar_inputs():
    rows = _by_path(build_register(default_assumptions()))
    for name in (
        "unit_cogs_usd", "opex_allocation_pct", "discount_rate_wacc", "tax_rate",
        "supplier_payment_dpo_days", "inventory_lead_months",
        "current_stock_price_usd", "assumed_volatility", "shares_outstanding",
    ):
        assert f"assumptions.{name}" in rows


def test_contract_facts_included():
    rows = _by_path(build_register(default_assumptions(), terms=synthetic_package().terms))
    asp = rows["terms[PRICING].base_asp_usd"]
    assert asp.assumption_type == AssumptionType.CONTRACT_FACT
    assert asp.basis == ProvenanceClass.CONTRACT
    assert asp.owner.startswith("contract §")


def test_warrant_judgment_inputs_owned_by_deal_team():
    pkg = synthetic_package_with_warrant()
    rows = build_register(warrant_assumptions(), terms=pkg.terms, warrant_terms=pkg.warrant_terms)
    vest = [r for r in rows if r.field_path.startswith("assumptions.tranche_vest_probabilities")]
    assert len(vest) == 4
    for r in vest:
        assert r.assumption_type == AssumptionType.STRATEGIC_JUDGMENT
        assert r.owner == "deal team"
        assert r.basis == ProvenanceClass.PLACEHOLDER
    price = next(r for r in rows if r.field_path == "assumptions.warrant_measurement_price_usd")
    assert price.assumption_type == AssumptionType.STRATEGIC_JUDGMENT
    assert price.owner == "deal team"
