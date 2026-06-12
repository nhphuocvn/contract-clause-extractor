# KICKOFF v4 — Deal Economics Copilot (Enterprise Spec)

## BUILD STATUS

**Done & committed on `deal-copilot` (also merged to `main`):**

- **Phase 1** (`c01e5a6`) — schemas v1, synthetic two-document deal package (`gpu_purchase_agreement.{docx,pdf}` + `warrant_agreement.{docx,pdf}`), `ground_truth.json` covering all 12 commercial term types + warrant tranches + the unresolved-cross-reference fixture.
- **Step 0** (`69bcd7e`) — schema retrofit for v4: added `ProvenanceClass` / `DealStatus` / `PolicyRuleKind` / `PolicyOutcome` / `DistributionKind` enums; `TermVariant`, `AssumptionProvenance`, `CapacityBridgeInputs` (with `derived_units()` helper), `GenerationTranche`, `ScenarioProbability`, `DistributionSpec`, `ChangeJournalEntry`, `PolicyRule` / `PolicyRuleResult` / `PolicyVerdict`, `DealRecord`, `ActualsRecord`. Additive fields on `CommercialTerm` (variants), `DealAssumptions` (capacity_bridge, generation_tranches, scenario_probabilities, assumption_provenance, distribution_specs), `DealPackage` (deal_id, status, counterparty, archetype, change_journal, policy_verdicts). 38 symbols exported. Phase 1 backward-compat preserved.
- **Phase 2** (`09c5a71`) — extraction + validation + eval harness. 9 new `deal_copilot/` modules (`intake`, `retrieval`, `prompts`, `extraction_payloads`, `validators`, `review_queue`, `extraction_cache`, `term_extractor`, `eval_harness`) + 3 smoke scripts under `_smoke/`. Four-layer untrusted-input defense (nonce-delimited block, schema-constrained response, bounded-value validators, source-quote requirement). DOCX support added to `extract.py`. Cached extraction by `(sha256, prompt_version)`.
- **Chunker fallback** (`bbb4947`) — paragraph-pack chunking in `index.chunk_contract` for header-less long documents (real SEC filings, HTML-derived PDFs); the existing section-header path is unchanged for synthetic-format docs. `data/sample_contracts/micron_intel_real.pdf` added as a real-doc test fixture.

**Live verification against the synthetic deal:**

- Precision **0.923**, Recall **1.000**, F1 **0.960** vs `ground_truth.json`.
- REBATE ambiguity quantified (2 variants populated).
- Cross-reference fixtures both pass (Warrant Agreement detected when uploaded; goes to `unresolved_cross_references` when only Doc A uploaded).
- Prompt-injection defense holds (doctored doc with "IGNORE ALL PRIOR INSTRUCTIONS" produces no injected values).
- Cache: re-run is 0.00s with 2 cache hits; bumping `EXTRACTION_PROMPT_VERSION` invalidates.

**Live verification against the real Intel-Micron SEC filing** (`micron_intel_real.pdf`):

- 5 terms extracted (TAKE_OR_PAY, PREPAYMENT, PAYMENT_TERMS, TERMINATION, LIABILITY); 7 returned `not_found=True` because the wafer-supply structure is genuinely different from the synthetic GPU deal.
- 3 terms flagged ambiguous with notes — including PAYMENT_TERMS where `net_days` is literally `[***]` SEC-redacted; the extractor correctly refused to invent a number.
- 1 validation warning surfaced to the review queue.

**Committed on `deal-copilot` (pushed to origin; not yet merged to `main`):**

