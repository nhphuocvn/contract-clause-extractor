"""Payback shown both ways on the BASE scenario, on the MONTHLY cash grid with
the full working-capital model (DSO collections, DPO supplier terms, inventory
lead). Revenue recognition stays quarterly; only cash timing is monthly.

The $500M customer prepayment is a financing overlay. Measured two ways:

(1) Financed view (INCLUDING the prepayment): the prepayment inflow lands the
    month deliveries begin and dwarfs the early outflows, so cumulative
    discounted cash is non-negative almost immediately → payback maps to Q0.

(2) Deployment view (EXCLUDING the prepayment): the deal's own operating cash.
    With the synthetic deal's net-90 collections (+3 months), net-60 supplier
    terms (DPO +2 months) and a 3-month inventory lead, COGS cash actually
    leaves ONE month BEFORE each shipment (cogs_cash_lag = 2 − 3 = −1), opex
    leaves +2 months, and collections arrive +3 months. That realistic
    working-capital drag pushes the operationally meaningful payback to the
    month-18 boundary → Q6 (one quarter later than the naive at-delivery model,
    which is exactly the point of modeling working capital).

NPV here is pre-tax operating cash; collections are assumed perfect.
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


def test_deployment_payback_excluding_prepayment_is_q6():
    # Operationally meaningful payback on the deal's own deployment cash flows,
    # under the full working-capital model (inventory build + collection lag).
    assert _base().payback_quarters_ex_prepayment == 6


def test_deployment_payback_is_later_than_financed():
    res = _base()
    assert res.payback_quarters_ex_prepayment > res.payback_quarters
