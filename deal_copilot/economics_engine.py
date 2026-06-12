"""Deterministic economics engine — the heart of the tool.

Every function here is a **pure** function of its inputs: no I/O, no globals, no
wall-clock, no mutation of arguments. That is the non-negotiable design bar from
KICKOFF — it makes recompute trivially fast, keeps results reproducible under
tests, and lets goal-seek / Monte Carlo become thin sampling layers later.

Design principle: **the LLM extracts and explains; this code computes.** No
LLM-produced number ever enters a calculation here — the engine reads the
extracted `CommercialTerm` parameters and the user-editable `DealAssumptions`,
and produces the typed economics output models in `schemas.py`.

Layering: `compute_economics` imports `driver_mapper` (terms → drivers and the
rebate tier math). `driver_mapper` never imports this module, so there is no
cycle.

Phase 3 scope is the P0 core: quarterly P&L, the four scenarios, probability
weighting, one-way sensitivities, the capacity bridge, and the effective-ASP
waterfall. Warrant contra-revenue is wired as a zero schedule (Phase 4 fills it).
"""

from __future__ import annotations

from dataclasses import dataclass

from deal_copilot import driver_mapper as dm
from deal_copilot.schemas import (
    DealAssumptions,
    DealEconomics,
    DealPackage,
    DriverType,
    EffectiveAsp,
    ModelDriver,
    QuarterRow,
    ScenarioName,
    ScenarioResult,
    SensitivityRow,
    TermType,
    ViewMode,
)
from deal_copilot.driver_mapper import Retroactivity


# ---------------------------------------------------------------------------
# Extracted deal primitives (built once from the package; pure data)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DealInputs:
    """Flat, primitive view of the package the engine needs. Built by
    `extract_inputs`; downstream functions take primitives so they are easy to
    unit-test with hand-computed values."""
    committed_quarterly: tuple[float, ...]
    qpy: int
    base_asp: float
    rebate_tiers: tuple[tuple[float, float], ...]
    take_or_pay_floor_pct: float | None
    shortfall_per_unit_usd: float
    prepayment_usd: float
    prepayment_drawdown_pct: float
    dso_days: int
    dpo_days: int
    inventory_lead_months: int
    contra_schedule: tuple[float, ...]
    adhoc_schedule: tuple[float, ...]
    total_committed_units: float


def _param(term, key, default=None):
    if term is None or not isinstance(term.parameters, dict):
        return default
    return term.parameters.get(key, default)


def extract_inputs(
    pkg: DealPackage, dso_days: int = 90, assumptions: DealAssumptions | None = None
) -> DealInputs:
    """Pull the scalar/series inputs the engine needs out of a package.

    `assumptions` is only consulted when the package carries warrant terms (to
    value the contra-revenue schedule); a warrant-bearing package should pass the
    real assumptions. Defaults to a fresh `DealAssumptions` otherwise.
    """
    if assumptions is None:
        assumptions = DealAssumptions()
    committed = dm.quarterly_schedule(pkg)
    qpy = dm.quarters_per_year(pkg)
    asp = dm._resolve_base_asp(pkg)

    rebate_term = dm._first(pkg, TermType.REBATE)
    tiers = dm._normalize_tiers(rebate_term) if rebate_term is not None else []

    top = dm._first(pkg, TermType.TAKE_OR_PAY)
    floor_pct = _param(top, "annual_minimum_pct_of_committed")
    shortfall_per_unit = _param(top, "shortfall_payment_per_unit_usd", asp)

    pp = dm._first(pkg, TermType.PREPAYMENT)
    prepay = _param(pp, "amount_usd", 0.0) or 0.0
    drawdown_pct = _param(pp, "default_drawdown_pct_of_invoice", 0.20) or 0.20

    pt = dm._first(pkg, TermType.PAYMENT_TERMS)
    net_days = _param(pt, "net_days")
    dso = int(net_days) if isinstance(net_days, (int, float)) else dso_days

    # Warrant contra-revenue fills the slot Phase 3 wired with zeros. Imported
    # locally to keep the module-load arrow one-way (warrant_economics imports
    # driver_mapper, never economics_engine).
    if pkg.warrant_terms is not None:
        from deal_copilot import warrant_economics as we
        contra = we.contra_revenue_schedule(pkg.warrant_terms, assumptions, committed)
    else:
        contra = [0.0] * len(committed)

    adhoc = _adhoc_schedule(pkg.ad_hoc_drivers, len(committed))

    return DealInputs(
        committed_quarterly=tuple(committed),
        qpy=qpy,
        base_asp=asp,
        rebate_tiers=tuple(tiers),
        take_or_pay_floor_pct=float(floor_pct) if isinstance(floor_pct, (int, float)) else None,
        shortfall_per_unit_usd=float(shortfall_per_unit) if isinstance(shortfall_per_unit, (int, float)) else asp,
        prepayment_usd=float(prepay),
        prepayment_drawdown_pct=float(drawdown_pct),
        dso_days=dso,
        dpo_days=int(assumptions.supplier_payment_dpo_days),
        inventory_lead_months=int(assumptions.inventory_lead_months),
        contra_schedule=tuple(contra),
        adhoc_schedule=tuple(adhoc),
        total_committed_units=float(sum(committed)),
    )


