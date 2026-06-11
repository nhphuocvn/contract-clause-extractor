# Claude Code Kickoff Prompt — Deal Economics Copilot

Copy everything below the line into Claude Code, run from the root of the `contract-clause-extractor` repo.

---

I have an existing Python project, `contract-clause-extractor`: a Retrieval-Augmented Generation (RAG) application that ingests contracts (PDF/DOCX), chunks and embeds them into ChromaDB with OpenAI embeddings, extracts clauses via LLM calls, risk-scores them, supports multi-contract comparison, and serves everything through a Streamlit UI.

I want to extend it into a **Deal Economics Copilot** — a tool that simulates the workflow of a Staff Finance Analyst supporting Cloud/Hyperscaler GPU deals at a semiconductor company (think AMD selling MI355X GPUs to Meta). The tool takes a supply/purchase contract in, extracts the commercial terms, translates those terms into financial model drivers, runs deal economics with scenarios and sensitivities, benchmarks against the company's reported segment financials, and outputs a Contract Review Board (CRB) memo plus an auditable Excel model.

Read the existing codebase first and reuse its ingestion, chunking, embedding, retrieval, and Streamlit patterns. Do not rewrite working infrastructure — extend it.

## Architecture (new modules)

```
deal_copilot/
├── schemas.py           # Pydantic models for all structured data
├── term_extractor.py    # Commercial term extraction (structured JSON, not prose)
├── driver_mapper.py     # Term → financial model driver translation
├── economics_engine.py  # Deal P&L, scenarios, sensitivities, NPV
├── warrant_economics.py # Customer warrant valuation, contra-revenue schedule, effective ASP, dilution
├── benchmarks.py        # Segment financials loader (10-Q data, manual JSON/CSV input)
├── crb_memo.py          # CRB memo generator (markdown → rendered in UI, exportable)
├── excel_export.py      # openpyxl model export with formulas, not hardcoded values
└── ui_deal.py           # New Streamlit tabs
data/
├── benchmarks/amd_dc_segment.json   # AMD Data Center segment actuals (I will populate from the 10-Q)
└── sample_contracts/                # Synthetic test contract (see Deliverable 0)
```

## Deliverable 0 — Synthetic deal package (TWO documents)

Real hyperscaler GPU deals (AMD–OpenAI October 2025, AMD–Meta February 2026) are multi-document packages: a Product Purchase Agreement PLUS a Warrant Agreement issued to the customer. The tool must ingest and analyze the package as one deal. Generate both documents as DOCX (and PDF), realistic legal language, terms embedded naturally in prose (not labeled), with a `ground_truth.json` listing every term and its parameters so extraction accuracy can be measured.

### Document A — "GPU Cloud Product Purchase Agreement" (12–18 pages)
Between "Advanced Micro Devices, Inc." and "Meta Platforms, Inc." (synthetic, clearly labeled fictional). Must contain ALL of:

1. 3-year term, committed volume: 150,000 GPU units total with a quarterly ramp schedule (slow start, peak in year 2)
2. Base ASP of $25,000/unit with tiered volume rebates: 3% above 30,000 cumulative units, 5% above 75,000, 7% above 120,000 (rebates settled annually)
3. Take-or-pay: customer must pay for 80% of annual committed volume regardless of actual purchases
4. Prepayment: $500M paid at signing, drawn down against shipments
5. Payment terms: net 90
6. Price protection: if seller offers a lower price to any comparable-volume customer, buyer receives the lower price prospectively (most-favored-nation clause)
7. Termination for convenience by buyer with 180 days notice and a wind-down fee equal to 25% of remaining committed value
8. Liability cap at 12 months of fees; carve-out for IP indemnification (uncapped)
9. Delivery/supply commitment: seller guarantees quarterly supply allocation; liquidated damages of 2% of quarterly order value per week of delay, capped at 10%
10. A cross-reference clause: "concurrently with execution of this Agreement, Seller shall issue Buyer a warrant pursuant to the Warrant Agreement of even date" — the tool must detect that the deal includes an equity component and demand the second document
11. One deliberately ambiguous clause (e.g., vaguely worded rebate trigger) to demo the tool flagging ambiguity rather than hallucinating a number

### Document B — "Warrant to Purchase Shares of Common Stock" (6–10 pages)
Modeled on the real AMD–OpenAI warrant (publicly filed as an 8-K exhibit on SEC EDGAR — use its structure as the stylistic template). Must contain ALL of:

