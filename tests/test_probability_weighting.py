"""Scenario probability weighting: expected value = Σ pᵢ·metricᵢ, plus the
sum-not-≈-1 warning flag.

Fixture NPVs BASE/DOWNSIDE/UPSIDE = 100 / 50 / 200 with probabilities
0.5 / 0.3 / 0.2 → expected NPV = 50 + 15 + 40 = 105.
"""

from __future__ import annotations

import pytest

from deal_copilot.economics_engine import probability_weighted
from deal_copilot.schemas import (
    DealAssumptions,
    ScenarioName,
    ScenarioProbability,
    ScenarioResult,
    ViewMode,
)


def _result(scenario: ScenarioName, npv: float) -> ScenarioResult:
    return ScenarioResult(
        scenario=scenario, view=ViewMode.GAAP, quarterly_pl=[],
        npv_usd=npv, total_net_revenue=1000.0,
        total_gross_margin=npv, total_gross_margin_pct=0.1,
    )


def _results():
    return [
        _result(ScenarioName.BASE, 100.0),
        _result(ScenarioName.DOWNSIDE_TAKE_OR_PAY, 50.0),
        _result(ScenarioName.UPSIDE_VOLUME, 200.0),
    ]


def test_expected_npv_weighted():
    a = DealAssumptions(scenario_probabilities=[
        ScenarioProbability(scenario=ScenarioName.BASE, probability=0.5),
        ScenarioProbability(scenario=ScenarioName.DOWNSIDE_TAKE_OR_PAY, probability=0.3),
        ScenarioProbability(scenario=ScenarioName.UPSIDE_VOLUME, probability=0.2),
    ])
    out = probability_weighted(_results(), a)
    assert out["expected_npv_usd"] == pytest.approx(105.0, abs=1e-9)
    assert out["weights_valid"] is True


def test_weights_invalid_when_sum_off():
    a = DealAssumptions(scenario_probabilities=[
        ScenarioProbability(scenario=ScenarioName.BASE, probability=0.5),
        ScenarioProbability(scenario=ScenarioName.DOWNSIDE_TAKE_OR_PAY, probability=0.3),
        ScenarioProbability(scenario=ScenarioName.UPSIDE_VOLUME, probability=0.1),
    ])
    out = probability_weighted(_results(), a)
    assert out["weights_valid"] is False


def test_equal_weights_when_unset():
    out = probability_weighted(_results(), DealAssumptions())
    # equal 1/3 across BASE/DOWNSIDE/UPSIDE (EARLY_TERMINATION absent from fixture)
    assert out["expected_npv_usd"] == pytest.approx((100 + 50 + 200) / 3, abs=1e-9)
    assert out["weights_valid"] is True