def _adhoc_schedule(ad_hoc_drivers, n_quarters: int) -> list[float]:
    """Per-quarter net ad-hoc adjustment from all AdHocDrivers on the package.

    Each driver contributes its `quarterly_schedule_usd` if given, otherwise its
    `amount_usd` spread evenly across the deal's quarters. Positive increases net
    revenue/margin; negative decreases (the schema's sign convention)."""
    sched = [0.0] * n_quarters
    if n_quarters <= 0:
        return sched
    for d in ad_hoc_drivers or []:
        if d.quarterly_schedule_usd:
            for q, amt in enumerate(d.quarterly_schedule_usd):
                if q < n_quarters:
                    sched[q] += amt
        else:
            per_q = d.amount_usd / n_quarters
            for q in range(n_quarters):
                sched[q] += per_q
    return sched


# ---------------------------------------------------------------------------
# Quarterly P&L
# ---------------------------------------------------------------------------


def build_quarterly_pl(
    units: list[float],
    base_asp: float,
    rebate_schedule: list[float],
    contra_schedule: list[float],
    unit_cogs_usd: float,
    opex_allocation_pct: float,
    view: ViewMode,
    extra_revenue: list[float] | None = None,
    adhoc_schedule: list[float] | None = None,
) -> list[QuarterRow]:
    """Build the quarterly P&L for one scenario and one view.

    `extra_revenue` carries non-unit billings (e.g. take-or-pay shortfall
    payments) that add to gross revenue without adding COGS. Warrant
    contra-revenue is subtracted only in the GAAP view; the CASH_COMMERCIAL view
    zeroes it (it is a non-cash ASC 606 transaction-price reduction).

    `adhoc_schedule` is the net ad-hoc adjustment per quarter (positive =
    increase). It is added to net revenue, gross margin, and contribution as the
    `adhoc_adjustment` line, kept visible for traceability; allocated opex is
    computed on the operational net revenue (before ad-hoc) so an ad-hoc credit
    does not inflate the opex base.
    """
    n = len(units)
    extra = extra_revenue or [0.0] * n
    adhoc = adhoc_schedule or [0.0] * n
    rows: list[QuarterRow] = []
    for q in range(n):
        gross = units[q] * base_asp + extra[q]
        rebate = rebate_schedule[q] if q < len(rebate_schedule) else 0.0
        contra = (contra_schedule[q] if q < len(contra_schedule) else 0.0) if view == ViewMode.GAAP else 0.0
        adj = adhoc[q] if q < len(adhoc) else 0.0
        operational_net = gross - rebate - contra
        opex = operational_net * opex_allocation_pct
        net_revenue = operational_net + adj
        cogs = units[q] * unit_cogs_usd
        gross_margin = net_revenue - cogs
        rows.append(QuarterRow(
            quarter_index=q,
            units=units[q],
            gross_revenue=gross,
            rebates=rebate,
            warrant_contra_revenue=contra,
            adhoc_adjustment=adj,
            net_revenue=net_revenue,
            cogs=cogs,
            gross_margin=gross_margin,
            allocated_opex=opex,
            contribution_margin=gross_margin - opex,
        ))
    return rows


