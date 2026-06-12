"""Monthly working-capital cash layer — net-30 / net-60 / net-90 must produce
genuinely different collection schedules, peak receivables, NPV, and working-
capital draw, and the inventory build must show up as a real cash draw.

Revenue recognition stays quarterly; this is purely the CASH timing layer.
Within-quarter activity is spread evenly across the quarter's 3 months.

All figures below are hand-traceable on the synthetic BASE deal:
  - quarterly units ramp peaks at Q5 = 20,000 units → $500.0M billed/quarter →
    $166.667M/month at $25,000 ASP.
  - peak receivables = a trailing window of 1 / 2 / 3 months of Q5 billing for
    net-30 / net-60 / net-90 → $166.667M / $333.333M / $500.000M.
  - inventory build: Q0 ships 7,000 units → COGS 7,000 × $15,000 = $105.0M,
    spread over 3 months = $35.0M/month, funded one month AHEAD of shipment
    (cogs_cash_lag = DPO 2mo − inventory lead 3mo = −1mo).
"""

from __future__ import annotations

import pytest

from deal_copilot import economics_engine as ee
from deal_copilot import accounting_schedules as acc
from deal_copilot.schemas import ScenarioName, ViewMode
from tests.fixtures import default_assumptions, synthetic_package

WACC = 0.10


def _rows_and_inputs(dso_days: int):
    inp = ee._replace_inputs(ee.extract_inputs(synthetic_package()), dso_days=dso_days)
    res = ee.run_scenario(ScenarioName.BASE, ViewMode.GAAP, inp, default_assumptions(), "prospective")
    return res, inp


# --- Primitives -------------------------------------------------------------

def test_monthly_discount_rate_from_wacc():
    assert ee.monthly_discount_rate(0.10) == pytest.approx(0.007974140428903764, abs=1e-15)


def test_lag_months_net_30_60_90():
    assert (ee._lag_months(30), ee._lag_months(60), ee._lag_months(90)) == (1, 2, 3)


def test_npv_monthly_hand_vector():
    assert ee.npv_monthly([-1000, 500, 500, 300], 0.10) == pytest.approx(281.100934481272, abs=1e-9)


def test_payback_month_hand_vector():
    assert ee.payback_month([-1000, 400, 400, 400, 400], 0.10) == 3


# --- DSO: peak receivables (the working-capital float) ----------------------

def test_peak_receivables_distinct_by_payment_terms():
    billings = [r.gross_revenue for r in _rows_and_inputs(90)[0].quarterly_pl]
    p30, q30 = acc.peak_receivables(billings, 30)
    p60, q60 = acc.peak_receivables(billings, 60)
    p90, q90 = acc.peak_receivables(billings, 90)
    assert p30 == pytest.approx(166_666_666.666667, abs=1.0)   # 1 month of Q5
    assert p60 == pytest.approx(333_333_333.333333, abs=1.0)   # 2 months of Q5
    assert p90 == pytest.approx(500_000_000.0, abs=1.0)        # full Q5 quarter
    assert q30 == q60 == q90 == 5                              # all peak in Q5


def test_working_capital_float_swing_net30_to_net90():
    billings = [r.gross_revenue for r in _rows_and_inputs(90)[0].quarterly_pl]
    p30 = acc.peak_receivables(billings, 30)[0]
    p90 = acc.peak_receivables(billings, 90)[0]
    assert p90 - p30 == pytest.approx(333_333_333.333333, abs=1.0)


# --- DSO: NPV cost of slower collection -------------------------------------

def test_deployment_npv_monotonic_in_payment_terms():
    n30 = ee.npv_monthly(ee.monthly_cash_flows(*_dep(30))[0], WACC)
    n60 = ee.npv_monthly(ee.monthly_cash_flows(*_dep(60))[0], WACC)
    n90 = ee.npv_monthly(ee.monthly_cash_flows(*_dep(90))[0], WACC)
    assert n30 > n60 > n90                                     # longer terms → lower NPV
    assert n30 == pytest.approx(774_660_583.035916, abs=1.0)
    assert n60 == pytest.approx(749_973_998.169355, abs=1.0)
    assert n90 == pytest.approx(725_482_710.271774, abs=1.0)


def test_npv_cost_of_payment_terms():
    n30 = ee.npv_monthly(ee.monthly_cash_flows(*_dep(30))[0], WACC)
    n60 = ee.npv_monthly(ee.monthly_cash_flows(*_dep(60))[0], WACC)
    n90 = ee.npv_monthly(ee.monthly_cash_flows(*_dep(90))[0], WACC)
    assert n30 - n90 == pytest.approx(49_177_872.764, abs=1.0)
    assert n60 - n90 == pytest.approx(24_491_287.898, abs=1.0)


def test_financed_npv_anchor():
    n90 = ee.npv_monthly(ee.monthly_cash_flows(*_fin(90))[0], WACC)
    assert n90 == pytest.approx(780_545_471.363774, abs=1.0)


# --- Inventory build & netted COGS cash lag ---------------------------------

def test_cogs_cash_lag_nets_dpo_against_inventory_lead():
    a = default_assumptions()
    dpo_months = ee._lag_months(a.supplier_payment_dpo_days)     # net-60 → 2
    cogs_cash_lag = dpo_months - a.inventory_lead_months         # 2 − 3 = −1
    assert dpo_months == 2
    assert a.inventory_lead_months == 3
    assert cogs_cash_lag == -1                                   # COGS cash 1mo AHEAD


def test_inventory_build_funds_cogs_ahead_of_first_shipment():
    rows = _rows_and_inputs(90)[0].quarterly_pl
    assert rows[0].cogs == pytest.approx(105_000_000.0, abs=1.0)   # 7,000 × $15,000
    assert rows[0].cogs / 3.0 == pytest.approx(35_000_000.0, abs=1.0)  # per-month build


def test_peak_working_capital_draw_deepens_with_payment_terms():
    d30 = _rows_and_inputs(30)[0].peak_working_capital_draw_usd
    d60 = _rows_and_inputs(60)[0].peak_working_capital_draw_usd
    d90 = _rows_and_inputs(90)[0].peak_working_capital_draw_usd
    assert d30 < 0 and d60 < 0 and d90 < 0
    assert d90 < d60 < d30                                       # longer terms → deeper draw
    assert d30 == pytest.approx(-70_000_000.0, abs=1.0)
    assert d60 == pytest.approx(-105_000_000.0, abs=1.0)
    assert d90 == pytest.approx(-157_000_000.0, abs=1.0)


# --- Payback by payment terms (deployment view) -----------------------------

def test_deployment_payback_later_for_longer_terms():
    assert _rows_and_inputs(30)[0].payback_quarters_ex_prepayment == 2
    assert _rows_and_inputs(60)[0].payback_quarters_ex_prepayment == 4
    assert _rows_and_inputs(90)[0].payback_quarters_ex_prepayment == 6


def _dep(dso_days: int):
    res, inp = _rows_and_inputs(dso_days)
    return res.quarterly_pl, inp, False


def _fin(dso_days: int):
    res, inp = _rows_and_inputs(dso_days)
    return res.quarterly_pl, inp, True
