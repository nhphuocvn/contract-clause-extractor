"""Map extracted commercial terms to financial-model drivers.

`map_terms_to_drivers` turns a `DealPackage`'s `CommercialTerm`s into a list of
`ModelDriver`s the economics engine consumes. One private helper per term type,
each reading `term.parameters` by the exact keys produced by extraction (see
`ground_truth.json`). Every driver carries a plain-English
`accounting_treatment_note` so the Drivers tab and CRB memo can trace each model
line back to its clause and its revenue-recognition treatment.

This module is pure — no I/O, no globals, no mutation of its inputs.

The rebate tier math also lives here (it is term→driver logic: turning a tier
table into a per-quarter rebate schedule). It is kept in this module rather than
`economics_engine` so the engine can import it without a circular dependency
(`economics_engine` imports `driver_mapper`, never the reverse).

The **rebate ambiguity** is the load-bearing piece. The synthetic clause is
silent on whether crossing a tier mid-Year applies retroactively to that Year's
earlier volume. Two readings are modeled:

  - ``"prospective"``  — each cumulative unit earns the rate of the cumulative
    band it lands in (marginal, term-wide).  Total: $142.5M on the synthetic deal.
  - ``"retroactive_within_year"`` — every unit purchased in a Year earns the
    highest tier reached by that Year's cumulative end, applied to the whole
    year's volume.  Total: $183.5M.

`rebate_variant_comparison` reports both totals and the $41.0M delta — that delta
becomes an Assumption Gap Report line (Phase 6) urging Legal resolution.
"""

from __future__ import annotations

from typing import Any, Literal

from deal_copilot.schemas import (
    CommercialTerm,
    DealAssumptions,
    DealPackage,
    DriverType,
    ModelDriver,
    TermType,
    TermVariant,
    validate_assumptions_against_warrant,
)

Retroactivity = Literal["prospective", "retroactive_within_year"]


# ---------------------------------------------------------------------------
# Parameter accessors (mirror validators._param / _terms_of conventions)
# ---------------------------------------------------------------------------


def _terms_of(pkg: DealPackage, term_type: TermType) -> list[CommercialTerm]:
    return [t for t in pkg.terms if t.term_type == term_type]


def _first(pkg: DealPackage, term_type: TermType) -> CommercialTerm | None:
    terms = _terms_of(pkg, term_type)
    return terms[0] if terms else None


def _param(term: CommercialTerm, key: str, default: Any = None) -> Any:
    if not isinstance(term.parameters, dict):
        return default
    return term.parameters.get(key, default)


# ---------------------------------------------------------------------------
# Quarterly schedule / year structure
# ---------------------------------------------------------------------------


def quarterly_schedule(pkg: DealPackage) -> list[float]:
    """The committed per-quarter unit ramp from the VOLUME_COMMITMENT term."""
    vc = _first(pkg, TermType.VOLUME_COMMITMENT)
    if vc is None:
        return []
    sched = _param(vc, "quarterly_schedule_units", [])
    if not isinstance(sched, list):
        return []
    return [float(x) for x in sched]


def quarters_per_year(pkg: DealPackage) -> int:
    """Quarters per Year for annual roll-ups (rebate settlement, take-or-pay).

    Derived from the VOLUME_COMMITMENT term's `term_years` and schedule length;
    falls back to 4 when the schedule does not divide evenly.
    """
    vc = _first(pkg, TermType.VOLUME_COMMITMENT)
    if vc is None:
        return 4
    sched = _param(vc, "quarterly_schedule_units", [])
    term_years = _param(vc, "term_years")
    if isinstance(sched, list) and term_years and len(sched) % int(term_years) == 0:
        return len(sched) // int(term_years)
    return 4


# ---------------------------------------------------------------------------
# Rebate tier math (term -> per-quarter rebate schedule)
# ---------------------------------------------------------------------------


def _normalize_tiers(rebate_term: CommercialTerm) -> list[tuple[float, float]]:
    """Return rebate tiers as a sorted list of (cumulative_threshold, pct)."""
    raw = _param(rebate_term, "tiers", [])
    tiers: list[tuple[float, float]] = []
    for t in raw or []:
        thr = t.get("threshold_cumulative_units")
        pct = t.get("pct_off_base_asp")
        if thr is None or pct is None:
            continue
        tiers.append((float(thr), float(pct)))
    tiers.sort(key=lambda x: x[0])
    return tiers


