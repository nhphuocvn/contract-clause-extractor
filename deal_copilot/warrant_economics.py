"""Warrant economics — valuing the equity given to the customer.

A warrant issued to a customer is *consideration payable to a customer* → a
reduction of transaction price (contra-revenue) under ASC 606, measured at fair
value under ASC 718. This module computes that value and produces the
contra-revenue schedule that fills the engine's CONTRA_REVENUE slot (wired with
zeros in Phase 3).

Pure module: no I/O, no globals, no mutation of inputs. Imports `driver_mapper`
for the cumulative-band allocation and the rebate-per-unit figure; it does NOT
import `economics_engine` (the engine imports this module — keeping the arrow
one-way avoids a cycle).

Contract facts vs judgment (governance):
- Contract facts live on `WarrantTerms`: shares, exercise price, tranche
  milestones and stock-price hurdles, expiration.
- JUDGMENT inputs live on `DealAssumptions`: `tranche_vest_probabilities` (will
  this milestone vest?) and `warrant_measurement_price_usd` (the assumed
  measurement price; falls back to `current_stock_price_usd`). These are
  strategic estimates — `assumption_provenance_overrides` stamps them PLACEHOLDER
  with a "confirm with deal team" note.

Because the value turns on judgment, it is reported as a RANGE across three
vest-probability sets (conservative / base / aggressive), not a single point.

Valuation: a near-zero-strike warrant is deep-in-the-money free stock, so the
default intrinsic mode uses fair value per share = measurement price - exercise
price. A Black-Scholes mode is provided as a clearly-labeled illustrative
alternative.
"""

from __future__ import annotations

import math
from datetime import datetime

from deal_copilot import driver_mapper as dm
from deal_copilot.schemas import (
    AssumptionProvenance,
    DealAssumptions,
    DealPackage,
    EffectiveAsp,
    ProvenanceClass,
    TermType,
    WarrantEconomics,
    WarrantProbabilityScenario,
    WarrantTerms,
    WarrantTrancheValuation,
    WarrantValueAtPrice,
    validate_assumptions_against_warrant,
)


# Vest-probability judgment sets driving the expected-value range.
CONSERVATIVE_VEST_PROBABILITIES = [0.7, 0.5, 0.3, 0.1]
BASE_VEST_PROBABILITIES = [0.9, 0.7, 0.5, 0.3]
AGGRESSIVE_VEST_PROBABILITIES = [1.0, 0.9, 0.7, 0.4]

JUDGMENT_BASIS_NOTE = "strategic estimate - confirm with deal team"
DEFAULT_PRICE_LEVELS = (300.0, 470.0, 600.0)


# ---------------------------------------------------------------------------
# Core valuation
# ---------------------------------------------------------------------------


def measurement_price(assumptions: DealAssumptions) -> float:
    """The judgment measurement stock price: the dedicated field if set,
    otherwise the current spot price."""
    if assumptions.warrant_measurement_price_usd is not None:
        return assumptions.warrant_measurement_price_usd
    return assumptions.current_stock_price_usd


def per_share_fair_value(price: float, exercise_price_usd: float) -> float:
    """Intrinsic fair value per share = max(0, measurement price - strike)."""
    return max(0.0, price - exercise_price_usd)


def black_scholes_call(
    spot: float, strike: float, years: float, volatility: float, risk_free_rate: float
) -> float:
    """Illustrative Black-Scholes European call value (per share). Uses math.erf
    for the standard-normal CDF (no scipy). Labeled illustrative because the
    warrant's near-zero strike makes it deep ITM, where BS ≈ intrinsic."""
    if years <= 0 or volatility <= 0 or spot <= 0 or strike <= 0:
        return max(0.0, spot - strike)
    vol_sqrt_t = volatility * math.sqrt(years)
    d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * volatility ** 2) * years) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    norm_cdf = lambda x: 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
    return spot * norm_cdf(d1) - strike * math.exp(-risk_free_rate * years) * norm_cdf(d2)


def _vest_probabilities(warrant: WarrantTerms, assumptions: DealAssumptions) -> list[float]:
    """The deal's chosen vest probabilities, falling back to the base set."""
    if assumptions.tranche_vest_probabilities:
        return list(assumptions.tranche_vest_probabilities)
    return BASE_VEST_PROBABILITIES[: len(warrant.tranches)]


