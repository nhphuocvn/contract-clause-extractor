"""BASE-case quarterly P&L totals, hand-computed on the full 150,000-unit deal
at $25,000 ASP and $15,000 unit COGS, GAAP view, prospective rebate, zero
warrant contra:

  gross revenue = 150,000 × $25,000           = $3,750.0M
  COGS          = 150,000 × $15,000           = $2,250.0M
  rebates (prospective)                       =   $142.5M
  net revenue   = 3,750.0 − 142.5             = $3,607.5M
  gross margin  = net − COGS = 3,607.5 − 2,250 = $1,357.5M
"""

from __future__ import annotations

import pytest

from deal_copilot.economics_engine import extract_inputs, run_scenario
from deal_copilot.schemas import ScenarioName, ViewMode
from tests.fixtures import default_assumptions, synthetic_package


def _base():
    inp = extract_inputs(synthetic_package())
    return run_scenario(ScenarioName.BASE, ViewMode.GAAP, inp, default_assumptions(), "prospective")


def test_gross_revenue():
    res = _base()
    assert sum(r.gross_revenue for r in res.quarterly_pl) == pytest.approx(3_750_000_000.0, abs=1.0)


def test_cogs():
    res = _base()
    assert sum(r.cogs for r in res.quarterly_pl) == pytest.approx(2_250_000_000.0, abs=1.0)


def test_net_revenue():
    res = _base()
    assert res.total_net_revenue == pytest.approx(3_607_500_000.0, abs=1.0)


def test_gross_margin():
    res = _base()
    assert res.total_gross_margin == pytest.approx(1_357_500_000.0, abs=1.0)


def test_gross_margin_pct():
    res = _base()
    # 1,357.5 / 3,607.5 = 0.37630...
    assert res.total_gross_margin_pct == pytest.approx(0.376299, abs=1e-5)


def test_units_recognized():
    res = _base()
    assert sum(r.units for r in res.quarterly_pl) == pytest.approx(150_000.0, abs=1.0)
