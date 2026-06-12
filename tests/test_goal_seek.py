"""Goal-seek — deterministic bisection over the pure engine.

Gross margin is linear in base ASP (warrant-free, prospective):
  GM = 144,300·asp − 2.25e9.
Solving GM = $1.5B gives asp = 3.75e9 / 144,300 = $25,987.53.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from deal_copilot.goal_seek import goal_seek
from deal_copilot.versioning import snapshot_version
from tests.fixtures import default_assumptions, synthetic_package

T0 = datetime(2026, 6, 11)


def _version():
    return snapshot_version(synthetic_package(), default_assumptions(), "A", T0)


def test_goal_seek_base_asp_for_target_margin():
    r = goal_seek(
        synthetic_package(), _version(), knob="base_asp",
        target_metric="gross_margin", target_value_usd=1_500_000_000.0,
        lo=20_000.0, hi=30_000.0, tol_usd=100.0,
    )
    assert r.converged
    assert r.solved_value == pytest.approx(25_987.53, abs=0.5)
    assert r.achieved_metric_usd == pytest.approx(1_500_000_000.0, abs=100.0)


def test_goal_seek_reports_not_converged_when_unbracketed():
    # Target gross margin far above what any ASP in a tiny bracket can reach.
    r = goal_seek(
        synthetic_package(), _version(), knob="base_asp",
        target_metric="gross_margin", target_value_usd=9_000_000_000.0,
        lo=24_000.0, hi=26_000.0, tol_usd=100.0,
    )
    assert not r.converged
