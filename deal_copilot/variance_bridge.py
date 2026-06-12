"""Variance bridge — explain, dollar by dollar, why a deal's economics changed
between two versions.

This is the negotiation desk's daily-use feature: given "Counterparty initial"
and "Our counter v1", show a driver-level walk — which terms and assumptions
changed and the dollar impact of each on a chosen metric — that **sums exactly to
the total delta**.

Mechanism — sequential (waterfall) attribution. Many inputs change at once and
their effects interact (a higher ASP also raises the rebate), so isolating each
driver's effect and adding them up would NOT reconcile to the true delta.
Instead: start from version A's full state, apply the A→B changes one at a time
in a fixed order, and recompute the metric after each via the pure engine. Each
change's contribution = metric after − metric before. The contributions telescope
to `metric_B − metric_A`. We compute the destination metric independently from
version B as an integrity check: `residual_usd` (= total delta − Σ steps) is ~0
only if the diff captured every economic change — that is the sums-to-delta
property the test asserts.

Order attributes interaction between steps but never changes the total; this is a
standard, documented property of waterfall bridges.

Pure module: no I/O, no globals, inputs never mutated (every step works on deep
copies).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable

from deal_copilot.economics_engine import compute_economics
from deal_copilot.schemas import (
    AdHocDriver,
    BridgeStep,
    CommercialTerm,
    DealAssumptions,
    DealPackage,
    DealVersion,
    DocumentRef,
    ScenarioName,
    VarianceBridge,
    VarianceMetric,
    ViewMode,
    WarrantTerms,
)
from deal_copilot.driver_mapper import Retroactivity


# Assumptions scalar fields the bridge tracks (negotiation levers + drivers).
_ASSUMPTION_FIELDS = (
    "unit_cogs_usd",
    "opex_allocation_pct",
    "discount_rate_wacc",
    "tax_rate",
    "current_stock_price_usd",
    "warrant_measurement_price_usd",
    "shares_outstanding",
    "assumed_volatility",
)
_ASSUMPTION_LIST_FIELDS = ("tranche_vest_probabilities",)


# ---------------------------------------------------------------------------
# Working state and the change set
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _State:
    """A deal's modelable inputs, deep-copied so steps never mutate a version."""
    terms: tuple[CommercialTerm, ...]
    warrant: WarrantTerms | None
    assumptions: DealAssumptions
    ad_hoc: tuple[AdHocDriver, ...]


def _state_of(version: DealVersion) -> _State:
    return _State(
        terms=tuple(t.model_copy(deep=True) for t in version.terms),
        warrant=version.warrant_terms.model_copy(deep=True) if version.warrant_terms else None,
        assumptions=version.assumptions.model_copy(deep=True),
        ad_hoc=tuple(d.model_copy(deep=True) for d in version.ad_hoc_drivers),
    )


@dataclass(frozen=True)
class Change:
    """One atomic A→B change: how to describe it and how to apply it to a state."""
    field_path: str
    label: str
    old_value: Any
    new_value: Any
    apply: Callable[[_State], _State]


def _terms_by_type(terms: tuple[CommercialTerm, ...]) -> dict[str, CommercialTerm]:
    return {t.term_type.value: t for t in terms}


def _set_term_param(state: _State, term_type: str, key: str, value: Any) -> _State:
    new_terms = []
    for t in state.terms:
        if t.term_type.value == term_type:
            params = dict(t.parameters)
            params[key] = value
            new_terms.append(t.model_copy(update={"parameters": params}, deep=True))
        else:
            new_terms.append(t)
    return replace(state, terms=tuple(new_terms))


def _set_assumption(state: _State, field: str, value: Any) -> _State:
    return replace(state, assumptions=state.assumptions.model_copy(update={field: value}))


def _set_warrant(state: _State, warrant: WarrantTerms | None) -> _State:
    return replace(state, warrant=warrant.model_copy(deep=True) if warrant else None)


def _set_adhoc(state: _State, ad_hoc: tuple[AdHocDriver, ...]) -> _State:
    return replace(state, ad_hoc=ad_hoc)