# ---------------------------------------------------------------------------
# Cash flow & NPV
#
# Revenue recognition stays quarterly (the P&L above). Cash is modeled on a
# MONTHLY grid so the three working-capital legs are distinguishable:
#   - DSO  (collections):     cash IN  lagged `dso` months after billing.
#   - DPO  (supplier terms):  cash OUT lagged `dpo` months (COGS and opex).
#   - inventory lead:         COGS cash OUT pulled `inventory_lead_months`
#                             months EARLIER (the ramp's inventory build).
# DPO and inventory lead net into one explicit COGS cash lag:
#     cogs_cash_lag = dpo_months − inventory_lead_months
# (a negative lag means COGS cash leaves before the shipment it supports).
#
# Within-quarter activity is spread EVENLY across the quarter's 3 months — the
# cash-timing simplification: it reflects continuous shipment/invoicing and keeps
# the arithmetic hand-traceable. (Quarter-end concentration would be a more
# conservative stress toggle; not modeled.)
#
# NPV here is PRE-TAX operating cash (no tax shield applied to the flows);
# after-tax NPV is a roadmap item. Collections are assumed perfect — no bad
# debt, disputes, or receivables dilution are modeled.
# ---------------------------------------------------------------------------

DAYS_PER_MONTH = 365.25 / 12.0     # 30.4375 — calendar-average month length


def quarterly_discount_rate(wacc_annual: float) -> float:
    """Convert an annual WACC to the equivalent quarterly discount rate."""
    return (1.0 + wacc_annual) ** 0.25 - 1.0


def monthly_discount_rate(wacc_annual: float) -> float:
    """Convert an annual WACC to the equivalent monthly discount rate."""
    return (1.0 + wacc_annual) ** (1.0 / 12.0) - 1.0


def npv(cash_flows: list[float], wacc_annual: float) -> float:
    """NPV of a quarterly cash-flow series, index 0 discounted by 0 periods."""
    r = quarterly_discount_rate(wacc_annual)
    return sum(cf / (1.0 + r) ** t for t, cf in enumerate(cash_flows))


def payback_quarter(cash_flows: list[float], wacc_annual: float) -> int | None:
    """First quarter index at which cumulative *discounted* cash flow turns
    non-negative, or None if it never does."""
    r = quarterly_discount_rate(wacc_annual)
    cum = 0.0
    for t, cf in enumerate(cash_flows):
        cum += cf / (1.0 + r) ** t
        if cum >= 0.0:
            return t
    return None


def npv_monthly(cash_flows: list[float], wacc_annual: float) -> float:
    """NPV of a monthly cash-flow series, index 0 discounted by 0 periods."""
    r = monthly_discount_rate(wacc_annual)
    return sum(cf / (1.0 + r) ** t for t, cf in enumerate(cash_flows))


def payback_month(cash_flows: list[float], wacc_annual: float) -> int | None:
    """First month index at which cumulative *discounted* cash flow turns
    non-negative, or None if it never does."""
    r = monthly_discount_rate(wacc_annual)
    cum = 0.0
    for t, cf in enumerate(cash_flows):
        cum += cf / (1.0 + r) ** t
        if cum >= 0.0:
            return t
    return None


def _lag_months(days: int) -> int:
    """Whole-month lag for a payment term in days (net-30/60/90 → 1/2/3)."""
    return int(round(days / DAYS_PER_MONTH))


