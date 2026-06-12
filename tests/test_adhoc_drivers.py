"""Ad-hoc drivers flow through the model and the variance bridge like any term.

Sign convention (schema): positive amount_usd increases net revenue / margin;
negative decreases. Base gross margin (warrant-free) = $1,357.5M.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from deal_copilot.economics_engine import extract_inputs, run_scenario
from deal_copilot.schemas import AdHocDriver, ScenarioName, ViewMode
from deal_copilot.variance_bridge import variance_bridge
from deal_copilot.versioning import snapshot_version
from tests.fixtures import default_assumptions, synthetic_package

T0 = datetime(2026, 6, 11)


def _gm_with(drivers):
    pkg, a = synthetic_package(), default_assumptions()
    pkg.ad_hoc_drivers = drivers
    res = run_scenario(ScenarioName.BASE, ViewMode.GAAP, extract_inputs(pkg, 90, a), a, "prospective")
    return res


def test_positive_driver_raises_net_and_margin_by_amount():
    base = _gm_with([])
    plus = _gm_with([AdHocDriver(label="OpenCompute marketing credit", amount_usd=50_000_000.0)])
    assert plus.total_net_revenue - base.total_net_revenue == pytest.approx(50_000_000.0, abs=1.0)
    assert plus.total_gross_margin - base.total_gross_margin == pytest.approx(50_000_000.0, abs=1.0)


def test_negative_driver_lowers_by_amount():
    base = _gm_with([])
    minus = _gm_with([AdHocDriver(label="Side-letter discount", amount_usd=-30_000_000.0)])
    assert minus.total_gross_margin - base.total_gross_margin == pytest.approx(-30_000_000.0, abs=1.0)


def test_adhoc_adjustment_line_visible_and_sums():
    res = _gm_with([AdHocDriver(label="credit", amount_usd=50_000_000.0)])
    # The ad-hoc line is its own visible field on each QuarterRow and sums to total.
    assert sum(r.adhoc_adjustment for r in res.quarterly_pl) == pytest.approx(50_000_000.0, abs=1.0)


def test_quarterly_schedule_respected():
    # An explicit schedule front-loads the whole credit into Q0.
    sched = [50_000_000.0] + [0.0] * 11
    res = _gm_with([AdHocDriver(label="Q0 credit", amount_usd=50_000_000.0, quarterly_schedule_usd=sched)])
    assert res.quarterly_pl[0].adhoc_adjustment == pytest.approx(50_000_000.0, abs=1.0)
    assert res.quarterly_pl[1].adhoc_adjustment == pytest.approx(0.0, abs=1.0)


def test_adhoc_appears_as_bridge_step():
    vA = snapshot_version(synthetic_package(), default_assumptions(), "A", T0)
    pkgB = synthetic_package()
    pkgB.ad_hoc_drivers = [AdHocDriver(label="marketing credit", amount_usd=50_000_000.0)]
    vB = snapshot_version(pkgB, default_assumptions(), "B", T0)
    br = variance_bridge(vA, vB, synthetic_package(), metric="gross_margin")
    step = next(s for s in br.steps if s.field_path == "ad_hoc[marketing credit]")
    assert step.metric_delta_usd == pytest.approx(50_000_000.0, abs=1.0)
    assert br.residual_usd == pytest.approx(0.0, abs=1.0)