- **Phase 3 schema fix** (`5d97a7f`) — formula-based take-or-pay: `TakeOrPayPayload.annual_minimum_pct_of_committed` now `float | None`; added `shortfall_basis` Literal (`pct_of_committed` / `unbooked_unit_price_formula` / `other`) + `shortfall_formula_description`; prompt branches on basis (`EXTRACTION_PROMPT_VERSION` v1→v2); validators skip formula-basis terms and route them to manual review. (Resolves the real-doc backlog below.)
- **Phase 3 engine** (`9c3b834`) — `assumptions_library.py` + `data/assumptions_library.json` (only I/O module), `driver_mapper.py` (terms → ModelDrivers; rebate dual-variant **$142.5M prospective vs $183.5M retroactive, $41M delta**), `economics_engine.py` (pure quarterly P&L, 4 scenarios incl. take-or-pay+Banked Units, net-operating cash + NPV, payback shown both ways — financed Q0 vs deployment Q5, probability weighting, ±10% tornado, capacity bridge, effective-ASP), `accounting_schedules.py` (rebate accrual walk, prepayment schedule, peak receivables; `ending[q]==beginning[q+1]`). Warrant contra wired as a zero slot.
- **Phase 4 warrant economics** (`c5e5ff2`) — `warrant_economics.py` (pure): intrinsic + illustrative Black-Scholes valuation, band-allocated contra-revenue schedule that fills the Phase 3 slot, dilution, value-at-price asymmetry, and a conservative/base/aggressive expected-value **range**. Vest probabilities and measurement price are JUDGMENT inputs (PLACEHOLDER provenance, "confirm with deal team"). At AMD spot $470 the warrant is **$3.384B expected (range $2.256B–$4.230B)** — larger than gross margin; effective net ASP $25,000 → **$1,490.48/unit**; GAAP net revenue $3,607.5M → **$223.572M**; dilution 0.7417%.
- **Docs** (`056ff16`) — KICKOFF §8/§9.1 design principles: Excel traceability-over-cleverness, engine-granularity, and the Warrant Assumptions tab.
- **Phase 5 negotiation core** (`ce1c690`) — `versioning.py` (append-only deep `DealVersion` snapshots + `build_change_journal`), `variance_bridge.py` (sequential/waterfall attribution between two versions on net_revenue / gross_margin / NPV; steps telescope to the total delta, `residual_usd` checked against an independent eval of B = the **sums-to-delta** property), ad-hoc drivers wired into the engine as a visible `adhoc_adjustment` line, and `goal_seek.py` (**P1, done** — deterministic bisection on ASP / COGS / take-or-pay % / prepayment). Bridge demo: a counter (ASP cut + rebate bump + cost-down + marketing credit) walks to a −$192.0M gross-margin delta with $0 residual.

- **Cash-layer refinement** (this commit) — replaced the whole-quarter DSO approximation with a **monthly working-capital cash layer** covering all three legs: collections (DSO), supplier payments (DPO), and inventory build (lead time). Revenue recognition stays quarterly; only cash timing is monthly, with within-quarter activity spread evenly across 3 months. net-30/60/90 now produce genuinely different collection schedules, peak receivables, NPV, and working-capital draw. DPO and inventory lead net into one explicit `cogs_cash_lag = dpo_months − inventory_lead_months` (defaults: net-60 DPO → 2mo, 3mo inventory lead → **−1mo**, COGS cash funded one month ahead of shipment). New library defaults `supplier_payment_dpo_days` (60; owner Treasury/Procurement) and `inventory_lead_months` (3; owner Operations/Supply Chain), each owner/type-tagged for the §5 register. New additive output `ScenarioResult.peak_working_capital_draw_usd`. Operating NPV documented as **pre-tax** (after-tax = roadmap); **perfect collections** assumed (no bad debt/disputes). **Re-pin:** BASE deployment payback Q5→**Q6** under the realistic WC drag (intended — the fix working); financed payback Q0 unchanged. Hand-calc pins: peak receivables net-30/60/90 = **$166.667M / $333.333M / $500.000M**; deployment NPV = **$774.661M / $749.974M / $725.483M** (net-30 vs net-90 = **$49.178M** NPV cost); peak WC draw net-90 = **−$157.0M**; inventory build = **$35.0M/month** funded ahead of first ship.

**All financial math is hand-calc pinned: `101 tests passing` (88 prior + 13 cash-timing; `test_payback` re-pinned).**

## Next: Phase 6 — policy, benchmarks, reports

Policy engine (`data/crb_policy.json` → per-rule pass/escalate/block + required approvers), benchmarks (with staleness check), the CRB memo (LLM prose, every number injected from the engine — incl. the warrant correlation caveat per §4), the Assumption Gap Report (drawing from the §5 Assumption Register), and the glossary. Pure/tested where there is math; per the Phase 3–5 standard.

## Phase-3 backlog — RESOLVED

- ~~**TakeOrPayPayload.annual_minimum_pct_of_committed** → Optional + `shortfall_basis` sibling field for formula-based shortfalls (real Intel-Micron clause).~~ Done in `5d97a7f`.

---