def monthly_cash_flows(
    rows: list[QuarterRow],
    inputs: DealInputs,
    include_prepayment: bool = True,
) -> tuple[list[float], int]:
    """Monthly net cash series for a scenario's P&L rows, plus `lead_pad` — the
    number of leading months prepended so a pre-shipment inventory build (a
    negative COGS cash lag) lands at a non-negative index.

    Each quarter's gross revenue, rebate, COGS, and opex are split evenly across
    its 3 months. Per month:
      - collection (invoice − drawdown − rebate) lands `dso` months later;
      - COGS cash lands `cogs_cash_lag = dpo − inventory_lead_months` months
        later (may be negative → before the shipment);
      - opex cash lands `dpo` months later.

    The customer prepayment is a financing overlay:
      - ``include_prepayment=True`` (financed view): the $500M prepayment is an
        inflow at month 0, and each invoice's collection is reduced by the
        20%-of-invoice drawdown until the prepayment is exhausted. Used for the
        headline NPV and the "with customer financing" payback (front-loaded).
      - ``include_prepayment=False`` (deployment view): no prepayment inflow and
        no drawdown — collections in full. Isolates the deal's own operating
        cash for the meaningful payback and the peak working-capital draw.

    The grid origin (index 0) is the EARLIEST cash event, so discounting starts
    when cash first moves. `lead_pad` lets callers map an index back to a
    calendar month: `calendar_month = index − lead_pad`.
    """
    dso = _lag_months(inputs.dso_days)
    dpo = _lag_months(inputs.dpo_days)
    cogs_cash_lag = dpo - inputs.inventory_lead_months   # net leg; may be < 0
    opex_lag = dpo
    lead_pad = max(0, -cogs_cash_lag, -opex_lag)
    months = len(rows) * 3
    size = months + max(dso, opex_lag, cogs_cash_lag, 0) + lead_pad + 1
    cf = [0.0] * size

    def put(month: int, amount: float) -> None:
        cf[month + lead_pad] += amount

    remaining = inputs.prepayment_usd if include_prepayment else 0.0
    if include_prepayment:
        put(0, inputs.prepayment_usd)
    for q, row in enumerate(rows):
        invoice_m = row.gross_revenue / 3.0
        rebate_m = row.rebates / 3.0
        cogs_m = row.cogs / 3.0
        opex_m = row.allocated_opex / 3.0
        for k in range(3):
            m = q * 3 + k
            if include_prepayment:
                drawdown = min(inputs.prepayment_drawdown_pct * invoice_m, remaining)
                remaining -= drawdown
            else:
                drawdown = 0.0
            put(m + dso, invoice_m - drawdown - rebate_m)   # collection (DSO)
            put(m + cogs_cash_lag, -cogs_m)                 # COGS cash (DPO − lead)
            put(m + opex_lag, -opex_m)                      # opex cash (DPO)
    return cf, lead_pad


def peak_working_capital_draw(rows: list[QuarterRow], inputs: DealInputs) -> float:
    """Most negative undiscounted cumulative cash balance on the deployment view
    (excluding the prepayment) — the peak operating working capital tied up
    before the deal turns cash-positive. Negative = a draw. Reflects all three
    legs (DSO collection lag, DPO supplier lag, inventory build)."""
    cf, _ = monthly_cash_flows(rows, inputs, include_prepayment=False)
    cum = 0.0
    trough = 0.0
    for c in cf:
        cum += c
        if cum < trough:
            trough = cum
    return trough


# ---------------------------------------------------------------------------
# Take-or-pay (used by the DOWNSIDE scenario and tested directly)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TakeOrPayYear:
    year_index: int
    committed_units: float
    taken_units: float
    floor_units: float
    shortfall_units: float
    shortfall_payment_usd: float


def compute_take_or_pay(
    committed_quarterly: list[float],
    demand_quarterly: list[float],
    qpy: int,
    floor_pct: float,
    shortfall_per_unit_usd: float,
) -> tuple[list[TakeOrPayYear], float]:
    """Per-year take-or-pay settlement plus total Banked Units forfeited.

    For each Year: `taken = min(demand, committed)` summed over the Year; if
    `taken < floor (= floor_pct × committed)`, the buyer pays for the gap at
    `shortfall_per_unit_usd` and those units become Banked Units. Banked Units
    may be drawn in a later quarter whose demand exceeds its committed schedule;
    any still undrawn at term end are forfeited. Returns the per-year records and
    the total forfeited Banked Units.
    """
    n = len(committed_quarterly)
    years: list[TakeOrPayYear] = []
    banked = 0.0
    for yi, y0 in enumerate(range(0, n, qpy)):
        y1 = min(y0 + qpy, n)
        committed = sum(committed_quarterly[y0:y1])
        demand = sum(demand_quarterly[y0:y1])
        # Demand above committed in a Year draws down banked units first.
        if demand > committed and banked > 0:
            draw = min(demand - committed, banked)
            banked -= draw
        taken = min(demand, committed)
        floor_units = floor_pct * committed
        shortfall = max(0.0, floor_units - taken)
        banked += shortfall
        years.append(TakeOrPayYear(
            year_index=yi,
            committed_units=committed,
            taken_units=taken,
            floor_units=floor_units,
            shortfall_units=shortfall,
            shortfall_payment_usd=shortfall * shortfall_per_unit_usd,
        ))
    return years, banked


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

