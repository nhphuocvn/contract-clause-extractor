"""NPV / payback primitives on hand-computed cash-flow vectors.

Quarterly discount rate from WACC 10%: (1.10)**0.25 - 1 = 0.0241136890844.
For cf = [-1000, 500, 500, 300]:
  NPV = -1000 + 500/(1+r) + 500/(1+r)^2 + 300/(1+r)^3 = 244.2620728476.
For cf = [-1000, 400, 400, 400, 400], cumulative discounted turns non-negative
first at quarter index 3 (cum = +144.37).
"""

from __future__ import annotations

import pytest

from deal_copilot.economics_engine import (
    npv,
    payback_quarter,
    quarterly_discount_rate,
)


def test_quarterly_rate_from_wacc():
    assert quarterly_discount_rate(0.10) == pytest.approx(0.0241136890844, abs=1e-12)


def test_npv_hand_vector():
    assert npv([-1000, 500, 500, 300], 0.10) == pytest.approx(244.2620728476, abs=1e-6)


def test_npv_zero_when_no_flows():
    assert npv([], 0.10) == 0.0


def test_payback_quarter():
    assert payback_quarter([-1000, 400, 400, 400, 400], 0.10) == 3


def test_payback_none_when_never_recovered():
    assert payback_quarter([-1000, 100, 100], 0.10) is None
