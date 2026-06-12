"""Payback shown both ways on the BASE scenario.

The $500M customer prepayment is a financing overlay. Measured two ways:

(1) Financed view (INCLUDING the prepayment): the Q0 prepayment inflow exceeds
    Q0 outflows, so cumulative discounted cash is positive immediately → payback
    at Q0. This is real cash to the seller but reflects customer financing.

(2) Deployment view (EXCLUDING the prepayment): collections net of COGS and
    opex, no Q0 prepayment, invoices collected in full. Cumulative discounted
    cash (WACC 10%, quarterly rate 0.0241137), in $M:
        Q0 -126.0  Q1 -113.3  Q2 -104.7  Q3 -75.7  Q4 -36.7  Q5 +33.1
    First non-negative at Q5 → operationally meaningful payback = Q5.
"""

from __future__ import annotations

from deal_copilot.economics_engine import extract_inputs, run_scenario
from deal_copilot.schemas import ScenarioName, ViewMode
from tests.fixtures import default_assumptions, synthetic_package


def _base():
    inp = extract_inputs(synthetic_package())
    return run_scenario(ScenarioName.BASE, ViewMode.GAAP, inp, default_assumptions(), "prospective")


def test_financed_payback_is_q0():
    # Prepayment front-loads cash; payback including the prepayment is Q0.
    assert _base().payback_quarters == 0


def test_deployment_payback_excluding_prepayment_is_q5():
    # Operationally meaningful payback on the deal's own deployment cash flows.
    assert _base().payback_quarters_ex_prepayment == 5


def test_deployment_payback_is_later_than_financed():
    res = _base()
    assert res.payback_quarters_ex_prepayment > res.payback_quarters
