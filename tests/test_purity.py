"""Engine purity: the economics functions are pure — calling twice on the same
inputs yields equal output, and inputs are not mutated. This guards the bar that
makes goal-seek and Monte Carlo cheap layers later.
"""

from __future__ import annotations

from deal_copilot.economics_engine import compute_economics, extract_inputs, run_scenario
from deal_copilot.schemas import ScenarioName, ViewMode
from tests.fixtures import default_assumptions, synthetic_package


def test_compute_economics_is_deterministic():
    pkg, a = synthetic_package(), default_assumptions()
    first = compute_economics(pkg, a)
    second = compute_economics(pkg, a)
    assert first.model_dump() == second.model_dump()


def test_inputs_not_mutated():
    pkg, a = synthetic_package(), default_assumptions()
    before_assumptions = a.model_dump()
    before_terms = [t.model_dump() for t in pkg.terms]
    compute_economics(pkg, a)
    assert a.model_dump() == before_assumptions
    assert [t.model_dump() for t in pkg.terms] == before_terms


def test_run_scenario_repeatable():
    inp = extract_inputs(synthetic_package())
    a = default_assumptions()
    r1 = run_scenario(ScenarioName.BASE, ViewMode.GAAP, inp, a, "prospective")
    r2 = run_scenario(ScenarioName.BASE, ViewMode.GAAP, inp, a, "prospective")
    assert r1.model_dump() == r2.model_dump()
