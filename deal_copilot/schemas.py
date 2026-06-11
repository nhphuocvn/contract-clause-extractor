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


class ProvenanceClass(str, Enum):
    """Source/basis classification for every assumption surfaced in UI and Excel."""
    CONTRACT = "CONTRACT"                   # extracted from the deal documents
    TERM_SHEET = "TERM_SHEET"               # from a non-definitive term sheet or summary
    LIBRARY_DEFAULT = "LIBRARY_DEFAULT"     # filled from assumptions_library.json
    PLACEHOLDER = "PLACEHOLDER"             # unresolved; needs confirmation from a team
    USER_OVERRIDE = "USER_OVERRIDE"         # analyst typed a value over a default


class DealStatus(str, Enum):
    """Pipeline status for the deal registry / dashboard."""
    DRAFT = "DRAFT"
    IN_NEGOTIATION = "IN_NEGOTIATION"
    IN_CRB = "IN_CRB"
    APPROVED = "APPROVED"
    SIGNED = "SIGNED"
    LIVE = "LIVE"
    TERMINATED = "TERMINATED"


class PolicyRuleKind(str, Enum):
    """Kinds of policy rules the CRB engine evaluates against each deal version."""
    MARGIN_FLOOR = "MARGIN_FLOOR"
    DEAL_SIZE_TIER = "DEAL_SIZE_TIER"
    UNCAPPED_LIABILITY = "UNCAPPED_LIABILITY"
    MFN_PRESENT = "MFN_PRESENT"
    WARRANT_PRESENT = "WARRANT_PRESENT"
    PAYMENT_TERMS_THRESHOLD = "PAYMENT_TERMS_THRESHOLD"
    TAKE_OR_PAY_FLOOR = "TAKE_OR_PAY_FLOOR"
    CUSTOM = "CUSTOM"


class PolicyOutcome(str, Enum):
    PASS = "PASS"
    ESCALATE = "ESCALATE"
    BLOCK = "BLOCK"


class DistributionKind(str, Enum):
    """[P2 schema] Distribution kinds for Monte Carlo on uncertain assumptions."""
    NORMAL = "NORMAL"
    TRIANGULAR = "TRIANGULAR"
    UNIFORM = "UNIFORM"
    BETA = "BETA"


# ---------------------------------------------------------------------------
# Constrained primitive aliases
# ---------------------------------------------------------------------------


# Probability / share-of-total values
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]


# ---------------------------------------------------------------------------
# Extracted commercial terms
# ---------------------------------------------------------------------------


