"""Warrant contra-revenue is a wired slot defaulting to zero in Phase 3.

- With no contra schedule, GAAP warrant_contra_revenue is 0 and the GAAP and
  CASH_COMMERCIAL views produce identical net revenue.
- When a synthetic contra schedule is injected, GAAP net revenue drops by
  exactly the schedule total and the CASH_COMMERCIAL view is unaffected (contra
  is a non-cash ASC 606 transaction-price reduction).
"""

from __future__ import annotations

import pytest

from deal_copilot.economics_engine import build_quarterly_pl, extract_inputs
from deal_copilot.schemas import ViewMode
from tests.fixtures import synthetic_package


def _units():
    return list(extract_inputs(synthetic_package()).committed_quarterly)


def test_default_contra_is_zero_and_views_match():
    units = _units()
    n = len(units)
    zero = [0.0] * n
    gaap = build_quarterly_pl(units, 25000.0, zero, zero, 15000.0, 0.12, ViewMode.GAAP)
    cash = build_quarterly_pl(units, 25000.0, zero, zero, 15000.0, 0.12, ViewMode.CASH_COMMERCIAL)
    assert sum(r.warrant_contra_revenue for r in gaap) == 0.0
    assert sum(r.net_revenue for r in gaap) == pytest.approx(sum(r.net_revenue for r in cash), abs=1.0)


def test_injected_contra_reduces_gaap_only():
    units = _units()
    n = len(units)
    zero = [0.0] * n
    contra = [1_000_000.0] * n          # $1M/quarter synthetic contra, $12M total
    gaap = build_quarterly_pl(units, 25000.0, zero, contra, 15000.0, 0.12, ViewMode.GAAP)
    cash = build_quarterly_pl(units, 25000.0, zero, contra, 15000.0, 0.12, ViewMode.CASH_COMMERCIAL)
    gaap_net = sum(r.net_revenue for r in gaap)
    cash_net = sum(r.net_revenue for r in cash)
    assert sum(r.warrant_contra_revenue for r in gaap) == pytest.approx(12_000_000.0, abs=1.0)
    assert cash_net - gaap_net == pytest.approx(12_000_000.0, abs=1.0)
