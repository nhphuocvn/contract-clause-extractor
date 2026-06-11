"""Smoke test: extract the Phase 1 synthetic deal end-to-end and pretty-print
the result. No assertions; the eval_against_ground_truth script handles those.

Run with:
    python -m deal_copilot._smoke.extract_phase1_deal
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from deal_copilot.intake import load_documents
from deal_copilot.term_extractor import extract_deal

DOCS = [
    Path("data/sample_contracts/gpu_purchase_agreement.pdf"),
    Path("data/sample_contracts/warrant_agreement.docx"),
]


def main() -> int:
    load_dotenv()
    if os.environ.get("SKIP_LIVE_API"):
        print("SKIP_LIVE_API set — skipping.")
        return 0
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set; export it or add to .env. Skipping.", file=sys.stderr)
        return 1

    client = OpenAI()
    loaded = load_documents(DOCS)
    print(f"\n=== Loaded {len(loaded)} documents ===")
    for d in loaded:
        print(f"  {d.filename} ({d.document_type}, {len(d.text)} chars)")

    print("\n=== Running extract_deal ===")
    result = extract_deal(
        client, loaded,
        deal_name="AMD-Meta MI355X (synthetic)",
        deal_id="DEAL-SYNTH-001",
        counterparty="Meta Platforms, Inc.",
    )

    print("\n--- Extraction log ---")
    for line in result.extraction_log:
        print(line)

    pkg = result.package
    print(f"\n--- Package summary ---")
    print(f"  deal_name: {pkg.deal_name}")
    print(f"  deal_id: {pkg.deal_id}")
    print(f"  counterparty: {pkg.counterparty}")
    print(f"  status: {pkg.status.value}")
    print(f"  docs: {len(pkg.documents)}")
    print(f"  terms: {len(pkg.terms)}")
    print(f"  warrant_terms: {'yes' if pkg.warrant_terms else 'no'}")
    print(f"  unresolved_cross_references: {pkg.unresolved_cross_references}")

    print(f"\n--- Terms ({len(pkg.terms)}) ---")
    for t in pkg.terms:
        flag = " [AMBIGUOUS]" if t.ambiguity_flag else ""
        var = f" [{len(t.variants)} variants]" if t.variants else ""
        params_preview = str(t.parameters)[:120]
        print(f"  {t.term_type.value:24s} §{t.source_section:6s} conf={t.confidence:.2f}{flag}{var}")
        print(f"    params: {params_preview}{'...' if len(str(t.parameters)) > 120 else ''}")

    if pkg.warrant_terms:
        w = pkg.warrant_terms
        print(f"\n--- WarrantTerms ---")
        print(f"  total_shares: {w.total_shares:,}")
        print(f"  exercise_price_usd: ${w.exercise_price_usd}")
        print(f"  expiration_years: {w.expiration_years}")
        print(f"  tranches ({len(w.tranches)}):")
        for i, tr in enumerate(w.tranches, 1):
            hurdle = f"${tr.stock_price_hurdle_usd:.0f}" if tr.stock_price_hurdle_usd else "-"
            print(f"    {i}. {tr.share_count:>9,} shares @ {tr.deployment_milestone_units:>7,} units / hurdle {hurdle}")

    print(f"\n--- Validation ({len(result.validation_issues)} issues) ---")
    for issue in result.validation_issues:
        print(f"  [{issue.severity}] {issue.rule_id}: {issue.message[:90]}")

    print(f"\n--- Review queue ({len(result.review_queue)} items) ---")
    for r in result.review_queue:
        ttype = r.term_type.value if r.term_type else "—"
        print(f"  [{r.reason:18s}] {ttype:20s} {r.detail[:80]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
