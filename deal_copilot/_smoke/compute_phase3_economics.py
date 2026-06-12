"""Smoke test: run the Phase 3 economics engine on the synthetic deal and
pretty-print the results. No LLM call — builds the package from the ground-truth
parameters directly. Eyeball the figures against the hand numbers in the
pytest suite.

Run with:
    python -m deal_copilot._smoke.compute_phase3_economics
"""

from __future__ import annotations

from datetime import datetime

from deal_copilot.accounting_schedules import (
    prepayment_schedule,
    rebate_accrual_walk,
    peak_receivables,
)
from deal_copilot.assumptions_library import build_default_assumptions, load_library
from deal_copilot.driver_mapper import rebate_variant_comparison
from deal_copilot.economics_engine import (
    compute_economics,
    extract_inputs,
    probability_weighted,
)
from deal_copilot.schemas import ScenarioName, TermType, ViewMode

# Reuse the test fixture's package builder (no LLM, deterministic).
from tests.fixtures import synthetic_package


def _m(x: float) -> str:
    return f"${x/1e6:,.1f}M"


def main() -> int:
    pkg = synthetic_package()
    assumptions, _prov = build_default_assumptions(load_library(), datetime(2026, 6, 11))
    inp = extract_inputs(pkg)

    print("=== Deal:", pkg.deal_name, "===")
    print(f"  committed units: {int(inp.total_committed_units):,}  base ASP: ${inp.base_asp:,.0f}  "
          f"qpy: {inp.qpy}  DSO: {inp.dso_days}d")

    econ = compute_economics(pkg, assumptions)

    print("\n--- Drivers ---")
    for d in econ.drivers:
        print(f"  {d.driver_type.value:28s} {d.driver_id}")

    print("\n--- Scenario economics (GAAP) ---")
    print("  payback shown both ways: [fin]=with customer prepayment financing  "
          "[dep]=deployment cash flows, ex-prepayment (operational)")
    print(f"  {'scenario':22s} {'net rev':>12s} {'gross margin':>14s} {'GM%':>7s} {'NPV':>12s} {'payback':>14s}")
    for r in econ.scenarios:
        if r.view != ViewMode.GAAP:
            continue
        fin = "-" if r.payback_quarters is None else f"Q{r.payback_quarters}"
        dep = "-" if r.payback_quarters_ex_prepayment is None else f"Q{r.payback_quarters_ex_prepayment}"
        pb = f"fin {fin} / dep {dep}"
        print(f"  {r.scenario.value:22s} {_m(r.total_net_revenue):>12s} {_m(r.total_gross_margin):>14s} "
              f"{r.total_gross_margin_pct*100:6.1f}% {_m(r.npv_usd):>12s} {pb:>14s}")

    print("\n--- Rebate ambiguity (the $41M question) ---")
    rb = next(t for t in pkg.terms if t.term_type == TermType.REBATE)
    cmp = rebate_variant_comparison(rb, list(inp.committed_quarterly), inp.base_asp, inp.qpy)
    print(f"  prospective (marginal):        {_m(cmp['prospective_total_usd'])}")
    print(f"  retroactive (within-year):     {_m(cmp['retroactive_total_usd'])}")
    print(f"  delta (resolve with Legal):    {_m(cmp['delta_usd'])}")

    print("\n--- Effective ASP waterfall ---")
    e = econ.effective_asp
    print(f"  sticker ${e.sticker_usd:,.0f} - rebate ${e.rebate_per_unit_usd:,.0f}/u "
          f"- warrant ${e.warrant_per_unit_usd:,.0f}/u = all-in ${e.all_in_usd:,.0f}")

    print("\n--- Probability-weighted expected value (equal weights) ---")
    pw = probability_weighted(econ.scenarios, assumptions)
    print(f"  expected NPV {_m(pw['expected_npv_usd'])}  "
          f"expected GM {_m(pw['expected_gross_margin_usd'])}  weights_valid={pw['weights_valid']}")

    print("\n--- Sensitivities (tornado, top 4) ---")
    for row in econ.sensitivities[:4]:
        print(f"  {row.variable:20s} {row.delta_label:>5s}  delta {_m(row.delta_vs_base_usd)}")

    print("\n--- Rebate accrual walk (prospective, $M) ---")
    walk = rebate_accrual_walk(list(inp.committed_quarterly), list(inp.rebate_tiers),
                               inp.base_asp, "prospective", inp.qpy)
    print(f"  {'Q':>2s} {'begin':>8s} {'accrue':>8s} {'settle':>8s} {'end':>8s}")
    for r in walk:
        print(f"  {r.quarter_index:>2d} {r.beginning/1e6:>8.2f} {r.accrual_expense/1e6:>8.2f} "
              f"{r.settlement_payment/1e6:>8.2f} {r.ending/1e6:>8.2f}")

    print("\n--- Prepayment (contract liability) schedule ($M) ---")
    invoices = [u * inp.base_asp for u in inp.committed_quarterly]
    pp = prepayment_schedule(invoices)
    for r in pp:
        print(f"  Q{r.quarter_index:>2d} begin {r.beginning/1e6:>7.1f}  draw {r.drawdown/1e6:>6.1f}  end {r.ending/1e6:>7.1f}")

    peak, peak_q = peak_receivables(invoices, inp.dso_days)
    print(f"\n  Peak receivables exposure: {_m(peak)} at Q{peak_q}")

    # Purity check: recompute and confirm identical output.
    again = compute_economics(pkg, assumptions)
    assert again.model_dump() == econ.model_dump(), "engine is not pure!"
    print("\nPurity check: recompute identical [OK]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
