"""Warrant economics — valuing the free stock given to the customer.

Hand-computed on the ground-truth warrant (12,000,000 shares @ $0.01 strike, four
3,000,000-share tranches at milestones 30k/75k/120k/150k) at AMD spot $470:

  per_share_fv = 470.00 - 0.01 = 469.99
  gross per tranche = 3,000,000 * 469.99 = $1,409,970,000

  Expected fair value (base vest probs [0.9, 0.7, 0.5, 0.3]):
    T1 1,409,970,000 * 0.9 = $1,268,973,000
    T2 1,409,970,000 * 0.7 =   $986,979,000
    T3 1,409,970,000 * 0.5 =   $704,985,000
    T4 1,409,970,000 * 0.3 =   $422,991,000
                       total = $3,383,928,000

  Expected-value range (= $1,409,970,000 * sum(probs)):
    conservative [0.7,0.5,0.3,0.1] sum 1.6 -> $2,255,952,000
    base         [0.9,0.7,0.5,0.3] sum 2.4 -> $3,383,928,000
    aggressive   [1.0,0.9,0.7,0.4] sum 3.0 -> $4,229,910,000
"""

from __future__ import annotations

import pytest

from deal_copilot import warrant_economics as we
from deal_copilot.economics_engine import compute_economics, extract_inputs, run_scenario
from deal_copilot.schemas import ProvenanceClass, ScenarioName, ViewMode
from tests.fixtures import (
    AS_OF,
    synthetic_package_with_warrant,
    synthetic_warrant_terms,
    warrant_assumptions,
)


def _econ():
    return we.compute_warrant_economics(synthetic_package_with_warrant(), warrant_assumptions())


# --- per-tranche fair value ------------------------------------------------

def test_per_tranche_expected_fair_value():
    vals = _econ().tranche_valuations
    assert vals[0].expected_fair_value_usd == pytest.approx(1_268_973_000.0, abs=1.0)
    assert vals[1].expected_fair_value_usd == pytest.approx(986_979_000.0, abs=1.0)
    assert vals[2].expected_fair_value_usd == pytest.approx(704_985_000.0, abs=1.0)
    assert vals[3].expected_fair_value_usd == pytest.approx(422_991_000.0, abs=1.0)


def test_per_share_fair_value():
    vals = _econ().tranche_valuations
    assert all(v.fair_value_per_share_usd == pytest.approx(469.99, abs=1e-9) for v in vals)


def test_total_expected_fair_value():
    assert _econ().total_expected_fair_value_usd == pytest.approx(3_383_928_000.0, abs=1.0)


# --- expected-value range --------------------------------------------------

def test_expected_value_range_three_sets():
    rng = {s.label: s.total_expected_fair_value_usd for s in _econ().expected_value_range}
    assert rng["conservative"] == pytest.approx(2_255_952_000.0, abs=1.0)
    assert rng["base"] == pytest.approx(3_383_928_000.0, abs=1.0)
    assert rng["aggressive"] == pytest.approx(4_229_910_000.0, abs=1.0)


# --- contra-revenue schedule (fills the slot) ------------------------------

def test_contra_schedule_total_and_q0():
    sched = _econ().contra_revenue_schedule_usd
    assert sum(sched) == pytest.approx(3_383_928_000.0, abs=1.0)
    # Q0: 7,000 units all in band 1 (0-30k), per-unit = 1,268,973,000/30,000.
    assert sched[0] == pytest.approx(296_093_700.0, abs=1.0)


# --- effective ASP waterfall ----------------------------------------------

def test_effective_asp_all_in():
    eff = _econ().effective_asp
    assert eff.sticker_usd == pytest.approx(25_000.0, abs=1e-6)
    assert eff.rebate_per_unit_usd == pytest.approx(950.0, abs=1e-6)
    assert eff.warrant_per_unit_usd == pytest.approx(22_559.52, abs=0.01)
    assert eff.all_in_usd == pytest.approx(1_490.48, abs=0.01)


# --- GAAP vs cash bridge ---------------------------------------------------

