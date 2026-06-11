"""Smoke test: extract the Phase 1 deal, evaluate vs ground_truth.json,
print a structured report. Exits non-zero if acceptance thresholds aren't met.

Acceptance per Phase 2 plan:
  - overall precision >= 0.85
  - overall recall >= 0.85
  - rebate_ambiguity_quantified == True
  - cross_ref_warrant_detected == True
  - cross_ref_unresolved_fixture_passes == True

Run with:
    python -m deal_copilot._smoke.eval_against_ground_truth
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from deal_copilot.eval_harness import evaluate, evaluate_cross_ref_only_doc_a
from deal_copilot.intake import load_documents
from deal_copilot.term_extractor import extract_deal

ACCEPTANCE_THRESHOLD = 0.85

GT_PATH = Path("data/sample_contracts/ground_truth.json")
PURCHASE_AGREEMENT = Path("data/sample_contracts/gpu_purchase_agreement.pdf")
WARRANT = Path("data/sample_contracts/warrant_agreement.docx")


def main() -> int:
    load_dotenv()
    if os.environ.get("SKIP_LIVE_API"):
        print("SKIP_LIVE_API set — skipping.")
        return 0
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set; cannot run live eval.", file=sys.stderr)
        return 1

    client = OpenAI()

    # Pass 1: full package
    print("=== Pass 1: full package (purchase agreement + warrant) ===")
    loaded_full = load_documents([PURCHASE_AGREEMENT, WARRANT])
    extraction_full = extract_deal(
        client, loaded_full,
        deal_name="AMD-Meta MI355X (synthetic)",
        deal_id="DEAL-SYNTH-001",
        counterparty="Meta Platforms, Inc.",
    )
    print(f"  -> extracted {len(extraction_full.package.terms)} terms, "
          f"warrant={'yes' if extraction_full.package.warrant_terms else 'no'}")

    # Pass 2: only Doc A (the unresolved-cross-reference fixture)
    print("\n=== Pass 2: doc A only (unresolved cross-reference fixture) ===")
    loaded_a_only = load_documents([PURCHASE_AGREEMENT])
    extraction_a = extract_deal(
        client, loaded_a_only,
        deal_name="AMD-Meta MI355X (Doc A only)",
        deal_id="DEAL-SYNTH-001-A",
        counterparty="Meta Platforms, Inc.",
    )
    print(f"  -> unresolved_cross_references: {extraction_a.package.unresolved_cross_references}")

    # Evaluate
    print("\n=== Eval report ===")
    report = evaluate(extraction_full, GT_PATH)
    report.cross_ref_unresolved_fixture_passes = evaluate_cross_ref_only_doc_a(
        extraction_a, GT_PATH
    )

    print(f"\nOverall: precision={report.overall_precision:.3f}  "
          f"recall={report.overall_recall:.3f}  F1={report.overall_f1:.3f}  "
          f"(tp={report.overall_tp}, fp={report.overall_fp}, fn={report.overall_fn})")

    print("\nPer-term-type:")
    print(f"  {'term_type':24s} {'tp':>3s} {'fp':>3s} {'fn':>3s} "
          f"{'precision':>9s} {'recall':>7s} {'F1':>5s} {'param_acc_tp':>13s}")
    for m in report.per_type:
        print(f"  {m.term_type.value:24s} {m.tp:>3d} {m.fp:>3d} {m.fn:>3d} "
              f"{m.precision:>9.3f} {m.recall:>7.3f} {m.f1:>5.3f} {m.parameter_accurate_tp:>13d}")

    print(f"\nAmbiguity scorecard: tp={report.ambiguity_tp} fn={report.ambiguity_fn} "
          f"fp={report.ambiguity_fp}  rebate quantified={report.rebate_ambiguity_quantified}")

    print(f"\nCross-reference: warrant detected={report.cross_ref_warrant_detected}  "
          f"unresolved-only-Doc-A fixture passes={report.cross_ref_unresolved_fixture_passes}")

    # Diff drill-down for any non-matched / parameter-imperfect terms
    print("\n--- Per-term verdicts ---")
    for v in report.term_verdicts:
        if v.outcome == "matched" and v.parameter_accuracy == "all_match":
            print(f"  OK  {v.term_type.value:24s} @ {v.source_document_stem}")
            continue
        line = f"  {v.outcome.upper():7s} {v.term_type.value:24s} @ {v.source_document_stem}"
        if v.outcome == "matched":
            line += f" — param: {v.parameter_accuracy} ({v.matched_keys}/{v.total_truth_keys})"
        print(line)
        for d in v.parameter_diffs[:3]:
            print(f"      .{d.key}: pred={d.predicted!r} expected={d.expected!r}  ({d.why})")
        if len(v.parameter_diffs) > 3:
            print(f"      ...{len(v.parameter_diffs) - 3} more diffs")

    # Acceptance check
    passes_acc = report.passes_acceptance(ACCEPTANCE_THRESHOLD)
    passes_cross = report.cross_ref_unresolved_fixture_passes is True
    print(f"\n{'='*60}\nAcceptance:")
    print(f"  precision >= {ACCEPTANCE_THRESHOLD}: {report.overall_precision >= ACCEPTANCE_THRESHOLD} ({report.overall_precision:.3f})")
    print(f"  recall >= {ACCEPTANCE_THRESHOLD}: {report.overall_recall >= ACCEPTANCE_THRESHOLD} ({report.overall_recall:.3f})")
    print(f"  rebate_ambiguity_quantified: {report.rebate_ambiguity_quantified}")
    print(f"  cross_ref_warrant_detected: {report.cross_ref_warrant_detected}")
    print(f"  cross_ref_unresolved_fixture_passes: {report.cross_ref_unresolved_fixture_passes}")

    if passes_acc and passes_cross:
        print("\nPASS")
        return 0
    print("\nFAIL — acceptance thresholds not met")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
