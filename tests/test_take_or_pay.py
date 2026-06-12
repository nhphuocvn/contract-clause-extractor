"""Take-or-pay floor + Banked Units, hand-computed at 75% demand (below the 80%
floor) on the synthetic year totals [43000, 72000, 35000]:

  Y1: floor 0.80×43000 = 34,400; taken 0.75×43000 = 32,250 → shortfall 2,150 → $53.75M
  Y2: floor 0.80×72000 = 57,600; taken 0.75×72000 = 54,000 → shortfall 3,600 → $90.00M
  Y3: floor 0.80×35000 = 28,000; taken 0.75×35000 = 26,250 → shortfall 1,750 → $43.75M
  Banked Units = 2,150 + 3,600 + 1,750 = 7,500, all forfeited (no recovery).
  Revenue floor: taken×ASP + shortfall payment == floor×ASP each Year.
"""

from __future__ import annotations

import pytest

from deal_copilot.economics_engine import (
    DOWNSIDE_DEMAND_PCT,
    compute_take_or_pay,
    extract_inputs,
)
from tests.fixtures import synthetic_package


def _downside():
    inp = extract_inputs(synthetic_package())
    committed = list(inp.committed_quarterly)
    demand = [u * DOWNSIDE_DEMAND_PCT for u in committed]
    years, banked = compute_take_or_pay(committed, demand, inp.qpy, 0.80, 25000.0)
    return inp, years, banked


def test_shortfall_units_per_year():
    _, years, _ = _downside()
    assert [round(y.shortfall_units) for y in years] == [2150, 3600, 1750]


def test_shortfall_payments_per_year():
    _, years, _ = _downside()
    pay = [y.shortfall_payment_usd for y in years]
    assert pay[0] == pytest.approx(53_750_000.0, abs=1.0)
    assert pay[1] == pytest.approx(90_000_000.0, abs=1.0)
    assert pay[2] == pytest.approx(43_750_000.0, abs=1.0)


def test_banked_units_forfeited_at_term_end():
    _, _, banked = _downside()
    assert banked == pytest.approx(7500.0, abs=1.0)


def test_revenue_floor_enforced():
    inp, years, _ = _downside()
    asp = inp.base_asp
    for y in years:
        taken_rev = y.taken_units * asp
        floor_rev = y.floor_units * asp
        assert taken_rev + y.shortfall_payment_usd == pytest.approx(floor_rev, abs=1.0)


def test_banked_units_drawn_down_on_recovery():
    """A later Year whose demand exceeds committed draws banked units first, so
    no double shortfall accrues."""
    inp = extract_inputs(synthetic_package())
    committed = list(inp.committed_quarterly)
    # Year 1 below floor (banks units); Year 3 demand spikes above committed.
    demand = list(committed)
    for q in range(0, 4):
        demand[q] = committed[q] * 0.75            # Y1 shortfall -> banks units
    for q in range(8, 12):
        demand[q] = committed[q] * 1.30            # Y3 recovery -> draws banked
    years, banked = compute_take_or_pay(committed, demand, inp.qpy, 0.80, 25000.0)
    assert years[0].shortfall_units == pytest.approx(2150.0, abs=1.0)
    # Y3 over-demand consumed banked units; fewer than the 2,150 banked remain.
    assert banked < 2150.0
