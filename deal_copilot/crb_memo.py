"""CRB memo (§9.2) — the one-page Contract Review Board memo.

`build_crb_memo` is a PURE assembler: every number is injected from engine /
policy / benchmark / gap-report output. It never computes a figure itself and
never calls an LLM. `render_crb_memo_markdown` renders the structured payload to
deterministic markdown — the graceful-degradation path when no LLM is available
(KICKOFF §8). In production an LLM rewrites this prose from the same payload,
but the numbers shown are exactly the ones the deterministic renderer prints, so
the LLM can add no number of its own.

The warrant section MUST carry the §4 correlation caveat: valuing the warrant
with a single spot price and independent per-tranche vest probabilities likely
understates upside-scenario warrant cost, because deployment milestones and
stock-price hurdles are positively correlated.
"""

from __future__ import annotations

from deal_copilot import driver_mapper as dm
from deal_copilot.schemas import (
    BenchmarkComparison,
    CRBMemo,
    DealEconomics,
    DealPackage,
    PolicyOutcome,
    PolicyVerdict,
    RiskItem,
    ScenarioName,
    TermType,
    ViewMode,
    WarrantEconomics,
    AssumptionGapLine,
)

CORRELATION_CAVEAT = (
    "Correlation caveat: this valuation uses a single spot price and independent "
    "per-tranche vest probabilities — a deliberate simplification. In reality, "
    "deployment milestones and stock-price hurdles are positively correlated "
    "(deal success lifts the stock, making the later, higher hurdles more likely "
    "to clear just as the deployment milestones are hit), so the model likely "
    "UNDERSTATES warrant cost in the upside scenario."
)


def _scenario(econ: DealEconomics, scenario: ScenarioName, view: ViewMode):
    for s in econ.scenarios:
        if s.scenario == scenario and s.view == view:
            return s
    return None