1. Warrant for up to 12,000,000 shares of Seller common stock at an exercise price of $0.01 per share (scaled-down from the real 160M-share deals so the synthetic math stays distinct from real figures)
2. Vesting in 4 tranches tied to cumulative GPU deployment milestones: 25% at 30,000 units deployed, 25% at 75,000, 25% at 120,000, 25% at 150,000
3. Each tranche additionally contingent on Seller's stock achieving escalating price hurdles (e.g., $180 / $230 / $300 / $400 per share, 30-day VWAP)
4. Buyer technical/commercial milestone condition on the final tranche (deployment at scale certification)
5. Anti-dilution adjustment provisions, transfer restrictions, expiration at year 6
6. A confidentiality clause (tests that the extractor distinguishes commercial terms from boilerplate)

Ground truth must cover both documents and flag the cross-reference linkage as a term.

## Module specs

### 1. schemas.py
Pydantic models:
- `CommercialTerm`: term_type (enum: PRICING, VOLUME_COMMITMENT, REBATE, TAKE_OR_PAY, PREPAYMENT, PAYMENT_TERMS, PRICE_PROTECTION_MFN, TERMINATION, LIABILITY, SUPPLY_COMMITMENT, WARRANT_EQUITY, CROSS_REFERENCE, OTHER), raw_text, source_document, source_section, parameters (dict), confidence (0–1), ambiguity_flag (bool), ambiguity_note
- `DealPackage`: container for multiple documents belonging to one deal; if a CROSS_REFERENCE term points to a missing document, the UI must warn "this deal references a Warrant Agreement that has not been uploaded — economics are incomplete"
- `WarrantTerms`: total_shares, exercise_price, tranches (each: share count, deployment milestone, stock price hurdle, other conditions), expiration
- `ModelDriver`: driver_type, value(s), schedule (quarterly array where applicable), source_term_id, accounting_treatment_note
- `DealAssumptions`: unit COGS, opex allocation %, discount rate (WACC), tax rate — user-editable in UI with sensible defaults
- `ScenarioResult`, `DealEconomics`, `CRBMemo`

### 2. term_extractor.py
- Reuse existing RAG retrieval to pull relevant chunks per term category, then run a structured extraction call per category with JSON-mode output validated against `CommercialTerm`
- Extraction prompt must instruct: extract only what the text states; if a parameter is ambiguous or missing, set ambiguity_flag=true and explain — never invent numbers
- Include an evaluation function that compares extraction output against `ground_truth.json` and reports precision/recall per term type (this is my demo metric)

### 3. driver_mapper.py — the core finance logic
Deterministic Python (not LLM) mapping each term type to model impact:
- VOLUME_COMMITMENT + ramp → quarterly unit schedule
- PRICING + REBATE tiers → gross-to-net revenue waterfall; rebate accrual estimated quarterly based on projected cumulative volume (accrue at expected blended rate, true-up annually) — annotate with the revenue recognition concept: variable consideration estimate under ASC 606
- TAKE_OR_PAY → revenue floor scenario (minimum guaranteed revenue line)
- PREPAYMENT → deferred revenue/contract liability drawdown schedule; note financing benefit
- PAYMENT_TERMS → days sales outstanding assumption → working capital impact estimate
- PRICE_PROTECTION_MFN → not modeled numerically; surfaced as contingent margin risk with a one-line quantified illustration (e.g., "a 5% MFN-triggered price cut on remaining volume = $X net revenue impact")
- TERMINATION → downside scenario input (early termination at month N with wind-down fee)
- SUPPLY_COMMITMENT liquidated damages → quantified maximum exposure
- WARRANT_EQUITY → routed to warrant_economics.py; mapped as a contra-revenue driver with accounting note: equity instruments issued to a customer are consideration payable to a customer — measured under ASC 718, recognized as a reduction of the transaction price (contra-revenue) under ASC 606 as the related tranches vest/become probable
Each mapping outputs a `ModelDriver` with an `accounting_treatment_note` written in plain finance language (revenue recognition, accrual, contract liability, contingency).

