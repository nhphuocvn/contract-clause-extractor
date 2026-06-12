"""Golden-file tests for deal_copilot/excel_export.py.

Checks (openpyxl opens the workbook with data_only=False so formula strings
are visible rather than cached values):

 1. Correct tab names in order.
 2. Key named ranges registered with correct cell addresses.
 3. All computed Model-tab cells contain live formulas (start with '=').
 4. Assumption seed values are correct numeric values (not formulas).
 5. Assumption input cells are unlocked (protection.locked == False).
 6. Rebate A/B toggle formula contains 'RebateToggle' and 'B-Retroactive'.
 7. Reading B VLOOKUP references year-end cumulative column (not quarter-end).
 8. Warrant contra-revenue formula is live (references TotalEFV and UnitQ1).
 9. Scenarios BASE row is live (=Model!...); DOWNSIDE/UPSIDE/ET are static.
10. Engine total_gross_margin == $1,357.5M; Assumptions seed values consistent.
"""
from __future__ import annotations

import datetime
import io

import openpyxl
import pytest

from deal_copilot.economics_engine import compute_economics
from deal_copilot.assumption_register import build_register
from deal_copilot.assumptions_library import build_default_assumptions, load_library
from deal_copilot.excel_export import (
    _M_ACT_REBATE,
    _M_ASP,
    _M_COGS,
    _M_CUM_END,
    _M_GROSS_MRG,
    _M_GROSS_REV,
    _M_NET_REV,
    _M_REBATE_A,
    _M_REBATE_B,
    _M_UNITS,
    _Q1_COL,
    _W_CONTRA_ROW_START,
    _W_TOTAL_EFV_ROW,
    _W_VAL_COL,
    build_workbook,
)
from deal_copilot.warrant_economics import compute_warrant_economics
from tests.fixtures import (
    QUARTERLY_SCHEDULE,
    synthetic_package,
    synthetic_package_with_warrant,
    warrant_assumptions,
)

# Column N = 14 is the TOTAL column in the Model tab.
_TOTAL_COL = 14


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _basic_pkg_asmp():
    pkg = synthetic_package()
    lib = load_library()
    asmp, _ = build_default_assumptions(lib, datetime.datetime(2026, 6, 11))
    return pkg, asmp


@pytest.fixture(scope="module")
def wb_basic(_basic_pkg_asmp):
    """Workbook without warrant deal — exercises the $1,357.5 M GM baseline."""
    pkg, asmp = _basic_pkg_asmp
    econ = compute_economics(pkg, asmp)
    reg = build_register(asmp, terms=pkg.terms)
    raw = build_workbook(pkg, asmp, econ, None, reg)
    # Round-trip through bytes so openpyxl reads formula strings (data_only=False).
    buf = io.BytesIO()
    raw.save(buf)
    buf.seek(0)
    return openpyxl.load_workbook(buf, data_only=False)


@pytest.fixture(scope="module")
def base_econ(_basic_pkg_asmp):
    pkg, asmp = _basic_pkg_asmp
    econ = compute_economics(pkg, asmp)
    return next(s for s in econ.scenarios if s.scenario == "BASE")


@pytest.fixture(scope="module")
def wb_warrant():
    """Workbook with warrant deal — exercises Warrant tab formula circuit."""
    pkg = synthetic_package_with_warrant()
    asmp = warrant_assumptions()
    econ = compute_economics(pkg, asmp)
    we = compute_warrant_economics(pkg, asmp)
    reg = build_register(asmp, terms=pkg.terms, warrant_terms=pkg.warrant_terms)
    raw = build_workbook(pkg, asmp, econ, we, reg)
    buf = io.BytesIO()
    raw.save(buf)
    buf.seek(0)
    return openpyxl.load_workbook(buf, data_only=False)


# ---------------------------------------------------------------------------
# 1. Tab names
# ---------------------------------------------------------------------------


def test_tab_names(wb_basic):
    assert wb_basic.sheetnames == [
        "Assumptions",
        "Warrant_Assump",
        "Drivers",
        "Model",
        "Warrant",
        "Scenarios",
        "Acct_Sched",
        "Variance",
        "Assumption_Reg",
        "CRB_Summary",
        "Changelog",
    ]


# ---------------------------------------------------------------------------
# 2. Named ranges
# ---------------------------------------------------------------------------


def test_named_range_asp(wb_basic):
    assert wb_basic.defined_names["ASP"].attr_text == "Assumptions!$B$12"


def test_named_range_unit_q1(wb_basic):
    assert wb_basic.defined_names["UnitQ1"].attr_text == "Assumptions!$B$18"


def test_named_range_unit_q12(wb_basic):
    assert wb_basic.defined_names["UnitQ12"].attr_text == "Assumptions!$B$29"