DOWNSIDE_DEMAND_PCT = 0.75      # flat demand haircut for DOWNSIDE (below the floor)
UPSIDE_VOLUME_PCT = 1.15        # +15% volume for UPSIDE
EARLY_TERMINATION_EXIT_Q = 8    # default exit quarter for EARLY_TERMINATION


def _scenario_units(scenario: ScenarioName, inputs: DealInputs) -> list[float]:
    committed = list(inputs.committed_quarterly)
    if scenario == ScenarioName.BASE:
        return committed
    if scenario == ScenarioName.DOWNSIDE_TAKE_OR_PAY:
        return [u * DOWNSIDE_DEMAND_PCT for u in committed]
    if scenario == ScenarioName.UPSIDE_VOLUME:
        return [u * UPSIDE_VOLUME_PCT for u in committed]
    if scenario == ScenarioName.EARLY_TERMINATION:
        return [u if q < EARLY_TERMINATION_EXIT_Q else 0.0 for q, u in enumerate(committed)]
    return committed


def _scenario_extra_revenue(
    scenario: ScenarioName, inputs: DealInputs, units: list[float]
) -> list[float]:
    """Non-unit billings per quarter for a scenario (take-or-pay shortfall at
    year-end quarters; wind-down fee at the exit quarter)."""
    n = len(units)
    extra = [0.0] * n
    if scenario == ScenarioName.DOWNSIDE_TAKE_OR_PAY and inputs.take_or_pay_floor_pct:
        years, _ = compute_take_or_pay(
            list(inputs.committed_quarterly), units, inputs.qpy,
            inputs.take_or_pay_floor_pct, inputs.shortfall_per_unit_usd,
        )
        for yi, rec in enumerate(years):
            y_end = min((yi + 1) * inputs.qpy, n) - 1
            extra[y_end] += rec.shortfall_payment_usd
    if scenario == ScenarioName.EARLY_TERMINATION:
        undelivered = inputs.total_committed_units - sum(units)
        wind_down = 0.25 * inputs.base_asp * undelivered
        net_of_prepay = max(0.0, wind_down - inputs.prepayment_usd)
        exit_q = min(EARLY_TERMINATION_EXIT_Q, n - 1)
        extra[exit_q] += net_of_prepay
    return extra


def run_scenario(
    scenario: ScenarioName,
    view: ViewMode,
    inputs: DealInputs,
    assumptions: DealAssumptions,
    retroactivity: Retroactivity = "prospective",
) -> ScenarioResult:
    """Compute one (scenario, view) result: quarterly P&L, NPV, payback, totals."""
    units = _scenario_units(scenario, inputs)
    rebate_sched = dm.compute_rebate_schedule(
        list(inputs.rebate_tiers), units, inputs.base_asp, retroactivity, inputs.qpy
    )
    extra = _scenario_extra_revenue(scenario, inputs, units)
    rows = build_quarterly_pl(
        units, inputs.base_asp, rebate_sched, list(inputs.contra_schedule),
        assumptions.unit_cogs_usd, assumptions.opex_allocation_pct, view, extra,
        list(inputs.adhoc_schedule),
    )
    wacc = assumptions.discount_rate_wacc
    cf_financed, pad_fin = monthly_cash_flows(rows, inputs, include_prepayment=True)
    cf_deployment, pad_dep = monthly_cash_flows(rows, inputs, include_prepayment=False)

    def to_quarter(month: int | None, pad: int) -> int | None:
        """Map a monthly payback index back to the calendar quarter it falls in."""
        if month is None:
            return None
        return max(0, month - pad) // 3

    total_net = sum(r.net_revenue for r in rows)
    total_gm = sum(r.gross_margin for r in rows)
    return ScenarioResult(
        scenario=scenario,
        view=view,
        quarterly_pl=rows,
        npv_usd=npv_monthly(cf_financed, wacc),
        payback_quarters=to_quarter(payback_month(cf_financed, wacc), pad_fin),
        payback_quarters_ex_prepayment=to_quarter(payback_month(cf_deployment, wacc), pad_dep),
        total_net_revenue=total_net,
        total_gross_margin=total_gm,
        total_gross_margin_pct=(total_gm / total_net) if total_net else 0.0,
        peak_working_capital_draw_usd=peak_working_capital_draw(rows, inputs),
    )


