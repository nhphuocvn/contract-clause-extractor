# Deal Economics Copilot

**A tool that reads a commercial contract and builds the full financial model of the deal — with every number traceable back to the clause it came from.**

When a large supply or purchase deal lands on a finance team's desk, someone has to turn dense legal prose into numbers: How much revenue? At what margin? What happens if the customer buys less than promised? What is the equity we handed them actually worth? Today that work is manual, slow, and hard to audit. This project automates the mechanical parts and shows its work at every step.

It is the working toolkit of a finance analyst on a hyperscaler GPU deal desk — the kind of multi-billion-dollar, multi-year chip-supply agreement (think the recent AMD/OpenAI and Nvidia-scale deals) where the contract is long, the terms interact, and an approval committee will challenge every figure.

---

## The core principle

> **The AI extracts and explains. Deterministic, tested code computes. No number produced by the AI ever enters a calculation.**

Large language models are excellent at reading a contract and pulling out "the take-or-pay floor is 80% of committed volume." They are unreliable at arithmetic and cannot be audited. So this tool draws a hard line:

- The **AI** reads the documents, extracts each commercial term as structured data, and attaches a **verbatim source quote** to every value so a human can verify it against the original.
- **Plain, tested Python** does all the math — the P&L, the scenarios, the valuations — as pure functions with no AI in the loop.

The result: every figure in the model traces back either to a specific clause in the contract or to a clearly-labelled, owner-assigned assumption. Nothing is a black box.

---

## What works today

This is a **backend prototype under active development.** The core is built and verified end-to-end — contract extraction, the economics engine, and the CRB-ready outputs around it:

### 1. Contract extraction
- Pulls all twelve commercial term types (pricing, volume commitment, rebates, take-or-pay, prepayment, payment terms, MFN price protection, termination, liability, supply commitment, warrant/equity, cross-references) from purchase agreements in DOCX or PDF.
- **~92% precision / 100% recall** against a hand-built ground-truth on a synthetic AMD–Meta GPU deal, and tested against a **real Intel–Micron SEC filing** — where it correctly extracted what was there and honestly returned "not found" for terms the real contract structures differently, including refusing to invent a number for an SEC-redacted `[***]` payment term.
- **Defends against malicious contracts.** Contract text is treated as data, never as instructions; a planted "IGNORE ALL PRIOR INSTRUCTIONS" clause produces no injected values.

### 2. Economics engine
A pure, fully-tested financial model that turns the extracted terms into deal economics:
- **Quarterly P&L** — gross revenue → rebates → warrant cost → net revenue → COGS → margin, in both GAAP and cash views.
- **Scenarios** — base case, downside (customer buys only the take-or-pay floor, with "banked units" mechanics), upside (+15% volume), and early termination — each with NPV, and payback shown two ways (with and without customer prepayment financing).
- **Ambiguity quantified, not guessed.** The synthetic rebate clause is genuinely ambiguous about whether crossing a volume tier applies retroactively. Rather than pick one reading, the tool models **both** and reports the gap: **$142.5M vs $183.5M — a $41M question** flagged for Legal to resolve before signing.
- **Warrant / equity valuation.** When a deal hands the customer stock (as these deals increasingly do), the tool values it as consideration given to the customer. On the synthetic deal at a $470 share price the warrant is worth **~$3.4B — larger than the deal's gross margin** — collapsing the effective price per unit from $25,000 to ~$1,490. It shows this as a **range** ($2.3B–$4.2B) across conservative/base/aggressive assumptions, because the inputs are strategic judgment, not contract facts.
- **Accounting schedules** an accountant can trust — rebate accrual walk, prepayment drawdown, and peak receivables exposure, each reconciling period to period.
- **Working capital modeled on a monthly grid.** Cash timing (not revenue recognition) runs monthly across all three legs — collections (DSO), supplier payments (DPO), and the inventory build (lead time) — so net-30 / net-60 / net-90 produce genuinely different peak receivables (**$166.7M / $333.3M / $500.0M**), NPV, and operating cash draw. The ramp's inventory build shows up as the **−$157M** working-capital draw it really is, pushing operational payback to Q6.
- **CRB-ready outputs.** A configurable **policy engine** routes the deal (verdict + required approvers), an **Assumption Register** tags every input by type and owner, an **Assumption Gap Report** ranks the open questions by dollar sensitivity, and a **CRB memo** is assembled with every number injected from the engine — the AI only writes the prose.

**Quality bar:** every piece of financial math is covered by tests whose expected values were computed **by hand**, not read back from the code — **204 passing tests** (including 49 Excel golden-file tests that assert live formulas, not cached values).

---

## Status: active development

This is a backend prototype. The extraction and economics core — and the Excel model that presents it — are built and tested; the analyst-facing web application around them is planned.

