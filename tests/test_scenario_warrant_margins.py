"""Per-scenario warrant contra-revenue (the Phase 7 engine bug fix).

The warrant vests on DEPLOYMENT (Warrant §2): each tranche's expected fair value
is allocated across the cumulative-unit band from the prior milestone to its own.
A reduced-volume scenario therefore crosses fewer milestones and must carry LESS
contra. The bug was that the BASE full-deployment contra schedule ($3.384B) was
reused on every scenario, so DOWNSIDE subtracted the full contra from reduced
revenue → GAAP net revenue went negative and GM% exploded (−$2.15B / 463%).

Hand-calc (measurement price $470, exercise $0.01, base vest set [0.9,0.7,0.5,0.3],
four 3,000,000-share tranches at deployment milestones 30k/75k/120k/150k):

  fair value/share          = 470 − 0.01           = $469.99
  T1 expected FV = 3,000,000 × 469.99 × 0.9         = $1,268,973,000   band  0–30k
  T2 expected FV = 3,000,000 × 469.99 × 0.7         =   $986,979,000   band 30k–75k
  T3 expected FV = 3,000,000 × 469.99 × 0.5         =   $704,985,000   band 75k–120k
  T4 expected FV = 3,000,000 × 469.99 × 0.3         =   $422,991,000   band 120k–150k
  total (full deployment)                            = $3,383,928,000

  BASE / UPSIDE deploy ≥ 150k  → full $3,383.928M contra
  DOWNSIDE deploys 0.75×150k = 112,500 units
     = T1 + T2 + (37,500/45,000)·T3
     = 1,268,973,000 + 986,979,000 + 587,487,500   = $2,843,439,500
  EARLY_TERMINATION deploys Q1–Q8 = 115,000 units
     = T1 + T2 + (40,000/45,000)·T3
     = 1,268,973,000 + 986,979,000 + 626,653,333.3 = $2,882,605,333

The negative GAAP gross margin is the CORRECT, headline result: the $3.384B equity
grant to the customer is ASC 606 contra-revenue and exceeds the $1.358B product
margin. The healthy ~37–42% margin lives in the CASH / commercial view, which
excludes the non-cash warrant.
"""

from __future__ import annotations

import pytest

from deal_copilot.economics_engine import extract_inputs, run_scenario
from deal_copilot.schemas import ScenarioName, ViewMode
from tests.fixtures import synthetic_package_with_warrant, warrant_assumptions

# Hand-calc tranche expected fair values (USD).
_T1, _T2, _T3, _T4 = 1_268_973_000.0, 986_979_000.0, 704_985_000.0, 422_991_000.0
_FULL_CONTRA = _T1 + _T2 + _T3 + _T4                       # 3,383,928,000
_DOWNSIDE_CONTRA = _T1 + _T2 + (37_500 / 45_000) * _T3     # 2,843,439,500
_ET_CONTRA = _T1 + _T2 + (40_000 / 45_000) * _T3           # 2,882,605,333


def _inp():
    pkg = synthetic_package_with_warrant()
    return extract_inputs(pkg, 90, warrant_assumptions()), warrant_assumptions()


def _run(scenario, view):
    inp, a = _inp()
    return run_scenario(scenario, view, inp, a, "prospective")


def _contra(scenario):
    """Total warrant contra (GAAP view) for a scenario."""
    res = _run(scenario, ViewMode.GAAP)
    return sum(r.warrant_contra_revenue for r in res.quarterly_pl)


# ---------------------------------------------------------------------------
# Per-scenario contra scales with deployment (the bug fix)
# ---------------------------------------------------------------------------


def test_base_contra_is_full_deployment():
    assert _contra(ScenarioName.BASE) == pytest.approx(_FULL_CONTRA, abs=1_000.0)


def test_upside_contra_equals_full():
    """UPSIDE deploys 172.5k > 150k final milestone → all four tranches vest."""
    assert _contra(ScenarioName.UPSIDE_VOLUME) == pytest.approx(_FULL_CONTRA, abs=1_000.0)


def test_downside_contra_is_reduced():
    assert _contra(ScenarioName.DOWNSIDE_TAKE_OR_PAY) == pytest.approx(_DOWNSIDE_CONTRA, abs=1_000.0)


def test_early_termination_contra_is_reduced():
    assert _contra(ScenarioName.EARLY_TERMINATION) == pytest.approx(_ET_CONTRA, abs=1_000.0)


def test_downside_contra_strictly_below_base():
    """The fix's core invariant: fewer deployed units ⇒ less contra."""
    assert _contra(ScenarioName.DOWNSIDE_TAKE_OR_PAY) < _contra(ScenarioName.BASE)


# ---------------------------------------------------------------------------
# Cash-view margins are sane (~37–42%); the negative-net garbage is gone
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario,expected_pct", [
    (ScenarioName.BASE, 0.376),
    (ScenarioName.DOWNSIDE_TAKE_OR_PAY, 0.422),
    (ScenarioName.UPSIDE_VOLUME, 0.374),
    (ScenarioName.EARLY_TERMINATION, 0.382),
])
def test_cash_view_margin_is_sane(scenario, expected_pct):
    res = _run(scenario, ViewMode.CASH_COMMERCIAL)
    assert res.total_gross_margin_pct == pytest.approx(expected_pct, abs=0.01)
    assert 0.30 <= res.total_gross_margin_pct <= 0.45


@pytest.mark.parametrize("scenario", [
    ScenarioName.BASE,
    ScenarioName.DOWNSIDE_TAKE_OR_PAY,
    ScenarioName.UPSIDE_VOLUME,
])
def test_gaap_net_revenue_non_negative(scenario):
    """Post-fix, GAAP net revenue no longer goes negative for these scenarios
    (it did when the full contra was subtracted from reduced revenue)."""
    res = _run(scenario, ViewMode.GAAP)
    assert res.total_net_revenue >= 0.0


# ---------------------------------------------------------------------------
# The negative GAAP gross margin is the correct, headline result
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", list(ScenarioName))
def test_gaap_gross_margin_is_negative(scenario):
    """The $3.384B warrant exceeds the $1.358B product margin, so GAAP gross
    margin (which carries the contra) is negative across all scenarios. This is
    correct — the deal is cash-positive but GAAP-dilutive."""
    res = _run(scenario, ViewMode.GAAP)
    assert res.total_gross_margin < 0.0
