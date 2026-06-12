"""Prepayment drawdown: 20% of each invoice against a $500M contract liability.

Invoices are gross revenue per quarter (units × $25,000). The prepayment
exhausts when cumulative invoices reach $500M / 0.20 = $2,500M, i.e. cumulative
units reach 100,000 — which happens during Q7 (cumulative units: Q6=99,000,
Q7=115,000). The balance then stays at 0.
"""

from __future__ import annotations

import pytest

from deal_copilot.accounting_schedules import prepayment_schedule
from deal_copilot.economics_engine import extract_inputs
from tests.fixtures import synthetic_package


def _invoices():
    inp = extract_inputs(synthetic_package())
    return [u * inp.base_asp for u in inp.committed_quarterly]


def test_drawdown_is_20pct_until_exhausted():
    rows = prepayment_schedule(_invoices())
    # While the balance is ample, each drawdown is exactly 20% of the invoice.
    inv = _invoices()
    assert rows[0].drawdown == pytest.approx(0.20 * inv[0], abs=1.0)
    assert rows[5].drawdown == pytest.approx(0.20 * inv[5], abs=1.0)


def test_exhausts_during_q7():
    rows = prepayment_schedule(_invoices())
    assert rows[6].ending > 0.0           # not yet exhausted at end of Q6
    assert rows[7].ending == pytest.approx(0.0, abs=1.0)  # exhausted during Q7


def test_total_drawn_equals_prepayment():
    rows = prepayment_schedule(_invoices())
    assert sum(r.drawdown for r in rows) == pytest.approx(500_000_000.0, abs=1.0)


def test_balance_stays_zero_after_exhaustion():
    rows = prepayment_schedule(_invoices())
    for r in rows[7:]:
        assert r.ending == pytest.approx(0.0, abs=1.0)
        assert r.beginning == pytest.approx(r.ending + r.drawdown, abs=1.0)
