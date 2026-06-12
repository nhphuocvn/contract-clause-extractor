"""Accrual-walk continuity: each quarter's ending balance is the next quarter's
beginning balance, for both rebate readings and the prepayment schedule.

Reconciliation to totals:
  - rebate accrual expense sums to $142.5M (prospective) / $183.5M (retroactive);
  - prepayment ending balance reaches $0 and stays there.
"""

from __future__ import annotations

import pytest

from deal_copilot.accounting_schedules import (
    prepayment_schedule,
    rebate_accrual_walk,
)
from deal_copilot.economics_engine import extract_inputs
from tests.fixtures import synthetic_package


def _inp():
    return extract_inputs(synthetic_package())


@pytest.mark.parametrize("variant,total", [
    ("prospective", 142_500_000.0),
    ("retroactive_within_year", 183_500_000.0),
])
def test_rebate_accrual_continuity_and_total(variant, total):
    inp = _inp()
    rows = rebate_accrual_walk(
        list(inp.committed_quarterly), list(inp.rebate_tiers), inp.base_asp, variant, inp.qpy,
    )
    for q in range(len(rows) - 1):
        assert rows[q].ending == pytest.approx(rows[q + 1].beginning, abs=1e-6)
    assert sum(r.accrual_expense for r in rows) == pytest.approx(total, abs=1.0)
    assert rows[0].beginning == 0.0


def test_prepayment_continuity_and_reconciliation():
    inp = _inp()
    invoices = [u * inp.base_asp for u in inp.committed_quarterly]
    rows = prepayment_schedule(invoices)
    for q in range(len(rows) - 1):
        assert rows[q].ending == pytest.approx(rows[q + 1].beginning, abs=1e-6)
    assert rows[0].beginning == pytest.approx(500_000_000.0, abs=1.0)
    assert rows[-1].ending == pytest.approx(0.0, abs=1.0)
