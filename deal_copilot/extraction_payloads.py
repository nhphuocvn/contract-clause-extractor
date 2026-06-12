"""Typed payload schemas for the three highest-stakes TermTypes.

The extractor calls `chat.completions.parse(response_format=<Payload>)` for
REBATE, VOLUME_COMMITMENT, and TAKE_OR_PAY — Pydantic enforces the parameter
shape at output time, not via prompt discipline alone. The orchestrator then
copies the validated payload's `model_dump()` into a freshly-constructed
`CommercialTerm.parameters` so downstream consumers see a uniform shape.

The fourth strict-schema case is the warrant document, which uses the
existing `schemas.WarrantTerms` directly as `response_format` — no new payload
class needed.

For the remaining 9 term types, the extractor uses `CommercialTerm` directly
(with `parameters: dict[str, Any]`) and relies on prompt discipline + the
deterministic validators in `validators.py` for shape enforcement.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# REBATE
# ---------------------------------------------------------------------------


class RebateTier(BaseModel):
    """One tier in a volume-rebate table."""
    model_config = ConfigDict(extra="forbid")

    threshold_cumulative_units: int = Field(
        ge=0,
        description="Cumulative GPU units at or above which this tier's pct applies.",
    )
    pct_off_base_asp: float = Field(
        ge=0.0, le=0.5,
        description="Decimal in [0, 0.5]. Bound at 0.5 because anything ≥50% rebate "
                    "is implausible and likely a misextraction.",
    )


class RebatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tiers: list[RebateTier] = Field(
        description="Ordered by ascending threshold_cumulative_units. Empty list "
                    "is not allowed for a REBATE term — if extraction finds no "
                    "tiers, the orchestrator should not produce a REBATE term at all.",
    )
    settlement_cadence: str = Field(
        description="snake_case label, e.g. 'annual_in_arrears', 'quarterly_in_arrears'.",
    )
    settlement_window_days: int | None = Field(
        default=None,
        ge=0, le=365,
        description="Days after the settlement period within which the rebate is paid.",
    )
    measurement_basis: str | None = Field(
        default=None,
        description="How cumulative volume is measured, e.g. 'cumulative_since_effective_date'.",
    )

    @field_validator("tiers")
    @classmethod
    def _tiers_sorted_and_distinct(cls, v: list[RebateTier]) -> list[RebateTier]:
        if not v:
            raise ValueError("REBATE term must have at least one tier.")
        thresholds = [t.threshold_cumulative_units for t in v]
        if thresholds != sorted(thresholds):
            raise ValueError(
                f"tiers must be sorted by ascending threshold_cumulative_units; "
                f"got {thresholds}"
            )
        if len(set(thresholds)) != len(thresholds):
            raise ValueError(f"tier thresholds must be distinct; got {thresholds}")
        return v


# ---------------------------------------------------------------------------
# VOLUME_COMMITMENT
# ---------------------------------------------------------------------------


class VolumeCommitmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_units: int = Field(
        ge=0,
        description="Aggregate committed GPU units over the contract term.",
    )
    term_years: int | None = Field(
        default=None,
        ge=1, le=20,
        description="Contract term in whole years, if stated.",
    )
    quarterly_schedule_units: list[int] = Field(
        default_factory=list,
        description="Per-quarter delivery quantities, index 0 = first quarter. "
                    "When non-empty, must sum to total_units; the model validator "
                    "enforces this.",
    )

    @field_validator("quarterly_schedule_units")
    @classmethod
    def _all_nonneg(cls, v: list[int]) -> list[int]:
        if any(q < 0 for q in v):
            raise ValueError(f"quarterly_schedule_units must all be ≥ 0; got {v}")
        return v


# ---------------------------------------------------------------------------
# TAKE_OR_PAY
# ---------------------------------------------------------------------------


class TakeOrPayPayload(BaseModel):
    """Take-or-pay clause parameters.

    Two shortfall mechanisms supported:

      - `shortfall_basis='pct_of_committed'` — the synthetic-contract style.
        Buyer must pay for at least X% of annual committed volume regardless
        of actual purchases. `annual_minimum_pct_of_committed` is REQUIRED.

      - `shortfall_basis='unbooked_unit_price_formula'` — the real wafer-supply
        style (Intel-Micron 2017). The clause defines shortfall by formula
        (unbooked units × Final Price), not by a percentage floor.
        `annual_minimum_pct_of_committed` is None; `shortfall_formula_description`
        carries the verbatim formula text.

      - `shortfall_basis='other'` — anything else. Engine treats the term as a
        manual-review driver.
    """
    model_config = ConfigDict(extra="forbid")

    annual_minimum_pct_of_committed: float | None = Field(
        default=None,
        ge=0.0, le=1.0,
        description="Fraction of annual committed volume the buyer must pay for. "
                    "REQUIRED when shortfall_basis == 'pct_of_committed'. None when "
                    "the contract uses a formula-based shortfall.",
    )
    shortfall_basis: Literal["pct_of_committed", "unbooked_unit_price_formula", "other"] = Field(
        default="pct_of_committed",
        description="How the contract defines the shortfall amount. See class docstring.",
    )
    shortfall_formula_description: str | None = Field(
        default=None,
        description="Free-text formula when shortfall_basis != 'pct_of_committed'. "
                    "E.g. 'Buyer shall pay Seller (Binding Forecast shortfall) * "
                    "(Final Price per Schedule 1)'.",
    )
    shortfall_payment_due_days: int | None = Field(
        default=None,
        ge=0, le=365,
        description="Days after year-end within which the shortfall payment is due.",
    )
    banked_units_eligible_for_carryforward: bool = Field(
        default=False,
        description="True if shortfall-paid units convert to Banked Units that can be "
                    "drawn in later quarters.",
    )
    banked_units_forfeit_at_term_end: bool = Field(
        default=False,
        description="True if Banked Units that remain undrawn at term end are forfeited.",
    )

    @model_validator(mode="after")
    def _shortfall_basis_consistency(self) -> "TakeOrPayPayload":
        if self.shortfall_basis == "pct_of_committed" and self.annual_minimum_pct_of_committed is None:
            raise ValueError(
                "annual_minimum_pct_of_committed is required when "
                "shortfall_basis == 'pct_of_committed'."
            )
        return self


# ---------------------------------------------------------------------------
# LLM response wrappers (used as `response_format=`)
#
# Each wrapper carries the metadata the orchestrator needs (raw_text source
# quote, source_section pointer, ambiguity flag/note, variants) in addition to
# the term-type-specific payload or dict. The orchestrator turns each wrapper
# into a `CommercialTerm` with the known term_type, term_id, and
# source_document populated.
# ---------------------------------------------------------------------------


class _ExtractedBase(BaseModel):
    """Shared fields across every extraction wrapper.

    Note: `variants_json` is a JSON-encoded string rather than a typed
    list[TermVariant] because OpenAI's strict structured-output mode rejects
    `dict[str, Any]` fields (which TermVariant.parameters has). The orchestrator
    decodes this string and constructs TermVariants explicitly.
    """
    model_config = ConfigDict(extra="forbid")

    not_found: bool = Field(
        default=False,
        description="True if the term type is not present in the supplied excerpts. "
                    "When true, all other fields should be ignored by the orchestrator.",
    )
    raw_text: str = Field(
        default="",
        description="Verbatim quote from the contract supporting the extracted "
                    "parameters. Empty string when not_found is True.",
    )
    source_section: str = Field(
        default="",
        description="Section number or short heading where the term was found "
                    "(e.g. '5' or '5. VOLUME REBATES'). Empty when not_found is True.",
    )
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Extractor confidence in the extracted parameters (1.0 = explicit).",
    )
    ambiguity_flag: bool = Field(default=False)
    ambiguity_note: str = Field(default="")
    variants_json: str = Field(
        default="[]",
        description="JSON-encoded list of TermVariant dicts (each with 'label', "
                    "'parameters' as a JSON-encoded string, and 'note'). Empty list "
                    "string '[]' when no variants apply.",
    )


class ExtractedRebate(_ExtractedBase):
    """LLM response for the REBATE term type (strict-schema path)."""
    payload: RebatePayload | None = Field(
        default=None,
        description="Required when not_found is False. Strict Pydantic shape enforced "
                    "via response_format.",
    )


class ExtractedVolumeCommitment(_ExtractedBase):
    """LLM response for the VOLUME_COMMITMENT term type (strict-schema path)."""
    payload: VolumeCommitmentPayload | None = None


class ExtractedTakeOrPay(_ExtractedBase):
    """LLM response for the TAKE_OR_PAY term type (strict-schema path)."""
    payload: TakeOrPayPayload | None = None


class ExtractedDictTerm(_ExtractedBase):
    """LLM response for the remaining 9 term types (dict-shape path).

    `parameters_json` is a JSON-encoded dict (same reason as variants_json above —
    strict structured-output mode requires closed object schemas). Prompt-driven
    keys; post-extraction validators do the shape checking.
    """
    parameters_json: str = Field(
        default="{}",
        description="JSON-encoded dict of term-type-specific parameters. The "
                    "expected keys per term type are enumerated in the prompt.",
    )


__all__ = [
    # Strict payload schemas
    "RebateTier",
    "RebatePayload",
    "VolumeCommitmentPayload",
    "TakeOrPayPayload",
    # LLM response wrappers
    "ExtractedRebate",
    "ExtractedVolumeCommitment",
    "ExtractedTakeOrPay",
    "ExtractedDictTerm",
]