**Built (Phases 1–7):**
- ✅ Data schemas + a synthetic two-document deal package with ground truth
- ✅ Contract extraction, validation, untrusted-input defense, and an accuracy harness
- ✅ Economics engine — P&L, scenarios, NPV, sensitivities, rebate-ambiguity range, accounting schedules
- ✅ Monthly working-capital cash layer — DSO / DPO / inventory-lead, so payment terms drive genuinely different receivables, NPV, and the operating cash draw
- ✅ Warrant / equity valuation, wired into the model
- ✅ Negotiation tools — deal versioning, change journal, a "variance bridge" that explains what changed between two negotiation rounds dollar by dollar (and reconciles exactly to the total), ad-hoc manual line items, and goal-seek ("what ASP holds gross margin at the target?")
- ✅ Policy engine — encodes a Contract Review Board's rules and auto-routes a deal (verdict + required approvers: "ESCALATE — CFO, General Counsel, Treasury")
- ✅ Assumption Register + Assumption Gap Report — every input typed and owner-tagged; open questions ranked by dollar sensitivity (COGS $225M → cost accounting; rebate ambiguity $41M → Legal)
- ✅ CRB memo + benchmarks + glossary — a one-page approval memo, prose written by the AI but every number injected from the engine; portfolio benchmarks with a staleness check; a no-jargon glossary
- ✅ Excel export — a 14-tab workbook built like a circuit: every input is an editable named-range cell and every downstream number is a formula that reads it, so a finance person can trace any figure to its source and edit any assumption and watch the model recompute (NPV is a live `=NPV()`; the warrant contra-revenue scales with a single "Demand %" dial). It is self-documenting (plain-English notes, verbatim clause text, and hover comments) and **fully editable — no sheet protection, no passwords.** Verified clean: a cell-by-cell scan across all 14 tabs confirms zero formula-error cells (`#NAME?` / `#REF!` / `#VALUE!`).

**Planned:**
- ⬜ A user interface for the deal-modeling workflow

**A note on the UI:** the *economics / deal-modeling* layer described above has **no interface yet** — it runs and is exercised through its test suite and small demo scripts. The repository also contains the project's predecessor, a simpler **Contract Clause Extractor** with a working command-line tool and Streamlit web app for single-clause field extraction; the Deal Economics Copilot is built on that foundation. (See *Repository layout* below.)

---

## A concrete example of the judgment it surfaces

On the synthetic GPU deal, a naïve read says "$3.75B of revenue at a healthy margin." The tool surfaces what an experienced analyst would actually flag:

| Insight | Why it matters |
|---|---|
| Rebate ambiguity = **$41M** | One sentence in the contract has two defensible readings worth $41M apart — resolve with Legal *before* signing. |
| Warrant cost ≈ **$3.4B** | The "free" stock given to the customer is worth more than the deal's gross margin; effective price per unit drops from $25,000 to ~$1,490. |
| Warrant cost is **asymmetric** | It rises precisely when the deal succeeds and the seller's stock climbs — a risk that grows when things go well. |

These are exactly the questions that get asked in an approval meeting — and the tool answers each with a number tied to its source.

---

## How it is built (for the technically curious)

- **Python 3.13**, Pydantic v2 for every data shape, OpenAI structured-output API for extraction (temperature 0, schema-constrained, retry on parse failure, cached by file hash).
- The economics engine is **pure functions** — no file access, no global state — so results are reproducible, fast to recompute, and trivially testable. Every intermediate value a human would want to see is its own named field.
- Assumptions come from a versioned library with **provenance on every value** (contract clause / market data / policy number / strategic judgment), each carrying who is accountable for confirming it.

### Repository layout
- `deal_copilot/` — the Deal Economics Copilot (this README): extraction, validation, economics engine, warrant economics, and `excel_export.py` (the live-formula workbook builder).
- `tests/` — the 204 hand-verified tests (financial math + Excel golden-file).
- `scripts/` — `build_demo_workbook.py` (generates `deal_model_demo.xlsx`) and `_verify_no_error_cells.py` (scans the workbook for formula-error cells).
- `data/` — the synthetic deal package, ground truth, and the assumptions library.
- `extract.py`, `app.py`, `index.py`, `query.py`, `excel_export.py` (repo root) — the predecessor **Contract Clause Extractor** (CLI + Streamlit UI) the copilot builds on.
- `KICKOFF.md` — the full product specification and build log.

### Running the tests
```powershell
python -m pip install openai pydantic PyPDF2 python-dotenv streamlit openpyxl python-docx pytest
python -m pytest tests/ -v
```

Two demo scripts print the economics and warrant analysis for the synthetic deal (no API key needed):
```powershell
python -m deal_copilot._smoke.compute_phase3_economics
python -m deal_copilot._smoke.compute_warrant_economics
```

Build the full Excel model for the synthetic deal (no API key needed):
```powershell
python scripts/build_demo_workbook.py deal_model_demo.xlsx
python scripts/_verify_no_error_cells.py deal_model_demo.xlsx   # confirms zero formula-error cells
```

All sample documents are **synthetic and labelled fictional**; no real customer data is used.

---

## About the author

Built by [@nhphuocvn](https://github.com/nhphuocvn), drawing on 10+ years in Quote-to-Cash and finance-systems transformation. The project comes from a recurring frustration in those years: deal desks, legal, and finance spend enormous effort turning contracts into models and defending the numbers in approval meetings — work that is mechanical enough to automate, but only if every figure stays traceable to its source. That traceability, not the automation, is the point.