def test_named_range_tier_table(wb_basic):
    assert wb_basic.defined_names["TierTable"].attr_text == "Drivers!$E$13:$F$16"


def test_named_range_rebate_toggle(wb_basic):
    assert "RebateToggle" in wb_basic.defined_names


def test_named_range_contra_q1(wb_warrant):
    assert wb_warrant.defined_names["ContraSchedQ1"].attr_text == "Warrant!$B$15"


def test_named_range_contra_q12(wb_warrant):
    assert wb_warrant.defined_names["ContraSchedQ12"].attr_text == "Warrant!$B$26"


def test_named_range_vest_prob_t1(wb_warrant):
    assert wb_warrant.defined_names["VestProbT1"].attr_text == "Warrant_Assump!$B$7"


# ---------------------------------------------------------------------------
# 3. Model tab: all computed cells are live formulas
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("row", [
    _M_GROSS_REV,
    _M_CUM_END,
    _M_REBATE_A,
    _M_REBATE_B,
    _M_ACT_REBATE,
    _M_NET_REV,
    _M_COGS,
    _M_GROSS_MRG,
])
def test_model_q1_cell_is_formula(wb_basic, row):
    val = wb_basic["Model"].cell(row, _Q1_COL).value
    assert str(val).startswith("="), (
        f"Model row {row} Q1 col should be a live formula; got: {val!r}"
    )


@pytest.mark.parametrize("row", [_M_GROSS_REV, _M_NET_REV, _M_GROSS_MRG])
def test_model_total_col_is_sum_formula(wb_basic, row):
    val = wb_basic["Model"].cell(row, _TOTAL_COL).value
    assert str(val).startswith("=SUM"), (
        f"Model row {row} TOTAL col should be =SUM(...); got: {val!r}"
    )


def test_model_units_references_named_range(wb_basic):
    """Model!B3 must pull from the named range, not a hard-coded number."""
    assert wb_basic["Model"].cell(_M_UNITS, _Q1_COL).value == "=UnitQ1"


def test_model_asp_references_named_range(wb_basic):
    assert wb_basic["Model"].cell(_M_ASP, _Q1_COL).value == "=ASP"


def test_model_gross_rev_formula_q1(wb_basic):
    """GrossRev Q1 must multiply the two rows immediately above it: =B3*B4."""
    assert wb_basic["Model"].cell(_M_GROSS_REV, _Q1_COL).value == "=B3*B4"


# ---------------------------------------------------------------------------
# 4. Rebate toggle and VLOOKUP circuit
# ---------------------------------------------------------------------------


def test_rebate_toggle_formula(wb_basic):
    act = str(wb_basic["Model"].cell(_M_ACT_REBATE, _Q1_COL).value)
    assert "RebateToggle" in act
    assert "B-Retroactive" in act


def test_rebate_b_q1_uses_year1_end_col(wb_basic):
    """Reading B Q1: VLOOKUP must look up year-1 year-end cumulative ($E$8)."""
    rb_q1 = str(wb_basic["Model"].cell(_M_REBATE_B, _Q1_COL).value)
    assert "VLOOKUP" in rb_q1
    assert "$E$8" in rb_q1
    assert "TierTable" in rb_q1


def test_rebate_b_q5_uses_year2_end_col(wb_basic):
    """Reading B Q5 (year 2): VLOOKUP must look up year-2 year-end ($I$8)."""
    rb_q5 = str(wb_basic["Model"].cell(_M_REBATE_B, _Q1_COL + 4).value)
    assert "$I$8" in rb_q5


def test_rebate_b_q9_uses_year3_end_col(wb_basic):
    """Reading B Q9 (year 3): VLOOKUP must look up year-3 year-end ($M$8)."""
    rb_q9 = str(wb_basic["Model"].cell(_M_REBATE_B, _Q1_COL + 8).value)
    assert "$M$8" in rb_q9


# ---------------------------------------------------------------------------
# 5. Assumption seed values (not formulas)
# ---------------------------------------------------------------------------


def test_asp_seed_value(wb_basic):
    assert wb_basic["Assumptions"].cell(12, 2).value == pytest.approx(25_000.0)


def test_unit_q1_seed_value(wb_basic):
    assert wb_basic["Assumptions"].cell(18, 2).value == QUARTERLY_SCHEDULE[0]


def test_unit_q12_seed_value(wb_basic):
    assert wb_basic["Assumptions"].cell(29, 2).value == QUARTERLY_SCHEDULE[11]