def _money(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"${x / 1e6:,.1f}M"


def _economics_table(econ: DealEconomics) -> list[dict]:
    rows: list[dict] = []
    for scenario in ScenarioName:
        for view in ViewMode:
            s = _scenario(econ, scenario, view)
            if s is None:
                continue
            rows.append({
                "scenario": scenario.value,
                "view": view.value,
                "net_revenue": _money(s.total_net_revenue),
                "gross_margin": _money(s.total_gross_margin),
                "gross_margin_pct": f"{s.total_gross_margin_pct * 100:.1f}%",
                "npv": _money(s.npv_usd),
                "payback_quarters": s.payback_quarters_ex_prepayment,
                "peak_wc_draw": _money(s.peak_working_capital_draw_usd),
            })
    return rows


def _summary_lines(pkg: DealPackage, econ: DealEconomics) -> list[str]:
    base = _scenario(econ, ScenarioName.BASE, ViewMode.CASH_COMMERCIAL)
    committed = sum(r.gross_revenue for r in base.quarterly_pl) if base else None
    has_warrant = pkg.warrant_terms is not None or dm._first(pkg, TermType.WARRANT_EQUITY) is not None
    structure = "purchase agreement with volume rebate, take-or-pay floor, customer prepayment"
    if has_warrant:
        structure += ", and a customer warrant (equity component)"
    return [
        f"Counterparty: {pkg.counterparty or 'n/a'}.",
        f"Committed value {_money(committed)} over the contract term at "
        f"{base.total_gross_margin_pct * 100:.1f}% blended gross margin (cash view)."
        if base else "Economics unavailable.",
        f"Structure: {structure}.",
    ]


def _top_risks(
    pkg: DealPackage,
    econ: DealEconomics,
    warrant_econ: WarrantEconomics | None,
    gap_lines: list[AssumptionGapLine],
    margin_floor_pct: float,
) -> list[RiskItem]:
    risks: list[RiskItem] = []
    base_cash = _scenario(econ, ScenarioName.BASE, ViewMode.CASH_COMMERCIAL)

    # Warrant dilution / cost
    if warrant_econ is not None:
        risks.append(RiskItem(
            description=(
                f"Warrant (equity to customer) expected cost "
                f"{_money(warrant_econ.total_expected_fair_value_usd)} (contra-revenue); "
                f"dilution "
                f"{warrant_econ.dilution_pct_of_shares_outstanding * 100:.3f}%"
                if warrant_econ.dilution_pct_of_shares_outstanding is not None else
                f"Warrant expected cost {_money(warrant_econ.total_expected_fair_value_usd)}"
            ),
            quantified_exposure_usd=warrant_econ.total_expected_fair_value_usd,
            mitigation="Approve equity component; confirm vest probabilities with deal team. " + CORRELATION_CAVEAT,
        ))
    elif dm._first(pkg, TermType.WARRANT_EQUITY) is not None:
        risks.append(RiskItem(
            description="Customer warrant (equity component) present; value not yet resolved (warrant document not attached).",
            quantified_exposure_usd=None,
            mitigation="Attach the warrant agreement and value the contra-revenue before approval.",
        ))

    # Margin below floor
    if base_cash is not None and base_cash.total_gross_margin_pct < margin_floor_pct:
        gap = (margin_floor_pct - base_cash.total_gross_margin_pct) * base_cash.total_net_revenue
        risks.append(RiskItem(
            description=(
                f"Blended gross margin {base_cash.total_gross_margin_pct * 100:.1f}% is below the "
                f"{margin_floor_pct * 100:.0f}% policy floor."
            ),
            quantified_exposure_usd=gap,
            mitigation="Renegotiate price/COGS or obtain CFO approval for the margin exception.",
        ))

    # Working-capital draw
    if base_cash is not None and base_cash.peak_working_capital_draw_usd < 0:
        risks.append(RiskItem(
            description=(
                f"Peak operating working-capital draw {_money(base_cash.peak_working_capital_draw_usd)} "
                f"(inventory build + collection lag); operational payback Q{base_cash.payback_quarters_ex_prepayment}."
            ),
            quantified_exposure_usd=abs(base_cash.peak_working_capital_draw_usd),
            mitigation="Fund the inventory build; confirm DPO and inventory lead with Procurement/Operations.",
        ))

    # Rebate ambiguity (from the gap report)
    rebate_gap = next((g for g in gap_lines if g.owner == "Legal"), None)
    if rebate_gap is not None:
        risks.append(RiskItem(
            description=f"Rebate tier-crossing retroactivity unresolved; exposure {_money(rebate_gap.dollar_sensitivity_usd)}.",
            quantified_exposure_usd=rebate_gap.dollar_sensitivity_usd,
            mitigation="Resolve §5 retroactivity with Legal before signature.",
        ))

    # MFN
    if dm._first(pkg, TermType.PRICE_PROTECTION_MFN) is not None:
        risks.append(RiskItem(
            description="Most-favored-nation clause present — repricing exposure if a lower-priced comparable-volume deal is signed.",
            quantified_exposure_usd=None,
            mitigation="Run the cross-deal MFN check before pricing any comparable-volume deal.",
        ))

    # Rank by quantified exposure desc; unquantified last. Top 5.
    risks.sort(key=lambda r: (r.quantified_exposure_usd is not None, r.quantified_exposure_usd or 0.0), reverse=True)
    return risks[:5]


def _recommendation(verdict: PolicyVerdict | None) -> tuple[str, list[str]]:
    if verdict is None:
        return "Proceed to approval (no policy verdict supplied).", []
    conditions = [f"Requires sign-off: {a}." for a in verdict.all_required_approvers]
    if verdict.overall_outcome == PolicyOutcome.BLOCK:
        rec = "BLOCK — the deal violates a hard policy rule and cannot proceed as drafted."
    elif verdict.overall_outcome == PolicyOutcome.ESCALATE:
        rec = (
            "ESCALATE — approve subject to the conditions below and the listed "
            f"approvers ({', '.join(verdict.all_required_approvers) or 'none'})."
        )
    else:
        rec = "PASS — within policy; recommend approval."
    return rec, conditions


def build_crb_memo(
    pkg: DealPackage,
    econ: DealEconomics,
    *,
    policy_verdict: PolicyVerdict | None = None,
    benchmark_comparisons: list[BenchmarkComparison] | None = None,
    gap_lines: list[AssumptionGapLine] | None = None,
    warrant_econ: WarrantEconomics | None = None,
    margin_floor_pct: float = 0.45,
) -> CRBMemo:
    """Assemble the structured CRB memo. Pure — all numbers injected."""
    gap_lines = gap_lines or []
    benchmark_comparisons = benchmark_comparisons or []

    risks = _top_risks(pkg, econ, warrant_econ, gap_lines, margin_floor_pct)
    recommendation, conditions = _recommendation(policy_verdict)
    # Fold the highest-value gap resolutions into approval conditions.
    for g in gap_lines[:3]:
        conditions.append(f"Confirm: {g.question}")

    has_warrant_component = warrant_econ is not None or dm._first(pkg, TermType.WARRANT_EQUITY) is not None
    if has_warrant_component:
        if warrant_econ is not None:
            warrant_section = (
                f"Warrant expected cost {_money(warrant_econ.total_expected_fair_value_usd)} "
                f"(contra-revenue under ASC 606, measured under ASC 718); effective net ASP "
                f"${warrant_econ.effective_asp.all_in_usd:,.2f}. " + CORRELATION_CAVEAT
            )
        else:
            warrant_section = (
                "Customer warrant (equity component) present; value pending the warrant "
                "agreement. " + CORRELATION_CAVEAT
            )
    else:
        warrant_section = ""

    return CRBMemo(
        deal_name=pkg.deal_name,
        summary_lines=_summary_lines(pkg, econ),
        economics_table=_economics_table(econ),
        effective_asp=econ.effective_asp,
        top_risks=risks,
        benchmark_sentences=[c.verdict_sentence for c in benchmark_comparisons],
        warrant_section=warrant_section,
        policy_verdict=policy_verdict,
        gap_report_lines=gap_lines,
        recommendation=recommendation,
        approval_conditions=conditions,
    )


def render_crb_memo_markdown(memo: CRBMemo) -> str:
    """Deterministic markdown render of the memo payload (LLM-free fallback)."""
    lines: list[str] = [f"# CRB Memo — {memo.deal_name}", ""]
    lines += [f"- {s}" for s in memo.summary_lines] + [""]

    lines.append("## Economics by scenario")
    lines.append("| Scenario | View | Net rev | Gross margin | GM% | NPV | Payback | Peak WC draw |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in memo.economics_table:
        pb = "-" if r["payback_quarters"] is None else f"Q{r['payback_quarters']}"
        lines.append(
            f"| {r['scenario']} | {r['view']} | {r['net_revenue']} | {r['gross_margin']} | "
            f"{r['gross_margin_pct']} | {r['npv']} | {pb} | {r['peak_wc_draw']} |"
        )
    lines.append("")

    ea = memo.effective_asp
    lines += [
        "## Effective net ASP",
        f"Sticker ${ea.sticker_usd:,.0f} - rebate ${ea.rebate_per_unit_usd:,.2f} - "
        f"warrant ${ea.warrant_per_unit_usd:,.2f} = **${ea.all_in_usd:,.2f}** all-in.", "",
    ]

    lines.append("## Top risks")
    for i, risk in enumerate(memo.top_risks, 1):
        exp = "" if risk.quantified_exposure_usd is None else f" (exposure {_money(risk.quantified_exposure_usd)})"
        lines.append(f"{i}. {risk.description}{exp} — *{risk.mitigation}*")
    lines.append("")

    if memo.benchmark_sentences:
        lines.append("## Benchmarks")
        lines += [f"- {s}" for s in memo.benchmark_sentences] + [""]

    if memo.warrant_section:
        lines += ["## Warrant", memo.warrant_section, ""]

    if memo.gap_report_lines:
        lines.append("## Assumption gaps")
        for g in memo.gap_report_lines:
            s = "" if g.dollar_sensitivity_usd is None else f" [{_money(g.dollar_sensitivity_usd)}]"
            lines.append(f"- ({g.owner}){s} {g.question}")
        lines.append("")

    if memo.policy_verdict is not None:
        v = memo.policy_verdict
        lines += [
            "## Policy verdict",
            f"**{v.overall_outcome.value}** — approvers: {', '.join(v.all_required_approvers) or 'none'}",
            "",
        ]

    lines += ["## Recommendation", memo.recommendation, ""]
    if memo.approval_conditions:
        lines.append("### Approval conditions")
        lines += [f"- {c}" for c in memo.approval_conditions]

    return "\n".join(lines)


__all__ = ["CORRELATION_CAVEAT", "build_crb_memo", "render_crb_memo_markdown"]