def tranche_valuations(
    warrant: WarrantTerms, vest_probabilities: list[float], price: float
) -> list[WarrantTrancheValuation]:
    """Per-tranche valuation at the given measurement price and vest set."""
    psf = per_share_fair_value(price, warrant.exercise_price_usd)
    out: list[WarrantTrancheValuation] = []
    for i, (tr, prob) in enumerate(zip(warrant.tranches, vest_probabilities)):
        gross = tr.share_count * psf
        out.append(WarrantTrancheValuation(
            tranche_index=i,
            share_count=tr.share_count,
            exercise_price_usd=warrant.exercise_price_usd,
            stock_price_hurdle_usd=tr.stock_price_hurdle_usd,
            deployment_milestone_units=tr.deployment_milestone_units,
            vest_probability=prob,
            fair_value_per_share_usd=psf,
            gross_fair_value_usd=gross,
            expected_fair_value_usd=gross * prob,
        ))
    return out


def total_expected_fair_value(
    warrant: WarrantTerms, vest_probabilities: list[float], price: float
) -> float:
    return sum(v.expected_fair_value_usd for v in tranche_valuations(warrant, vest_probabilities, price))


def expected_value_range(
    warrant: WarrantTerms, price: float
) -> list[WarrantProbabilityScenario]:
    """Conservative / base / aggressive vest-probability sets and the total
    expected warrant value each yields — the value shown as a range."""
    n = len(warrant.tranches)
    sets = [
        ("conservative", CONSERVATIVE_VEST_PROBABILITIES[:n]),
        ("base", BASE_VEST_PROBABILITIES[:n]),
        ("aggressive", AGGRESSIVE_VEST_PROBABILITIES[:n]),
    ]
    return [
        WarrantProbabilityScenario(
            label=label,
            probabilities=probs,
            total_expected_fair_value_usd=total_expected_fair_value(warrant, probs, price),
        )
        for label, probs in sets
    ]


# ---------------------------------------------------------------------------
# Contra-revenue schedule (fills the engine slot)
# ---------------------------------------------------------------------------


def _deployment_bands(
    warrant: WarrantTerms, vest_probabilities: list[float], price: float
) -> list[tuple[float, float, float]]:
    """Per-tranche deployment band as (lower_units, upper_units, per_unit_fv).

    Each tranche's expected fair value is spread over the cumulative-unit band
    from the previous milestone to its own milestone."""
    vals = sorted(
        tranche_valuations(warrant, vest_probabilities, price),
        key=lambda v: v.deployment_milestone_units,
    )
    bands: list[tuple[float, float, float]] = []
    prev = 0.0
    for v in vals:
        hi = float(v.deployment_milestone_units)
        width = hi - prev
        per_unit = v.expected_fair_value_usd / width if width > 0 else 0.0
        bands.append((prev, hi, per_unit))
        prev = hi
    return bands


def _allocate(lo: float, hi: float, bands: list[tuple[float, float, float]]) -> float:
    """Contra for cumulative units in (lo, hi]: sum over band overlaps."""
    total = 0.0
    for blo, bhi, per_unit in bands:
        overlap = max(0.0, min(hi, bhi) - max(lo, blo))
        total += overlap * per_unit
    return total


def contra_revenue_schedule(
    warrant: WarrantTerms,
    assumptions: DealAssumptions,
    quarterly_units: list[float],
) -> list[float]:
    """Per-quarter contra-revenue: the deal's expected warrant fair value
    allocated across each tranche's deployment band, by the units delivered each
    quarter that fall in that band. Sums to the deal's total expected fair value
    when deployment reaches the final milestone."""
    price = measurement_price(assumptions)
    probs = _vest_probabilities(warrant, assumptions)
    bands = _deployment_bands(warrant, probs, price)
    out: list[float] = []
    cum = 0.0
    for u in quarterly_units:
        out.append(_allocate(cum, cum + u, bands))
        cum += u
    return out


# ---------------------------------------------------------------------------
# Dilution / asymmetry
# ---------------------------------------------------------------------------


def dilution_pct(total_shares: int, shares_outstanding: float | None) -> float | None:
    """Warrant shares as a fraction of the seller's shares outstanding."""
    if not shares_outstanding:
        return None
    return total_shares / shares_outstanding


def value_at_price_levels(
    warrant: WarrantTerms, price_levels: tuple[float, ...]
) -> list[WarrantValueAtPrice]:
    """Total intrinsic value transferred (all shares) at each assumed price —
    the asymmetry callout."""
    out: list[WarrantValueAtPrice] = []
    for p in price_levels:
        psf = per_share_fair_value(p, warrant.exercise_price_usd)
        out.append(WarrantValueAtPrice(
            stock_price_usd=p, total_intrinsic_value_usd=warrant.total_shares * psf,
        ))
    return out


# ---------------------------------------------------------------------------
# Judgment-field provenance
# ---------------------------------------------------------------------------


