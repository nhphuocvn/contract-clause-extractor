"""One-way sensitivities, tornado-ranked by |Δ vs base| on total gross margin.

Directional hand-checks (BASE, GAAP, prospective rebate):
  - +10% ASP raises gross margin; −10% ASP lowers it (and by ~the same size).
  - +10% unit COGS lowers gross margin.
  - Every row's total_gross_margin_usd = base + delta_vs_base_usd.
  - Rows are sorted descending by |delta| (tornado order).
"""

from __future__ import annotations

import pytest

from deal_copilot.economics_engine import (
    extract_inputs,
    run_scenario,
    sensitivities,
)
from deal_copilot.schemas import ScenarioName, ViewMode
from tests.fixtures import default_assumptions, synthetic_package


def _rows():
    inp = extract_inputs(synthetic_package())
    return sensitivities(inp, default_assumptions(), "prospective")


def _base_gm():
    inp = extract_inputs(synthetic_package())
    return run_scenario(ScenarioName.BASE, ViewMode.GAAP, inp, default_assumptions(), "prospective").total_gross_margin


def test_asp_up_raises_margin():
    row = next(r for r in _rows() if r.variable == "asp" and r.delta_label == "+10%")
    assert row.delta_vs_base_usd > 0


def test_asp_down_lowers_margin_symmetrically():
    rows = _rows()
    up = next(r for r in rows if r.variable == "asp" and r.delta_label == "+10%")
    down = next(r for r in rows if r.variable == "asp" and r.delta_label == "-10%")
    assert down.delta_vs_base_usd < 0
    assert up.delta_vs_base_usd == pytest.approx(-down.delta_vs_base_usd, rel=1e-6)


def test_cogs_up_lowers_margin():
    row = next(r for r in _rows() if r.variable == "unit_cogs" and r.delta_label == "+10%")
    assert row.delta_vs_base_usd < 0


def test_levels_consistent_with_delta():
    base = _base_gm()
    for r in _rows():
        assert r.total_gross_margin_usd == pytest.approx(base + r.delta_vs_base_usd, abs=1.0)


def test_rows_sorted_descending_by_abs_delta():
    deltas = [abs(r.delta_vs_base_usd) for r in _rows()]
    assert deltas == sorted(deltas, reverse=True)
