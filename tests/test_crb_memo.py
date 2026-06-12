"""CRB memo (§9.2): the structured payload is a pure assembly of engine / policy
/ benchmark / gap-report numbers — the prose layer injects, never computes.

Pinned on the synthetic deal: BASE cash net revenue $3,607.5M, gross margin
$1,357.5M (37.6%); rebate ambiguity $41.0M and working-capital draw −$157.0M
surface as ranked risks; the policy verdict (ESCALATE) is embedded; and the
warrant section carries the §4 correlation caveat."""

from __future__ import annotations

from datetime import datetime

import pytest

from deal_copilot import benchmarks as bm
from deal_copilot import economics_engine as ee
from deal_copilot import policy_engine as pe
from deal_copilot.assumption_gap_report import build_gap_report
from deal_copilot.crb_memo import CORRELATION_CAVEAT, build_crb_memo, render_crb_memo_markdown
from deal_copilot.schemas import PolicyOutcome, ScenarioName, ViewMode
from deal_copilot.warrant_economics import compute_warrant_economics
from tests.fixtures import (
    default_assumptions,
    synthetic_package,
    synthetic_package_with_warrant,
    warrant_assumptions,
)

AS_OF = datetime(2026, 6, 11)


def _memo_no_warrant():
    pkg = synthetic_package()
    a = default_assumptions()
    econ = ee.compute_economics(pkg, a)
    verdict = pe.evaluate_package(pkg, econ, pe.load_policy(), version_name="Initial", evaluated_at=AS_OF)
    comps = bm.compare_to_benchmarks(bm.deal_benchmark_metrics(pkg, econ), bm.load_benchmarks(), AS_OF)
    gaps = build_gap_report(pkg, a, econ)
    return build_crb_memo(pkg, econ, policy_verdict=verdict, benchmark_comparisons=comps, gap_lines=gaps), pkg, econ


def _row(memo, scenario, view):
    return next(r for r in memo.economics_table if r["scenario"] == scenario.value and r["view"] == view.value)


def test_economics_table_injects_engine_numbers():
    memo, *_ = _memo_no_warrant()
    base = _row(memo, ScenarioName.BASE, ViewMode.CASH_COMMERCIAL)
    assert base["net_revenue"] == "$3,607.5M"
    assert base["gross_margin"] == "$1,357.5M"
    assert base["gross_margin_pct"] == "37.6%"
    assert base["payback_quarters"] == 6           # working-capital-aware payback
    assert base["peak_wc_draw"] == "$-157.0M"


def test_policy_verdict_embedded():
    memo, *_ = _memo_no_warrant()
    assert memo.policy_verdict is not None
    assert memo.policy_verdict.overall_outcome == PolicyOutcome.ESCALATE
    assert memo.policy_verdict.all_required_approvers == ["CFO", "General Counsel", "Treasury"]


def test_top_risks_ranked_with_exposures():
    memo, *_ = _memo_no_warrant()
    by_owner_exposure = {round((r.quantified_exposure_usd or 0) / 1e6, 1) for r in memo.top_risks}
    assert 41.0 in by_owner_exposure          # rebate ambiguity
    assert 157.0 in by_owner_exposure         # working-capital draw
    # All quantified risks rank ahead of unquantified ones.
    exposures = [r.quantified_exposure_usd for r in memo.top_risks]
    quantified = [e for e in exposures if e is not None]
    assert quantified == sorted(quantified, reverse=True)


def test_warrant_section_carries_correlation_caveat():
    memo, *_ = _memo_no_warrant()
    assert "UNDERSTATES" in memo.warrant_section
    assert memo.warrant_section.endswith(CORRELATION_CAVEAT[-40:])


def test_gap_lines_present_with_rebate():
    memo, *_ = _memo_no_warrant()
    assert any(g.owner == "Legal" and g.dollar_sensitivity_usd == pytest.approx(41_000_000.0, abs=1.0)
               for g in memo.gap_report_lines)


def test_recommendation_and_conditions():
    memo, *_ = _memo_no_warrant()
    assert "ESCALATE" in memo.recommendation
    assert any("CFO" in c for c in memo.approval_conditions)
    assert any("General Counsel" in c for c in memo.approval_conditions)


def test_markdown_render_shows_injected_numbers():
    memo, *_ = _memo_no_warrant()
    md = render_crb_memo_markdown(memo)
    assert "37.6%" in md
    assert "$3,607.5M" in md
    assert "UNDERSTATES" in md
    assert "$41.0M" in md


def test_build_is_pure():
    m1, *_ = _memo_no_warrant()
    m2, *_ = _memo_no_warrant()
    assert m1.model_dump() == m2.model_dump()


def test_warrant_memo_injects_warrant_cost():
    pkg = synthetic_package_with_warrant()
    a = warrant_assumptions()
    econ = ee.compute_economics(pkg, a)
    we = compute_warrant_economics(pkg, a)
    memo = build_crb_memo(pkg, econ, warrant_econ=we)
    assert "ASC 606" in memo.warrant_section and "ASC 718" in memo.warrant_section
    assert "UNDERSTATES" in memo.warrant_section
    # Warrant expected cost $3,384.0M is the top risk by exposure.
    assert memo.top_risks[0].quantified_exposure_usd == pytest.approx(we.total_expected_fair_value_usd, abs=1.0)
