"""Phase 6 live verification: policy verdict + benchmarks + assumption register
+ gap report + CRB memo against the synthetic deal. Run:

    python -m deal_copilot._smoke.compute_phase6_reports
"""

from __future__ import annotations

import sys
from datetime import datetime

# Print UTF-8 regardless of the console code page (Windows cp1252 chokes on §, —).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from deal_copilot import benchmarks as bm
from deal_copilot import economics_engine as ee
from deal_copilot import policy_engine as pe
from deal_copilot.assumption_gap_report import build_gap_report
from deal_copilot.assumption_register import build_register
from deal_copilot.crb_memo import build_crb_memo, render_crb_memo_markdown
from tests.fixtures import default_assumptions, synthetic_package

AS_OF = datetime(2026, 6, 11)


def main() -> int:
    pkg = synthetic_package()
    a = default_assumptions()
    econ = ee.compute_economics(pkg, a)

    print("=== Policy verdict ===")
    verdict = pe.evaluate_package(pkg, econ, pe.load_policy(), version_name="Initial", evaluated_at=AS_OF)
    for r in verdict.rule_results:
        appr = f" -> {', '.join(r.required_approvers)}" if r.required_approvers else ""
        print(f"  [{r.outcome.value:8s}] {r.rule_id:20s} {r.reason}{appr}")
    print(f"  OVERALL: {verdict.overall_outcome.value}; approvers: {', '.join(verdict.all_required_approvers)}")

    print("\n=== Benchmarks ===")
    comps = bm.compare_to_benchmarks(bm.deal_benchmark_metrics(pkg, econ), bm.load_benchmarks(), AS_OF)
    for c in comps:
        print(f"  {c.verdict_sentence}")

    print("\n=== Assumption register (type | owner) ===")
    for e in build_register(a, terms=pkg.terms):
        print(f"  {e.label:34s} {e.assumption_type.value:18s} {e.owner}")

    print("\n=== Assumption gap report (ranked) ===")
    gaps = build_gap_report(pkg, a, econ)
    for g in gaps:
        s = "  n/a  " if g.dollar_sensitivity_usd is None else f"${g.dollar_sensitivity_usd/1e6:>8,.1f}M"
        print(f"  {s} ({g.owner}) {g.question}")

    print("\n=== CRB memo (markdown) ===")
    memo = build_crb_memo(pkg, econ, policy_verdict=verdict, benchmark_comparisons=comps, gap_lines=gaps)
    print(render_crb_memo_markdown(memo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