def judgment_provenance(
    assumptions: DealAssumptions, as_of: datetime
) -> dict[str, AssumptionProvenance]:
    """Provenance entries stamping the two warrant judgment inputs as PLACEHOLDER
    ('confirm with deal team'). Returned for the caller to merge into
    `DealAssumptions.assumption_provenance` — kept out of mutation here so the
    module stays pure."""
    return {
        "tranche_vest_probabilities": AssumptionProvenance(
            value=list(assumptions.tranche_vest_probabilities),
            basis=ProvenanceClass.PLACEHOLDER, note=JUDGMENT_BASIS_NOTE, as_of=as_of,
        ),
        "warrant_measurement_price_usd": AssumptionProvenance(
            value=measurement_price(assumptions),
            basis=ProvenanceClass.PLACEHOLDER, note=JUDGMENT_BASIS_NOTE, as_of=as_of,
        ),
    }


# ---------------------------------------------------------------------------
# Effective ASP / top-level
# ---------------------------------------------------------------------------


def _rebate_per_unit(pkg: DealPackage, total_units: float, asp: float) -> float:
    """Prospective rebate per unit, via driver_mapper (0 if no rebate term)."""
    rebate_term = dm._first(pkg, TermType.REBATE)
    if rebate_term is None or total_units <= 0:
        return 0.0
    sched = dm.compute_rebate_schedule(
        dm._normalize_tiers(rebate_term),
        dm.quarterly_schedule(pkg), asp, "prospective", dm.quarters_per_year(pkg),
    )
    return sum(sched) / total_units


def compute_warrant_economics(
    pkg: DealPackage,
    assumptions: DealAssumptions,
    price_levels: tuple[float, ...] = DEFAULT_PRICE_LEVELS,
) -> WarrantEconomics:
    """Full warrant economics for a package's warrant terms. Raises via
    `validate_assumptions_against_warrant` if the vest-probability count does not
    match the tranche count."""
    warrant = pkg.warrant_terms
    if warrant is None:
        raise ValueError("compute_warrant_economics requires pkg.warrant_terms to be set.")
    validate_assumptions_against_warrant(assumptions, warrant)

    price = measurement_price(assumptions)
    probs = _vest_probabilities(warrant, assumptions)
    units = dm.quarterly_schedule(pkg)
    asp = dm._resolve_base_asp(pkg)
    total_units = sum(units)

    tranche_vals = tranche_valuations(warrant, probs, price)
    total_exp = sum(v.expected_fair_value_usd for v in tranche_vals)
    contra = contra_revenue_schedule(warrant, assumptions, units)
    contra_total = sum(contra)

    gross = total_units * asp
    rebate_per_unit = _rebate_per_unit(pkg, total_units, asp)
    rebate_total = rebate_per_unit * total_units
    cash_net = gross - rebate_total
    gaap_net = cash_net - contra_total
    warrant_per_unit = contra_total / total_units if total_units else 0.0

    eff = EffectiveAsp(
        sticker_usd=asp,
        rebate_per_unit_usd=rebate_per_unit,
        warrant_per_unit_usd=warrant_per_unit,
        all_in_usd=asp - rebate_per_unit - warrant_per_unit,
    )

    levels = value_at_price_levels(warrant, price_levels)
    asymmetry = (
        f"Warrant cost rises with the seller's own stock success: at "
        f"${price_levels[0]:,.0f} the warrant transfers "
        f"${levels[0].total_intrinsic_value_usd/1e9:,.2f}B, rising to "
        f"${levels[-1].total_intrinsic_value_usd/1e9:,.2f}B at "
        f"${price_levels[-1]:,.0f} - an asymmetric cost that grows precisely "
        f"when the deal looks most successful."
    )

    return WarrantEconomics(
        valuation_mode="intrinsic",
        measurement_price_usd=price,
        tranche_valuations=tranche_vals,
        total_expected_fair_value_usd=total_exp,
        expected_value_range=expected_value_range(warrant, price),
        contra_revenue_schedule_usd=contra,
        effective_asp=eff,
        cash_net_revenue_usd=cash_net,
        gaap_net_revenue_usd=gaap_net,
        warrant_contra_bridge_usd=cash_net - gaap_net,
        dilution_pct_of_shares_outstanding=dilution_pct(warrant.total_shares, assumptions.shares_outstanding),
        value_at_price_levels=levels,
        asymmetry_note=asymmetry,
    )


__all__ = [
    "CONSERVATIVE_VEST_PROBABILITIES",
    "BASE_VEST_PROBABILITIES",
    "AGGRESSIVE_VEST_PROBABILITIES",
    "measurement_price",
    "per_share_fair_value",
    "black_scholes_call",
    "tranche_valuations",
    "total_expected_fair_value",
    "expected_value_range",
    "contra_revenue_schedule",
    "dilution_pct",
    "value_at_price_levels",
    "judgment_provenance",
    "compute_warrant_economics",
]
