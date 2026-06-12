"""Tests for the TakeOrPay schema fix: shortfall_basis Literal + Optional
annual_minimum_pct_of_committed + consistency validator.

Before this fix the strict schema forced the extractor to invent a placeholder
percentage when the real contract used a formula-based shortfall (the
Intel-Micron wafer-supply case). The fix lets the schema express the formula
case honestly.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from deal_copilot.extraction_payloads import TakeOrPayPayload


def test_pct_of_committed_requires_pct() -> None:
    """shortfall_basis='pct_of_committed' must come with annual_minimum_pct_of_committed."""
    with pytest.raises(ValidationError) as exc_info:
        TakeOrPayPayload(shortfall_basis="pct_of_committed")
    # The model_validator emits a clear message naming the missing field.
    assert "annual_minimum_pct_of_committed" in str(exc_info.value)


def test_pct_of_committed_with_pct_constructs() -> None:
    """The synthetic-contract case (Phase 1 fixture)."""
    t = TakeOrPayPayload(
        shortfall_basis="pct_of_committed",
        annual_minimum_pct_of_committed=0.80,
        banked_units_eligible_for_carryforward=True,
        banked_units_forfeit_at_term_end=True,
        shortfall_payment_due_days=60,
    )
    assert t.annual_minimum_pct_of_committed == 0.80
    assert t.shortfall_basis == "pct_of_committed"
    assert t.shortfall_formula_description is None


def test_formula_basis_allows_no_pct() -> None:
    """The real Intel-Micron case: formula-based shortfall, no percentage floor.
    Previously rejected by the strict `gt=0` constraint; now allowed."""
    t = TakeOrPayPayload(
        shortfall_basis="unbooked_unit_price_formula",
        shortfall_formula_description=(
            "Buyer shall pay Seller (Binding Forecast Wafers shortfall) * "
            "(Final Price per Schedule 1)"
        ),
    )
    assert t.annual_minimum_pct_of_committed is None
    assert t.shortfall_basis == "unbooked_unit_price_formula"
    assert "Final Price" in t.shortfall_formula_description


def test_other_basis_allows_no_pct() -> None:
    """'other' is a catch-all that also doesn't require the percentage."""
    t = TakeOrPayPayload(
        shortfall_basis="other",
        shortfall_formula_description="Custom mechanism described in Schedule X",
    )
    assert t.annual_minimum_pct_of_committed is None
    assert t.shortfall_basis == "other"


def test_default_basis_is_pct_of_committed() -> None:
    """Backward-compat: existing callers who omit shortfall_basis still get the
    synthetic-style behavior."""
    t = TakeOrPayPayload(annual_minimum_pct_of_committed=0.80)
    assert t.shortfall_basis == "pct_of_committed"


def test_pct_out_of_range_still_rejected() -> None:
    """The (0, 1] range check still applies when pct is provided."""
    with pytest.raises(ValidationError):
        TakeOrPayPayload(annual_minimum_pct_of_committed=1.5)


def test_real_intel_micron_round_trip() -> None:
    """A TakeOrPayPayload matching the real Intel-Micron extraction must
    survive JSON round-trip with no loss of information."""
    original = TakeOrPayPayload(
        shortfall_basis="unbooked_unit_price_formula",
        shortfall_formula_description=(
            "Intel shall pay Micron an amount equal to the sum of the Binding "
            "Forecast Wafers it fails to purchase multiplied by the applicable "
            "Final Price per Binding Forecast Wafer as set forth in Schedule 1."
        ),
        banked_units_eligible_for_carryforward=False,
        banked_units_forfeit_at_term_end=False,
    )
    js = original.model_dump_json()
    restored = TakeOrPayPayload.model_validate_json(js)
    assert restored.shortfall_basis == "unbooked_unit_price_formula"
    assert restored.annual_minimum_pct_of_committed is None
    assert restored.shortfall_formula_description == original.shortfall_formula_description
