"""Benchmark comparison + staleness (§9.2 / §9.5), pinned on the synthetic deal.

Deal vs portfolio medians (CASH base):
  blended GM   37.6% vs 42%   -> below / worse
  rebate %      3.8% vs  5%    -> below / better (lower is better)
  payment terms net-90 vs net-60 -> above / worse (longer is worse)
  take-or-pay   80% vs 75%     -> above / better

Staleness threshold is 2 quarters (183 days). As of 2026-06-11, the take-or-pay
benchmark (as_of 2025-09-30) is stale; the rest (as_of 2026-03-31) are fresh.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from deal_copilot import benchmarks as bm
from deal_copilot import economics_engine as ee
from tests.fixtures import default_assumptions, synthetic_package

AS_OF = datetime(2026, 6, 11)


def _comparisons():
    pkg = synthetic_package()
    econ = ee.compute_economics(pkg, default_assumptions())
    metrics = bm.deal_benchmark_metrics(pkg, econ)
    return {c.metric: c for c in bm.compare_to_benchmarks(metrics, bm.load_benchmarks(), AS_OF)}, metrics


def test_deal_metrics_extracted():
    _, metrics = _comparisons()
    assert metrics["blended_gross_margin_pct"] == pytest.approx(0.376299, abs=1e-5)
    assert metrics["rebate_pct_of_revenue"] == pytest.approx(0.038, abs=1e-3)   # 142.5M / 3,750M
    assert metrics["payment_terms_net_days"] == 90.0
    assert metrics["take_or_pay_pct"] == 0.80


def test_margin_below_benchmark():
    comps, _ = _comparisons()
    c = comps["blended_gross_margin_pct"]
    assert c.deal_value == pytest.approx(0.376299, abs=1e-5)
    assert c.benchmark_value == 0.42
    assert "below" in c.verdict_sentence and "worse than" in c.verdict_sentence


def test_payment_terms_worse_than_benchmark():
    comps, _ = _comparisons()
    c = comps["payment_terms_net_days"]
    assert "above" in c.verdict_sentence and "worse than" in c.verdict_sentence
    assert "net-90" in c.verdict_sentence and "net-60" in c.verdict_sentence


def test_rebate_better_than_benchmark():
    comps, _ = _comparisons()
    c = comps["rebate_pct_of_revenue"]
    assert "below" in c.verdict_sentence and "better than" in c.verdict_sentence


def test_staleness_flag_two_quarter_boundary():
    comps, _ = _comparisons()
    assert comps["take_or_pay_pct"].is_stale is True            # as_of 2025-09-30
    assert comps["blended_gross_margin_pct"].is_stale is False  # as_of 2026-03-31
    assert "stale" in comps["take_or_pay_pct"].verdict_sentence


def test_missing_benchmark_file_is_labeled_absence():
    assert bm.load_benchmarks("data/does_not_exist.json") == []
    comps = bm.compare_to_benchmarks({"blended_gross_margin_pct": 0.4}, [], AS_OF)
    assert comps == []   # nothing to compare against; caller shows a labeled absence