def _rate_at_floor(tiers: list[tuple[float, float]], position: float) -> float:
    """Marginal rebate rate for a unit whose cumulative position is just above
    `position`. A tier "for cumulative purchases above T" applies once the
    cumulative count exceeds T, so a sub-interval starting at `position` earns
    the highest tier with threshold <= position.
    """
    rate = 0.0
    for thr, pct in tiers:
        if thr <= position:
            rate = pct
    return rate


def _prospective_interval(
    lo: float, hi: float, tiers: list[tuple[float, float]], asp: float
) -> float:
    """Rebate $ earned on cumulative units in the half-open interval (lo, hi].

    Splits the interval at tier thresholds; each sub-interval earns the marginal
    rate of its lower bound (see `_rate_at_floor`).
    """
    if hi <= lo:
        return 0.0
    cuts = sorted({lo, hi, *(thr for thr, _ in tiers if lo < thr < hi)})
    total = 0.0
    for a, b in zip(cuts, cuts[1:]):
        total += (b - a) * _rate_at_floor(tiers, a) * asp
    return total


def compute_rebate_schedule(
    tiers: list[tuple[float, float]],
    quarterly_units: list[float],
    asp: float,
    retroactivity: Retroactivity,
    qpy: int,
) -> list[float]:
    """Per-quarter rebate $ for the chosen reading.

    - ``prospective``: each quarter earns the marginal rebate on the cumulative
      units it adds (term-wide bands).
    - ``retroactive_within_year``: each Year's whole volume earns the highest
      tier reached by that Year's cumulative end; the Year's rebate is allocated
      across its quarters in proportion to units (ratable accrual).
    """
    n = len(quarterly_units)
    out = [0.0] * n
    if not tiers or not quarterly_units:
        return out

    if retroactivity == "prospective":
        cum = 0.0
        for q, u in enumerate(quarterly_units):
            out[q] = _prospective_interval(cum, cum + u, tiers, asp)
            cum += u
        return out

    # retroactive_within_year
    cum = 0.0
    cumulative = []
    for u in quarterly_units:
        cum += u
        cumulative.append(cum)
    for y0 in range(0, n, qpy):
        y1 = min(y0 + qpy, n)
        year_units = sum(quarterly_units[y0:y1])
        if year_units <= 0:
            continue
        end_cum = cumulative[y1 - 1]
        rate = _rate_at_floor(tiers, end_cum)
        year_rebate = year_units * rate * asp
        for q in range(y0, y1):
            out[q] = year_rebate * (quarterly_units[q] / year_units)
    return out


def rebate_variant_comparison(
    rebate_term: CommercialTerm,
    quarterly_units: list[float],
    asp: float,
    qpy: int,
) -> dict[str, Any]:
    """Both rebate readings and their dollar delta — the headline gap-report
    number. Returns prospective/retroactive totals, the delta, and the
    per-quarter schedules for each reading.
    """
    tiers = _normalize_tiers(rebate_term)
    pro = compute_rebate_schedule(tiers, quarterly_units, asp, "prospective", qpy)
    retro = compute_rebate_schedule(
        tiers, quarterly_units, asp, "retroactive_within_year", qpy
    )
    pro_total = sum(pro)
    retro_total = sum(retro)
    return {
        "prospective_total_usd": pro_total,
        "retroactive_total_usd": retro_total,
        "delta_usd": retro_total - pro_total,
        "prospective_schedule": pro,
        "retroactive_schedule": retro,
    }


def build_rebate_variants(
    rebate_term: CommercialTerm,
    quarterly_units: list[float],
    asp: float,
    qpy: int,
) -> list[TermVariant]:
    """Two `TermVariant`s for the ambiguous rebate clause, each carrying its
    reading's per-quarter schedule and term total. Consumed by the gap report
    and UI; the engine can run either schedule.
    """
    cmp = rebate_variant_comparison(rebate_term, quarterly_units, asp, qpy)
    return [
        TermVariant(
            label="tier-crossing prospective",
            parameters={
                "retroactivity": "prospective",
                "quarterly_rebate_usd": cmp["prospective_schedule"],
                "total_rebate_usd": cmp["prospective_total_usd"],
            },
            note="Crossing a tier applies the higher rate only to volume "
                 "purchased thereafter (marginal, term-wide cumulative bands).",
        ),
        TermVariant(
            label="tier-crossing retroactive",
            parameters={
                "retroactivity": "retroactive_within_year",
                "quarterly_rebate_usd": cmp["retroactive_schedule"],
                "total_rebate_usd": cmp["retroactive_total_usd"],
            },
            note="Crossing a tier during a Year applies the higher rate to that "
                 "Year's entire volume (retroactive within the Year).",
        ),
    ]


