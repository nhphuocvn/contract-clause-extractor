"""Assumption Gap Report (§9.6) — ranked clarifying questions for the deal team,
each with the dollar sensitivity of the unknown and the owner who resolves it.

Pure. Draws from two sources:
  1. The Assumption Register (§5): every input typed market_data or
     strategic_judgment, or carrying a placeholder provenance, becomes a gap
     line addressed to its named owner. (Policy numbers — WACC, tax — are NOT
     gaps; they are set by a function, not unknown.)
  2. Ambiguous terms: a term with quantifiable alternative readings becomes a
     gap line for the dollar delta between readings — the rebate tier-crossing
     retroactivity ($41.0M prospective vs retroactive) is the canonical case.

Dollar sensitivities reuse the pure engine (the tornado for COGS, the warrant
expected-value range width for the warrant judgment inputs). Inputs whose
sensitivity is not separately quantified still produce a line (ranked last) so
nothing requiring confirmation is silently dropped.
"""

from __future__ import annotations

from deal_copilot import driver_mapper as dm
from deal_copilot import economics_engine as ee
from deal_copilot.assumption_register import build_register
from deal_copilot.schemas import (
    AssumptionGapLine,
    AssumptionType,
    DealAssumptions,
    DealEconomics,
    DealPackage,
    ProvenanceClass,
    RegisterEntry,
    TermType,
    WarrantEconomics,
)

_GAP_TYPES = {AssumptionType.MARKET_DATA, AssumptionType.STRATEGIC_JUDGMENT}


def _cogs_sensitivity(econ: DealEconomics) -> float | None:
    deltas = [abs(r.delta_vs_base_usd) for r in econ.sensitivities if r.variable == "unit_cogs"]
    return max(deltas) if deltas else None


def _warrant_range_width(warrant_econ: WarrantEconomics | None) -> float | None:
    if warrant_econ is None or not warrant_econ.expected_value_range:
        return None
    totals = [s.total_expected_fair_value_usd for s in warrant_econ.expected_value_range]
    return max(totals) - min(totals)


def _is_gap(entry: RegisterEntry) -> bool:
    return entry.assumption_type in _GAP_TYPES or entry.basis == ProvenanceClass.PLACEHOLDER


def _register_line(entry: RegisterEntry, sensitivity: float | None) -> AssumptionGapLine:
    type_word = entry.assumption_type.value.lower().replace("_", " ")
    if sensitivity is not None:
        basis = f"{type_word} input; sensitivity ${sensitivity / 1e6:,.1f}M."
        question = (
            f"{entry.label} is a {type_word} input (owner {entry.owner}); confirm it — "
            f"its uncertainty moves the deal by ${sensitivity / 1e6:,.1f}M."
        )
    else:
        basis = f"{type_word} input; sensitivity not separately quantified."
        question = (
            f"{entry.label} is a {type_word} input (owner {entry.owner}); confirm before "
            f"relying on it."
        )
    return AssumptionGapLine(
        question=question,
        field_path=entry.field_path,
        owner=entry.owner,
        dollar_sensitivity_usd=sensitivity,
        basis_note=basis,
    )


def _rebate_ambiguity_line(pkg: DealPackage) -> AssumptionGapLine | None:
    rebate = dm._first(pkg, TermType.REBATE)
    if rebate is None or not rebate.ambiguity_flag:
        return None
    inp = ee.extract_inputs(pkg)
    cmp = dm.rebate_variant_comparison(
        rebate, list(inp.committed_quarterly), inp.base_asp, inp.qpy
    )
    delta = abs(float(cmp["delta_usd"]))
    return AssumptionGapLine(
        question=(
            f"Rebate tier-crossing retroactivity is unspecified (§{rebate.source_section}); "
            f"prospective vs retroactive-within-year readings differ by ${delta / 1e6:,.1f}M "
            f"over the term. Resolve with Legal before signature."
        ),
        field_path=f"terms[{rebate.term_type.value}].variants",
        owner="Legal",
        dollar_sensitivity_usd=delta,
        basis_note="Ambiguity delta from rebate_variant_comparison (prospective vs retroactive).",
    )


def build_gap_report(
    pkg: DealPackage,
    assumptions: DealAssumptions,
    econ: DealEconomics,
    *,
    register: list[RegisterEntry] | None = None,
    warrant_econ: WarrantEconomics | None = None,
) -> list[AssumptionGapLine]:
    """Ranked gap lines (descending by dollar sensitivity; unquantified last)."""
    register = register or build_register(
        assumptions, terms=pkg.terms, warrant_terms=pkg.warrant_terms
    )
    cogs_sens = _cogs_sensitivity(econ)
    warrant_sens = _warrant_range_width(warrant_econ)

    lines: list[AssumptionGapLine] = []
    for entry in register:
        if not _is_gap(entry):
            continue
        if entry.field_path == "assumptions.unit_cogs_usd":
            sens = cogs_sens
        elif entry.field_path == "assumptions.warrant_measurement_price_usd":
            sens = warrant_sens
        else:
            sens = None
        lines.append(_register_line(entry, sens))

    rebate_line = _rebate_ambiguity_line(pkg)
    if rebate_line is not None:
        lines.append(rebate_line)

    # Rank by dollar sensitivity descending; unquantified (None) last.
    lines.sort(key=lambda gl: (gl.dollar_sensitivity_usd is not None, gl.dollar_sensitivity_usd or 0.0), reverse=True)
    return lines


__all__ = ["build_gap_report"]
