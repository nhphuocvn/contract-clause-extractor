"""Rebate ambiguity dual-variant — the headline feature.

Every figure here is hand-computed from the synthetic schedule and tier table,
not a recompute of the implementation:

  Reading A (prospective / marginal cumulative bands):
    units 30k-75k @3% (45,000 × $750)  = $33.75M
    units 75k-120k @5% (45,000 × $1,250) = $56.25M
    units 120k-150k @7% (30,000 × $1,750) = $52.50M
                                    total = $142.50M
  Reading B (retroactive within Year, at the Year-end tier):
    Y1 43,000 @3% × $25k = $32.25M
    Y2 72,000 @5% × $25k = $90.00M
    Y3 35,000 @7% × $25k = $61.25M
                   total = $183.50M
  Delta = $41.00M
"""

from __future__ import annotations

import pytest

from deal_copilot.driver_mapper import (
    compute_rebate_schedule,
    rebate_variant_comparison,
)
from deal_copilot.economics_engine import extract_inputs
from tests.fixtures import synthetic_package


def _inputs():
    return extract_inputs(synthetic_package())


def test_prospective_total_is_142_5M():
    inp = _inputs()
    sched = compute_rebate_schedule(
        list(inp.rebate_tiers), list(inp.committed_quarterly), inp.base_asp,
        "prospective", inp.qpy,
    )
    assert sum(sched) == pytest.approx(142_500_000.0, abs=1.0)


def test_retroactive_total_is_183_5M():
    inp = _inputs()
    sched = compute_rebate_schedule(
        list(inp.rebate_tiers), list(inp.committed_quarterly), inp.base_asp,
        "retroactive_within_year", inp.qpy,
    )
    assert sum(sched) == pytest.approx(183_500_000.0, abs=1.0)


def test_delta_is_41M():
    inp = _inputs()
    rb = next(t for t in synthetic_package().terms if t.term_type.value == "REBATE")
    cmp = rebate_variant_comparison(rb, list(inp.committed_quarterly), inp.base_asp, inp.qpy)
    assert cmp["prospective_total_usd"] == pytest.approx(142_500_000.0, abs=1.0)
    assert cmp["retroactive_total_usd"] == pytest.approx(183_500_000.0, abs=1.0)
    assert cmp["delta_usd"] == pytest.approx(41_000_000.0, abs=1.0)


def test_retroactive_per_year_split():
    inp = _inputs()
    sched = compute_rebate_schedule(
        list(inp.rebate_tiers), list(inp.committed_quarterly), inp.base_asp,
        "retroactive_within_year", inp.qpy,
    )
    assert sum(sched[0:4]) == pytest.approx(32_250_000.0, abs=1.0)   # Y1 @3%
    assert sum(sched[4:8]) == pytest.approx(90_000_000.0, abs=1.0)   # Y2 @5%
    assert sum(sched[8:12]) == pytest.approx(61_250_000.0, abs=1.0)  # Y3 @7%