### 4. economics_engine.py
- Quarterly deal P&L over contract term: gross revenue → rebates/discounts → net revenue → COGS → gross margin ($ and %) → allocated opex → contribution margin
- Scenarios: Base (committed ramp), Downside (take-or-pay floor: customer takes only the 80% minimum), Upside (volume 15% above commitment, hits top rebate tier earlier — show the margin-dilution tradeoff), Early Termination (buyer exits at month 18, wind-down fee applied)
- Sensitivities: one-way tables for ASP ±10%, unit COGS ±10%, ramp slip of 1–2 quarters; output a tornado-style ranking of impact on total deal gross margin
- NPV of deal cash flows at the assumed WACC, including prepayment timing benefit; payback period
- Two parallel views of every scenario: (a) GAAP view — net revenue after rebate AND warrant contra-revenue; (b) Cash/commercial view — excluding the non-cash warrant charge. Show the bridge between them explicitly (this mirrors the real GAAP vs. non-GAAP debate around customer warrants)
- All numbers flow from drivers + assumptions — nothing hardcoded

**Capacity bridge (Phase 3 — defer; Phase 1 synthetic deal stays unit-based.)**
Real hyperscaler GPU deals are sized in gigawatts of power, not unit counts. Add an *optional* "capacity bridge" input mode to `DealAssumptions` (i.e., extend `deal_copilot/schemas.py` when Phase 3 lands) and to the economics engine, exposing three user-editable fields:

- `total_power_gw` — committed power, in gigawatts.
- `power_per_gpu_watts` — nameplate power draw per GPU.
- `pue` — facility power-usage-effectiveness ratio (overhead for cooling, conversion losses, etc.).

Conversion: `units = (total_power_gw * 1e9) / (power_per_gpu_watts * pue)`.

When the user supplies the bridge, the engine derives the unit count from power; otherwise it uses an explicit unit count as today. The mode is a *toggle*, not a replacement — both code paths must work, and a deal can be re-run either way for comparison. The synthetic AMD–Meta package built in Phase 1 stays unit-based; the bridge is added solely as an alternative input mode for power-anchored deals.

### 4b. warrant_economics.py
Deterministic warrant analysis (no LLM math):
- Inputs from `WarrantTerms` + user assumptions (current stock price, simple volatility assumption, probability of hitting each price hurdle — user-editable sliders with documented simplifications)
- Fair value: default to a simplified intrinsic-plus-probability approach (shares × (assumed vest-date stock price − $0.01 exercise) × vesting probability per tranche); optional Black-Scholes mode clearly labeled as illustrative. Document the simplification honestly in the README — the point is the framework, not derivatives pricing
- Contra-revenue schedule: allocate each tranche's fair value against revenue over the deployment period it relates to, recognized as vesting becomes probable
- Effective net ASP: gross ASP − per-unit rebate − per-unit warrant cost, by scenario. This is the headline number: "the sticker price is $25,000/unit; the all-in effective price after rebates and warrant cost is $X"
- Dilution math: warrant shares as % of assumed shares outstanding; value transferred to customer at each stock price hurdle
- Asymmetry callout: warrant cost scales WITH the seller's stock price success — quantify warrant value at 3 stock price levels

### 5. benchmarks.py
- Load `amd_dc_segment.json` (fields: quarterly Data Center segment revenue, segment operating margin, company gross margin — I will populate from the latest Form 10-Q)
- Compute comparisons: deal blended gross margin vs. company gross margin; deal annual revenue vs. segment quarterly run-rate ("this deal ≈ X% of Data Center segment revenue")
- Output 2–3 plain-English benchmark sentences for the CRB memo

### 6. crb_memo.py
Generate a one-page CRB memo (markdown):
- Deal summary (counterparty, term, committed value, structure INCLUDING equity component) — 3 lines max
- Economics table: net revenue, gross margin $/%, contribution, NPV — by scenario, shown in both GAAP (post-warrant contra-revenue) and cash/commercial views with the bridge
- Effective net ASP line: sticker ASP vs. all-in ASP after rebates and warrant cost
- Top 5 financial risks, ranked, each with: the contract term, the financial exposure (quantified where possible), and a recommended mitigation or approval condition — warrant dilution and the MFN clause should naturally rank high
- Benchmark context sentences
- Recommendation line with explicit approval asks (e.g., "approve subject to rebate accrual methodology sign-off by Accounting")
LLM generates the prose, but every number is injected from the economics engine output — the LLM never computes.

### 7. excel_export.py
openpyxl workbook: Assumptions tab (inputs, color-coded), Drivers tab (extracted terms → drivers with source clause text), Model tab (quarterly P&L with live Excel formulas referencing the Assumptions tab — a reviewer changing ASP must see the model recalculate), Scenarios tab, CRB Summary tab. Professional formatting: number formats, borders, frozen panes.

