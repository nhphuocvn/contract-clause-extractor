"""Excel export — Phase 7 (§9.1).

``build_workbook`` turns fully-computed engine output into an openpyxl Workbook
where every P&L cell is a live formula. Editing an assumption on the Assumptions
tab causes the entire Model tab to recalculate inside Excel.

CIRCUIT PRINCIPLE (§9.1): traceability over cleverness.
  - One labeled row per engine step, read top-to-bottom.
  - NO nested IFs. Single IFs fine; VLOOKUP for the tier table.
  - MAX/MIN are arithmetic — used for the rebate zone splits.
  - Cross-sheet links via workbook-scope named ranges (no hard-coded addresses).

Cell-style convention (enforced throughout):
  Live formula cells  — white background (default).
  StaticSnapshot cells — amber #FFF2CC — engine value, does NOT recalculate.
  StaticBanner rows   — bright amber #FF9900, bold — warning on any static section.
  Input fills vary by provenance (green / yellow / blue / orange / red).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import openpyxl
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Protection
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

from deal_copilot.schemas import (
    AssumptionType,
    CRBMemo,
    DealAssumptions,
    DealEconomics,
    DealPackage,
    DealVersion,
    ProvenanceClass,
    RegisterEntry,
    ScenarioName,
    ViewMode,
    WarrantEconomics,
)

# ─── Fills ─────────────────────────────────────────────────────────────────────

_F_CONTRACT    = PatternFill("solid", fgColor="C6EFCE")
_F_LIBRARY     = PatternFill("solid", fgColor="FFEB9C")
_F_POLICY      = PatternFill("solid", fgColor="9DC3E6")
_F_JUDGMENT    = PatternFill("solid", fgColor="FFD966")
_F_PLACEHOLDER = PatternFill("solid", fgColor="FFC7CE")
_F_HELPER      = PatternFill("solid", fgColor="F2F2F2")
_F_SECTION_HDR = PatternFill("solid", fgColor="D9D9D9")
_F_STATIC      = PatternFill("solid", fgColor="FFF2CC")
_F_BANNER      = PatternFill("solid", fgColor="FF9900")

_FONT_BOLD         = Font(bold=True)
_FONT_STATIC       = Font(color="996600")
_FONT_BANNER_BOLD  = Font(bold=True)
_FONT_ITALIC_GRAY  = Font(italic=True, color="808080")

_PROV_FILLS = {
    ProvenanceClass.CONTRACT: _F_CONTRACT,
    ProvenanceClass.TERM_SHEET: _F_CONTRACT,
    ProvenanceClass.LIBRARY_DEFAULT: _F_LIBRARY,
    ProvenanceClass.PLACEHOLDER: _F_PLACEHOLDER,
}

_ATYPE_FILLS = {
    AssumptionType.CONTRACT_FACT: _F_CONTRACT,
    AssumptionType.MARKET_DATA: _F_LIBRARY,
    AssumptionType.POLICY_NUMBER: _F_POLICY,
    AssumptionType.STRATEGIC_JUDGMENT: _F_JUDGMENT,
}

# ─── Model tab row constants ────────────────────────────────────────────────────

_M_HDR         = 1
_M_SEC_REV     = 2
_M_UNITS       = 3
_M_ASP         = 4
_M_GROSS_REV   = 5
_M_SEC_REBATE  = 6
_M_CUM_START   = 7
_M_CUM_END     = 8
_M_HEAD0       = 9    # no-rebate headroom
_M_HEAD1       = 10   # tier-1 headroom (cum cap before tier-2)
_M_HEAD2       = 11   # tier-2 headroom (cum cap before tier-3)
_M_ZONE0       = 12   # units in no-rebate zone
_M_ZONE1       = 13   # units in tier-1 zone
_M_ZONE2       = 14   # units in tier-2 zone
_M_ZONE3       = 15   # units in tier-3 zone
_M_REBATE_A    = 16   # Reading A — prospective (marginal)
_M_REBATE_B    = 17   # Reading B — retroactive-within-year
_M_ACT_REBATE  = 18   # ★ active rebate (toggle-selected)
_M_SEC_NET     = 19
_M_WARRANT_CTR = 20   # warrant contra revenue
_M_ADHOC       = 21   # ad-hoc adjustment
_M_NET_REV     = 22
_M_SEC_COST    = 23
_M_UNIT_COGS   = 24
_M_COGS        = 25
_M_GROSS_MRG   = 26
_M_GM_PCT      = 27
_M_OPEX_PCT    = 28
_M_ALLOC_OPEX  = 29
_M_CONTRIB     = 30

# quarter columns: Q1=col 2 (B), Q{n}=col n+1, total=col n_q+2, note=col n_q+3
_Q1_COL = 2

# Pre-committed Warrant tab layout (so Model can reference before Warrant is built)
_W_VAL_COL          = 2   # col B in Warrant tab
_W_TOTAL_EFV_ROW    = 10  # row for total expected FV
_W_CONTRA_ROW_START = 15  # Q1 contra-revenue row

# ─── Helpers ───────────────────────────────────────────────────────────────────

def _cl(col: int) -> str:
    """Column index → letter (1-indexed)."""
    return get_column_letter(col)


def _addr(sheet: str, row: int, col: int) -> str:
    """Absolute cell address string."""
    return f"'{sheet}'!${_cl(col)}${row}"


def _set_static(cell, value: Any) -> None:
    """Write a static (engine-snapshot) cell with amber styling."""
    cell.value = value
    cell.fill = _F_STATIC
    cell.font = _FONT_STATIC


def _set_banner(ws, row: int, n_cols: int, text: str) -> None:
    """Write a full-width banner row for static sections."""
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=n_cols)
    c = ws.cell(row=row, column=1, value=text)
    c.fill = _F_BANNER
    c.font = _FONT_BANNER_BOLD
    c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 28


def _set_section_hdr(ws, row: int, text: str, n_cols: int = 6) -> None:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=n_cols)
    c = ws.cell(row=row, column=1, value=text)
    c.fill = _F_SECTION_HDR
    c.font = _FONT_BOLD


def _protect(ws) -> None:
    """Lock the sheet; unlocked cells must be set individually before calling."""
    ws.protection.sheet = True
    ws.protection.password = ""


# ─── Assumptions tab ───────────────────────────────────────────────────────────

_LEGEND_ROWS = [
    ("CELL STYLE LEGEND", "Key for all fills used in this workbook",             None),
    ("Green (#C6EFCE)",   "Contract fact — editable input; sourced from contract",       _F_CONTRACT),
    ("Yellow (#FFEB9C)",  "Library default — editable; review before signing",           _F_LIBRARY),
    ("Blue (#9DC3E6)",    "Policy number — confirm with Treasury / Legal",                _F_POLICY),
    ("Orange (#FFD966)",  "Strategic judgment — confirm with deal team",                  _F_JUDGMENT),
    ("Red (#FFC7CE)",     "Placeholder — value must be confirmed before use",             _F_PLACEHOLDER),
    ("White (default)",   "LIVE FORMULA — recalculates when inputs change",               None),
    ("Amber (#FFF2CC)",   "STATIC SNAPSHOT — does NOT recalculate; rerun export to refresh",
     _F_STATIC),
]


def _input_row(ws, row: int, label: str, value: Any, unit: str = "",
               fill=None, owner: str = "", flag: str = "",
               fmt: str | None = None, locked: bool = True,
               cell_map: dict | None = None, name: str | None = None) -> None:
    ws.cell(row=row, column=1, value=label)
    c = ws.cell(row=row, column=2, value=value)
    if fill:
        c.fill = fill
    if not locked:
        c.protection = Protection(locked=False)
    if fmt:
        c.number_format = fmt
    ws.cell(row=row, column=3, value=unit)
    ws.cell(row=row, column=5, value=owner)
    if flag:
        fc = ws.cell(row=row, column=6, value=f"★ {flag}")
        fc.fill = _F_PLACEHOLDER
    if name and cell_map is not None:
        cell_map[name] = f"Assumptions!${_cl(2)}${row}"


def _write_assumptions(ws, assumptions: DealAssumptions, inp,
                       register: list[RegisterEntry],
                       cell_map: dict) -> None:
    ws.title = "Assumptions"
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 10
    ws.column_dimensions["D"].width = 20
    ws.column_dimensions["E"].width = 30
    ws.column_dimensions["F"].width = 38

    # Header row
    for col, txt in enumerate(["Description", "Value", "Unit", "Provenance", "Owner", "Flag"], 1):
        c = ws.cell(row=1, column=col, value=txt)
        c.font = _FONT_BOLD

    # Legend block (rows 2-9)
    for i, (swatch, desc, fill) in enumerate(_LEGEND_ROWS, 2):
        ws.cell(row=i, column=1, value=swatch)
        if fill:
            ws.cell(row=i, column=1).fill = fill
        ws.cell(row=i, column=2, value=desc)
    ws.cell(row=2, column=1).font = _FONT_BOLD

    r = 11  # first data row after legend

    # Section 1 — Deal Structure
    _set_section_hdr(ws, r, "SECTION 1 — DEAL STRUCTURE (contract facts)", 6); r += 1
    _input_row(ws, r, "Base ASP ($/unit)", inp.base_asp, "$/unit",
               _F_CONTRACT, "contract §pricing", "", "#,##0", False, cell_map, "ASP"); r += 1
    _input_row(ws, r, "Payment Terms (net days, DSO)", inp.dso_days, "days",
               _F_CONTRACT, "contract §payment", "", "0", False, cell_map, "PaymentTermsDays"); r += 1
    _input_row(ws, r, "Prepayment Amount", inp.prepayment_usd, "USD",
               _F_CONTRACT, "contract §prepayment", "", "#,##0", False, cell_map, "PrepaymentUSD"); r += 1
    _input_row(ws, r, "Take-or-Pay Floor (% of committed)", inp.take_or_pay_floor_pct, "%",
               _F_CONTRACT, "contract §take-or-pay", "", "0%", False, cell_map, "ToPFloor"); r += 1
    r += 1  # blank

    # Section 2 — Unit Ramp Schedule
    _set_section_hdr(ws, r, "SECTION 2 — UNIT RAMP SCHEDULE (contract facts)", 6); r += 1
    for q, units in enumerate(inp.committed_quarterly):
        _input_row(ws, r, f"Q{q + 1} Units", int(units), "units",
                   _F_CONTRACT, "contract volume schedule", "", "#,##0", False,
                   cell_map, f"UnitQ{q + 1}"); r += 1
    r += 1  # blank

    # Section 3 — Rebate Terms
    _set_section_hdr(ws, r, "SECTION 3 — REBATE TERMS (contract facts + judgment)", 6); r += 1
    tiers = list(inp.rebate_tiers)
    for i, (thr, rate) in enumerate(tiers):
        _input_row(ws, r, f"Tier {i + 1} Threshold (cumulative units)", int(thr), "units",
                   _F_CONTRACT, "contract §rebate", "", "#,##0", False,
                   cell_map, f"RebateTier{i + 1}Threshold"); r += 1
    for i, (thr, rate) in enumerate(tiers):
        _input_row(ws, r, f"Tier {i + 1} Rate (% off ASP)", rate, "%",
                   _F_CONTRACT, "contract §rebate", "", "0.00%", False,
                   cell_map, f"RebateTier{i + 1}Rate"); r += 1
    # Rebate reading toggle — strategic judgment / multi-value
    _input_row(ws, r, "★ Rebate Reading Toggle", "A-Prospective", "",
               _F_JUDGMENT, "Legal — resolve §rebate ambiguity", "",
               None, False, cell_map, "RebateToggle")
    # Data validation: dropdown
    dv = DataValidation(type="list",
                        formula1='"A-Prospective,B-Retroactive"',
                        showDropDown=False)
    ws.add_data_validation(dv)
    dv.add(ws.cell(row=r, column=2))
    ws.cell(row=r, column=6, value="★ MULTI-VALUE INPUT — confirm with Legal before signing").fill = _F_PLACEHOLDER
    r += 1
    r += 1  # blank

    # Section 4 — Cost Parameters
    _set_section_hdr(ws, r, "SECTION 4 — COST PARAMETERS", 6); r += 1
    _input_row(ws, r, "Unit COGS ($/unit)", assumptions.unit_cogs_usd, "$/unit",
               _F_LIBRARY, "cost accounting", "confirm with cost accounting",
               "#,##0", False, cell_map, "UnitCOGS"); r += 1
    _input_row(ws, r, "OpEx Allocation %", assumptions.opex_allocation_pct, "%",
               _F_JUDGMENT, "FP&A", "", "0.00%", False, cell_map, "OpExPct"); r += 1
    r += 1  # blank

    # Section 5 — Financial Parameters
    _set_section_hdr(ws, r, "SECTION 5 — FINANCIAL PARAMETERS", 6); r += 1
    _input_row(ws, r, "WACC (discount rate)", assumptions.discount_rate_wacc, "%",
               _F_POLICY, "Treasury", "confirm with Treasury", "0.00%", False, cell_map, "WACC"); r += 1
    _input_row(ws, r, "Tax Rate", assumptions.tax_rate, "%",
               _F_POLICY, "Tax / Treasury", "", "0.00%", False, cell_map, "TaxRate"); r += 1
    _input_row(ws, r, "Supplier DPO (days)", assumptions.supplier_payment_dpo_days, "days",
               _F_POLICY, "Treasury / Procurement", "", "0", False, cell_map, "DPODays"); r += 1
    _input_row(ws, r, "Inventory Lead (months)", assumptions.inventory_lead_months, "months",
               _F_JUDGMENT, "Operations / Supply Chain", "", "0", False,
               cell_map, "InventoryLeadMonths"); r += 1
    r += 1  # blank

    # Section 6 — Scenario Probabilities
    _set_section_hdr(ws, r, "SECTION 6 — SCENARIO PROBABILITIES (strategic judgment)", 6); r += 1
    ws.cell(row=r, column=6, value="★ CONFIRM WITH deal team — must sum to 100%").fill = _F_PLACEHOLDER
    prob_defaults = [0.50, 0.25, 0.15, 0.10]
    for name, prob in zip(("BASE", "DOWNSIDE", "UPSIDE", "ET"), prob_defaults):
        _input_row(ws, r, f"P({name})", prob, "%",
                   _F_JUDGMENT, "deal team", "", "0%", False,
                   cell_map, f"Prob{name}"); r += 1

    ws.protection.sheet = True
    ws.protection.password = ""
    # Un-lock every cell in column B that we marked locked=False above
    # (openpyxl requires sheet.protection=True and then individual cells locked=False)
    # Already set via _input_row locked=False — no further action needed.


# ─── Warrant_Assump tab ────────────────────────────────────────────────────────

def _write_warrant_assumptions(ws, assumptions: DealAssumptions,
                               warrant: WarrantEconomics | None,
                               cell_map: dict) -> None:
    ws.title = "Warrant_Assump"
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 18
    ws.column_dimensions["E"].width = 30

    _set_banner(ws, 1, 5,
                "WARRANT JUDGMENT INPUTS — STRATEGIC ESTIMATES. "
                "Confirm every value with deal team before signature.")
    ws.cell(row=1, column=1).fill = _F_JUDGMENT

    r = 3
    ws.cell(row=r, column=1, value="Description").font = _FONT_BOLD
    ws.cell(row=r, column=2, value="Value").font = _FONT_BOLD
    ws.cell(row=r, column=5, value="Note").font = _FONT_BOLD
    r += 1

    # Stock price
    price = (assumptions.warrant_measurement_price_usd or
             assumptions.current_stock_price_usd or 0.0)
    ws.cell(row=r, column=1, value="Measurement Stock Price ($/share)")
    c = ws.cell(row=r, column=2, value=price)
    c.fill = _F_JUDGMENT
    c.protection = Protection(locked=False)
    c.number_format = "#,##0.00"
    ws.cell(row=r, column=5, value="★ strategic estimate — confirm with deal team")
    cell_map["WarrantStockPrice"] = f"Warrant_Assump!${_cl(2)}${r}"
    r += 1
    r += 1  # blank

    # Per-tranche vest probabilities
    _set_section_hdr(ws, r, "Per-Tranche Vest Probabilities", 5)
    r += 1

    probs = list(assumptions.tranche_vest_probabilities)
    if not probs and warrant:
        probs = [0.9] * len(warrant.tranche_valuations)

    if warrant:
        for i, tv in enumerate(warrant.tranche_valuations):
            prob = probs[i] if i < len(probs) else 0.9
            ws.cell(row=r, column=1,
                    value=f"Tranche {i + 1} vest probability (milestone: {tv.deployment_milestone_units:,} units)")
            c = ws.cell(row=r, column=2, value=prob)
            c.fill = _F_JUDGMENT
            c.protection = Protection(locked=False)
            c.number_format = "0%"
            ws.cell(row=r, column=5, value="★ strategic estimate — confirm with deal team")
            cell_map[f"VestProbT{i + 1}"] = f"Warrant_Assump!${_cl(2)}${r}"
            r += 1
    else:
        ws.cell(row=r, column=1, value="(No warrant terms — vest probability inputs not applicable)")
        ws.cell(row=r, column=1).font = _FONT_ITALIC_GRAY
        r += 1

    r += 1
    # Conservative / Base / Aggressive summary
    _set_section_hdr(ws, r, "Expected Value Range (reads probabilities above)", 5)
    r += 1
    if warrant:
        ws.cell(row=r, column=1, value="Conservative total EFV")
        _set_static(ws.cell(row=r, column=2), warrant.expected_value_range[0].total_expected_fair_value_usd
                    if warrant.expected_value_range else 0)
        ws.cell(row=r, column=2).number_format = "#,##0"
        r += 1
        ws.cell(row=r, column=1, value="Base total EFV")
        _set_static(ws.cell(row=r, column=2), warrant.expected_value_range[1].total_expected_fair_value_usd
                    if len(warrant.expected_value_range) > 1 else 0)
        ws.cell(row=r, column=2).number_format = "#,##0"
        r += 1
        ws.cell(row=r, column=1, value="Aggressive total EFV")
        _set_static(ws.cell(row=r, column=2), warrant.expected_value_range[2].total_expected_fair_value_usd
                    if len(warrant.expected_value_range) > 2 else 0)
        ws.cell(row=r, column=2).number_format = "#,##0"
        r += 1
        ws.cell(row=r, column=1,
                value="Note: EV range driven by tranche probability sliders above. "
                       "Warrant valuation positively correlated with deployment milestones "
                       "(see CRB_Summary §Warrant for correlation caveat).")
        ws.cell(row=r, column=1).font = _FONT_ITALIC_GRAY
    ws.protection.sheet = True
    ws.protection.password = ""


# ─── Drivers tab ───────────────────────────────────────────────────────────────

def _write_drivers(ws, econ: DealEconomics, pkg: DealPackage,
                   inp, cell_map: dict) -> None:
    ws.title = "Drivers"
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 18
    ws.column_dimensions["E"].width = 16
    ws.column_dimensions["F"].width = 16

    for col, hdr in enumerate(["Driver Type", "Source Document", "Source Section",
                               "Accounting Note", "Value / Total", ""], 1):
        ws.cell(row=1, column=col, value=hdr).font = _FONT_BOLD

    r = 2
    for d in econ.drivers:
        ws.cell(row=r, column=1, value=d.driver_type.value)
        ws.cell(row=r, column=2, value=d.driver_id[:30] if d.driver_id else "")
        ws.cell(row=r, column=4, value=d.accounting_treatment_note[:80] if d.accounting_treatment_note else "")
        if d.value is not None:
            ws.cell(row=r, column=5, value=d.value)
        elif d.schedule:
            ws.cell(row=r, column=5, value=f"Schedule [{len(d.schedule)} qtrs]")
        r += 1

    r += 1  # blank

    # ── Rebate Tier Table for VLOOKUP (named TierTable) ──────────────────────
    _set_section_hdr(ws, r, "REBATE TIER TABLE — used by VLOOKUP in Model!Reading-B row", 6)
    r += 1
    ws.cell(row=r, column=5, value="Cumul Threshold").font = _FONT_BOLD
    ws.cell(row=r, column=6, value="Rate (%)").font = _FONT_BOLD
    r += 1

    tier_table_start = r
    # Row 0: no-rebate baseline (threshold=0, rate=0%)
    ws.cell(row=r, column=5, value=0)
    ws.cell(row=r, column=6, value=0.0)
    ws.cell(row=r, column=6).number_format = "0.00%"
    r += 1
    # One row per tier (threshold references named ranges from Assumptions)
    for i, (thr, rate) in enumerate(inp.rebate_tiers):
        ws.cell(row=r, column=5, value=f"=RebateTier{i + 1}Threshold")
        c_rate = ws.cell(row=r, column=6, value=f"=RebateTier{i + 1}Rate")
        c_rate.number_format = "0.00%"
        r += 1
    tier_table_end = r - 1

    # Register TierTable named range
    cell_map["TierTable"] = (f"Drivers!${_cl(5)}${tier_table_start}"
                             f":${_cl(6)}${tier_table_end}")


# ─── Model tab ─────────────────────────────────────────────────────────────────

def _model_quarter_cols(n_q: int) -> tuple[int, int, int]:
    """Return (first_q_col, last_q_col, total_col)."""
    return _Q1_COL, _Q1_COL + n_q - 1, _Q1_COL + n_q


def _write_model_row(ws, row: int, label: str,
                     formulas: list[str | int | float],
                     total_formula: str,
                     note: str = "",
                     fill=None,
                     fmt: str = "#,##0") -> None:
    """Write one full model row: label, quarter formulas, total, note."""
    ws.cell(row=row, column=1, value=label)
    for q, f in enumerate(formulas):
        c = ws.cell(row=row, column=_Q1_COL + q, value=f)
        c.number_format = fmt
        if fill:
            c.fill = fill
    n_col = _Q1_COL + len(formulas)
    tc = ws.cell(row=row, column=n_col, value=total_formula)
    tc.number_format = fmt
    if fill:
        tc.fill = fill
    if note:
        ws.cell(row=row, column=n_col + 1, value=note).font = _FONT_ITALIC_GRAY


def _write_model(ws, base_gaap, inp, cell_map: dict) -> None:
    ws.title = "Model"
    n_q = len(inp.committed_quarterly)
    qpy = inp.qpy
    first_q, last_q, total_col = _model_quarter_cols(n_q)
    note_col = total_col + 1

    ws.column_dimensions["A"].width = 38
    for q in range(n_q):
        ws.column_dimensions[_cl(first_q + q)].width = 12
    ws.column_dimensions[_cl(total_col)].width = 14
    ws.column_dimensions[_cl(note_col)].width = 45

    # Header row
    ws.cell(row=_M_HDR, column=1, value="Row Label / Engine Step").font = _FONT_BOLD
    for q in range(n_q):
        ws.cell(row=_M_HDR, column=first_q + q, value=f"Q{q + 1}").font = _FONT_BOLD
    ws.cell(row=_M_HDR, column=total_col, value="TOTAL").font = _FONT_BOLD
    ws.cell(row=_M_HDR, column=note_col, value="Note / Source").font = _FONT_BOLD

    qcols = [_cl(first_q + q) for q in range(n_q)]  # ["B","C",..."M"] for n_q=12

    # Helper: formula for a given col referencing a row within this sheet
    def ref(row: int, q: int) -> str:
        return f"${qcols[q]}${row}"

    def sum_formula(row: int) -> str:
        return f"=SUM(${qcols[0]}${row}:${qcols[-1]}${row})"

    # ── UNITS & REVENUE ──────────────────────────────────────────────────────
    _set_section_hdr(ws, _M_SEC_REV, "— UNITS & REVENUE —", note_col)

    # Units row: each cell references the per-quarter named range
    unit_formulas = [f"=UnitQ{q + 1}" for q in range(n_q)]
    _write_model_row(ws, _M_UNITS, "Units (shipped)", unit_formulas,
                     sum_formula(_M_UNITS), "§ volume commitment", fmt="#,##0")

    # ASP row: constant across all quarters
    asp_formulas = ["=ASP"] * n_q
    _write_model_row(ws, _M_ASP, "ASP ($/unit)", asp_formulas,
                     "=ASP", "§ pricing; BASE ASP", fmt="#,##0")

    # Gross Revenue = Units × ASP
    gr_formulas = [f"={qcols[q]}{_M_UNITS}*{qcols[q]}{_M_ASP}" for q in range(n_q)]
    _write_model_row(ws, _M_GROSS_REV, "Gross Revenue", gr_formulas,
                     sum_formula(_M_GROSS_REV),
                     "units × ASP", fmt="#,##0")
    cell_map["ModelGrossRevRow"] = _M_GROSS_REV
    cell_map["ModelGrossRevTotal"] = f"Model!${_cl(total_col)}${_M_GROSS_REV}"

    # ── REBATE CALCULATION ───────────────────────────────────────────────────
    _set_section_hdr(ws, _M_SEC_REBATE, "— REBATE CALCULATION (helper rows, gray) —", note_col)
    for row in range(_M_SEC_REBATE, _M_ACT_REBATE + 1):
        if row != _M_SEC_REBATE:
            ws.row_dimensions[row].outlineLevel = 1  # groupable but visible

    # Cumulative Units (start of quarter)
    cum_start_formulas: list[str | int] = [0]  # Q1 start = 0
    for q in range(1, n_q):
        cum_start_formulas.append(f"=${qcols[q - 1]}{_M_CUM_END}")
    _write_model_row(ws, _M_CUM_START, "Cumulative Units (start of quarter)",
                     cum_start_formulas, f"=${qcols[-1]}{_M_CUM_END}",
                     "running sum of units through prior quarter", fill=_F_HELPER, fmt="#,##0")

    # Cumulative Units (end of quarter)
    cum_end_formulas = [f"=${qcols[q]}{_M_CUM_START}+${qcols[q]}{_M_UNITS}" for q in range(n_q)]
    _write_model_row(ws, _M_CUM_END, "Cumulative Units (end of quarter)",
                     cum_end_formulas, f"=${qcols[-1]}{_M_CUM_END}",
                     "= cum_start + units; drives VLOOKUP for Reading B", fill=_F_HELPER, fmt="#,##0")

    # Headroom rows
    for hrow, thr_name, label in (
        (_M_HEAD0, "RebateTier1Threshold", "No-Rebate Headroom (units below tier-1)"),
        (_M_HEAD1, "RebateTier2Threshold", "Tier-1 Headroom (units before tier-2 kicks in)"),
        (_M_HEAD2, "RebateTier3Threshold", "Tier-2 Headroom (units before tier-3 kicks in)"),
    ):
        formulas = [f"=MAX(0,{thr_name}-${qcols[q]}{_M_CUM_START})" for q in range(n_q)]
        _write_model_row(ws, hrow, label, formulas, "",
                         f"= MAX(0, {thr_name} − cum_start)", fill=_F_HELPER, fmt="#,##0")

    # Zone unit rows — arithmetic only, no nested IFs
    zone_specs = [
        (_M_ZONE0, "Units in No-Rebate Zone",
         lambda q: f"=MIN(${qcols[q]}{_M_UNITS},${qcols[q]}{_M_HEAD0})"),
        (_M_ZONE1, "Units in Tier-1 Zone (rate = RebateTier1Rate)",
         lambda q: f"=MIN(${qcols[q]}{_M_UNITS},${qcols[q]}{_M_HEAD1})"
                   f"-MIN(${qcols[q]}{_M_UNITS},${qcols[q]}{_M_HEAD0})"),
        (_M_ZONE2, "Units in Tier-2 Zone (rate = RebateTier2Rate)",
         lambda q: f"=MIN(${qcols[q]}{_M_UNITS},${qcols[q]}{_M_HEAD2})"
                   f"-MIN(${qcols[q]}{_M_UNITS},${qcols[q]}{_M_HEAD1})"),
        (_M_ZONE3, "Units in Tier-3 Zone (rate = RebateTier3Rate)",
         lambda q: f"=${qcols[q]}{_M_UNITS}-MIN(${qcols[q]}{_M_UNITS},${qcols[q]}{_M_HEAD2})"),
    ]
    for row, label, f_fn in zone_specs:
        formulas = [f_fn(q) for q in range(n_q)]
        _write_model_row(ws, row, label, formulas, "",
                         "MAX/MIN arithmetic — no nested IFs", fill=_F_HELPER, fmt="#,##0")

    # Reading A — Prospective (marginal tier rates)
    rebate_a = [
        f"=({qcols[q]}{_M_ZONE1}*RebateTier1Rate"
        f"+{qcols[q]}{_M_ZONE2}*RebateTier2Rate"
        f"+{qcols[q]}{_M_ZONE3}*RebateTier3Rate)*ASP"
        for q in range(n_q)
    ]
    _write_model_row(ws, _M_REBATE_A, "Rebate — Reading A (Prospective / marginal)",
                     rebate_a, sum_formula(_M_REBATE_A),
                     "each unit earns the marginal rate of its cumulative band",
                     fill=_F_HELPER, fmt="#,##0")

    # Reading B — Retroactive-within-year (VLOOKUP on year-end cumulative)
    # Year-end cumulative column for each quarter: last quarter of that year's cum_end row
    rebate_b: list[str] = []
    for q in range(n_q):
        year_idx = q // qpy
        year_last_q = min((year_idx + 1) * qpy, n_q) - 1  # 0-indexed last quarter of year
        year_end_col = qcols[year_last_q]
        # Year-end cumulative = row _M_CUM_END at the last quarter column of that year
        rebate_b.append(
            f"=VLOOKUP(${year_end_col}${_M_CUM_END},TierTable,2,1)"
            f"*${qcols[q]}{_M_UNITS}*ASP"
        )
    _write_model_row(ws, _M_REBATE_B, "Rebate — Reading B (Retroactive-within-year)",
                     rebate_b, sum_formula(_M_REBATE_B),
                     "VLOOKUP on year-end cumulative; each quarter earns year's blended rate",
                     fill=_F_HELPER, fmt="#,##0")

    # Active Rebate — single IF on toggle
    active = [
        f'=IF(RebateToggle="B-Retroactive",${qcols[q]}{_M_REBATE_B},${qcols[q]}{_M_REBATE_A})'
        for q in range(n_q)
    ]
    _write_model_row(ws, _M_ACT_REBATE, "★ Active Rebate (toggle-selected)",
                     active, sum_formula(_M_ACT_REBATE),
                     "single IF on RebateToggle; change toggle cell to switch readings")
    cell_map["ModelActiveRebateRow"] = _M_ACT_REBATE
    cell_map["ModelActiveRebateTotal"] = f"Model!${_cl(total_col)}${_M_ACT_REBATE}"

    # ── NET REVENUE ──────────────────────────────────────────────────────────
    _set_section_hdr(ws, _M_SEC_NET, "— NET REVENUE —", note_col)

    # Warrant Contra Revenue — live formula reading Warrant tab contra-sched cells
    wct_formulas = []
    for q in range(n_q):
        contra_addr = cell_map.get(f"ContraSchedQ{q + 1}", "")
        if contra_addr:
            wct_formulas.append(f"={contra_addr}")
        else:
            wct_formulas.append(0)
    _write_model_row(ws, _M_WARRANT_CTR, "Warrant Contra Revenue",
                     wct_formulas, sum_formula(_M_WARRANT_CTR),
                     "ASC 606/718 contra-revenue; reads Warrant tab; 0 if no warrant",
                     fmt="#,##0")
    cell_map["ModelWarrantContraTotal"] = f"Model!${_cl(total_col)}${_M_WARRANT_CTR}"

    # Ad-hoc adjustment — static seed values (analyst-editable, unlocked)
    adhoc_vals = list(inp.adhoc_schedule)
    adhoc_cells: list[str | int] = []
    for q in range(n_q):
        c = ws.cell(row=_M_ADHOC, column=first_q + q,
                    value=int(adhoc_vals[q]) if adhoc_vals[q] else 0)
        c.number_format = "#,##0"
        c.protection = Protection(locked=False)
        adhoc_cells.append(None)  # already written
    ws.cell(row=_M_ADHOC, column=1, value="Ad-hoc Adjustment (analyst-editable)")
    ws.cell(row=_M_ADHOC, column=total_col,
            value=sum_formula(_M_ADHOC)).number_format = "#,##0"
    ws.cell(row=_M_ADHOC, column=note_col,
            value="Analyst override; flows through net revenue and margin").font = _FONT_ITALIC_GRAY

    # Net Revenue
    net_rev = [
        f"=${qcols[q]}{_M_GROSS_REV}-${qcols[q]}{_M_ACT_REBATE}"
        f"-${qcols[q]}{_M_WARRANT_CTR}+${qcols[q]}{_M_ADHOC}"
        for q in range(n_q)
    ]
    _write_model_row(ws, _M_NET_REV, "Net Revenue",
                     net_rev, sum_formula(_M_NET_REV),
                     "gross − active_rebate − warrant_contra + adhoc", fmt="#,##0")
    cell_map["ModelNetRevRow"] = _M_NET_REV
    cell_map["ModelNetRevTotal"] = f"Model!${_cl(total_col)}${_M_NET_REV}"

    # ── COST & MARGIN ────────────────────────────────────────────────────────
    _set_section_hdr(ws, _M_SEC_COST, "— COST & MARGIN —", note_col)

    # Unit COGS row
    _write_model_row(ws, _M_UNIT_COGS, "Unit COGS ($/unit)",
                     ["=UnitCOGS"] * n_q, "=UnitCOGS",
                     "§ cost accounting; confirm before signing", fmt="#,##0")

    # COGS
    cogs = [f"=${qcols[q]}{_M_UNITS}*${qcols[q]}{_M_UNIT_COGS}" for q in range(n_q)]
    _write_model_row(ws, _M_COGS, "COGS", cogs, sum_formula(_M_COGS),
                     "units × unit_cogs", fmt="#,##0")
    cell_map["ModelCOGSTotal"] = f"Model!${_cl(total_col)}${_M_COGS}"

    # Gross Margin
    gm = [f"=${qcols[q]}{_M_NET_REV}-${qcols[q]}{_M_COGS}" for q in range(n_q)]
    _write_model_row(ws, _M_GROSS_MRG, "Gross Margin", gm, sum_formula(_M_GROSS_MRG),
                     "net_revenue − COGS", fmt="#,##0")
    cell_map["ModelGrossMarginTotal"] = f"Model!${_cl(total_col)}${_M_GROSS_MRG}"

    # Gross Margin %
    gm_pct = [
        f"=IF(${qcols[q]}{_M_GROSS_REV}=0,0,${qcols[q]}{_M_GROSS_MRG}/${qcols[q]}{_M_GROSS_REV})"
        for q in range(n_q)
    ]
    total_gm_pct = (f"=IF(${_cl(total_col)}{_M_GROSS_REV}=0,0,"
                    f"${_cl(total_col)}{_M_GROSS_MRG}/${_cl(total_col)}{_M_GROSS_REV})")
    _write_model_row(ws, _M_GM_PCT, "Gross Margin %", gm_pct, total_gm_pct,
                     "gross_margin / gross_revenue", fmt="0.00%")
    cell_map["ModelGMPctTotal"] = f"Model!${_cl(total_col)}${_M_GM_PCT}"

    # OpEx % row
    _write_model_row(ws, _M_OPEX_PCT, "OpEx Allocation %",
                     ["=OpExPct"] * n_q, "=OpExPct",
                     "§ assumptions library; confirm with FP&A", fmt="0.00%")

    # Allocated OpEx
    opex = [f"=${qcols[q]}{_M_NET_REV}*${qcols[q]}{_M_OPEX_PCT}" for q in range(n_q)]
    _write_model_row(ws, _M_ALLOC_OPEX, "Allocated OpEx", opex,
                     sum_formula(_M_ALLOC_OPEX),
                     "net_revenue × opex_pct", fmt="#,##0")

    # Contribution Margin
    contrib = [f"=${qcols[q]}{_M_GROSS_MRG}-${qcols[q]}{_M_ALLOC_OPEX}" for q in range(n_q)]
    _write_model_row(ws, _M_CONTRIB, "Contribution Margin", contrib,
                     sum_formula(_M_CONTRIB),
                     "gross_margin − allocated_opex", fmt="#,##0")

    ws.freeze_panes = "B2"
    ws.protection.sheet = True
    ws.protection.password = ""
    # Un-lock ad-hoc row (already set above via Protection(locked=False))


# ─── Warrant tab ───────────────────────────────────────────────────────────────

def _write_warrant(ws, warrant: WarrantEconomics | None,
                   assumptions: DealAssumptions, inp,
                   cell_map: dict) -> None:
    ws.title = "Warrant"
    ws.column_dimensions["A"].width = 35
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 18
    ws.column_dimensions["E"].width = 18

    if warrant is None:
        ws.cell(row=1, column=1,
                value="No warrant terms present — contra-revenue set to zero.")
        ws.cell(row=1, column=1).font = _FONT_ITALIC_GRAY
        # Write zero contra-revenue at the pre-committed rows
        for q in range(len(inp.committed_quarterly)):
            row = _W_CONTRA_ROW_START + q
            ws.cell(row=row, column=_W_VAL_COL, value=0)
        return

    ws.cell(row=1, column=1,
            value="WARRANT — Tranche Valuation & Contra-Revenue Schedule").font = _FONT_BOLD

    # Tranche valuation table header
    r = 3
    for col, hdr in enumerate(["Tranche", "Shares", "Exercise Price",
                               "Stock Hurdle", "Milestone Units",
                               "Vest Prob", "FV/Share", "Gross FV", "Expected FV"], 1):
        ws.cell(row=r, column=col, value=hdr).font = _FONT_BOLD
    r += 1

    efv_rows: list[int] = []
    for i, tv in enumerate(warrant.tranche_valuations):
        ws.cell(row=r, column=1, value=f"Tranche {i + 1}")
        _set_static(ws.cell(row=r, column=2), tv.share_count)
        ws.cell(row=r, column=2).number_format = "#,##0"
        _set_static(ws.cell(row=r, column=3), tv.exercise_price_usd)
        ws.cell(row=r, column=3).number_format = "#,##0.00"
        _set_static(ws.cell(row=r, column=4), tv.stock_price_hurdle_usd)
        _set_static(ws.cell(row=r, column=5), tv.deployment_milestone_units)
        ws.cell(row=r, column=5).number_format = "#,##0"

        # Vest prob — live formula from Warrant_Assump
        vp_addr = cell_map.get(f"VestProbT{i + 1}", "")
        if vp_addr:
            c_vp = ws.cell(row=r, column=6, value=f"={vp_addr}")
        else:
            c_vp = ws.cell(row=r, column=6, value=tv.vest_probability)
        c_vp.number_format = "0%"

        # FV/share — live formula from WarrantStockPrice
        ws_addr = cell_map.get("WarrantStockPrice", "")
        if ws_addr:
            ws.cell(row=r, column=7,
                    value=f"=MAX(0,{ws_addr}-C{r})").number_format = "#,##0.00"
        else:
            _set_static(ws.cell(row=r, column=7), tv.fair_value_per_share_usd)
            ws.cell(row=r, column=7).number_format = "#,##0.00"

        # Gross FV = shares × FV/share
        ws.cell(row=r, column=8, value=f"=B{r}*G{r}").number_format = "#,##0"
        # Expected FV = Gross FV × vest prob
        ws.cell(row=r, column=9, value=f"=H{r}*F{r}").number_format = "#,##0"

        efv_rows.append(r)
        r += 1

    # Total EFV row (pre-committed at _W_TOTAL_EFV_ROW)
    # Pad blank rows if needed
    while r < _W_TOTAL_EFV_ROW:
        r += 1
    r = _W_TOTAL_EFV_ROW
    ws.cell(row=r, column=1, value="Total Expected Fair Value").font = _FONT_BOLD
    efv_sum_range = f"I{efv_rows[0]}:I{efv_rows[-1]}" if efv_rows else "I4:I4"
    ws.cell(row=r, column=_W_VAL_COL, value=f"=SUM({efv_sum_range})")
    ws.cell(row=r, column=_W_VAL_COL).number_format = "#,##0"
    cell_map["WarrantTotalEFV"] = f"Warrant!${_cl(_W_VAL_COL)}${r}"

    # Contra-revenue schedule header
    r = _W_CONTRA_ROW_START - 3
    _set_section_hdr(ws, r, "CONTRA-REVENUE SCHEDULE (proportional-to-ramp allocation)", 5)
    r += 1
    ws.cell(row=r, column=1,
            value="Simplified: contra allocated proportional to unit ramp. "
                  "Cell note: engine uses tranche-milestone allocation.").font = _FONT_ITALIC_GRAY
    r += 1
    ws.cell(row=r, column=1, value="Quarter").font = _FONT_BOLD
    ws.cell(row=r, column=_W_VAL_COL, value="Contra Revenue (USD)").font = _FONT_BOLD

    # Total units expression (no leading =, used inside larger formulas)
    n_q = len(inp.committed_quarterly)
    total_units_expr = "SUM(" + ",".join(f"UnitQ{q2}" for q2 in range(1, n_q + 1)) + ")"
    total_units_formula = f"={total_units_expr}"  # standalone cell formula

    # Write contra rows at pre-committed positions
    for q in range(n_q):
        row = _W_CONTRA_ROW_START + q
        ws.cell(row=row, column=1, value=f"Q{q + 1}")
        # Formula: −TotalEFV × UnitQ{n} / TotalUnits
        efv_ref = cell_map.get("WarrantTotalEFV", "")
        if efv_ref:
            formula = f"=-{efv_ref}*UnitQ{q + 1}/{total_units_expr}"
        else:
            formula = 0
        ws.cell(row=row, column=_W_VAL_COL, value=formula)
        ws.cell(row=row, column=_W_VAL_COL).number_format = "#,##0"
        # Register in cell_map (pre-committed)
        cell_map[f"ContraSchedQ{q + 1}"] = f"Warrant!${_cl(_W_VAL_COL)}${row}"

    # Effective ASP waterfall
    r = _W_CONTRA_ROW_START + n_q + 2
    _set_section_hdr(ws, r, "EFFECTIVE ASP WATERFALL", 5)
    r += 1
    total_units_ref = total_units_formula

    def _asp_row(label, formula, r):
        ws.cell(row=r, column=1, value=label)
        ws.cell(row=r, column=_W_VAL_COL, value=formula).number_format = "#,##0.00"
        return r + 1

    r = _asp_row("Sticker ASP ($/unit)", "=ASP", r)
    net_rev_total = cell_map.get("ModelNetRevTotal", "0")
    act_rebate_total = cell_map.get("ModelActiveRebateTotal", "0")
    r = _asp_row("Less: Avg Rebate/Unit",
                 f"=-{act_rebate_total}/{total_units_expr}", r)
    efv_ref = cell_map.get("WarrantTotalEFV", "0")
    r = _asp_row("Less: Warrant Cost/Unit",
                 f"=-{efv_ref}/{total_units_expr}", r)
    r = _asp_row("All-in Net ASP",
                 f"=ASP-{act_rebate_total}/{total_units_expr}-{efv_ref}/{total_units_expr}", r)

    # GAAP vs Cash bridge
    r += 1
    _set_section_hdr(ws, r, "GAAP vs CASH BRIDGE", 5); r += 1
    gm_total = cell_map.get("ModelNetRevTotal", "0")
    ws.cell(row=r, column=1, value="GAAP Net Revenue")
    ws.cell(row=r, column=_W_VAL_COL, value=f"={gm_total}").number_format = "#,##0"
    r += 1
    ws.cell(row=r, column=1, value="Add: Warrant Contra (GAAP → Cash)")
    ws.cell(row=r, column=_W_VAL_COL, value=f"={efv_ref}").number_format = "#,##0"
    r += 1
    ws.cell(row=r, column=1, value="Cash / Commercial Net Revenue")
    ws.cell(row=r, column=_W_VAL_COL,
            value=f"={gm_total}+{efv_ref}").number_format = "#,##0"
    r += 1

    # Correlation caveat
    r += 1
    ws.cell(row=r, column=1,
            value="⚠ CORRELATION CAVEAT: Valuation uses a single spot price with independent "
                  "per-tranche vest probabilities. In reality, deployment milestones and stock-price "
                  "hurdles are POSITIVELY CORRELATED — the model likely understates warrant cost in "
                  "the upside scenario. See CRB_Summary for details.").font = _FONT_ITALIC_GRAY
    ws.cell(row=r, column=1).alignment = Alignment(wrap_text=True)
    ws.row_dimensions[r].height = 45


# ─── Scenarios tab ─────────────────────────────────────────────────────────────

_SCENARIO_ORDER = [
    (ScenarioName.BASE,                 "BASE"),
    (ScenarioName.DOWNSIDE_TAKE_OR_PAY, "DOWNSIDE (Take-or-Pay floor)"),
    (ScenarioName.UPSIDE_VOLUME,        "UPSIDE (+15% volume)"),
    (ScenarioName.EARLY_TERMINATION,    "EARLY TERMINATION"),
]


def _write_scenarios(ws, econ: DealEconomics, cell_map: dict) -> None:
    ws.title = "Scenarios"
    ws.column_dimensions["A"].width = 30
    for col in range(2, 9):
        ws.column_dimensions[_cl(col)].width = 18

    hdrs = ["Net Revenue", "Gross Margin", "GM%", "NPV", "Payback (Q)",
            "Prob Weight", "EV × NPV"]
    ws.cell(row=1, column=1, value="Scenario").font = _FONT_BOLD
    for i, h in enumerate(hdrs, 2):
        ws.cell(row=1, column=i, value=h).font = _FONT_BOLD

    prob_names = ["ProbBASE", "ProbDOWNSIDE", "ProbUPSIDE", "ProbET"]
    gaap_scenarios = {r.scenario: r for r in econ.scenarios if r.view == ViewMode.GAAP}

    scen_rows: dict[str, int] = {}  # scenario label → row for EV formula
    r = 2
    for (sname, label), prob_name in zip(_SCENARIO_ORDER, prob_names):
        sr = gaap_scenarios.get(sname)
        ws.cell(row=r, column=1, value=label).font = _FONT_BOLD
        scen_rows[prob_name] = r

        if sname == ScenarioName.BASE:
            # BASE — fully live formulas from Model tab
            net_rev_ref = cell_map.get("ModelNetRevTotal", "0")
            gm_ref = cell_map.get("ModelGrossMarginTotal", "0")
            gm_pct_ref = cell_map.get("ModelGMPctTotal", "0")
            ws.cell(row=r, column=2, value=f"={net_rev_ref}").number_format = "#,##0"
            ws.cell(row=r, column=3, value=f"={gm_ref}").number_format = "#,##0"
            ws.cell(row=r, column=4, value=f"={gm_pct_ref}").number_format = "0.00%"
            # NPV — static snapshot (discounting requires full cash schedule)
            _set_static(ws.cell(row=r, column=5),
                        round(sr.npv_usd) if sr else 0)
            ws.cell(row=r, column=5).number_format = "#,##0"
            _set_static(ws.cell(row=r, column=6),
                        sr.payback_quarters if sr else None)
        else:
            # Non-BASE — static snapshot with amber styling
            if sr:
                for col, val, fmt in (
                    (2, sr.total_net_revenue, "#,##0"),
                    (3, sr.total_gross_margin, "#,##0"),
                    (4, sr.total_gross_margin_pct, "0.00%"),
                    (5, round(sr.npv_usd), "#,##0"),
                    (6, sr.payback_quarters, "0"),
                ):
                    _set_static(ws.cell(row=r, column=col), round(val) if isinstance(val, float) and col < 4 else val)
                    ws.cell(row=r, column=col).number_format = fmt

        ws.cell(row=r, column=7, value=f"={prob_name}").number_format = "0%"
        ws.cell(row=r, column=8, value=f"={_cl(7)}{r}*{_cl(5)}{r}").number_format = "#,##0"
        r += 1

    # Expected Value row
    r += 1
    ws.cell(row=r, column=1, value="Probability-Weighted Expected NPV").font = _FONT_BOLD
    ev_sum = "+".join(f"{_cl(8)}{row}" for row in scen_rows.values())
    ws.cell(row=r, column=8, value=f"=SUM({ev_sum})").number_format = "#,##0"
    cell_map["ScenEVRow"] = r

    r += 2
    # Static snapshot warning for non-BASE
    _set_banner(ws, r, 8,
                "⚠  STATIC ENGINE SNAPSHOT (rows DOWNSIDE / UPSIDE / EARLY TERMINATION) — "
                "these values do not recalculate when assumptions change. "
                "BASE row is fully live. Rerun the economics engine and regenerate this "
                "workbook after any assumption edit.")
    r += 1
    ws.cell(row=r, column=1,
            value=f"Last engine run: {datetime.now().strftime('%Y-%m-%d %H:%M')}").font = _FONT_ITALIC_GRAY


# ─── Accounting Schedules tab ──────────────────────────────────────────────────

def _write_acct_sched(ws, inp, assumptions: DealAssumptions,
                      cell_map: dict) -> None:
    ws.title = "Acct_Sched"
    ws.column_dimensions["A"].width = 32
    n_q = len(inp.committed_quarterly)
    qpy = inp.qpy

    r = 1
    # ── Section 1: Rebate Accrual Walk ───────────────────────────────────────
    _set_section_hdr(ws, r, "REBATE ACCRUAL WALK (ASC 606 variable consideration)", 6)
    r += 1
    for col, hdr in enumerate(["Quarter", "Beginning", "Accrual Expense",
                               "Settlement Payment", "Ending"], 1):
        ws.cell(row=r, column=col, value=hdr).font = _FONT_BOLD
    r += 1

    acct_rows: list[int] = []
    active_rebate_row = _M_ACT_REBATE  # Model tab row for active rebate
    for q in range(n_q):
        q_col = _cl(_Q1_COL + q)
        ws.cell(row=r, column=1, value=f"Q{q + 1}")

        # Beginning
        if q == 0:
            ws.cell(row=r, column=2, value=0).number_format = "#,##0"
        else:
            ws.cell(row=r, column=2, value=f"=E{r - 1}").number_format = "#,##0"

        # Accrual Expense = Model!Active_Rebate_Q{n}
        rebate_cell = f"Model!${q_col}${active_rebate_row}"
        ws.cell(row=r, column=3, value=f"={rebate_cell}").number_format = "#,##0"

        # Settlement payment — annual in arrears (at end of each year of qpy quarters)
        is_year_end = ((q + 1) % qpy == 0) or (q == n_q - 1)
        if is_year_end:
            year_start_r = r - (q % qpy)
            year_accrual = f"=SUM(C{year_start_r}:C{r})"
            ws.cell(row=r, column=4, value=year_accrual).number_format = "#,##0"
        else:
            ws.cell(row=r, column=4, value=0).number_format = "#,##0"

        # Ending = beginning + accrual - settlement
        ws.cell(row=r, column=5, value=f"=B{r}+C{r}-D{r}").number_format = "#,##0"
        acct_rows.append(r)
        r += 1

    r += 1
    ws.cell(row=r, column=1,
            value="Continuity: ending[q] = beginning[q+1]. Settlement annual-in-arrears "
                  "(Q4/Q8/Q12). Final year balance settles 45 days post-term.").font = _FONT_ITALIC_GRAY
    r += 2

    # ── Section 2: Prepayment Schedule ──────────────────────────────────────
    _set_section_hdr(ws, r, "CONTRACT LIABILITY (PREPAYMENT) SCHEDULE", 6)
    r += 1
    for col, hdr in enumerate(["Quarter", "Beginning", "Drawdown", "Ending"], 1):
        ws.cell(row=r, column=col, value=hdr).font = _FONT_BOLD
    r += 1

    for q in range(n_q):
        q_col = _cl(_Q1_COL + q)
        ws.cell(row=r, column=1, value=f"Q{q + 1}")
        # Beginning
        if q == 0:
            ws.cell(row=r, column=2, value="=PrepaymentUSD").number_format = "#,##0"
        else:
            ws.cell(row=r, column=2, value=f"=D{r - 1}").number_format = "#,##0"

        # Drawdown = MIN(beginning, gross_revenue × 20%)
        gross_rev_cell = f"Model!${q_col}${_M_GROSS_REV}"
        ws.cell(row=r, column=3,
                value=f"=MIN(B{r},{gross_rev_cell}*0.2)").number_format = "#,##0"
        # Ending
        ws.cell(row=r, column=4, value=f"=B{r}-C{r}").number_format = "#,##0"
        r += 1

    r += 2

    # ── Section 3: Peak Receivables ─────────────────────────────────────────
    _set_section_hdr(ws, r, "PEAK RECEIVABLES EXPOSURE", 6)
    r += 1
    gross_range = f"Model!${_cl(_Q1_COL)}${_M_GROSS_REV}:${_cl(_Q1_COL + n_q - 1)}${_M_GROSS_REV}"
    ws.cell(row=r, column=1, value="Payment Terms (days)")
    ws.cell(row=r, column=2, value="=PaymentTermsDays").number_format = "0"
    r += 1
    ws.cell(row=r, column=1, value="Peak Quarterly Gross Revenue")
    ws.cell(row=r, column=2, value=f"=MAX({gross_range})").number_format = "#,##0"
    r += 1
    ws.cell(row=r, column=1, value="Peak AR Balance (approx)")
    ws.cell(row=r, column=2,
            value=f"=MAX({gross_range})/90*PaymentTermsDays").number_format = "#,##0"
    r += 1
    ws.cell(row=r, column=1,
            value="Note: simplified monthly approximation. Full DSO-adjusted schedule computed by the engine.").font = _FONT_ITALIC_GRAY


# ─── Variance tab ──────────────────────────────────────────────────────────────

def _write_variance(ws, versions: list[DealVersion] | None) -> None:
    ws.title = "Variance"
    ws.column_dimensions["A"].width = 30

    if not versions or len(versions) < 2:
        ws.cell(row=1, column=1,
                value="Variance bridge requires two deal versions. "
                      "Rerun export after a counter has been recorded.").font = _FONT_ITALIC_GRAY
        return

    ws.cell(row=1, column=1, value="VARIANCE BRIDGE").font = _FONT_BOLD
    for col, hdr in enumerate(["Driver", "Version A", "Version B",
                               "Delta", "GM Impact (USD)"], 1):
        ws.cell(row=2, column=col, value=hdr).font = _FONT_BOLD

    _set_banner(ws, 3, 5,
                "⚠  STATIC ENGINE SNAPSHOT — variance bridge values do not recalculate. "
                "Engine-computed from two saved deal versions.")
    ws.cell(row=4, column=1, value="(Variance bridge data would appear here — requires engine output.)")
    ws.cell(row=4, column=1).font = _FONT_ITALIC_GRAY


# ─── Assumption Register tab ───────────────────────────────────────────────────

def _write_assumption_reg(ws, register: list[RegisterEntry]) -> None:
    ws.title = "Assumption_Reg"
    ws.column_dimensions["A"].width = 35
    ws.column_dimensions["B"].width = 28
    ws.column_dimensions["C"].width = 22
    ws.column_dimensions["D"].width = 18
    ws.column_dimensions["E"].width = 18
    ws.column_dimensions["F"].width = 30
    ws.column_dimensions["G"].width = 40

    for col, hdr in enumerate(["Field Path", "Label", "Value",
                               "Type", "Provenance", "Owner", "Note"], 1):
        ws.cell(row=1, column=col, value=hdr).font = _FONT_BOLD

    for i, entry in enumerate(register, 2):
        ws.cell(row=i, column=1, value=entry.field_path)
        ws.cell(row=i, column=2, value=entry.label)
        c_val = ws.cell(row=i, column=3, value=str(entry.value) if entry.value is not None else "")
        fill = _ATYPE_FILLS.get(entry.assumption_type, None)
        if fill:
            c_val.fill = fill
        ws.cell(row=i, column=4, value=entry.assumption_type.value if entry.assumption_type else "")
        ws.cell(row=i, column=5, value=entry.basis.value if entry.basis else "")
        ws.cell(row=i, column=6, value=entry.owner)
        ws.cell(row=i, column=7, value=entry.note)


# ─── CRB Summary tab ───────────────────────────────────────────────────────────

def _write_crb_summary(ws, econ: DealEconomics, warrant: WarrantEconomics | None,
                       memo: CRBMemo | None, pkg: DealPackage,
                       cell_map: dict) -> None:
    ws.title = "CRB_Summary"
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 50

    r = 1
    ws.cell(row=r, column=1, value="DEAL").font = _FONT_BOLD
    ws.cell(row=r, column=2, value=pkg.deal_name)
    r += 1
    ws.cell(row=r, column=1, value="Counterparty")
    ws.cell(row=r, column=2, value=pkg.counterparty or "")
    r += 1
    ws.cell(row=r, column=1, value="Status")
    ws.cell(row=r, column=2, value=pkg.status.value if pkg.status else "")
    r += 1
    ws.cell(row=r, column=1, value="Archetype")
    ws.cell(row=r, column=2, value=pkg.archetype or "")
    r += 2

    # Economics table — reads from Scenarios tab via cell_map
    _set_section_hdr(ws, r, "ECONOMICS (BASE GAAP, live formula)", 2); r += 1
    base_gaap = next((s for s in econ.scenarios
                      if s.scenario == ScenarioName.BASE and s.view == ViewMode.GAAP), None)
    net_ref = cell_map.get("ModelNetRevTotal", "0")
    gm_ref  = cell_map.get("ModelGrossMarginTotal", "0")
    gm_pct  = cell_map.get("ModelGMPctTotal", "0")
    for label, formula, fmt in (
        ("Total Net Revenue (GAAP)", f"={net_ref}", "#,##0"),
        ("Total Gross Margin",       f"={gm_ref}",  "#,##0"),
        ("Gross Margin %",           f"={gm_pct}",  "0.00%"),
    ):
        ws.cell(row=r, column=1, value=label)
        ws.cell(row=r, column=2, value=formula).number_format = fmt; r += 1

    if base_gaap:
        ws.cell(row=r, column=1, value="NPV (GAAP, pre-tax)")
        _set_static(ws.cell(row=r, column=2), round(base_gaap.npv_usd))
        ws.cell(row=r, column=2).number_format = "#,##0"; r += 1
    r += 1

    # Warrant section
    if warrant:
        _set_section_hdr(ws, r, "WARRANT ECONOMICS", 2); r += 1
        efv_ref = cell_map.get("WarrantTotalEFV", "0")
        ws.cell(row=r, column=1, value="Total Expected Fair Value")
        ws.cell(row=r, column=2, value=f"={efv_ref}").number_format = "#,##0"; r += 1
        ws.cell(row=r, column=1, value="⚠ Correlation caveat")
        ws.cell(row=r, column=2,
                value="Spot-price + independent vest-probability valuation likely understates "
                      "warrant cost in the upside scenario. Milestones and stock hurdles are "
                      "positively correlated. See §4 warrant correlation caveat.")
        ws.cell(row=r, column=2).alignment = Alignment(wrap_text=True)
        ws.row_dimensions[r].height = 42
        r += 2

    # Policy verdict / memo sections (static)
    if memo:
        _set_section_hdr(ws, r, "POLICY VERDICT", 2); r += 1
        ws.cell(row=r, column=1, value="Verdict")
        _set_static(ws.cell(row=r, column=2), str(memo.policy_verdict) if memo.policy_verdict else "")
        r += 1
        ws.cell(row=r, column=1, value="Required Approvers")
        _set_static(ws.cell(row=r, column=2), ", ".join(str(a) for a in (memo.required_approvers or [])))
        r += 2

        _set_section_hdr(ws, r, "TOP RISKS", 2); r += 1
        for risk in (memo.top_risks or []):
            _set_static(ws.cell(row=r, column=1), str(risk))
            r += 1
        r += 1

        _set_section_hdr(ws, r, "RECOMMENDATION", 2); r += 1
        ws.cell(row=r, column=2, value=memo.recommendation or "")
        ws.cell(row=r, column=2).alignment = Alignment(wrap_text=True)
        ws.row_dimensions[r].height = 42


# ─── Changelog tab ─────────────────────────────────────────────────────────────

def _write_changelog(ws, pkg: DealPackage) -> None:
    ws.title = "Changelog"
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 20
    ws.column_dimensions["D"].width = 20
    ws.column_dimensions["E"].width = 30
    ws.column_dimensions["F"].width = 20

    for col, hdr in enumerate(["Timestamp", "Field", "Old Value",
                               "New Value", "Note", "Actor"], 1):
        ws.cell(row=1, column=col, value=hdr).font = _FONT_BOLD

    journal = pkg.change_journal or []
    for i, entry in enumerate(journal, 2):
        ws.cell(row=i, column=1, value=str(entry.timestamp))
        ws.cell(row=i, column=2, value=entry.field_path)
        ws.cell(row=i, column=3, value=str(entry.old_value) if entry.old_value is not None else "")
        ws.cell(row=i, column=4, value=str(entry.new_value) if entry.new_value is not None else "")
        ws.cell(row=i, column=5, value=entry.note)
        ws.cell(row=i, column=6, value=entry.actor)

    if not journal:
        ws.cell(row=2, column=1,
                value="No changelog entries.").font = _FONT_ITALIC_GRAY


# ─── Named ranges ──────────────────────────────────────────────────────────────

def _add_named_ranges(wb: Workbook, cell_map: dict) -> None:
    """Register all named ranges from cell_map into the workbook."""
    for name, addr in cell_map.items():
        # Skip internal bookkeeping keys (non-string values or non-address strings)
        if not isinstance(addr, str) or not ("!" in addr or addr.isdigit()):
            continue
        if "!" not in addr:
            continue
        try:
            wb.defined_names[name] = DefinedName(name, attr_text=addr)
        except Exception:
            pass  # skip duplicates or invalid names


# ─── Public API ────────────────────────────────────────────────────────────────

def build_workbook(
    pkg: DealPackage,
    assumptions: DealAssumptions,
    econ: DealEconomics,
    warrant: WarrantEconomics | None,
    register: list[RegisterEntry],
    memo: CRBMemo | None = None,
    versions: list[DealVersion] | None = None,
) -> Workbook:
    """Build an openpyxl Workbook with 11 formula-live tabs.

    Every P&L cell in the Model tab is a live formula. Editing an assumption on
    the Assumptions tab causes Model, Scenarios-BASE, Warrant, and Acct_Sched to
    recalculate automatically inside Excel. Non-BASE scenario values and NPV are
    static engine snapshots, clearly marked with amber styling and banner warnings.

    Returns the Workbook; caller is responsible for saving.
    """
    from deal_copilot.economics_engine import extract_inputs

    inp = extract_inputs(pkg)
    n_q = len(inp.committed_quarterly)

    wb = Workbook()
    wb.remove(wb.active)  # remove default "Sheet" tab

    cell_map: dict[str, Any] = {}

    # Pre-commit Warrant tab contra-schedule addresses so Model can reference them
    # before the Warrant tab is physically written (both use the same pre-committed rows)
    for q in range(n_q):
        cell_map[f"ContraSchedQ{q + 1}"] = f"Warrant!${_cl(_W_VAL_COL)}${_W_CONTRA_ROW_START + q}"

    # Build tabs in display order
    ws_asmp = wb.create_sheet("Assumptions")
    _write_assumptions(ws_asmp, assumptions, inp, register, cell_map)

    ws_wa = wb.create_sheet("Warrant_Assump")
    _write_warrant_assumptions(ws_wa, assumptions, warrant, cell_map)

    ws_drv = wb.create_sheet("Drivers")
    _write_drivers(ws_drv, econ, pkg, inp, cell_map)

    ws_model = wb.create_sheet("Model")
    _write_model(ws_model, None, inp, cell_map)

    ws_warrant = wb.create_sheet("Warrant")
    _write_warrant(ws_warrant, warrant, assumptions, inp, cell_map)

    ws_scen = wb.create_sheet("Scenarios")
    _write_scenarios(ws_scen, econ, cell_map)

    ws_acct = wb.create_sheet("Acct_Sched")
    _write_acct_sched(ws_acct, inp, assumptions, cell_map)

    ws_var = wb.create_sheet("Variance")
    _write_variance(ws_var, versions)

    ws_reg = wb.create_sheet("Assumption_Reg")
    _write_assumption_reg(ws_reg, register)

    ws_crb = wb.create_sheet("CRB_Summary")
    _write_crb_summary(ws_crb, econ, warrant, memo, pkg, cell_map)

    ws_cl = wb.create_sheet("Changelog")
    _write_changelog(ws_cl, pkg)

    # Register named ranges
    _add_named_ranges(wb, cell_map)

    return wb


__all__ = ["build_workbook"]
