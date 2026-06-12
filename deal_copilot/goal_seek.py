"""Goal-seek — solve for the input that hits a target metric.

"Tier-2 rebate moves to 6% — what base ASP holds gross margin at 45%?" The
economics engine is a pure function, and each supported knob moves the metric
monotonically, so a deterministic **bisection** converges without any calculus or
solver dependency. This is a thin layer over `compute_economics`; no AI, fully
reproducible.

Pure module: no I/O, inputs never mutated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from deal_copilot.economics_engine import compute_economics
from deal_copilot.schemas import (
    DealAssumptions,
    DealPackage,
    DealVersion,
    ScenarioName,
    TermType,
    VarianceMetric,
    ViewMode,
)
from deal_copilot.driver_mapper import Retroactivity

Knob = Literal["base_asp", "unit_cogs", "take_or_pay_pct", "prepayment_usd"]


@dataclass(frozen=True)
class GoalSeekResult:
    knob: str
    solved_value: float
    achieved_metric_usd: float
    target_value_usd: float
    iterations: int
    converged: bool


def _apply_knob(
    version: DealVersion, template: DealPackage, knob: Knob, value: float
) -> tuple[DealPackage, DealAssumptions]:
    """Build the (package, assumptions) for `version` with one knob set to `value`."""
    terms = [t.model_copy(deep=True) for t in version.terms]
    assumptions = version.assumptions.model_copy(deep=True)

    if knob == "unit_cogs":
        assumptions = assumptions.model_copy(update={"unit_cogs_usd": value})
    else:
        term_type, key = {
            "base_asp": (TermType.PRICING, "base_asp_usd"),
            "take_or_pay_pct": (TermType.TAKE_OR_PAY, "annual_minimum_pct_of_committed"),
            "prepayment_usd": (TermType.PREPAYMENT, "amount_usd"),
        }[knob]
        for t in terms:
            if t.term_type == term_type:
                params = dict(t.parameters)
                params[key] = value
                t.parameters.clear()
                t.parameters.update(params)

    pkg = template.model_copy(update={
        "terms": terms,
        "warrant_terms": version.warrant_terms.model_copy(deep=True) if version.warrant_terms else None,
        "ad_hoc_drivers": [d.model_copy(deep=True) for d in version.ad_hoc_drivers],
        "versions": [], "change_journal": [], "policy_verdicts": [],
    }, deep=True)
    return pkg, assumptions


def _metric(result, metric: VarianceMetric) -> float:
    return {
        "net_revenue": result.total_net_revenue,
        "gross_margin": result.total_gross_margin,
        "npv": result.npv_usd,
    }[metric]


def goal_seek(
    template_pkg: DealPackage,
    version: DealVersion,
    knob: Knob,
    target_metric: VarianceMetric,
    target_value_usd: float,
    lo: float,
    hi: float,
    scenario: ScenarioName = ScenarioName.BASE,
    view: ViewMode = ViewMode.GAAP,
    retroactivity: Retroactivity = "prospective",
    tol_usd: float = 1_000.0,
    max_iter: int = 60,
) -> GoalSeekResult:
    """Bisect `knob` in [lo, hi] to drive `target_metric` to `target_value_usd`.

    Assumes the metric is monotonic in the knob over the bracket (true for the
    supported knobs). Returns the solved knob value, the achieved metric, and
    whether it converged within `tol_usd`."""
    def evaluate(value: float) -> float:
        pkg, assumptions = _apply_knob(version, template_pkg, knob, value)
        econ = compute_economics(pkg, assumptions, retroactivity=retroactivity)
        result = next(r for r in econ.scenarios if r.scenario == scenario and r.view == view)
        return _metric(result, target_metric)

    f_lo = evaluate(lo) - target_value_usd
    f_hi = evaluate(hi) - target_value_usd
    if f_lo == 0:
        return GoalSeekResult(knob, lo, target_value_usd, target_value_usd, 0, True)
    if f_hi == 0:
        return GoalSeekResult(knob, hi, target_value_usd, target_value_usd, 0, True)
    if (f_lo > 0) == (f_hi > 0):
        # Target not bracketed; return the nearer endpoint, not converged.
        nearer = lo if abs(f_lo) < abs(f_hi) else hi
        return GoalSeekResult(knob, nearer, target_value_usd + (f_lo if nearer == lo else f_hi), target_value_usd, 0, False)

    mid = (lo + hi) / 2.0
    achieved = evaluate(mid)
    for i in range(1, max_iter + 1):
        mid = (lo + hi) / 2.0
        achieved = evaluate(mid)
        diff = achieved - target_value_usd
        if abs(diff) <= tol_usd:
            return GoalSeekResult(knob, mid, achieved, target_value_usd, i, True)
        # Keep the sub-interval whose endpoints bracket the target.
        if (diff > 0) == (f_lo > 0):
            lo, f_lo = mid, diff
        else:
            hi, f_hi = mid, diff
    return GoalSeekResult(knob, mid, achieved, target_value_usd, max_iter, abs(achieved - target_value_usd) <= tol_usd)


__all__ = ["Knob", "GoalSeekResult", "goal_seek"]
