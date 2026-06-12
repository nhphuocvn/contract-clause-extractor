"""Smoke test: run the Phase 4 warrant economics on the synthetic deal and
pretty-print the results. No LLM call. Eyeball against the hand numbers in
tests/test_warrant_economics.py. ASCII only (Windows cp1252 console).

Run with:
    python -m deal_copilot._smoke.compute_warrant_economics
"""

from __future__ import annotations

from deal_copilot.economics_engine import compute_economics
from deal_copilot.schemas import ScenarioName, ViewMode
from deal_copilot.warrant_economics import compute_warrant_economics
from tests.fixtures import synthetic_package_with_warrant, warrant_assumptions


def _b(x: float) -> str:
    return f"${x/1e9:,.3f}B"


def _m(x: float) -> str:
    return f"${x/1e6:,.1f}M"


def main() -> int:
    pkg = synthetic_package_with_warrant()
    a = warrant_assumptions()
    w = compute_warrant_economics(pkg, a)

    print("=== Warrant economics:", pkg.deal_name, "===")
    print(f"  measurement price ${w.measurement_price_usd:,.2f}  (JUDGMENT - confirm with deal team)")
    print(f"  mode: {w.valuation_mode}")

    print("\n--- Tranche valuations (contract facts | JUDGMENT vest prob) ---")
    print(f"  {'T':>2s} {'shares':>10s} {'hurdle':>7s} {'milestone':>10s} {'vestP':>6s} {'expected FV':>14s}")
    for v in w.tranche_valuations:
        hurdle = f"${v.stock_price_hurdle_usd:.0f}" if v.stock_price_hurdle_usd else "-"
        print(f"  {v.tranche_index+1:>2d} {v.share_count:>10,} {hurdle:>7s} "
              f"{v.deployment_milestone_units:>10,} {v.vest_probability:>6.2f} {_m(v.expected_fair_value_usd):>14s}")
    print(f"  total expected warrant value: {_b(w.total_expected_fair_value_usd)}")

    print("\n--- Expected-value RANGE (judgment -> show a range, not a point) ---")
    for s in w.expected_value_range:
        print(f"  {s.label:13s} {s.probabilities}  -> {_b(s.total_expected_fair_value_usd)}")

    print("\n--- Effective ASP waterfall ---")
    e = w.effective_asp
    print(f"  sticker ${e.sticker_usd:,.0f} - rebate ${e.rebate_per_unit_usd:,.0f}/u "
          f"- warrant ${e.warrant_per_unit_usd:,.0f}/u = all-in ${e.all_in_usd:,.2f}")

    print("\n--- GAAP vs cash bridge ---")
    print(f"  cash/commercial net revenue: {_m(w.cash_net_revenue_usd)}")
    print(f"  warrant contra (consideration to customer): {_m(w.warrant_contra_bridge_usd)}")
    print(f"  GAAP net revenue:            {_m(w.gaap_net_revenue_usd)}")

    if w.dilution_pct_of_shares_outstanding is not None:
        print(f"\n--- Dilution ---\n  {w.dilution_pct_of_shares_outstanding*100:.4f}% of shares outstanding")

    print("\n--- Asymmetry (value transferred at three price levels) ---")
    for lv in w.value_at_price_levels:
        print(f"  @ ${lv.stock_price_usd:>6,.0f}  ->  {_b(lv.total_intrinsic_value_usd)}")
    print(f"  {w.asymmetry_note}")

    print("\n--- Engine wiring check (contra now flows into GAAP scenarios) ---")
    econ = compute_economics(pkg, a)
    gaap = next(r for r in econ.scenarios if r.scenario == ScenarioName.BASE and r.view == ViewMode.GAAP)
    cash = next(r for r in econ.scenarios if r.scenario == ScenarioName.BASE and r.view == ViewMode.CASH_COMMERCIAL)
    print(f"  BASE GAAP net revenue {_m(gaap.total_net_revenue)}  vs  CASH net revenue {_m(cash.total_net_revenue)}")
    print(f"  effective ASP warrant/unit ${econ.effective_asp.warrant_per_unit_usd:,.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
