"""Accounting schedules — the handoff that makes Accounting trust the tool.

Three formula-driven roll-forwards, each a pure function returning per-quarter
rows with a `beginning → movement → ending` structure and the continuity
invariant `ending[q] == beginning[q+1]`:

  - `rebate_accrual_walk` — variable-consideration accrual (ASC 606): accrue the
    rebate attributable to each quarter's units, settle annually in arrears.
  - `prepayment_schedule` — contract-liability roll-forward: the prepayment is
    drawn down against each invoice until exhausted.
  - `peak_receivables` — maximum accounts-receivable balance implied by the
    billing ramp and the payment terms (DSO), and the quarter it occurs.

These feed the UI Accounting Schedules section and the Excel tab (Phase 7).

Simplifications (documented for the README): the rebate accrual settles in the
first quarter of the following Year (annual-in-arrears, 45-day window); the final
Year's accrued balance settles 45 days after term end and therefore remains as
the closing balance of the modeled window rather than being paid within it.
"""

from __future__ import annotations

from dataclasses import dataclass

from deal_copilot.driver_mapper import Retroactivity, compute_rebate_schedule


# ---------------------------------------------------------------------------
# Rebate accrual walk
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AccrualRow:
    quarter_index: int
    beginning: float
    accrual_expense: float
    settlement_payment: float
    ending: float


def rebate_accrual_walk(
    quarterly_units: list[float],
    tiers: list[tuple[float, float]],
    asp: float,
    retroactivity: Retroactivity,
    qpy: int,
) -> list[AccrualRow]:
    """Quarterly rebate accrual roll-forward for the chosen reading.

    Accrual expense each quarter is the rebate attributable to that quarter's
    units (the variant's per-quarter schedule). The accrued balance for a
    completed Year is settled in the first quarter of the next Year. The final
    Year settles after term end, so its accrual remains as the closing balance.
    `ending[q] == beginning[q+1]` by construction.
    """
    accruals = compute_rebate_schedule(tiers, quarterly_units, asp, retroactivity, qpy)
    n = len(quarterly_units)

    # Year-end quarter index -> accrued balance for that Year, settled the
    # following quarter (year_end + 1).
    settlement_at: dict[int, float] = {}
    for y0 in range(0, n, qpy):
        y1 = min(y0 + qpy, n)
        year_accrued = sum(accruals[y0:y1])
        settle_q = y1  # first quarter of the next Year
        if settle_q < n:
            settlement_at[settle_q] = settlement_at.get(settle_q, 0.0) + year_accrued

    rows: list[AccrualRow] = []
    balance = 0.0
    for q in range(n):
        beginning = balance
        accrual = accruals[q]
        settlement = settlement_at.get(q, 0.0)
        ending = beginning + accrual - settlement
        rows.append(AccrualRow(
            quarter_index=q,
            beginning=beginning,
            accrual_expense=accrual,
            settlement_payment=settlement,
            ending=ending,
        ))
        balance = ending
    return rows


# ---------------------------------------------------------------------------
# Prepayment (contract liability) schedule
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PrepaymentRow:
    quarter_index: int
    beginning: float
    drawdown: float
    ending: float


def prepayment_schedule(
    invoices: list[float],
    amount_usd: float = 500_000_000.0,
    drawdown_pct: float = 0.20,
) -> list[PrepaymentRow]:
    """Contract-liability roll-forward: the prepayment is drawn down by
    `drawdown_pct` of each quarter's invoice until exhausted. `ending[q] ==
    beginning[q+1]`; the balance reaches 0 once cumulative invoices reach
    `amount_usd / drawdown_pct` and stays there.
    """
    rows: list[PrepaymentRow] = []
    balance = amount_usd
    for q, invoice in enumerate(invoices):
        beginning = balance
        drawdown = min(drawdown_pct * invoice, beginning)
        ending = beginning - drawdown
        rows.append(PrepaymentRow(
            quarter_index=q, beginning=beginning, drawdown=drawdown, ending=ending,
        ))
        balance = ending
    return rows


# ---------------------------------------------------------------------------
# Peak receivables exposure
# ---------------------------------------------------------------------------


def _dso_lag_quarters(dso_days: int) -> int:
    """Collection lag in whole quarters (≈91.25 days/quarter), at least 1 when
    any credit is extended."""
    lag = int(round(dso_days / 91.25))
    return max(lag, 1) if dso_days > 0 else 0


def peak_receivables(
    quarterly_billings: list[float], dso_days: int
) -> tuple[float, int]:
    """Maximum accounts-receivable balance implied by the billing ramp and DSO,
    and the quarter index at which it occurs.

    AR at the end of quarter q is the sum of billings still within the DSO
    collection window (the trailing `lag` quarters, including q). Returns
    `(peak_usd, quarter_index)`; `(0.0, -1)` if there are no billings.
    """
    if not quarterly_billings:
        return 0.0, -1
    lag = _dso_lag_quarters(dso_days)
    if lag == 0:
        return 0.0, -1
    peak = 0.0
    peak_q = -1
    for q in range(len(quarterly_billings)):
        ar = sum(quarterly_billings[max(0, q - lag + 1): q + 1])
        if ar > peak:
            peak, peak_q = ar, q
    return peak, peak_q


__all__ = [
    "AccrualRow",
    "rebate_accrual_walk",
    "PrepaymentRow",
    "prepayment_schedule",
    "peak_receivables",
]