def run_all_scenarios(
    inputs: DealInputs,
    assumptions: DealAssumptions,
    retroactivity: Retroactivity = "prospective",
) -> list[ScenarioResult]:
    """Every scenario × both views (consumers look up by (scenario, view))."""
    results: list[ScenarioResult] = []
    for scenario in ScenarioName:
        for view in ViewMode:
            results.append(run_scenario(scenario, view, inputs, assumptions, retroactivity))
    return results


# ---------------------------------------------------------------------------
# Probability weighting
# ---------------------------------------------------------------------------


def probability_weighted(
    scenario_results: list[ScenarioResult],
    assumptions: DealAssumptions,
    view: ViewMode = ViewMode.GAAP,
) -> dict[str, float | bool]:
    """Probability-weighted expected NPV and gross margin across scenarios for a
    given view. Uses `assumptions.scenario_probabilities` (equal weights if
    empty). Sets `weights_valid=False` when the probabilities do not sum to ~1.
    """
    rows = [r for r in scenario_results if r.view == view]
    probs = {sp.scenario: sp.probability for sp in assumptions.scenario_probabilities}
    if probs:
        weights = {r.scenario: probs.get(r.scenario, 0.0) for r in rows}
        total_w = sum(weights.values())
        weights_valid = 0.99 <= total_w <= 1.01
    else:
        weights = {r.scenario: 1.0 / len(rows) for r in rows} if rows else {}
        weights_valid = True
    exp_npv = sum(r.npv_usd * weights.get(r.scenario, 0.0) for r in rows)
    exp_gm = sum(r.total_gross_margin * weights.get(r.scenario, 0.0) for r in rows)
    return {
        "expected_npv_usd": exp_npv,
        "expected_gross_margin_usd": exp_gm,
        "weights_valid": weights_valid,
    }


# ---------------------------------------------------------------------------
# Sensitivities (one-way, tornado-ranked)
# ---------------------------------------------------------------------------


def _base_total_gross_margin(
    inputs: DealInputs, assumptions: DealAssumptions, retroactivity: Retroactivity
) -> float:
    res = run_scenario(ScenarioName.BASE, ViewMode.GAAP, inputs, assumptions, retroactivity)
    return res.total_gross_margin


def sensitivities(
    inputs: DealInputs,
    assumptions: DealAssumptions,
    retroactivity: Retroactivity = "prospective",
) -> list[SensitivityRow]:
    """One-way ±10% sensitivities on ASP, unit COGS, and rebate rates, plus ramp
    slip of +1 / +2 quarters; ranked descending by |Δ vs base| on total gross
    margin (tornado order)."""
    base_gm = _base_total_gross_margin(inputs, assumptions, retroactivity)
    rows: list[SensitivityRow] = []

    def record(variable: str, label: str, gm: float) -> None:
        rows.append(SensitivityRow(
            variable=variable, delta_label=label,
            total_gross_margin_usd=gm, delta_vs_base_usd=gm - base_gm,
        ))

    # ASP ±10%
    for sign, lbl in ((1.10, "+10%"), (0.90, "-10%")):
        bumped = _replace_inputs(inputs, base_asp=inputs.base_asp * sign)
        record("asp", lbl, _base_total_gross_margin(bumped, assumptions, retroactivity))

    # Unit COGS ±10%
    for sign, lbl in ((1.10, "+10%"), (0.90, "-10%")):
        a = assumptions.model_copy(update={"unit_cogs_usd": assumptions.unit_cogs_usd * sign})
        record("unit_cogs", lbl, _base_total_gross_margin(inputs, a, retroactivity))

    # Rebate rates ±10% (scale every tier pct)
    for sign, lbl in ((1.10, "+10%"), (0.90, "-10%")):
        tiers = tuple((thr, pct * sign) for thr, pct in inputs.rebate_tiers)
        bumped = _replace_inputs(inputs, rebate_tiers=tiers)
        record("rebate_rates", lbl, _base_total_gross_margin(bumped, assumptions, retroactivity))

    # Ramp slip +1 / +2 quarters (shift schedule right, dropping the tail)
    for slip in (1, 2):
        committed = (0.0,) * slip + inputs.committed_quarterly[:-slip]
        bumped = _replace_inputs(inputs, committed_quarterly=committed)
        record("ramp_slip_quarters", f"+{slip}", _base_total_gross_margin(bumped, assumptions, retroactivity))

    rows.sort(key=lambda r: abs(r.delta_vs_base_usd), reverse=True)
    return rows


