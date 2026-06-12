"""Policy engine / CRB routing (§9.5), pinned on the synthetic deal.

Signals: blended cash margin 37.63% (< 45% floor), committed value $3.75B
(> $1B → CFO tier), MFN present, warrant-equity present, payment terms net-90
(> net-60), take-or-pay 80% (>= 70% floor → PASS), uncapped IP indemnification.
Overall outcome ESCALATE; approvers CFO + General Counsel + Treasury.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from deal_copilot import economics_engine as ee
from deal_copilot import policy_engine as pe
from deal_copilot.schemas import PolicyOutcome
from tests.fixtures import default_assumptions, synthetic_package

AS_OF = datetime(2026, 6, 11)


def _verdict():
    pkg = synthetic_package()
    econ = ee.compute_economics(pkg, default_assumptions())
    rules = pe.load_policy()
    return pe.evaluate_package(pkg, econ, rules, version_name="Initial", evaluated_at=AS_OF), pkg, econ


def _by_rule(verdict):
    return {r.rule_id: r for r in verdict.rule_results}


def test_signals_pinned():
    pkg = synthetic_package()
    econ = ee.compute_economics(pkg, default_assumptions())
    s = pe.policy_signals(pkg, econ)
    assert s.blended_gross_margin_pct == pytest.approx(0.376299, abs=1e-5)
    assert s.committed_value_usd == pytest.approx(3_750_000_000.0, abs=1.0)
    assert s.has_mfn and s.has_warrant and s.liability_uncapped
    assert s.payment_net_days == 90
    assert s.take_or_pay_pct == 0.80


def test_margin_floor_escalates_to_cfo():
    v, *_ = _verdict()
    r = _by_rule(v)["margin_floor_45"]
    assert r.outcome == PolicyOutcome.ESCALATE
    assert "37.6% below 45% floor" in r.reason
    assert r.required_approvers == ["CFO"]


def test_deal_size_routes_to_cfo_tier():
    v, *_ = _verdict()
    r = _by_rule(v)["deal_size_tiers"]
    assert r.required_approvers == ["CFO"]            # $3.75B > $1B
    assert "3.75B" in r.reason


def test_mfn_and_warrant_and_liability_escalate():
    v, *_ = _verdict()
    by = _by_rule(v)
    assert by["mfn_present"].outcome == PolicyOutcome.ESCALATE
    assert by["mfn_present"].required_approvers == ["General Counsel"]
    assert by["warrant_present"].required_approvers == ["CFO", "General Counsel"]
    assert by["uncapped_liability"].required_approvers == ["General Counsel"]


def test_payment_terms_beyond_net60_escalates():
    v, *_ = _verdict()
    r = _by_rule(v)["payment_terms_net60"]
    assert r.outcome == PolicyOutcome.ESCALATE
    assert "net-90 beyond net-60" in r.reason
    assert r.required_approvers == ["Treasury"]


def test_take_or_pay_floor_passes_at_80pct():
    v, *_ = _verdict()
    r = _by_rule(v)["take_or_pay_floor_70"]
    assert r.outcome == PolicyOutcome.PASS
    assert r.required_approvers == []


def test_overall_outcome_and_approver_union():
    v, *_ = _verdict()
    assert v.overall_outcome == PolicyOutcome.ESCALATE
    # Order-preserving de-duped union across escalating rules
    # (margin CFO, deal-size CFO, uncapped GC, mfn GC, warrant CFO+GC, payment Treasury).
    assert v.all_required_approvers == ["CFO", "General Counsel", "Treasury"]


def test_passing_deal_has_no_approvers():
    """A clean deal: high margin, small, no MFN/warrant, short terms, strong T-o-P."""
    pkg = synthetic_package()
    # Strip the escalating terms.
    pkg.terms = [t for t in pkg.terms if t.term_type.value not in
                 ("PRICE_PROTECTION_MFN", "WARRANT_EQUITY", "LIABILITY")]
    for t in pkg.terms:
        if t.term_type.value == "PAYMENT_TERMS":
            t.parameters["net_days"] = 30
    econ = ee.compute_economics(pkg, default_assumptions().model_copy(update={"unit_cogs_usd": 8000.0}))
    s = pe.policy_signals(pkg, econ)
    assert s.blended_gross_margin_pct > 0.45            # high margin clears the floor
    v = pe.evaluate_package(pkg, econ, pe.load_policy(), version_name="clean", evaluated_at=AS_OF)
    by = _by_rule(v)
    assert by["margin_floor_45"].outcome == PolicyOutcome.PASS
    assert by["mfn_present"].outcome == PolicyOutcome.PASS
    assert by["payment_terms_net60"].outcome == PolicyOutcome.PASS
