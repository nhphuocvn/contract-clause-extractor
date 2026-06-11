"""Pydantic schemas for the Deal Economics Copilot.

These models are the contract between extraction, financial-modeling, and UI
layers. Every LLM extraction output is validated against these schemas; every
financial calculation reads and writes them. Downstream modules import from
here — do not duplicate these shapes elsewhere.

Design notes:
- All numeric quantities carry their units in field names (`_usd`, `_pct`,
  `_days`, `_months`, `_years`, `_units`).
- Percentages are stored as decimals in [0, 1], never as 0..100.
- Quarterly schedules are 0-indexed lists; index `i` is the (i+1)-th quarter
  from contract start.
- `extra="forbid"` on closed schemas catches typos in LLM output early.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums (str-backed so JSON-mode LLM output validates cleanly)
# ---------------------------------------------------------------------------


class TermType(str, Enum):
    PRICING = "PRICING"
    VOLUME_COMMITMENT = "VOLUME_COMMITMENT"
    REBATE = "REBATE"
    TAKE_OR_PAY = "TAKE_OR_PAY"
    PREPAYMENT = "PREPAYMENT"
    PAYMENT_TERMS = "PAYMENT_TERMS"
    PRICE_PROTECTION_MFN = "PRICE_PROTECTION_MFN"
    TERMINATION = "TERMINATION"
    LIABILITY = "LIABILITY"
    SUPPLY_COMMITMENT = "SUPPLY_COMMITMENT"
    WARRANT_EQUITY = "WARRANT_EQUITY"
    CROSS_REFERENCE = "CROSS_REFERENCE"
    OTHER = "OTHER"


class DriverType(str, Enum):
    """Financial-model driver categories produced by driver_mapper.

    Each maps to a specific role in economics_engine.py.
    """
    QUARTERLY_UNIT_SCHEDULE = "QUARTERLY_UNIT_SCHEDULE"
    GROSS_TO_NET_WATERFALL = "GROSS_TO_NET_WATERFALL"
    REVENUE_FLOOR = "REVENUE_FLOOR"
    DEFERRED_REVENUE_DRAWDOWN = "DEFERRED_REVENUE_DRAWDOWN"
    DSO_WORKING_CAPITAL = "DSO_WORKING_CAPITAL"
    CONTINGENT_MARGIN_RISK = "CONTINGENT_MARGIN_RISK"
    DOWNSIDE_SCENARIO_INPUT = "DOWNSIDE_SCENARIO_INPUT"
    EXPOSURE_CAP = "EXPOSURE_CAP"
    CONTRA_REVENUE = "CONTRA_REVENUE"
    OTHER = "OTHER"


class ScenarioName(str, Enum):
    BASE = "BASE"
    DOWNSIDE_TAKE_OR_PAY = "DOWNSIDE_TAKE_OR_PAY"
    UPSIDE_VOLUME = "UPSIDE_VOLUME"
    EARLY_TERMINATION = "EARLY_TERMINATION"


class ViewMode(str, Enum):
    """GAAP includes warrant contra-revenue; CASH_COMMERCIAL excludes it."""
    GAAP = "GAAP"
    CASH_COMMERCIAL = "CASH_COMMERCIAL"


# ---------------------------------------------------------------------------
# Constrained primitive aliases
# ---------------------------------------------------------------------------


# Probability / share-of-total values
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]


# ---------------------------------------------------------------------------
# Extracted commercial terms
# ---------------------------------------------------------------------------


class CommercialTerm(BaseModel):
    """One extracted commercial term, traceable back to its source clause."""
    model_config = ConfigDict(extra="forbid")

    term_id: str = Field(
        description="Stable identifier — typically a slugified hash of "
                    "(source_document, source_section, term_type)."
    )
    term_type: TermType
    raw_text: str = Field(
        description="Verbatim excerpt from the source document supporting the "
                    "extracted parameters. Reviewers verify against this."
    )
    source_document: str = Field(
        description="Filename of the document this term was extracted from."
    )
    source_section: str = Field(
        description="Section number or heading where the term was found, e.g. '5' "
                    "or '5. VOLUME REBATES'."
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Term-type-specific structured parameters (units, percentages, "
                    "tier tables, schedules). Shape varies by term_type.",
    )
    confidence: UnitInterval = Field(
        default=1.0,
        description="Extractor confidence in the parameter values. 1.0 = explicit "
                    "in the text; lower = inferred or noisy.",
    )
    ambiguity_flag: bool = Field(
        default=False,
        description="True when the clause is genuinely ambiguous and a parameter "
                    "would require invention to fill in. Prefer flagging over guessing.",
    )
    ambiguity_note: str = Field(
        default="",
        description="Plain-English description of what is ambiguous and why. "
                    "Required when ambiguity_flag is True.",
    )

    @model_validator(mode="after")
    def _ambiguity_note_required_when_flagged(self) -> "CommercialTerm":
        if self.ambiguity_flag and not self.ambiguity_note.strip():
            raise ValueError("ambiguity_note must be non-empty when ambiguity_flag is True")
        return self


# ---------------------------------------------------------------------------
# Warrant-specific structured terms
# ---------------------------------------------------------------------------


class WarrantTranche(BaseModel):
    model_config = ConfigDict(extra="forbid")

    share_count: int = Field(ge=0, description="Shares vesting in this tranche.")
    deployment_milestone_units: int = Field(
        ge=0,
        description="Cumulative GPU units that must be deployed for this tranche to vest.",
    )
    stock_price_hurdle_usd: float | None = Field(
        default=None,
        description="30-day VWAP threshold the seller's stock must clear. None = no hurdle.",
    )
    other_conditions: str = Field(
        default="",
        description="Free-text additional conditions, e.g. buyer-side deployment certification.",
    )


class WarrantTerms(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_shares: int = Field(ge=0)
    exercise_price_usd: float = Field(ge=0.0)
    tranches: list[WarrantTranche]
    expiration_years: int = Field(ge=1)
    transfer_restrictions: str = Field(default="")
    anti_dilution: str = Field(default="")

    @model_validator(mode="after")
    def _tranches_sum_to_total(self) -> "WarrantTerms":
        s = sum(t.share_count for t in self.tranches)
        if self.tranches and s != self.total_shares:
            raise ValueError(
                f"Sum of tranche share_counts ({s}) does not equal total_shares ({self.total_shares})."
            )
        return self


# ---------------------------------------------------------------------------
# Deal package (multi-document container)
# ---------------------------------------------------------------------------


class DocumentRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    document_type: str = Field(
        description="Short label like 'purchase_agreement', 'warrant', 'sow', 'amendment'."
    )
    sha256: str = Field(
        default="",
        description="Hex digest of the file bytes for audit reproducibility. Optional.",
    )


class DealPackage(BaseModel):
    """All documents and extracted terms for a single deal.

    If a CROSS_REFERENCE term names a document that is not in `documents`, the
    referenced name appears in `unresolved_cross_references` so the UI can warn
    'this deal references a Warrant Agreement that has not been uploaded —
    economics are incomplete'.

    The top-level `terms`, `warrant_terms`, and `ad_hoc_drivers` fields hold
    the current working state. `versions` is an append-only history of named
    snapshots; the variance bridge in Phase 8 compares any two entries here.
    """
    model_config = ConfigDict(extra="forbid")

    deal_name: str
    documents: list[DocumentRef]
    terms: list[CommercialTerm] = Field(default_factory=list)
    warrant_terms: WarrantTerms | None = Field(
        default=None,
        description="Populated when a WARRANT_EQUITY term resolves to a parsed warrant document.",
    )
    ad_hoc_drivers: list["AdHocDriver"] = Field(
        default_factory=list,
        description="User-injected line items the extractor did not produce.",
    )
    unresolved_cross_references: list[str] = Field(default_factory=list)
    versions: list["DealVersion"] = Field(
        default_factory=list,
        description="Named, timestamped snapshots of the working state. Use the "
                    "variance bridge (Phase 8) to compare any two.",
    )


# ---------------------------------------------------------------------------
# Financial-model drivers and assumptions
# ---------------------------------------------------------------------------


class DealAssumptions(BaseModel):
    """User-editable financial assumptions. Defaults are sensible UI starting points."""
    model_config = ConfigDict(extra="forbid")

    unit_cogs_usd: float = Field(default=15_000.0, ge=0.0)
    opex_allocation_pct: UnitInterval = Field(default=0.12)
    discount_rate_wacc: UnitInterval = Field(default=0.10)
    tax_rate: UnitInterval = Field(default=0.21)
    current_stock_price_usd: float = Field(default=150.0, ge=0.0)
    assumed_volatility: UnitInterval = Field(
        default=0.45,
        description="Annualized stock volatility for optional Black-Scholes mode.",
    )
    tranche_vest_probabilities: list[UnitInterval] = Field(
        default_factory=list,
        description="Per-tranche probability of vesting, same order as WarrantTerms.tranches. "
                    "Length must equal the number of tranches when warrant_terms is present.",
    )


class ModelDriver(BaseModel):
    model_config = ConfigDict(extra="forbid")

    driver_id: str
    driver_type: DriverType
    value: float | None = Field(
        default=None,
        description="Scalar driver value when applicable (e.g. a DSO in days, an exposure cap in USD).",
    )
    schedule: list[float] = Field(
        default_factory=list,
        description="Quarterly schedule when applicable (units, dollars, or accrual rates).",
    )
    source_term_id: str = Field(
        description="term_id of the CommercialTerm this driver was derived from.",
    )
    accounting_treatment_note: str = Field(
        description="Plain-English note explaining revenue-recognition / accrual / "
                    "contract-liability / contingency treatment.",
    )


class AdHocDriver(BaseModel):
    """A line item injected by the user that the extractor did not produce.

    Use cases: a known side-letter discount, a discretionary marketing credit,
    an internal cost allocation, or any other commercial reality the extractor
    missed or cannot see. Lives alongside `ModelDriver`s in the economics
    engine; carries no `source_term_id` because there is no source term.

    Sign convention: positive `amount_usd` = increase to net revenue or
    margin; negative = decrease.
    """
    model_config = ConfigDict(extra="forbid")

    label: str = Field(
        description="Short human-readable name shown in the model and Excel "
                    "(e.g. 'Side-letter discount Q3', 'OpenCompute marketing credit').",
    )
    amount_usd: float = Field(
        description="Total USD impact across the contract term. Positive increases "
                    "the line; negative decreases it.",
    )
    quarterly_schedule_usd: list[float] = Field(
        default_factory=list,
        description="Per-quarter USD recognition, index 0 = first quarter of the deal. "
                    "If non-empty, must sum to amount_usd within $1 tolerance. "
                    "Empty list means 'engine decides timing'.",
    )
    note: str = Field(
        default="",
        description="Free-text rationale or audit trail — why this line was added, "
                    "who authorized it, what document supports it.",
    )

    @model_validator(mode="after")
    def _schedule_matches_amount(self) -> "AdHocDriver":
        if self.quarterly_schedule_usd:
            total = sum(self.quarterly_schedule_usd)
            if abs(total - self.amount_usd) > 1.0:
                raise ValueError(
                    f"quarterly_schedule_usd sums to {total:.2f} which does not "
                    f"match amount_usd {self.amount_usd:.2f} (>$1 tolerance)."
                )
        return self


# ---------------------------------------------------------------------------
# Economics outputs
# ---------------------------------------------------------------------------


class QuarterRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quarter_index: int = Field(ge=0)
    units: float = 0.0
    gross_revenue: float = 0.0
    rebates: float = 0.0
    warrant_contra_revenue: float = 0.0
    net_revenue: float = 0.0
    cogs: float = 0.0
    gross_margin: float = 0.0
    allocated_opex: float = 0.0
    contribution_margin: float = 0.0


class ScenarioResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: ScenarioName
    view: ViewMode
    quarterly_pl: list[QuarterRow]
    npv_usd: float
    payback_quarters: int | None = None
    total_net_revenue: float
    total_gross_margin: float
    total_gross_margin_pct: float


class SensitivityRow(BaseModel):
    """One row of a one-way sensitivity table (tornado-style)."""
    model_config = ConfigDict(extra="forbid")

    variable: str = Field(description="e.g. 'asp', 'unit_cogs', 'ramp_slip_quarters'.")
    delta_label: str = Field(description="e.g. '-10%', '+10%', '+2 quarters'.")
    total_gross_margin_usd: float
    delta_vs_base_usd: float


class EffectiveAsp(BaseModel):
    """Sticker price vs all-in effective price after rebates and warrant cost."""
    model_config = ConfigDict(extra="forbid")

    sticker_usd: float
    rebate_per_unit_usd: float
    warrant_per_unit_usd: float
    all_in_usd: float


class DealEconomics(BaseModel):
    """Top-level economics output for one deal package."""
    model_config = ConfigDict(extra="forbid")

    assumptions: DealAssumptions
    drivers: list[ModelDriver] = Field(default_factory=list)
    scenarios: list[ScenarioResult] = Field(
        default_factory=list,
        description="Each scenario is emitted twice — once per ViewMode. "
                    "Consumers look up by (scenario, view).",
    )
    sensitivities: list[SensitivityRow] = Field(default_factory=list)
    effective_asp: EffectiveAsp | None = None


# ---------------------------------------------------------------------------
# CRB memo
# ---------------------------------------------------------------------------


class RiskItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term_id: str | None = Field(
        default=None,
        description="CommercialTerm.term_id this risk traces back to, when applicable.",
    )
    description: str
    quantified_exposure_usd: float | None = None
    mitigation: str = Field(
        description="Recommended mitigation or approval condition, in plain English.",
    )


class DealVersion(BaseModel):
    """A named, timestamped snapshot of a deal's terms, warrant, assumptions,
    and ad-hoc drivers.

    Versions are append-only: re-running extraction, editing assumptions, or
    adding an `AdHocDriver` does not mutate prior versions. Phase 8 will
    consume any two versions to compute a per-line variance bridge (revenue,
    margin, NPV deltas with per-driver attribution).

    `created_at` is supplied by the caller rather than auto-stamped so that
    persistence layers control the clock — keeps the schema deterministic
    under serialization and testing.
    """
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        description="Short human-readable label, e.g. 'Initial draft', "
                    "'Post-legal redline', 'Final signed'.",
    )
    created_at: datetime = Field(description="ISO 8601 timestamp set by the caller.")
    terms: list[CommercialTerm] = Field(default_factory=list)
    warrant_terms: WarrantTerms | None = None
    assumptions: DealAssumptions
    ad_hoc_drivers: list[AdHocDriver] = Field(default_factory=list)
    note: str = Field(
        default="",
        description="Free-text annotation — what changed since the prior version, "
                    "who approved this snapshot, links to redline diffs, etc.",
    )


class CRBMemo(BaseModel):
    """Structured payload behind the rendered CRB memo. The LLM writes prose
    from these fields; it never computes the numbers."""
    model_config = ConfigDict(extra="forbid")

    deal_name: str
    summary_lines: list[str] = Field(
        description="3-line deal summary: counterparty / term / committed value & structure.",
        max_length=5,
    )
    economics_table: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Rows for the by-scenario economics table. Pre-formatted dicts so "
                    "the LLM does no math.",
    )
    effective_asp: EffectiveAsp
    top_risks: list[RiskItem] = Field(
        description="Ranked, typically 5 entries. Warrant dilution and MFN should naturally rank high.",
    )
    benchmark_sentences: list[str] = Field(
        default_factory=list,
        description="2-3 plain-English benchmark comparisons from benchmarks.py.",
    )
    recommendation: str
    approval_conditions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Cross-model validators / helpers
# ---------------------------------------------------------------------------


def validate_assumptions_against_warrant(
    assumptions: DealAssumptions, warrant: WarrantTerms | None
) -> None:
    """Enforce the cross-model invariant: when a warrant is present, the
    per-tranche probability list must match the tranche count.

    Called at the boundary where assumptions and warrant terms are combined
    (driver_mapper / warrant_economics) rather than inside DealAssumptions
    itself, because the warrant is not part of DealAssumptions.
    """
    if warrant is None:
        return
    expected = len(warrant.tranches)
    got = len(assumptions.tranche_vest_probabilities)
    if got != expected:
        raise ValueError(
            f"DealAssumptions.tranche_vest_probabilities length ({got}) "
            f"does not match WarrantTerms.tranches length ({expected})."
        )


__all__ = [
    # Enums
    "TermType",
    "DriverType",
    "ScenarioName",
    "ViewMode",
    # Terms
    "CommercialTerm",
    "WarrantTranche",
    "WarrantTerms",
    # Package
    "DocumentRef",
    "DealPackage",
    # Drivers / assumptions
    "DealAssumptions",
    "ModelDriver",
    "AdHocDriver",
    # Versioning
    "DealVersion",
    # Economics
    "QuarterRow",
    "ScenarioResult",
    "SensitivityRow",
    "EffectiveAsp",
    "DealEconomics",
    # Memo
    "RiskItem",
    "CRBMemo",
    # Helpers
    "validate_assumptions_against_warrant",
]