The Assumptions tab MUST surface the **capacity bridge** fields from §4 (`total_power_gw`, `power_per_gpu_watts`, `pue`) alongside a derived `units` cell containing the live formula `= total_power_gw * 1e9 / (power_per_gpu_watts * pue)`. A reviewer changing any of the three power inputs should see the downstream unit count, revenue, and margin cells recalculate via the Excel formula chain — same principle as the rest of the Model tab. Group the bridge fields under a clearly labeled "Capacity bridge (optional)" section so users opting for an explicit unit count can see them and ignore them.

**Audit rigor (hard requirements, not nice-to-haves):**

1. **Source/basis column on Assumptions tab.** Every row on the Assumptions tab carries a dedicated "Source / basis" column whose value is one of three categories: a contract reference (e.g. `"contract §4"`, `"warrant §2 Tranche 3"`), an industry assumption flagged editable (e.g. `"industry assumption — editable"`, `"team default — editable"`), or a placeholder requiring resolution (e.g. `"placeholder — confirm with cost accounting"`, `"placeholder — confirm with finance"`). Placeholder rows MUST be visually distinct (e.g. highlighted in yellow) so reviewers can see at a glance what is not yet validated.

2. **No hardcoded numbers in the Model tab.** Every cell in the Model tab is either (a) an input — in which case it must live on Assumptions, not Model — or (b) a formula referencing Assumptions, Drivers, or another Model cell. The export script must fail loudly (raise) if it would otherwise emit a Model cell containing a literal numeric value. The point is reviewer trust: a Staff Finance Analyst opening this workbook should be able to trace every number back to either an input cell or a chain of formulas.

3. **Driver / source-clause audit trail.** Every Model-tab line (revenue, rebate, contra-revenue, COGS, opex, NPV component, etc.) carries either an Excel cell comment OR a dedicated "Audit" column tying that line back to (i) the `ModelDriver.driver_id` that produced it, (ii) the `CommercialTerm.term_id` upstream of that driver, and (iii) the `source_document` + `source_section` from the contract. Ad-hoc drivers carry their `label` and `note` in place of a contract reference. A reviewer should be able to click any line in the Model tab and see "this came from auto-renewal §3 / Driver D-04 — quarterly unit schedule" without leaving the workbook.

### 8. ui_deal.py — Streamlit tabs added to existing app
- **Deal Intake**: upload one or more documents as a deal package → extraction runs per document → terms table with confidence + ambiguity flags, clickable to show source clause text; missing-document warning if a cross-reference is unresolved
- **Model**: editable assumptions, quarterly P&L table, scenario selector, GAAP vs. cash toggle, sensitivity chart
- **Warrant**: tranche table, vesting probability sliders, contra-revenue schedule, effective-ASP waterfall chart (sticker → rebates → warrant → all-in)
- **CRB Memo**: rendered memo, download buttons (memo as DOCX, model as XLSX)
- **Accuracy**: extraction eval vs. ground truth (the demo-credibility tab)

## Build order
1. schemas.py + synthetic deal package (both documents) + ground_truth.json
2. term_extractor.py + eval harness — get extraction working and measured first, across both documents
3. driver_mapper.py + economics_engine.py with unit tests on the math (test rebate tier crossover, take-or-pay floor, NPV)
4. warrant_economics.py with unit tests (tranche vesting logic, contra-revenue allocation, effective-ASP math)
5. benchmarks.py + crb_memo.py
6. excel_export.py (add a Warrant tab: tranche schedule, fair value by assumption, contra-revenue flow into the Model tab via live formulas)
7. ui_deal.py
8. Deal versioning + variance bridge — append-only `DealVersion` snapshots of a `DealPackage` (terms + warrant + assumptions + ad-hoc drivers), variance engine that computes per-line deltas between any two versions (net revenue, gross margin, NPV, with per-driver attribution), UI gains a "Save as new version" action and a version picker, Excel gains a Variance tab. Schemas (`DealVersion`, `AdHocDriver`) already landed in Phase 1.
9. README section: architecture diagram (mermaid), demo walkthrough, screenshots, and an honest "Simplifications" section (warrant valuation approach, accrual estimation method)

## Quality bar
- Type hints everywhere, Pydantic validation on all LLM outputs, retries on JSON parse failure
- Unit tests on all financial math (pytest) — the finance logic must be provably correct, the LLM is only for extraction and prose
- No real customer data anywhere; synthetic contract clearly labeled as fictional in its header
- README must state the design principle explicitly: "LLM extracts and explains; deterministic code computes."

Start with Deliverable 0 and the schemas, show me the synthetic contract's term list for approval, then proceed through the build order.