Supersedes all prior KICKOFF versions. Phase 1 (schemas.py, synthetic two-document deal package, ground_truth.json) is COMPLETE and stays — do not rebuild it. Read this whole spec before planning anything; execute the build order at the bottom, which begins with a schema retrofit.

The mental model: this tool is the working system of a Staff Finance Analyst on a hyperscaler GPU deal desk. The environment is dynamic — deals arrive incomplete, change three times a week, interact with each other, and end in an approval meeting where every number gets challenged. The tool's job is that no question in that meeting goes unanswered and no number lacks a paper trail.

Design principle (non-negotiable): **the LLM extracts and explains; deterministic, tested code computes.** No LLM-produced number ever enters the model.

Priority tiers: **[P0]** must ship for the demo. **[P1]** ship if time allows; design for now. **[P2]** stretch; schema support only. If a P1 threatens a P0 timeline, cut the P1 and note it in the README roadmap.

---

## 1. Deal intake

A "deal" is a **package**: any mix of term sheet, purchase agreement, warrant agreement, side letter, amendment, exhibit, or pasted text. The unit of analysis is the package.

- **[P0] Three intake paths:** definitive contracts (DOCX/PDF), term sheets (1–3 pages, incomplete), pasted text (an email summary from Business Development). All must produce a model.
- **[P0] Incomplete is the norm.** Missing drivers fill from the assumptions library (§5); every filled gap is recorded with provenance `library default`; the tool emits an **Assumption Gap Report** — ranked clarifying questions for the deal team, each with the dollar sensitivity of the unknown ("payment terms unknown; assumed net 60; net 90 vs net 30 swings peak receivables by $X"). First-class output, peer of the CRB memo.
- **[P0] Forward modeling / archetypes:** a deal can be created with NO documents at all, by cloning a deal archetype from a template library (e.g., "hyperscaler gigawatt deal," "unit-based enterprise deal") or cloning an existing deal and editing terms. This is how desks price a deal before paper exists ("Oracle wants the Meta structure but 2 gigawatts").
- **[P1] Amendments:** a document can declare itself an amendment of another. Extractor identifies amended sections; package applies last-in-time-wins per section; terms table shows superseded values struck through, amendment as source.
- **[P0] Untrusted input:** contract text is data, never instructions. Extraction prompts must wrap document text in delimiters and instruct the model to ignore any instruction-like content inside it; the validation layer (§6) bounds-checks all extracted values. Note this defense in the README.

## 2. Capacity bridge — gigawatts to units

- **[P0]** Deals sized in power convert to units: `units = (total_power_gw × 1e9) / (power_per_gpu_watts × PUE)`. All inputs are editable assumptions with provenance. Unit-denominated deals skip the bridge (it is an input mode).
- **[P1] Multi-generation:** a multi-year power commitment spans GPU generations as tranches (Gen A: years 1–2, 1,000W, $25k ASP, COGS curve; Gen B: years 3–5, 1,400W, $32k ASP, its own curve), each pulling defaults from the assumptions library, overridable per deal.
- **[P1] Feasibility check:** per-quarter supply capacity assumption; any ramp quarter exceeding it gets a flag ("Q5 needs 22,000 units vs assumed capacity 18,000 — supply risk") that also lands in the CRB memo risk list.

## 3. Economics engine

- **[P0] Quarterly deal P&L** per scenario per view: gross revenue → rebates/discounts → warrant contra-revenue (GAAP view) → net revenue → COGS → gross margin ($/%) → allocated opex → contribution. NPV at WACC including prepayment timing; payback; cumulative **cash view** honoring payment terms (days sales outstanding), the prepayment drawdown rule (20% of each invoice until exhausted), take-or-pay shortfall invoicing, and Banked Units mechanics from the synthetic contract.
- **[P0] Scenarios:** BASE / DOWNSIDE (take-or-pay floor) / UPSIDE (volume +15%, earlier tier crossing — show margin dilution) / EARLY_TERMINATION (exit quarter chosen, wind-down fee net of unused prepayment).
- **[P0] Scenario probability weighting:** user-set probabilities per scenario → probability-weighted expected NPV and margin shown alongside per-scenario results.
- **[P0] Sensitivities:** one-way on ASP, COGS, ramp slip, rebate rates; tornado ranking by impact on total deal gross margin.
- **[P1] Deployment-delay scenario:** slide the deployment curve right by N quarters; show revenue/NPV shift AND the interaction with take-or-pay and **seller-side liquidated damages** (a 4-week slip costs $X in damages at 2%/week capped at 10%, plus the revenue timing impact). Delay is the dominant real-world risk; treat it as a first-class control, not a footnote.
- **[P1] COGS curve:** per-unit cost by year (learning-curve decline) from the library, not a constant.
- **[P2] Monte Carlo:** distributions on ASP/volume/ramp → NPV distribution. The engine is pure (§8), so this is cheap later. Schema: a `DistributionSpec` on assumptions.