def test_gaap_cash_bridge():
    w = _econ()
    assert w.cash_net_revenue_usd == pytest.approx(3_607_500_000.0, abs=1.0)
    assert w.gaap_net_revenue_usd == pytest.approx(223_572_000.0, abs=1.0)
    assert w.warrant_contra_bridge_usd == pytest.approx(3_383_928_000.0, abs=1.0)


# --- dilution & asymmetry --------------------------------------------------

def test_dilution_pct():
    # 12,000,000 / 1,618,000,000 = 0.7417%
    assert _econ().dilution_pct_of_shares_outstanding == pytest.approx(0.00741656, abs=1e-7)


def test_value_at_three_price_levels():
    levels = {lv.stock_price_usd: lv.total_intrinsic_value_usd for lv in _econ().value_at_price_levels}
    assert levels[300.0] == pytest.approx(3_599_880_000.0, abs=1.0)
    assert levels[470.0] == pytest.approx(5_639_880_000.0, abs=1.0)
    assert levels[600.0] == pytest.approx(7_199_880_000.0, abs=1.0)


# --- engine wiring (the slot fill) -----------------------------------------

def test_engine_gaap_reflects_contra_cash_does_not():
    pkg, a = synthetic_package_with_warrant(), warrant_assumptions()
    inp = extract_inputs(pkg, 90, a)
    gaap = run_scenario(ScenarioName.BASE, ViewMode.GAAP, inp, a, "prospective")
    cash = run_scenario(ScenarioName.BASE, ViewMode.CASH_COMMERCIAL, inp, a, "prospective")
    assert gaap.total_net_revenue == pytest.approx(223_572_000.0, abs=1.0)
    assert cash.total_net_revenue == pytest.approx(3_607_500_000.0, abs=1.0)


def test_compute_economics_effective_asp_picks_up_warrant():
    econ = compute_economics(synthetic_package_with_warrant(), warrant_assumptions())
    assert econ.effective_asp.warrant_per_unit_usd == pytest.approx(22_559.52, abs=0.01)


def test_warrantless_package_has_zero_contra():
    # Regression guard: the Phase 3 warrant-free package keeps a zero contra slot.
    from tests.fixtures import default_assumptions, synthetic_package
    inp = extract_inputs(synthetic_package(), 90, default_assumptions())
    assert sum(inp.contra_schedule) == 0.0


# --- judgment inputs -------------------------------------------------------

def test_measurement_price_defaults_to_current_spot():
    a = warrant_assumptions()  # warrant_measurement_price_usd is None
    assert a.warrant_measurement_price_usd is None
    assert we.measurement_price(a) == pytest.approx(470.0, abs=1e-9)


def test_measurement_price_override():
    a = warrant_assumptions().model_copy(update={"warrant_measurement_price_usd": 500.0})
    assert we.measurement_price(a) == pytest.approx(500.0, abs=1e-9)


def test_judgment_provenance_is_placeholder():
    prov = we.judgment_provenance(warrant_assumptions(), AS_OF)
    for key in ("tranche_vest_probabilities", "warrant_measurement_price_usd"):
        assert prov[key].basis == ProvenanceClass.PLACEHOLDER
        assert "confirm with deal team" in prov[key].note


def test_vest_probability_count_mismatch_raises():
    pkg = synthetic_package_with_warrant()
    bad = warrant_assumptions().model_copy(update={"tranche_vest_probabilities": [0.9, 0.7]})
    with pytest.raises(ValueError):
        we.compute_warrant_economics(pkg, bad)


# --- Black-Scholes (illustrative) ------------------------------------------

def test_black_scholes_textbook_case():
    # Standard Hull example: S=K=100, T=1, sigma=0.20, r=0.05 -> ~10.4506.
    assert we.black_scholes_call(100, 100, 1, 0.20, 0.05) == pytest.approx(10.4506, abs=1e-3)


def test_black_scholes_deep_itm_approximates_intrinsic():
    # Near-zero strike: BS ~ spot - strike.
    assert we.black_scholes_call(470, 0.01, 6, 0.45, 0.04) == pytest.approx(469.99, abs=0.5)