# ---------------------------------------------------------------------------
# Per-term-type driver builders
# ---------------------------------------------------------------------------


def _volume_driver(term: CommercialTerm) -> ModelDriver:
    sched = _param(term, "quarterly_schedule_units", []) or []
    return ModelDriver(
        driver_id="volume_quarterly_units",
        driver_type=DriverType.QUARTERLY_UNIT_SCHEDULE,
        schedule=[float(x) for x in sched],
        source_term_id=term.term_id,
        accounting_treatment_note=(
            "Committed quarterly unit ramp; basis for revenue recognition as "
            "units are delivered (ASC 606 point-in-time transfer of control)."
        ),
    )


def _rebate_driver(term: CommercialTerm, quarterly_units: list[float], asp: float, qpy: int) -> ModelDriver:
    cmp = rebate_variant_comparison(term, quarterly_units, asp, qpy)
    # Default (headline) reading is prospective; the note carries both totals so
    # the ambiguity exposure is visible on the driver itself.
    return ModelDriver(
        driver_id="rebate_gross_to_net",
        driver_type=DriverType.GROSS_TO_NET_WATERFALL,
        schedule=cmp["prospective_schedule"],
        source_term_id=term.term_id,
        accounting_treatment_note=(
            "Tiered volume rebate — variable consideration estimated and "
            "recognized as a reduction of transaction price (ASC 606). "
            f"AMBIGUOUS: prospective reading ${cmp['prospective_total_usd']:,.0f} "
            f"vs retroactive-within-year ${cmp['retroactive_total_usd']:,.0f} "
            f"(delta ${cmp['delta_usd']:,.0f}); resolve tier-crossing "
            "retroactivity with Legal before signature."
        ),
    )


def _take_or_pay_driver(term: CommercialTerm) -> ModelDriver:
    pct = _param(term, "annual_minimum_pct_of_committed")
    basis = _param(term, "shortfall_basis", "pct_of_committed")
    note = (
        "Annual take-or-pay floor: buyer pays for at least the Annual Minimum "
        "regardless of units taken; the unconditional right to consideration is "
        "recognized when the shortfall obligation crystallizes. Units paid-not-"
        "taken become Banked Units (carry forward; forfeit at term end)."
    )
    if basis != "pct_of_committed":
        note = (
            "Take-or-pay with a non-percentage shortfall mechanism "
            f"(basis={basis!r}); engine treats this as a manual-review driver — "
            "confirm the modeled shortfall with the deal team."
        )
    return ModelDriver(
        driver_id="take_or_pay_floor",
        driver_type=DriverType.REVENUE_FLOOR,
        value=float(pct) if isinstance(pct, (int, float)) else None,
        source_term_id=term.term_id,
        accounting_treatment_note=note,
    )


def _prepayment_driver(term: CommercialTerm) -> ModelDriver:
    amount = _param(term, "amount_usd")
    return ModelDriver(
        driver_id="prepayment_drawdown",
        driver_type=DriverType.DEFERRED_REVENUE_DRAWDOWN,
        value=float(amount) if isinstance(amount, (int, float)) else None,
        source_term_id=term.term_id,
        accounting_treatment_note=(
            "Non-refundable prepayment held as a contract liability and drawn "
            "down against each invoice (default 20% of the invoiced amount) "
            "until exhausted (ASC 606 contract liability)."
        ),
    )


def _payment_terms_driver(term: CommercialTerm, dso: int) -> ModelDriver:
    return ModelDriver(
        driver_id="payment_terms_dso",
        driver_type=DriverType.DSO_WORKING_CAPITAL,
        value=float(dso),
        source_term_id=term.term_id,
        accounting_treatment_note=(
            f"Net-{dso} payment terms drive days-sales-outstanding in the cash "
            "view; collection timing only, no effect on P&L recognition."
        ),
    )


def _mfn_driver(term: CommercialTerm) -> ModelDriver:
    return ModelDriver(
        driver_id="mfn_price_protection",
        driver_type=DriverType.CONTINGENT_MARGIN_RISK,
        source_term_id=term.term_id,
        accounting_treatment_note=(
            "Most-favored-nation price protection (prospective only, no "
            "retroactive refunds); contingent margin risk if a lower-priced "
            "comparable-volume third-party deal is signed."
        ),
    )