def diff_changes(version_a: DealVersion, version_b: DealVersion) -> list[Change]:
    """Atomic A→B changes in deterministic order: term params → assumptions →
    warrant → ad-hoc drivers. Shared with the change journal so both speak the
    same lever vocabulary."""
    changes: list[Change] = []

    # --- term parameters ---
    a_terms = _terms_by_type(tuple(version_a.terms))
    b_terms = _terms_by_type(tuple(version_b.terms))
    for ttype in sorted(set(a_terms) | set(b_terms)):
        a_params = dict(a_terms[ttype].parameters) if ttype in a_terms else {}
        b_params = dict(b_terms[ttype].parameters) if ttype in b_terms else {}
        for key in sorted(set(a_params) | set(b_params)):
            old = a_params.get(key)
            new = b_params.get(key)
            if old != new:
                changes.append(Change(
                    field_path=f"terms[{ttype}].{key}",
                    label=f"{ttype}.{key}: {old} -> {new}",
                    old_value=old, new_value=new,
                    apply=(lambda tt, k, v: lambda s: _set_term_param(s, tt, k, v))(ttype, key, new),
                ))

    # --- assumptions scalars + lists ---
    for field in _ASSUMPTION_FIELDS + _ASSUMPTION_LIST_FIELDS:
        old = getattr(version_a.assumptions, field)
        new = getattr(version_b.assumptions, field)
        if old != new:
            changes.append(Change(
                field_path=f"assumptions.{field}",
                label=f"assumptions.{field}: {old} -> {new}",
                old_value=old, new_value=new,
                apply=(lambda f, v: lambda s: _set_assumption(s, f, v))(field, new),
            ))

    # --- warrant (whole object) ---
    a_w = version_a.warrant_terms.model_dump() if version_a.warrant_terms else None
    b_w = version_b.warrant_terms.model_dump() if version_b.warrant_terms else None
    if a_w != b_w:
        changes.append(Change(
            field_path="warrant_terms",
            label="warrant terms changed",
            old_value=a_w, new_value=b_w,
            apply=(lambda w: lambda s: _set_warrant(s, w))(version_b.warrant_terms),
        ))

    # --- ad-hoc drivers (by label) ---
    a_adhoc = {d.label: d for d in version_a.ad_hoc_drivers}
    b_adhoc = {d.label: d for d in version_b.ad_hoc_drivers}
    for label in sorted(set(a_adhoc) | set(b_adhoc)):
        old_d = a_adhoc.get(label)
        new_d = b_adhoc.get(label)
        if (old_d.model_dump() if old_d else None) != (new_d.model_dump() if new_d else None):
            target = tuple(version_b.ad_hoc_drivers)
            old_amt = old_d.amount_usd if old_d else None
            new_amt = new_d.amount_usd if new_d else None
            changes.append(Change(
                field_path=f"ad_hoc[{label}]",
                label=f"ad-hoc '{label}': {old_amt} -> {new_amt}",
                old_value=old_amt, new_value=new_amt,
                apply=(lambda t: lambda s: _set_adhoc(s, tuple(d.model_copy(deep=True) for d in t)))(target),
            ))

    return changes


# ---------------------------------------------------------------------------
# Metric evaluation over the pure engine
# ---------------------------------------------------------------------------


def _package_from_state(state: _State, template: DealPackage) -> DealPackage:
    """Rebuild a DealPackage carrying `state`'s modelable inputs but the
    template's identity (documents, deal_id). assumptions travel separately."""
    return template.model_copy(update={
        "terms": list(state.terms),
        "warrant_terms": state.warrant,
        "ad_hoc_drivers": list(state.ad_hoc),
        "versions": [],
        "change_journal": [],
        "policy_verdicts": [],
    }, deep=True)


def _metric_value(result, metric: VarianceMetric) -> float:
    if metric == "net_revenue":
        return result.total_net_revenue
    if metric == "gross_margin":
        return result.total_gross_margin
    if metric == "npv":
        return result.npv_usd
    raise ValueError(f"unknown metric {metric!r}")


def _compute_metric(
    state: _State, template: DealPackage, metric: VarianceMetric,
    scenario: ScenarioName, view: ViewMode, retroactivity: Retroactivity,
) -> float:
    pkg = _package_from_state(state, template)
    econ = compute_economics(pkg, state.assumptions, retroactivity=retroactivity)
    result = next(r for r in econ.scenarios if r.scenario == scenario and r.view == view)
    return _metric_value(result, metric)


def variance_bridge(
    version_a: DealVersion,
    version_b: DealVersion,
    template_pkg: DealPackage,
    metric: VarianceMetric = "gross_margin",
    scenario: ScenarioName = ScenarioName.BASE,
    view: ViewMode = ViewMode.GAAP,
    retroactivity: Retroactivity = "prospective",
) -> VarianceBridge:
    """Driver-level walk from version A to version B on the chosen metric.

    Sequential attribution over the pure engine; the step contributions telescope
    to the total delta. `residual_usd` is the total delta minus the summed steps,
    computed against an INDEPENDENT evaluation of version B — ~0 confirms the diff
    captured every economic change (the sums-to-delta property)."""
    changes = diff_changes(version_a, version_b)

    state = _state_of(version_a)
    from_metric = _compute_metric(state, template_pkg, metric, scenario, view, retroactivity)

    steps: list[BridgeStep] = []
    prev = from_metric
    for ch in changes:
        state = ch.apply(state)
        cur = _compute_metric(state, template_pkg, metric, scenario, view, retroactivity)
        steps.append(BridgeStep(
            field_path=ch.field_path, label=ch.label,
            old_value=ch.old_value, new_value=ch.new_value,
            metric_delta_usd=cur - prev,
        ))
        prev = cur

    # Independent destination metric (integrity check on the diff completeness).
    to_metric = _compute_metric(_state_of(version_b), template_pkg, metric, scenario, view, retroactivity)
    total_delta = to_metric - from_metric
    residual = total_delta - sum(s.metric_delta_usd for s in steps)

    return VarianceBridge(
        metric=metric, scenario=scenario, view=view,
        from_version_name=version_a.name, to_version_name=version_b.name,
        from_metric_usd=from_metric, to_metric_usd=to_metric,
        total_delta_usd=total_delta, steps=steps, residual_usd=residual,
    )


__all__ = ["Change", "diff_changes", "variance_bridge"]