## 4. Warrant economics

- **[P0]** Deterministic module. Inputs: WarrantTerms + assumptions (current stock price, per-tranche vest probability sliders, simple volatility). Fair value per tranche = shares × (assumed vest-date price − exercise price) × vest probability; optional Black–Scholes mode labeled illustrative. Outputs: contra-revenue schedule allocated over the deployment each tranche relates to; **effective net ASP waterfall** (sticker → rebates → warrant → all-in); GAAP vs cash/commercial views with explicit bridge; dilution (% of shares outstanding; value transferred at three stock-price levels); asymmetry callout (warrant cost rises with the seller's own stock success).
- Accounting framing in all notes: equity to a customer = consideration payable to a customer → reduction of transaction price (contra-revenue) under ASC 606; measured under ASC 718.
- **Correlation caveat (document in `warrant_economics` docstrings + the CRB memo's warrant section).** Valuing the warrant with a single spot price and **independent** per-tranche vest probabilities is a deliberate simplification. In reality, deployment milestones and stock-price hurdles are **positively correlated** — deal success lifts the seller's stock, which makes the later, higher hurdles ($300/$400) more likely to clear at the same time the deployment milestones are hit. So the model **likely understates warrant cost in the upside scenario** (the tranches most likely to vest are exactly the most expensive ones). State this explicitly wherever warrant numbers appear; it is the honest health-warning on the warrant valuation.

## 5. Assumptions library, provenance, and governance

- **[P0]** `data/assumptions_library.json`: per-generation defaults (power, ASP, COGS curve, quarterly supply capacity) and globals (PUE, WACC, tax rate, opex %, payment-terms→DSO map, default vest probabilities). Every entry: value + basis note + as-of date. Engine reads the library; nothing hardcoded.
- **[P0] Provenance on every assumption**, enum: `contract §N` | `term sheet` | `library default` | `placeholder — confirm with <team>` | `user override`. Surfaced in UI and Excel.
- **[P0] Assumption Register (Phases 6–7).** A single register listing **every model input**, classified by type — `contract_fact` | `market_data` | `policy_number` | `strategic_judgment` — and carrying an **OWNER field naming who confirms it** (the accountability column the provenance system currently lacks). Examples: contract facts → "contract clause §N"; market data → "market data — refresh before use"; policy numbers → "Treasury sets WACC"; strategic judgment → "deal team owns vest probabilities & downside demand". **COGS** must carry "confirm with cost accounting"; **WACC** must carry "confirm with Treasury". The register surfaces as **its own Excel tab**, feeds the **Assumption Gap Report (§9.6)**, and extends the provenance system (`AssumptionProvenance`) with the owner/accountability dimension. It is the single place an analyst sees what each number is, where it came from, and whose sign-off it needs.
- **[P0] Change journal:** every assumption or term edit on a deal records (timestamp, field, old, new, note). Rendered as a per-version history; exported to the Excel Changelog tab. This is audit/governance, and it also feeds the variance bridge narrative.

## 6. Validation layer & human review

- **[P0] Deterministic sanity checks** before modeling: ramp sums to committed total; rebate tiers monotonic; take-or-pay % in (0,1]; payment terms recognized; dates parse; warrant tranche shares sum to total; cross-reference resolution computed (missing-document warning). Failures annotate the term and route to the Assumption Gap Report — never crash.
- **[P0] Ambiguity → quantify both readings.** Ambiguous terms (planted test: rebate tier-crossing retroactivity) carry alternative parameter variants; the engine models both; output the dollar delta ("Reading A vs B: $X over the term") and auto-add a gap-report line ("resolve §5 with Legal before signature; exposure $X"). Generic mechanism, demoed on the rebate clause. Highest-credibility feature in the tool.
- **[P0] Review queue:** any term below a confidence threshold (configurable, default 0.8) or failing validation enters a human-review checklist in the UI; a deal shows "N terms pending review" until cleared. Human-in-the-loop is the enterprise posture.

## 7. Negotiation & portfolio intelligence

- **[P0] Deal versions:** named, timestamped snapshots of terms + assumptions ("Counterparty initial," "Our counter v1," "Final"); a package holds many.
- **[P0] Variance bridge:** any two versions → driver-level walk (which terms/assumptions changed; dollar impact of each on net revenue, gross margin, NPV; sums exactly to total delta). Table + waterfall chart. Daily-use feature; dedicated UI tab.
- **[P1] Goal-seek:** deterministic bisection over the pure engine to hold a target metric: "tier-2 rebate moves to 6% — what base ASP holds gross margin at 45%?"; "what take-or-pay % keeps downside NPV positive?" Expose for ASP, rebate rates, take-or-pay %, prepayment size.
- **[P0] Ad-hoc drivers:** labeled manual line item (amount, quarterly timing, sign, note) injectable into any version; flows through model, Excel, and variance bridge like any other driver.
- **[P0] Deal registry & pipeline dashboard:** all deals listed with status (DRAFT / IN_NEGOTIATION / IN_CRB / APPROVED / SIGNED / LIVE / TERMINATED), counterparty, committed value, blended margin, NPV, pending-review count. This is the analyst's 8:30am pipeline view.
- **[P1] Cross-deal MFN exposure:** for any deal containing a most-favored-nation clause, evaluate every other deal (and any hypothetical new deal being priced) against it: comparable-volume test per the clause, lower-price detection, and the repricing cost on the protected deal's remaining volume ("signing Oracle at $23.5k triggers Meta MFN: $410M repricing exposure"). Run automatically when pricing any new deal; surface as a blocking warning. No single feature better demonstrates portfolio-level judgment.
- **[P1] Precedent comparison:** rank a deal's key terms against the portfolio (rebate rates, payment terms, take-or-pay %, margin): "rebate tier above portfolio median; payment terms worse than 80% of comparables." Builds on the repo's existing multi-contract comparison.

## 8. Engineering quality bar

- **[P0]** Type hints; Pydantic v2 validation on all LLM outputs; JSON mode, temperature 0, retry on parse failure; extraction cached by (file bytes, prompt version).
- **[P0] Engine purity:** economics_engine, warrant_economics, variance, and goal-seek are pure functions of (drivers, assumptions) — no I/O, no globals. Recompute target <1s; goal-seek and Monte Carlo become trivial layers.
- **[P0] Engine granularity for traceability (Phase 3+; already mostly satisfied):** expose every intermediate value a human would want to see in Excel as its own named field (the `QuarterRow` line items, both paybacks, accrual-walk columns, etc.), so Phase 7 can map one engine step to one Excel row. Do NOT collapse steps into combined expressions — granular fields are what make the spreadsheet traceable.
- **[P0] pytest on ALL financial math:** rebate crossover under both ambiguity readings; take-or-pay floor + Banked Units; prepayment drawdown; NPV; warrant vesting + contra-revenue allocation; capacity bridge; probability weighting; variance bridge sums-to-delta property; goal-seek convergence; accrual walk continuity (each quarter's ending balance = next quarter's beginning).
- **[P0] Graceful degradation:** partial extraction → flagged model; missing benchmark file → labeled absence (and staleness warning if >2 quarters old); LLM unavailable → deterministic-only mode with banner.
- **[P0]** No real customer data; synthetic docs labeled fictional; README has the design principle, a Simplifications section (warrant valuation, accrual estimation, capacity assumptions), and the untrusted-input note.

## 9. Outputs

### 9.1 Excel model [P0] — the credibility artifact

> ### ⭐ THE MOST IMPORTANT EXCEL RULE — BUILD THE EXCEL LIKE A CIRCUIT
> **Traceability over cleverness.** This rule outranks every other Excel
> consideration. Cleverness that obscures the flow is a **defect, not a feature.**
>
> - **The model is a visible stack of simple arithmetic.** Signal flows
>   input → step → step → output, and anyone can trace any value back through the
>   steps by eye.
> - **NO advanced formulas.** No INDEX/MATCH, no VLOOKUP, no array formulas, no
>   nested IFs. **Simple arithmetic only** (`=B5*B6`, `=B7-B8`).
> - **ONE calculation step per labeled row**, read top to bottom like a sentence.
>   **Show the work:** a gross-revenue row, then a rebate row, then
>   `net revenue = gross row − rebate row` — never one compressed mega-formula.
> - **Formulas reference clearly-labeled cells on the same or adjacent area**, not
>   lookups scattered across tabs.
> - **Many simple single-purpose tabs are encouraged over few clever ones.**
> - **The test:** a finance person who did NOT build it can open it, follow any
>   number to its source, and add or change an assumption confidently without
>   hunting for where a value came from. (This mirrors how transparent, editable
>   models are built in practice.)
>
> **Each Excel row maps to one engine step** — the `QuarterRow` fields already
> give this granularity — **in the same order, so the spreadsheet IS the engine's
> logic made visible.**

**Also (assumption transparency):** flag every assumption with more than one
defensible value (rebate dual-reading, `[***]`-redacted values, library-default
guesses): show the value used, the alternative, the dollar impact of the choice,
and a "confirm with [team]" flag. Include a simple A/B toggle cell for the rebate
reading (prospective vs retroactive-within-year) that flows through the formula
stack.

openpyxl workbook:
- **Assumptions tab:** every input, provenance class color-coded, mandatory Source/Basis column. Named ranges for key inputs; formula cells locked (sheet protection with inputs unlocked).
- **Assumption Register tab (§5):** every model input with its type (`contract_fact` / `market_data` / `policy_number` / `strategic_judgment`) and **OWNER** column (who confirms it — e.g. COGS → "cost accounting", WACC → "Treasury", vest probabilities & downside demand → "deal team"). The accountability view; drives the Assumption Gap Report.
- **Drivers tab:** terms → drivers with source clause text and document/section.
- **Model tab:** quarterly P&L, **live formulas only** referencing Assumptions via named ranges — edit ASP in Excel, model recalculates. Zero hardcoded computed cells. Footnote column or cell comments tying each line to its driver and clause.
- **Warrant Assumptions tab:** a dedicated tab grouping the editable *judgment* inputs — per-tranche vest probabilities and the measurement stock price — **separate from the contract-fact warrant terms** (shares, strike, milestones, hurdles), each flagged "strategic estimate — confirm with deal team". Live formula links so editing a probability or the price recomputes the Warrant and Model tabs. This is where the warrant value's conservative/base/aggressive range is driven.
- **Scenarios tab** (with probability weights and expected value), **Variance tab** (when ≥2 versions), **Warrant tab** (tranches, fair value, contra-revenue flowing into Model via formulas; reads the Warrant Assumptions tab), **Accounting Schedules tab** (§9.4), **CRB Summary tab** (print-ready), **Changelog tab** (change journal).
- **Golden-file test:** generate, reopen, assert formulas (not cached values) in sampled computed cells; recompute one full chain by hand in the test.

### 9.2 CRB memo [P0]
One page, markdown in UI + DOCX download: 3-line deal summary (structure incl. equity component); economics table by scenario, GAAP and cash views, with bridge and expected value; effective net ASP line; top 5 risks ranked with quantified exposure and recommended approval condition (warrant dilution, MFN, ambiguity delta, supply feasibility should surface naturally); benchmark sentences; policy verdict (§9.5); recommendation with explicit approval asks. LLM writes prose; every number injected from engine output. The **warrant section must carry the correlation caveat (§4)** — that the spot-price + independent-vest-probability valuation likely understates upside-scenario warrant cost because milestones and stock hurdles are positively correlated.

### 9.3 CRB slide [P1]
One PowerPoint slide via python-pptx: deal header, economics mini-table, effective-ASP waterfall image, top 3 risks, policy verdict. The job names PowerPoint; one clean slide beats a deck.

### 9.4 Accounting schedules [P0]
The handoff that makes Accounting trust the tool:
- **Rebate accrual walk** by quarter: beginning balance, accrual expense (at expected blended rate — variable consideration estimate), payments/true-ups at annual settlement, ending balance.
- **Contract liability (prepayment) schedule:** beginning balance, drawdown, ending balance by quarter.
- **Peak receivables exposure:** maximum accounts-receivable balance implied by ramp × ASP × payment terms, and the quarter it occurs.
Each schedule appears in the UI and the Excel Accounting Schedules tab, formula-driven.

### 9.5 Policy engine / approval routing [P0]
`data/crb_policy.json` — configurable thresholds: margin floor, deal size tiers mapped to required approvers, auto-escalation terms (uncapped liability, MFN, warrant/equity component, payment terms beyond net-60, take-or-pay below a floor). Engine evaluates every deal version and outputs a **policy verdict**: pass/escalate per rule, required approver list, and reasons ("requires CFO approval: blended margin 43.8% below 45% floor; MFN present"). Feeds memo and dashboard. This is the Contract Review Board encoded.

### 9.6 Assumption Gap Report [P0]
Ranked clarifying questions with dollar sensitivities (§1). UI section + memo section when gaps exist. Draws from the **Assumption Register (§5)**: every input typed `strategic_judgment` or `market_data`, or carrying a `placeholder` provenance, becomes a gap-report line addressed to its named OWNER.

### 9.7 Glossary [P0]
`data/glossary.json`: every finance term and abbreviation used anywhere in the UI or outputs (ASP, COGS, NPV, WACC, MFN, take-or-pay, contra-revenue, accrual, contract liability, PUE...) mapped to a one-sentence plain-English explanation. UI shows hover/expander definitions; README includes the full table. No unexplained jargon anywhere in the product.

### 9.8 Deal bundle export/import [P1]
A deal package (terms, versions, assumptions, journal) serializes to a single JSON bundle for sharing/backup; import recreates it.

## 10. UI (Streamlit tabs)

[P0] **Pipeline** (registry dashboard) · **Deal Intake** (multi-doc upload, term-sheet paste, archetype/clone start, missing-doc + validation warnings, review queue) · **Model** (assumptions with provenance badges, scenario + GAAP/cash toggles, probability weights, sensitivity tornado, capacity bridge inputs when active) · **Warrant** (tranche table, probability sliders, effective-ASP waterfall) · **Negotiation** (versions, variance bridge, ad-hoc drivers; goal-seek [P1]) · **Memo & Reports** (CRB memo, gap report, accounting schedules, policy verdict, downloads: XLSX/DOCX/PPTX) · **Accuracy** (eval precision/recall + validation results) · [P1] **Portfolio** (MFN exposure matrix, precedent comparison).

## 11. Build order

0. **[P0] Schema retrofit** (no Phase 1 breakage): DealVersion; AdHocDriver; AssumptionProvenance (value+basis+note+as_of); CapacityBridgeInputs; GenerationTranche; TermVariant (ambiguity readings); DealStatus + registry-level DealRecord; ActualsRecord [P2 schema]; ChangeJournalEntry; PolicyRule + PolicyVerdict; ScenarioProbability; DistributionSpec [P2 schema]. Re-run import check. Commit.
1. ~~Phase 1~~ DONE.
2. **[P0] Extraction:** term_extractor.py + term-sheet/pasted-text intake + untrusted-input hardening + validation layer + review-queue flagging + eval harness vs ground_truth.json (precision/recall per term type). Amendment layering [P1] behind a clean interface. Commit.
3. **[P0] Engine:** assumptions library; driver_mapper (incl. TermVariant dual readings); economics_engine (P&L, scenarios, probability weighting, sensitivities, capacity bridge, Banked Units, prepayment mechanics); accounting schedules; full pytest suite. [P1]: multi-generation, COGS curve, feasibility, deployment-delay + liquidated-damages interaction. Commit.
4. **[P0] Warrant:** warrant_economics.py + tests. Commit.
5. **[P0] Negotiation core:** versioning, change journal, variance bridge + sums-to-delta property test, ad-hoc drivers. [P1] goal-seek. Commit.
6. **[P0] Policy + benchmarks + reports:** policy engine, benchmarks.py (staleness check), crb_memo.py, Assumption Gap Report, glossary. Commit.
7. **[P0] Excel:** excel_export.py per §9.1 with golden-file test. [P1] PowerPoint slide. Commit.
8. **[P0] UI:** all P0 tabs incl. Pipeline dashboard and archetype/clone intake. [P1] Portfolio tab (cross-deal MFN, precedents). Commit.
9. **[P0] README:** architecture diagram (mermaid); demo walkthrough scripted as a negotiation story (forward-model from archetype → documents arrive → extraction + gap report → counterparty counter → variance bridge → goal-seek → MFN check against a second deal → policy verdict → CRB memo + Excel); screenshots; Simplifications; glossary table; roadmap of any cut P1s. Commit.
10. [P2] Post-signing actuals UI; Monte Carlo.

At each phase: plan mode first, show me the plan, build, run tests, stop for my review, commit. Never start the next phase without my approval.
