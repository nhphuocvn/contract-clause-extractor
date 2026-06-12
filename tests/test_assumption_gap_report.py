"""Assumption Gap Report (§9.6): ranked clarifying questions with dollar
sensitivities, addressed to owners.

Pinned on the synthetic deal: the rebate tier-crossing ambiguity is worth
$41.0M (prospective vs retroactive), and a ±10% COGS move swings gross margin
$225.0M — so COGS (cost accounting) and the rebate ambiguity (Legal) are the
top two lines. With the warrant attached, the warrant valuation judgment range
($2.256B → $4.230B = $1.974B wide) becomes the largest gap (deal team)."""

from __future__ import annotations

import pytest

from deal_copilot import economics_engine as ee
from deal_copilot.assumption_gap_report import build_gap_report
from deal_copilot.schemas import AssumptionType
from deal_copilot.assumption_register import build_register
from deal_copilot.warrant_economics import compute_warrant_economics
from tests.fixtures import (
    default_assumptions,
    synthetic_package,
    synthetic_package_with_warrant,
    warrant_assumptions,
)


def _report_no_warrant():
    pkg = synthetic_package()
    a = default_assumptions()
    econ = ee.compute_economics(pkg, a)
    return build_gap_report(pkg, a, econ)


def test_rebate_ambiguity_line_is_41m_to_legal():
    lines = _report_no_warrant()
    rebate = next(l for l in lines if l.owner == "Legal")
    assert rebate.dollar_sensitivity_usd == pytest.approx(41_000_000.0, abs=1.0)
    assert "Legal" in rebate.question


def test_cogs_line_is_225m_to_cost_accounting():
    lines = _report_no_warrant()
    cogs = next(l for l in lines if l.field_path == "assumptions.unit_cogs_usd")
    assert cogs.owner == "cost accounting"
    assert cogs.dollar_sensitivity_usd == pytest.approx(225_000_000.0, abs=1.0)


def test_top_two_are_cogs_then_rebate():
    lines = _report_no_warrant()
    assert lines[0].field_path == "assumptions.unit_cogs_usd"      # $225.0M
    assert lines[1].owner == "Legal"                               # $41.0M
    assert lines[0].dollar_sensitivity_usd > lines[1].dollar_sensitivity_usd


def test_every_market_or_judgment_input_becomes_a_line_to_its_owner():
    pkg = synthetic_package()
    a = default_assumptions()
    register = build_register(a, terms=pkg.terms)
    gap_paths = {l.field_path for l in build_gap_report(pkg, a, ee.compute_economics(pkg, a), register=register)}
    for entry in register:
        if entry.assumption_type in (AssumptionType.MARKET_DATA, AssumptionType.STRATEGIC_JUDGMENT):
            assert entry.field_path in gap_paths, entry.field_path


def test_policy_numbers_are_not_gap_lines():
    """WACC / tax / DPO are policy numbers (set by Treasury), not unknowns."""
    lines = _report_no_warrant()
    paths = {l.field_path for l in lines}
    assert "assumptions.discount_rate_wacc" not in paths
    assert "assumptions.tax_rate" not in paths
    assert "assumptions.supplier_payment_dpo_days" not in paths


def test_warrant_valuation_is_largest_gap_when_present():
    pkg = synthetic_package_with_warrant()
    a = warrant_assumptions()
    econ = ee.compute_economics(pkg, a)
    we = compute_warrant_economics(pkg, a)
    lines = build_gap_report(pkg, a, econ, warrant_econ=we)
    top = lines[0]
    assert top.field_path == "assumptions.warrant_measurement_price_usd"
    assert top.owner == "deal team"
    assert top.dollar_sensitivity_usd == pytest.approx(1_973_958_000.0, abs=1e3)
