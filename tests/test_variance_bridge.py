"""Variance bridge — driver-level walk that sums exactly to the total delta.

Hand-computed on the warrant-free synthetic deal, BASE / GAAP / prospective rebate.
Gross margin is linear in ASP and COGS here:
  GM(asp, cogs) = 150,000·asp − rebate(asp) − 150,000·cogs,
  rebate scales with ASP (142.5M at $25,000 → 5,700·asp), so
  GM = 144,300·asp − 150,000·cogs.

Base (asp 25,000, cogs 15,000): GM_A = $1,357.5M.
Version B (asp 25,000→26,000, cogs 15,000→16,000):
  ASP step  : +150,000×1,000 gross − $5.7M rebate scaling = +$144.3M
  COGS step : −150,000×1,000 = −$150.0M
  GM_B = $1,351.8M  →  total delta = −$5.7M
"""

from __future__ import annotations

from datetime import datetime

import pytest

from deal_copilot.schemas import ScenarioName, TermType, ViewMode
from deal_copilot.variance_bridge import variance_bridge
from deal_copilot.versioning import snapshot_version
from tests.fixtures import default_assumptions, synthetic_package

T0 = datetime(2026, 6, 11)


def _version_a():
    return snapshot_version(synthetic_package(), default_assumptions(), "A", T0)


def _version_b(asp=26000, cogs=16000.0, opex=None):
    pkg = synthetic_package()
    next(t for t in pkg.terms if t.term_type == TermType.PRICING).parameters["base_asp_usd"] = asp
    update = {"unit_cogs_usd": cogs}
    if opex is not None:
        update["opex_allocation_pct"] = opex
    a = default_assumptions().model_copy(update=update)
    return snapshot_version(pkg, a, "B", T0)


def test_step_contributions_pinned():
    br = variance_bridge(_version_a(), _version_b(), synthetic_package(), metric="gross_margin")
    steps = {s.field_path: s.metric_delta_usd for s in br.steps}
    assert steps["terms[PRICING].base_asp_usd"] == pytest.approx(144_300_000.0, abs=1.0)
    assert steps["assumptions.unit_cogs_usd"] == pytest.approx(-150_000_000.0, abs=1.0)


def test_totals_and_endpoints():
    br = variance_bridge(_version_a(), _version_b(), synthetic_package(), metric="gross_margin")
    assert br.from_metric_usd == pytest.approx(1_357_500_000.0, abs=1.0)
    assert br.to_metric_usd == pytest.approx(1_351_800_000.0, abs=1.0)
    assert br.total_delta_usd == pytest.approx(-5_700_000.0, abs=1.0)


def test_sums_to_delta_property():
    br = variance_bridge(_version_a(), _version_b(), synthetic_package(), metric="gross_margin")
    assert sum(s.metric_delta_usd for s in br.steps) == pytest.approx(br.total_delta_usd, abs=1.0)
    assert br.residual_usd == pytest.approx(0.0, abs=1.0)


def test_zero_impact_change_handled():
    # Opex change does not affect gross margin: its step is 0, residual stays ~0,
    # total is unchanged from the two-knob case.
    br = variance_bridge(_version_a(), _version_b(opex=0.14), synthetic_package(), metric="gross_margin")
    steps = {s.field_path: s.metric_delta_usd for s in br.steps}
    assert "assumptions.opex_allocation_pct" in steps
    assert steps["assumptions.opex_allocation_pct"] == pytest.approx(0.0, abs=1.0)
    assert br.total_delta_usd == pytest.approx(-5_700_000.0, abs=1.0)
    assert br.residual_usd == pytest.approx(0.0, abs=1.0)


def test_net_revenue_metric_sums_to_delta():
    # The property holds for any metric, not just gross margin.
    br = variance_bridge(_version_a(), _version_b(), synthetic_package(), metric="net_revenue")
    assert sum(s.metric_delta_usd for s in br.steps) == pytest.approx(br.total_delta_usd, abs=1.0)
    assert br.residual_usd == pytest.approx(0.0, abs=1.0)


def test_no_changes_yields_empty_bridge():
    br = variance_bridge(_version_a(), _version_a(), synthetic_package(), metric="gross_margin")
    assert br.steps == []
    assert br.total_delta_usd == pytest.approx(0.0, abs=1.0)
