"""Policy engine / approval routing (§9.5) — the Contract Review Board encoded.

`load_policy` is the only I/O (cached per path). `policy_signals` extracts the
policy-relevant facts from a deal package + its economics; `evaluate_policy` is
a pure function of (signals, rules) → PolicyVerdict. Each PolicyRuleKind has its
own small evaluator returning a PolicyRuleResult; the overall outcome is the
worst (BLOCK > ESCALATE > PASS) and the approver list is the order-preserving
union over escalating/blocking rules.

Design decision: the MARGIN_FLOOR rule tests the CASH / commercial blended gross
margin, not the GAAP view. The warrant's contra-revenue is enormous and is
handled by its own WARRANT_PRESENT rule and the memo's warrant section, so it is
never double-counted into the margin floor.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from deal_copilot import driver_mapper as dm
from deal_copilot.schemas import (
    DealEconomics,
    DealPackage,
    PolicyOutcome,
    PolicyRule,
    PolicyRuleKind,
    PolicyRuleResult,
    PolicyVerdict,
    ScenarioName,
    TermType,
    ViewMode,
)

DEFAULT_POLICY_PATH = Path("data/crb_policy.json")

_SEVERITY = {PolicyOutcome.PASS: 0, PolicyOutcome.ESCALATE: 1, PolicyOutcome.BLOCK: 2}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_policy(path: str | Path = DEFAULT_POLICY_PATH) -> list[PolicyRule]:
    """Read the CRB rule set. Returns `[]` if the file is absent (deterministic
    degradation — no rules means an all-PASS verdict, surfaced as such)."""
    resolved = str(Path(path).resolve())
    try:
        raw = _load_cached(resolved)
    except FileNotFoundError:
        return []
    return [PolicyRule(**r) for r in raw]


@lru_cache(maxsize=8)
def _load_cached(resolved_path: str) -> tuple[dict, ...]:
    with open(resolved_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return tuple(data.get("rules", []))


# ---------------------------------------------------------------------------
# Signals (pure extraction)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicySignals:
    """The policy-relevant facts about one deal version."""
    blended_gross_margin_pct: float | None
    committed_value_usd: float | None
    has_mfn: bool
    has_warrant: bool
    payment_net_days: int | None
    take_or_pay_pct: float | None
    liability_uncapped: bool


def _base_cash(econ: DealEconomics):
    for s in econ.scenarios:
        if s.scenario == ScenarioName.BASE and s.view == ViewMode.CASH_COMMERCIAL:
            return s
    return None


def policy_signals(pkg: DealPackage, econ: DealEconomics) -> PolicySignals:
    """Extract policy signals from a package and its economics. Pure."""
    base = _base_cash(econ)
    margin = base.total_gross_margin_pct if base is not None else None
    committed = sum(r.gross_revenue for r in base.quarterly_pl) if base is not None else None

    has_mfn = dm._first(pkg, TermType.PRICE_PROTECTION_MFN) is not None
    has_warrant = pkg.warrant_terms is not None or dm._first(pkg, TermType.WARRANT_EQUITY) is not None

    pt = dm._first(pkg, TermType.PAYMENT_TERMS)
    net_days = pt.parameters.get("net_days") if pt is not None else None
    payment_net_days = int(net_days) if isinstance(net_days, (int, float)) else None

    top = dm._first(pkg, TermType.TAKE_OR_PAY)
    floor = top.parameters.get("annual_minimum_pct_of_committed") if top is not None else None
    take_or_pay_pct = float(floor) if isinstance(floor, (int, float)) else None

    liab = dm._first(pkg, TermType.LIABILITY)
    if liab is not None:
        p = liab.parameters
        liability_uncapped = bool(p.get("ip_indemnification_uncapped")) or (
            p.get("cap_months_of_fees") in (None, 0) and not p.get("cap_basis")
        )
    else:
        liability_uncapped = False

    return PolicySignals(
        blended_gross_margin_pct=margin,
        committed_value_usd=committed,
        has_mfn=has_mfn,
        has_warrant=has_warrant,
        payment_net_days=payment_net_days,
        take_or_pay_pct=take_or_pay_pct,
        liability_uncapped=liability_uncapped,
    )


# ---------------------------------------------------------------------------
# Per-rule evaluators (pure)
# ---------------------------------------------------------------------------


def _result(rule: PolicyRule, outcome: PolicyOutcome, reason: str) -> PolicyRuleResult:
    approvers = list(rule.required_approvers_on_breach) if outcome != PolicyOutcome.PASS else []
    return PolicyRuleResult(rule_id=rule.rule_id, outcome=outcome, reason=reason, required_approvers=approvers)


def _eval_margin_floor(rule: PolicyRule, s: PolicySignals) -> PolicyRuleResult:
    threshold = float(rule.parameters.get("threshold_pct", 0.45))
    m = s.blended_gross_margin_pct
    if m is None:
        return _result(rule, PolicyOutcome.ESCALATE, "blended margin unavailable — cannot confirm floor")
    if m < threshold:
        return _result(rule, PolicyOutcome.ESCALATE,
                       f"blended margin {m * 100:.1f}% below {threshold * 100:.0f}% floor")
    return _result(rule, PolicyOutcome.PASS, f"blended margin {m * 100:.1f}% meets {threshold * 100:.0f}% floor")


def _eval_deal_size_tier(rule: PolicyRule, s: PolicySignals) -> PolicyRuleResult:
    tiers = rule.parameters.get("tiers", [])
    value = s.committed_value_usd
    if value is None:
        return _result(rule, PolicyOutcome.ESCALATE, "committed value unavailable — cannot route tier")
    for tier in tiers:
        max_usd = tier.get("max_usd")
        if max_usd is None or value <= float(max_usd):
            approvers = list(tier.get("approvers", []))
            reason = f"committed value ${value / 1e9:,.2f}B routes to {', '.join(approvers) or 'no'} approval"
            # Tier routing always requires its named approver(s).
            r = PolicyRuleResult(rule_id=rule.rule_id, outcome=PolicyOutcome.ESCALATE,
                                 reason=reason, required_approvers=approvers)
            return r
    return _result(rule, PolicyOutcome.PASS, "no matching deal-size tier")


def _eval_flag(rule: PolicyRule, present: bool, breach_reason: str, ok_reason: str) -> PolicyRuleResult:
    if present:
        return _result(rule, PolicyOutcome.ESCALATE, breach_reason)
    return _result(rule, PolicyOutcome.PASS, ok_reason)


def _eval_payment_terms(rule: PolicyRule, s: PolicySignals) -> PolicyRuleResult:
    max_days = int(rule.parameters.get("max_net_days", 60))
    if s.payment_net_days is None:
        return _result(rule, PolicyOutcome.PASS, "payment terms not specified")
    if s.payment_net_days > max_days:
        return _result(rule, PolicyOutcome.ESCALATE,
                       f"payment terms net-{s.payment_net_days} beyond net-{max_days} limit")
    return _result(rule, PolicyOutcome.PASS, f"payment terms net-{s.payment_net_days} within net-{max_days}")


def _eval_take_or_pay_floor(rule: PolicyRule, s: PolicySignals) -> PolicyRuleResult:
    min_pct = float(rule.parameters.get("min_pct", 0.70))
    if s.take_or_pay_pct is None:
        return _result(rule, PolicyOutcome.ESCALATE, "no take-or-pay floor — revenue unprotected")
    if s.take_or_pay_pct < min_pct:
        return _result(rule, PolicyOutcome.ESCALATE,
                       f"take-or-pay {s.take_or_pay_pct * 100:.0f}% below {min_pct * 100:.0f}% floor")
    return _result(rule, PolicyOutcome.PASS,
                   f"take-or-pay {s.take_or_pay_pct * 100:.0f}% meets {min_pct * 100:.0f}% floor")


def _evaluate_rule(rule: PolicyRule, s: PolicySignals) -> PolicyRuleResult:
    k = rule.kind
    if k == PolicyRuleKind.MARGIN_FLOOR:
        return _eval_margin_floor(rule, s)
    if k == PolicyRuleKind.DEAL_SIZE_TIER:
        return _eval_deal_size_tier(rule, s)
    if k == PolicyRuleKind.UNCAPPED_LIABILITY:
        return _eval_flag(rule, s.liability_uncapped,
                          "uncapped liability exposure (e.g. uncapped IP indemnification)",
                          "liability fully capped")
    if k == PolicyRuleKind.MFN_PRESENT:
        return _eval_flag(rule, s.has_mfn, "most-favored-nation clause present", "no MFN clause")
    if k == PolicyRuleKind.WARRANT_PRESENT:
        return _eval_flag(rule, s.has_warrant, "equity/warrant component present", "no equity component")
    if k == PolicyRuleKind.PAYMENT_TERMS_THRESHOLD:
        return _eval_payment_terms(rule, s)
    if k == PolicyRuleKind.TAKE_OR_PAY_FLOOR:
        return _eval_take_or_pay_floor(rule, s)
    # CUSTOM / unknown: no-op pass (placeholder for future rule kinds).
    return _result(rule, PolicyOutcome.PASS, rule.description or "custom rule (no evaluator)")


# ---------------------------------------------------------------------------
# Verdict (pure)
# ---------------------------------------------------------------------------


def evaluate_policy(
    signals: PolicySignals,
    rules: list[PolicyRule],
    *,
    deal_id: str,
    version_name: str,
    evaluated_at: datetime,
) -> PolicyVerdict:
    """Evaluate every rule against the signals and aggregate into a verdict."""
    results = [_evaluate_rule(rule, signals) for rule in rules]

    overall = PolicyOutcome.PASS
    for r in results:
        if _SEVERITY[r.outcome] > _SEVERITY[overall]:
            overall = r.outcome

    approvers: list[str] = []
    for r in results:
        if r.outcome != PolicyOutcome.PASS:
            for a in r.required_approvers:
                if a not in approvers:
                    approvers.append(a)

    return PolicyVerdict(
        deal_id=deal_id,
        version_name=version_name,
        evaluated_at=evaluated_at,
        rule_results=results,
        overall_outcome=overall,
        all_required_approvers=approvers,
    )


def evaluate_package(
    pkg: DealPackage,
    econ: DealEconomics,
    rules: list[PolicyRule],
    *,
    version_name: str,
    evaluated_at: datetime,
) -> PolicyVerdict:
    """Convenience: build signals from a package + economics and evaluate."""
    signals = policy_signals(pkg, econ)
    return evaluate_policy(
        signals, rules, deal_id=pkg.deal_id, version_name=version_name, evaluated_at=evaluated_at,
    )


__all__ = [
    "DEFAULT_POLICY_PATH",
    "load_policy",
    "PolicySignals",
    "policy_signals",
    "evaluate_policy",
    "evaluate_package",
]