def test_assumption_seed_values_are_not_formulas(wb_basic):
    ws = wb_basic["Assumptions"]
    for col_idx, row_idx in [(12, 2), (18, 2), (29, 2)]:
        v = ws.cell(col_idx, row_idx).value
        assert not str(v).startswith("="), (
            f"Assumptions row {col_idx} col B should be a seed value, got formula: {v}"
        )


# ---------------------------------------------------------------------------
# 6. Assumption input cells are unlocked
# ---------------------------------------------------------------------------


def test_asp_cell_unlocked(wb_basic):
    cell = wb_basic["Assumptions"].cell(12, 2)
    assert not cell.protection.locked, "ASP input cell must be unlocked for editing"


def test_unit_q1_cell_unlocked(wb_basic):
    cell = wb_basic["Assumptions"].cell(18, 2)
    assert not cell.protection.locked, "UnitQ1 input cell must be unlocked for editing"


# ---------------------------------------------------------------------------
# 7. Warrant tab: live formula circuit
# ---------------------------------------------------------------------------


def test_warrant_total_efv_is_sum_formula(wb_warrant):
    val = str(wb_warrant["Warrant"].cell(_W_TOTAL_EFV_ROW, _W_VAL_COL).value)
    assert val.startswith("=SUM"), f"TotalEFV must be =SUM(...); got: {val}"


def test_warrant_contra_q1_is_live_formula(wb_warrant):
    val = str(wb_warrant["Warrant"].cell(_W_CONTRA_ROW_START, _W_VAL_COL).value)
    assert val.startswith("=-"), f"ContraSchedQ1 must be a live negative formula; got: {val}"
    assert "UnitQ1" in val, "ContraSchedQ1 must reference UnitQ1 named range"


def test_warrant_contra_formula_no_embedded_equals(wb_warrant):
    """The denominator must be SUM(...) not =SUM(...) — no embedded '='."""
    val = str(wb_warrant["Warrant"].cell(_W_CONTRA_ROW_START, _W_VAL_COL).value)
    # After the leading '=-.../', the denominator must not start with '='
    idx = val.index("/")
    denominator = val[idx + 1:]
    assert not denominator.startswith("="), (
        f"Embedded '=' in contra formula denominator: {val!r}"
    )


# ---------------------------------------------------------------------------
# 8. Scenarios: BASE live, DOWNSIDE static snapshot
# ---------------------------------------------------------------------------


def test_scenarios_base_gross_margin_is_live(wb_basic):
    """BASE Gross Margin cell must be a live formula referencing Model tab."""
    gm_cell = wb_basic["Scenarios"].cell(2, 3).value  # row 2 = BASE, col C = GM
    assert str(gm_cell).startswith("=Model!"), (
        f"Scenarios BASE GM must reference Model tab; got: {gm_cell!r}"
    )


def test_scenarios_downside_gross_margin_is_static(wb_basic):
    """DOWNSIDE Gross Margin must be a static engine-written value, not a formula."""
    gm_cell = wb_basic["Scenarios"].cell(3, 3).value  # row 3 = DOWNSIDE
    assert not str(gm_cell).startswith("="), (
        f"DOWNSIDE GM should be static snapshot, got formula: {gm_cell!r}"
    )
    assert isinstance(gm_cell, (int, float)), (
        f"DOWNSIDE GM should be a number; got: {gm_cell!r}"
    )


# ---------------------------------------------------------------------------
# 9. Cross-check: engine total GM == $1,357.5 M (formula-seed consistency)
# ---------------------------------------------------------------------------


def test_engine_total_gross_margin_pinned(base_econ):
    """The engine total GM must equal the canonical $1,357.5 M figure.

    openpyxl cannot evaluate formulas, so we verify the engine output that
    seeded the Assumptions tab: if ASP=25,000 and unit schedule = QUARTERLY_SCHEDULE
    then the formula circuit should reach this figure.  Computed once in the
    economics-engine test suite; asserted here as a cross-reference anchor.
    """
    assert base_econ.total_gross_margin == pytest.approx(1_357_500_000.0, rel=1e-6)


def test_assumption_seed_asp_matches_engine_input(wb_basic):
    """The ASP seed value in the workbook must equal the engine's ASP input."""
    assert wb_basic["Assumptions"].cell(12, 2).value == pytest.approx(25_000.0)


def test_assumption_seed_units_match_engine_schedule(wb_basic):
    """All 12 quarterly unit cells must match the fixture's QUARTERLY_SCHEDULE."""
    ws = wb_basic["Assumptions"]
    for q_idx, expected_units in enumerate(QUARTERLY_SCHEDULE):
        row = 18 + q_idx  # UnitQ1 at row 18 … UnitQ12 at row 29
        actual = ws.cell(row, 2).value
        assert actual == expected_units, (
            f"UnitQ{q_idx + 1}: expected {expected_units}, got {actual}"
        )