def _liability_driver(term: CommercialTerm) -> ModelDriver:
    cap_months = _param(term, "cap_months_of_fees")
    return ModelDriver(
        driver_id="liability_cap",
        driver_type=DriverType.EXPOSURE_CAP,
        value=float(cap_months) if isinstance(cap_months, (int, float)) else None,
        source_term_id=term.term_id,
        accounting_treatment_note=(
            "Liability capped at trailing-12-months fees, with IP-infringement "
            "indemnification and amounts owed for delivered units carved out "
            "(uncapped); consequential damages excluded."
        ),
    )


def _warrant_contra_driver(
    term: CommercialTerm, n_quarters: int, contra_schedule: list[float] | None = None
) -> ModelDriver:
    """Contra-revenue driver for the warrant. `contra_schedule`, when supplied by
    warrant_economics (via compute_economics), is the per-quarter contra-revenue
    allocation; otherwise the slot carries zeros (deterministic-only / no-warrant).
    """
    schedule = list(contra_schedule) if contra_schedule else [0.0] * n_quarters
    populated = bool(contra_schedule) and any(schedule)
    detail = (
        f"Per-quarter contra-revenue total ${sum(schedule):,.0f}."
        if populated else
        "Zero until warrant economics supplies the schedule."
    )
    return ModelDriver(
        driver_id="warrant_contra_revenue",
        driver_type=DriverType.CONTRA_REVENUE,
        schedule=schedule,
        source_term_id=term.term_id,
        accounting_treatment_note=(
            "Warrant issued to the customer = consideration payable to a "
            "customer -> reduction of transaction price / contra-revenue under "
            "ASC 606 (measured under ASC 718). " + detail
        ),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def map_terms_to_drivers(
    pkg: DealPackage,
    assumptions: DealAssumptions,
    dso: int = 90,
    warrant_contra_schedule: list[float] | None = None,
) -> list[ModelDriver]:
    """Build the full driver list for a deal package. Pure: does not mutate
    `pkg` or `assumptions`.

    `dso` is the resolved days-sales-outstanding for the cash view (caller looks
    it up via `assumptions_library.dso_for_payment_terms`); a PAYMENT_TERMS term
    with an explicit `net_days` overrides it.

    `warrant_contra_schedule`, when supplied (by `compute_economics` from
    `warrant_economics`), populates the CONTRA_REVENUE driver's schedule; absent
    it, that driver carries zeros.
    """
    # Cross-model invariant: warrant present => vest-probability list matches.
    validate_assumptions_against_warrant(assumptions, pkg.warrant_terms)

    sched = quarterly_schedule(pkg)
    qpy = quarters_per_year(pkg)
    asp = _resolve_base_asp(pkg)
    n_quarters = len(sched)

    drivers: list[ModelDriver] = []

    if (vc := _first(pkg, TermType.VOLUME_COMMITMENT)) is not None:
        drivers.append(_volume_driver(vc))
    if (rb := _first(pkg, TermType.REBATE)) is not None:
        drivers.append(_rebate_driver(rb, sched, asp, qpy))
    if (top := _first(pkg, TermType.TAKE_OR_PAY)) is not None:
        drivers.append(_take_or_pay_driver(top))
    if (pp := _first(pkg, TermType.PREPAYMENT)) is not None:
        drivers.append(_prepayment_driver(pp))
    if (pt := _first(pkg, TermType.PAYMENT_TERMS)) is not None:
        net_days = _param(pt, "net_days")
        drivers.append(_payment_terms_driver(pt, int(net_days) if net_days else dso))
    if (mfn := _first(pkg, TermType.PRICE_PROTECTION_MFN)) is not None:
        drivers.append(_mfn_driver(mfn))
    if (lia := _first(pkg, TermType.LIABILITY)) is not None:
        drivers.append(_liability_driver(lia))
    if (we := _first(pkg, TermType.WARRANT_EQUITY)) is not None:
        drivers.append(_warrant_contra_driver(we, n_quarters, warrant_contra_schedule))

    return drivers


def _resolve_base_asp(pkg: DealPackage, default: float = 25000.0) -> float:
    """Base ASP from the PRICING term, falling back to the synthetic default."""
    pricing = _first(pkg, TermType.PRICING)
    if pricing is not None:
        asp = _param(pricing, "base_asp_usd")
        if isinstance(asp, (int, float)):
            return float(asp)
    return default


__all__ = [
    "Retroactivity",
    "quarterly_schedule",
    "quarters_per_year",
    "compute_rebate_schedule",
    "rebate_variant_comparison",
    "build_rebate_variants",
    "map_terms_to_drivers",
]