def _replace_inputs(inputs: DealInputs, **changes) -> DealInputs:
    """Return a copy of DealInputs with fields replaced (DealInputs is frozen)."""
    from dataclasses import replace
    return replace(inputs, **changes)


# ---------------------------------------------------------------------------
# Capacity bridge
# ---------------------------------------------------------------------------


def bridge_unit_schedule(assumptions: DealAssumptions, n_quarters: int) -> list[float]:
    """Distribute power-derived units evenly across `n_quarters`.

    Used only in power-denominated (capacity-bridge) mode; unit-denominated
    deals carry an explicit schedule and never call this. The synthetic deal is
    unit-mode. Uses `CapacityBridgeInputs.derived_units()` from the schema.
    """
    if assumptions.capacity_bridge is None or n_quarters <= 0:
        return [0.0] * max(0, n_quarters)
    total = assumptions.capacity_bridge.derived_units()
    per_q = total / n_quarters
    return [per_q] * n_quarters


# ---------------------------------------------------------------------------
# Effective ASP waterfall
# ---------------------------------------------------------------------------


def effective_asp(
    inputs: DealInputs,
    retroactivity: Retroactivity = "prospective",
) -> EffectiveAsp:
    """Sticker → −rebate/unit → −warrant/unit (0 in Phase 3) → all-in."""
    units = list(inputs.committed_quarterly)
    total_units = sum(units) or 1.0
    rebate_sched = dm.compute_rebate_schedule(
        list(inputs.rebate_tiers), units, inputs.base_asp, retroactivity, inputs.qpy
    )
    rebate_per_unit = sum(rebate_sched) / total_units
    warrant_per_unit = sum(inputs.contra_schedule) / total_units
    return EffectiveAsp(
        sticker_usd=inputs.base_asp,
        rebate_per_unit_usd=rebate_per_unit,
        warrant_per_unit_usd=warrant_per_unit,
        all_in_usd=inputs.base_asp - rebate_per_unit - warrant_per_unit,
    )


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


def compute_economics(
    pkg: DealPackage,
    assumptions: DealAssumptions,
    dso_days: int = 90,
    retroactivity: Retroactivity = "prospective",
) -> DealEconomics:
    """Full economics output for a package: drivers, all scenarios × views,
    sensitivities, and the effective-ASP waterfall.

    `retroactivity` selects the rebate reading for the headline scenarios
    (default prospective). The rebate ambiguity delta is reported separately via
    `driver_mapper.rebate_variant_comparison` and surfaced on the rebate driver's
    accounting note.
    """
    inputs = extract_inputs(pkg, dso_days, assumptions)
    drivers: list[ModelDriver] = dm.map_terms_to_drivers(
        pkg, assumptions, dso_days, warrant_contra_schedule=list(inputs.contra_schedule),
    )
    return DealEconomics(
        assumptions=assumptions,
        drivers=drivers,
        scenarios=run_all_scenarios(inputs, assumptions, retroactivity),
        sensitivities=sensitivities(inputs, assumptions, retroactivity),
        effective_asp=effective_asp(inputs, retroactivity),
    )


__all__ = [
    "DealInputs",
    "extract_inputs",
    "build_quarterly_pl",
    "quarterly_discount_rate",
    "monthly_discount_rate",
    "npv",
    "payback_quarter",
    "npv_monthly",
    "payback_month",
    "monthly_cash_flows",
    "peak_working_capital_draw",
    "TakeOrPayYear",
    "compute_take_or_pay",
    "run_scenario",
    "run_all_scenarios",
    "probability_weighted",
    "sensitivities",
    "bridge_unit_schedule",
    "effective_asp",
    "compute_economics",
    "DOWNSIDE_DEMAND_PCT",
    "UPSIDE_VOLUME_PCT",
    "EARLY_TERMINATION_EXIT_Q",
]