class TermVariant(BaseModel):
    """One alternative reading of an ambiguous term.

    When a clause admits two materially different interpretations (the planted
    rebate tier-crossing retroactivity is the canonical example), each reading
    becomes a `TermVariant` with its own parameter dict. The engine models all
    variants in parallel and reports the dollar delta between them — that delta
    drives an Assumption Gap Report line urging the deal team to resolve the
    ambiguity with Legal before signing.
    """
    model_config = ConfigDict(extra="forbid")

    label: str = Field(
        description="Short name for this reading, e.g. "
                    "'tier-crossing prospective' or 'tier-crossing retroactive'.",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Alternative parameter values for this reading. Same shape as "
                    "CommercialTerm.parameters; the engine substitutes these in "
                    "when running this variant.",
    )
    note: str = Field(
        default="",
        description="What contractual interpretation this variant captures and why "
                    "it produces a different model outcome.",
    )


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
    variants: list[TermVariant] = Field(
        default_factory=list,
        description="Alternative readings of the term when it is materially "
                    "ambiguous. Empty list = no quantifiable alternatives. "
                    "Non-empty REQUIRES ambiguity_flag=True.",
    )

    @model_validator(mode="after")
    def _ambiguity_consistency(self) -> "CommercialTerm":
        if self.ambiguity_flag and not self.ambiguity_note.strip():
            raise ValueError("ambiguity_note must be non-empty when ambiguity_flag is True")
        if self.variants and not self.ambiguity_flag:
            raise ValueError(
                "variants is non-empty but ambiguity_flag is False — set "
                "ambiguity_flag=True (and write an ambiguity_note) when supplying "
                "alternative readings."
            )
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

    Registry fields (`deal_id`, `status`, `counterparty`, `archetype`) populate
    the pipeline dashboard. `change_journal` records every term/assumption edit
    for governance and feeds the variance-bridge narrative. `policy_verdicts`
    accumulates one entry per evaluated DealVersion.
    """
    model_config = ConfigDict(extra="forbid")

    deal_name: str
    deal_id: str = Field(
        default="",
        description="Stable registry identifier. Phase 1 callers leave this empty; "
                    "registry-bound deals populate it from a UUID or slug.",
    )
    counterparty: str = Field(default="")
    status: DealStatus = Field(default=DealStatus.DRAFT)
    archetype: str | None = Field(
        default=None,
        description="If this deal was created by cloning a template (e.g. "
                    "'hyperscaler_gigawatt'), record the archetype label here.",
    )
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
    change_journal: list["ChangeJournalEntry"] = Field(
        default_factory=list,
        description="Append-only audit trail of every term/assumption edit on this "
                    "deal. Exported to the Excel Changelog tab.",
    )
    policy_verdicts: list["PolicyVerdict"] = Field(
        default_factory=list,
        description="One entry per evaluated DealVersion. Latest verdict is the "
                    "one shown on the pipeline dashboard and CRB memo.",
    )


# ---------------------------------------------------------------------------
# Financial-model drivers and assumptions
# ---------------------------------------------------------------------------


class AssumptionProvenance(BaseModel):
    """The source/basis of one assumption, surfaced in UI and the Excel
    Assumptions tab's Source/Basis column.

    Stored alongside `DealAssumptions` in a parallel `dict[str, AssumptionProvenance]`
    keyed by dotted field path (e.g. `"unit_cogs_usd"`,
    `"capacity_bridge.pue"`, `"generation_tranches[0].base_asp_usd"`). Keeps
    scalar assumption fields ergonomic for engine code while letting the UI/Excel
    layer render provenance badges and coverage gaps.
    """
    model_config = ConfigDict(extra="forbid")

    value: Any = Field(
        description="The actual assumption value at the time provenance was recorded. "
                    "Stored here for audit (compare against current scalar to detect drift).",
    )
    basis: ProvenanceClass
    note: str = Field(
        default="",
        description="Free-text source citation, e.g. 'contract §4', 'industry default — "
                    "Synergy Research Q1 2026', 'confirm with cost accounting'.",
    )
    as_of: datetime = Field(
        description="ISO 8601 timestamp set by the caller — when this provenance "
                    "was recorded (not when the schema was constructed).",
    )


class CapacityBridgeInputs(BaseModel):
    """Optional input mode: derive units from a gigawatt power commitment.

    Real hyperscaler GPU deals are sized in power, not unit counts. When this
    bridge is populated on a `DealAssumptions`, the engine computes units via
    `derived_units()` instead of using an explicit unit total. Unit-denominated
    deals leave `capacity_bridge=None` and the engine uses the explicit count.
    """
    model_config = ConfigDict(extra="forbid")

    total_power_gw: float = Field(gt=0.0, description="Committed power, gigawatts.")
    power_per_gpu_watts: float = Field(
        gt=0.0, description="Nameplate power draw per GPU, watts."
    )
    pue: float = Field(
        gt=0.0,
        description="Power-usage-effectiveness ratio. 1.0 = no overhead (ideal); "
                    "typical hyperscaler data centers run 1.1–1.5.",
    )

    def derived_units(self) -> int:
        """Units implied by `(total_power_gw × 1e9) / (power_per_gpu_watts × pue)`."""
        return int((self.total_power_gw * 1e9) / (self.power_per_gpu_watts * self.pue))


class GenerationTranche(BaseModel):
    """A GPU generation segment within a multi-year deal.

    Multi-year power commitments span GPU generations (Gen A in years 1–2, Gen
    B in years 3–5). Each generation carries its own ASP, power profile, and
    COGS learning curve. Schema-only in step 0; consumed by the engine when
    multi-generation modeling lands (P1, Phase 3).
    """
    model_config = ConfigDict(extra="forbid")

    generation_label: str = Field(
        description="Short label, e.g. 'Gen A (MI355X)', 'Gen B (MI400)'."
    )
    quarter_start: int = Field(ge=0, description="0-indexed first quarter (inclusive).")
    quarter_end: int = Field(ge=0, description="0-indexed last quarter (inclusive).")
    base_asp_usd: float = Field(ge=0.0)
    power_per_gpu_watts: float = Field(gt=0.0)
    cogs_curve_per_year_usd: list[float] = Field(
        default_factory=list,
        description="Per-year unit COGS for this generation; learning-curve decline. "
                    "Empty list = engine falls back to DealAssumptions.unit_cogs_usd.",
    )
    supply_capacity_per_quarter_units: int | None = Field(
        default=None,
        description="Assumed quarterly supply ceiling for this generation. None = no "
                    "ceiling; otherwise the feasibility check (P1) flags ramp "
                    "quarters that exceed it.",
    )

    @model_validator(mode="after")
    def _quarters_ordered(self) -> "GenerationTranche":
        if self.quarter_end < self.quarter_start:
            raise ValueError(
                f"quarter_end ({self.quarter_end}) must be >= quarter_start ({self.quarter_start})."
            )
        return self


class ScenarioProbability(BaseModel):
    """User-set probability for one scenario in the probability-weighted view."""
    model_config = ConfigDict(extra="forbid")

    scenario: ScenarioName
    probability: UnitInterval


class DistributionSpec(BaseModel):
    """[P2 schema] Distribution specification for Monte Carlo on an assumption.

    Schema-only in step 0. The engine is pure (no I/O, no globals) so Monte
    Carlo becomes a thin sampling layer in Phase 10 without further schema work.
    """
    model_config = ConfigDict(extra="forbid")

    parameter_path: str = Field(
        description="Dotted path of the assumption this distribution covers, "
                    "e.g. 'unit_cogs_usd', 'generation_tranches[1].base_asp_usd'.",
    )
    kind: DistributionKind
    parameters: dict[str, float] = Field(
        default_factory=dict,
        description="Kind-specific parameters: {mean,std} for NORMAL; "
                    "{low,mode,high} for TRIANGULAR; {low,high} for UNIFORM; "
                    "{alpha,beta,low,high} for BETA.",
    )


class DealAssumptions(BaseModel):
    """User-editable financial assumptions. Defaults are sensible UI starting points.

    Provenance for any populated assumption lives in `assumption_provenance`,
    keyed by the assumption's attribute name (dotted for nested paths). The
    parallel-map approach keeps scalar reads ergonomic for engine code while
    letting the UI and Excel layers render source/basis badges and coverage
    warnings. Nothing in this model enforces full provenance coverage — that's
    a policy/UI concern (Phase 6).
    """
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
    capacity_bridge: CapacityBridgeInputs | None = Field(
        default=None,
        description="When set, engine derives units from power instead of an "
                    "explicit unit count. None = unit-mode (the default).",
    )
    generation_tranches: list[GenerationTranche] = Field(
        default_factory=list,
        description="GPU-generation segments for multi-year deals (P1). Empty = "
                    "single-generation deal using top-level scalars.",
    )
    scenario_probabilities: list[ScenarioProbability] = Field(
        default_factory=list,
        description="User-set probability weights per scenario. Empty = engine uses "
                    "equal weights when computing probability-weighted expected value. "
                    "Sum is not enforced at construction (allows in-progress edits); "
                    "the engine warns at consumption if sum ∉ [0.99, 1.01].",
    )
    assumption_provenance: dict[str, AssumptionProvenance] = Field(
        default_factory=dict,
        description="Parallel map: attribute name (dotted for nested) → "
                    "AssumptionProvenance. Coverage is NOT enforced at construction.",
    )
    distribution_specs: list[DistributionSpec] = Field(
        default_factory=list,
        description="[P2 schema-only] Monte Carlo distributions on selected assumptions. "
                    "No engine consumption yet.",
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
# Change journal (audit / governance)
# ---------------------------------------------------------------------------


class ChangeJournalEntry(BaseModel):
    """One audit-trail entry for an edit to a term or assumption on a deal.

    Caller supplies the timestamp so the schema stays deterministic under tests
    and so a persistence layer can backfill historical entries with their
    original times rather than now().
    """
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime = Field(description="ISO 8601 set by the caller.")
    field_path: str = Field(
        description="Dotted/indexed path of the changed field, e.g. "
                    "'assumptions.unit_cogs_usd', 'terms[REBATE].parameters.tiers[1].pct'.",
    )
    old_value: Any | None = Field(default=None)
    new_value: Any | None = Field(default=None)
    note: str = Field(default="", description="Free-text rationale.")
    actor: str = Field(
        default="",
        description="Who made the change (user id, email, or system label). "
                    "Empty when the source is anonymous or batch.",
    )


# ---------------------------------------------------------------------------
# Policy / CRB routing
# ---------------------------------------------------------------------------


class PolicyRule(BaseModel):
    """One configurable CRB rule loaded from `data/crb_policy.json`.

    Rule evaluation logic lives in the policy engine (Phase 6); this schema
    only carries the rule's identity, parameters, and approver mapping.
    """
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(description="Stable rule identifier, e.g. 'margin_floor_45'.")
    kind: PolicyRuleKind
    description: str
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Kind-specific parameters: e.g. {threshold_pct: 0.45} for "
                    "MARGIN_FLOOR; {tiers: [{max_usd: 100_000_000, approvers: ['VP']}]} "
                    "for DEAL_SIZE_TIER.",
    )
    required_approvers_on_breach: list[str] = Field(
        default_factory=list,
        description="Approvers required if this rule escalates or blocks (e.g. 'CFO', "
                    "'General Counsel'). Joined into a deal's "
                    "PolicyVerdict.all_required_approvers.",
    )


class PolicyRuleResult(BaseModel):
    """The verdict for one rule against one DealVersion."""
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    outcome: PolicyOutcome
    reason: str = Field(
        description="Plain-English explanation, e.g. 'blended margin 43.8% below 45% floor'.",
    )
    required_approvers: list[str] = Field(default_factory=list)


class PolicyVerdict(BaseModel):
    """All rule results for one DealVersion, plus the aggregated outcome and
    approver list. Immutable — re-evaluation produces a new verdict; old ones
    stay on the package for audit.

    Keys on `(deal_id, version_name)` rather than holding a reference to a
    `DealVersion` object so that renaming a version cannot break historical
    verdicts.
    """
    model_config = ConfigDict(extra="forbid")

    deal_id: str
    version_name: str
    evaluated_at: datetime = Field(description="ISO 8601 set by the caller.")
    rule_results: list[PolicyRuleResult]
    overall_outcome: PolicyOutcome
    all_required_approvers: list[str] = Field(
        default_factory=list,
        description="Union of required_approvers across escalating/blocking rules. "
                    "De-duplicated; preserves insertion order.",
    )


# ---------------------------------------------------------------------------
# Deal registry (pipeline dashboard)
# ---------------------------------------------------------------------------


class DealRecord(BaseModel):
    """Registry-level summary of one deal — the row shown on the pipeline
    dashboard. Derived from a DealPackage plus its latest economics output;
    not embedded inside DealPackage (keeps the package free of
    economics-derived fields).
    """
    model_config = ConfigDict(extra="forbid")

    deal_id: str
    deal_name: str
    counterparty: str = Field(default="")
    status: DealStatus = Field(default=DealStatus.DRAFT)
    committed_value_usd: float | None = Field(default=None)
    blended_gross_margin_pct: float | None = Field(default=None)
    npv_usd: float | None = Field(default=None)
    pending_review_count: int = Field(default=0, ge=0)
    last_updated: datetime = Field(description="ISO 8601 set by the caller.")
    archetype: str | None = Field(default=None)


# ---------------------------------------------------------------------------
# Future (P2 schema only)
# ---------------------------------------------------------------------------


class ActualsRecord(BaseModel):
    """[P2 schema] Post-signing actuals for one (deal, quarter). Schema-only;
    no consumers in step 0. Phase 10 will compare these against the model's
    base-case forecast to produce a forecast-accuracy retro.
    """
    model_config = ConfigDict(extra="forbid")

    deal_id: str
    quarter_index: int = Field(ge=0)
    actual_units: int | None = Field(default=None, ge=0)
    actual_revenue_usd: float | None = Field(default=None)
    actual_cogs_usd: float | None = Field(default=None)
    note: str = Field(default="")


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
    "ProvenanceClass",
    "DealStatus",
    "PolicyRuleKind",
    "PolicyOutcome",
    "DistributionKind",
    # Terms (+ ambiguity variants)
    "TermVariant",
    "CommercialTerm",
    "WarrantTranche",
    "WarrantTerms",
    # Package
    "DocumentRef",
    "DealPackage",
    # Drivers / assumptions (+ provenance, capacity, multi-gen, probability, distribution)
    "AssumptionProvenance",
    "CapacityBridgeInputs",
    "GenerationTranche",
    "ScenarioProbability",
    "DistributionSpec",
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
    # Change journal (audit)
    "ChangeJournalEntry",
    # Memo
    "RiskItem",
    "CRBMemo",
    # Policy / CRB
    "PolicyRule",
    "PolicyRuleResult",
    "PolicyVerdict",
    # Registry / pipeline
    "DealRecord",
    # Future (P2 schema)
    "ActualsRecord",
    # Helpers
    "validate_assumptions_against_warrant",
]
