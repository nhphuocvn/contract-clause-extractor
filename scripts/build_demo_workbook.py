"""Build the demo deal-model workbook (`deal_model_demo.xlsx`).

Wires the full pipeline on the warrant-bearing AMD–Meta synthetic deal — with the
REAL contract clause text attached (see deal_copilot.demo_deal) — and writes the
14-tab, fully-live, self-documenting workbook.

    python scripts/build_demo_workbook.py [output.xlsx]
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deal_copilot import benchmarks as bm
from deal_copilot import economics_engine as ee
from deal_copilot import policy_engine as pe
from deal_copilot.assumption_gap_report import build_gap_report
from deal_copilot.assumption_register import build_register
from deal_copilot.assumptions_library import build_default_assumptions, load_library
from deal_copilot.crb_memo import build_crb_memo
from deal_copilot.demo_deal import demo_package_with_clauses
from deal_copilot.excel_export import build_workbook
from deal_copilot.warrant_economics import compute_warrant_economics

AS_OF = datetime(2026, 6, 13)


def build(output: Path) -> Path:
    pkg = demo_package_with_clauses()
    assumptions, _ = build_default_assumptions(load_library(), AS_OF)
    # AMD spot $470 + the base vest-probability set (matches the warrant tranches).
    assumptions = assumptions.model_copy(update={
        "current_stock_price_usd": 470.0,
        "tranche_vest_probabilities": [0.9, 0.7, 0.5, 0.3],
    })

    econ = ee.compute_economics(pkg, assumptions)
    warrant = compute_warrant_economics(pkg, assumptions)
    register = build_register(assumptions, terms=pkg.terms, warrant_terms=pkg.warrant_terms)
    verdict = pe.evaluate_package(pkg, econ, pe.load_policy(),
                                  version_name="Initial", evaluated_at=AS_OF)
    comps = bm.compare_to_benchmarks(bm.deal_benchmark_metrics(pkg, econ),
                                     bm.load_benchmarks(), AS_OF)
    gaps = build_gap_report(pkg, assumptions, econ)
    memo = build_crb_memo(pkg, econ, policy_verdict=verdict,
                          benchmark_comparisons=comps, gap_lines=gaps, warrant_econ=warrant)

    wb = build_workbook(pkg, assumptions, econ, warrant, register, memo=memo,
                        as_of=AS_OF.strftime("%Y-%m-%d"))
    wb.save(output)
    return output


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("deal_model_demo.xlsx")
    path = build(output.resolve())
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
