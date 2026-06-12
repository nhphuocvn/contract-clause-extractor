"""Smoke test: build two deal versions, print the change journal and the
variance-bridge waterfall (which must sum to the total delta with a ~$0
residual). No LLM call. ASCII only (Windows cp1252 console).

Run with:
    python -m deal_copilot._smoke.compute_variance_bridge
"""

from __future__ import annotations

from datetime import datetime

from deal_copilot.schemas import AdHocDriver, TermType
from deal_copilot.variance_bridge import variance_bridge
from deal_copilot.versioning import build_change_journal, snapshot_version
from tests.fixtures import default_assumptions, synthetic_package


def _m(x: float) -> str:
    return f"${x/1e6:,.1f}M"


def main() -> int:
    base_pkg = synthetic_package()
    a = default_assumptions()

    # Version A: the initial deal.
    vA = snapshot_version(base_pkg, a, "Counterparty initial", datetime(2026, 6, 11))

    # Version B: our counter -- price cut, tier-2 rebate bump, and a marketing credit.
    pkgB = synthetic_package()
    next(t for t in pkgB.terms if t.term_type == TermType.PRICING).parameters["base_asp_usd"] = 23500
    rebate = next(t for t in pkgB.terms if t.term_type == TermType.REBATE)
    rebate.parameters["tiers"][1]["pct_off_base_asp"] = 0.06   # tier 2: 5% -> 6%
    pkgB.ad_hoc_drivers = [AdHocDriver(label="Launch marketing credit", amount_usd=-40_000_000.0)]
    aB = a.model_copy(update={"unit_cogs_usd": 14_500.0})       # cost-down
    vB = snapshot_version(pkgB, aB, "Our counter v1", datetime(2026, 6, 12))

    print("=== Change journal: '%s' -> '%s' ===" % (vA.name, vB.name))
    for e in build_change_journal(vA, vB, datetime(2026, 6, 12), actor="analyst@firm"):
        print(f"  {e.field_path:38s} {e.old_value} -> {e.new_value}")

    br = variance_bridge(vA, vB, base_pkg, metric="gross_margin")
    print(f"\n=== Variance bridge (gross margin, BASE / GAAP) ===")
    print(f"  {vA.name:24s} {_m(br.from_metric_usd):>12s}")
    for s in br.steps:
        print(f"    {s.label:48s} {_m(s.metric_delta_usd):>12s}")
    print(f"  {vB.name:24s} {_m(br.to_metric_usd):>12s}")
    print(f"  total delta: {_m(br.total_delta_usd)}   residual: ${br.residual_usd:,.2f}")

    check = sum(s.metric_delta_usd for s in br.steps)
    print(f"\n  steps sum to {_m(check)}  (== total delta: {abs(check - br.total_delta_usd) < 1.0})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
