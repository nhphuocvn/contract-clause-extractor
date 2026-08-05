STAGED BUILD — Deal Copilot Excel: make it fully dynamic AND fully self-explaining.

GROUND RULES (apply to every stage):
- Work stages IN ORDER. Do not start a stage until the previous one is committed with green tests.
- After each stage: run `python -m pytest -q`. ALL tests must pass (204 baseline + any you add). Then `git commit` that stage ALONE with a clear message. Then continue.
- Do NOT modify the economics engine math (economics_engine.py, warrant_economics.py, driver_mapper.py calculation logic). You may READ them. You only change Excel rendering (deal_copilot/excel_export.py), documentation content, and tests.
- Before starting, READ: deal_copilot/excel_export.py (whole file), KICKOFF.md, deal_copilot/driver_mapper.py (to see how tiers/terms are structured), tests/fixtures.py (to see the test package builder).
- If a stage's tests won't pass after honest effort, STOP and leave a note in gnhf_progress.md explaining what blocked you. Do not force a broken commit.

═══════════════════════════════════════════════════════════
STAGE 1 — DYNAMIC REBATE TIERS (Model tab)
═══════════════════════════════════════════════════════════
PROBLEM: The Model tab hardcodes exactly 3 rebate tiers. Specifically:
  - Row constants _M_HEAD0/1/2 (lines ~121-123) and _M_ZONE0/1/2/3 (lines ~124-127)
  - Headroom rows referencing RebateTier1/2/3Threshold (lines ~794-796)
  - Zone-split formulas for exactly 4 zones (lines ~802-809)
  - Active-Rebate (Reading A) formula summing exactly 3 tiers' zone*rate (lines ~816-817)
The engine (driver_mapper._normalize_tiers) and the Assumptions tab already handle N tiers dynamically. Only the Model tab is stuck at 3.

DO: Refactor so headroom rows, zone rows, and the Reading-A rebate formula GENERATE from the actual tier count (len(inp.rebate_tiers)) for any N >= 1. For N tiers you get N headroom rows and N+1 zones (below-tier-1, each tier band, above-top-tier). Row layout must shift correctly so nothing below collides. Named ranges RebateTier{i}Rate / RebateTier{i}Threshold for i in 1..N. The Reading-B (retroactive VLOOKUP) path and the A/B toggle must still work identically.

TESTS TO ADD (tests/test_excel_dynamic_tiers.py):
  - Build a workbook from a 5-tier contract; assert 5 headroom rows, 6 zone rows, named ranges RebateTier1..5Rate and RebateTier1..5Threshold all exist, and the Active Rebate formula string references all 5 tier rates.
  - Build from a 2-tier contract; assert it renders 2 tiers correctly.
  - Build from the standard 3-tier deal; assert output matches the existing expected structure (no regression).
COMMIT when green.

═══════════════════════════════════════════════════════════
STAGE 2 — DYNAMIC WARRANT TRANCHES (Warrant tab)
═══════════════════════════════════════════════════════════
The warrant table already loops on n_tr = len(warrant.tranche_valuations) (lines ~577, 605, 1021), so it's mostly dynamic. But verify and harden: some row offsets (_W_TR_ROW_START, _W_TOTAL_EFV_ROW, _W_CONTRA_ROW) may assume exactly 4 tranche rows, causing collisions when the count differs.

DO: Make ALL warrant-tab row positions and any downstream tabs that reference warrant rows compute from the actual tranche count, not assume 4. Fix any collision.

TESTS TO ADD (tests/test_excel_dynamic_tranches.py):
  - Build a workbook with a 6-tranche warrant; assert 6 tranche rows render and totals/contra rows sit below them without overlap.
  - Build with a 2-tranche warrant; assert correct.
  - Build with the default 4-tranche; assert no regression.
COMMIT when green.

═══════════════════════════════════════════════════════════
STAGE 3 — OPTIONAL-TERMS ROBUSTNESS
═══════════════════════════════════════════════════════════
The workbook must build cleanly when terms are ABSENT — no warrant, no take-or-pay, no prepayment, no rebate, in any combination.

DO: Audit every tab-writer for assumptions that a term exists. When a term is absent: either omit its tab/section entirely, OR render it with a clean, plain-English 'Not applicable — this contract has no [term]' note. NEVER a broken grid, a #REF, or a formula referencing a missing named range.

TESTS TO ADD (tests/test_excel_optional_terms.py):
  - Build from a MINIMAL contract (only ASP + quarterly units, no rebate/warrant/take-or-pay/prepayment). Assert: file builds, opens, ZERO cells contain #REF!/#NAME?/#VALUE!, no empty broken tabs.
  - Build from a contract with rebate but NO warrant; assert no warrant tab errors.
  - Build with warrant but NO rebate; assert no rebate errors.
COMMIT when green.

═══════════════════════════════════════════════════════════
STAGE 4 — SELF-EXPLAINING DOCUMENTATION (the big one)
═══════════════════════════════════════════════════════════
GOAL: A smart person who is NOT a deal-finance specialist can open this workbook and FOLLOW THE REASONING and TRUST THE NUMBERS — without googling. Not a textbook; every non-obvious number gets a plain-English 'because'.

DO ALL OF:

(a) EVERY calculation row in the Model tab (and Warrant, Acct_Sched tabs) must have, in its Note/source column AND as an openpyxl cell comment on the row's first cell: a plain-English sentence saying WHAT it computes and WHY (the 'because'). Example for Gross Margin: 'Net revenue minus what the chips cost to make. This is the profit on the hardware itself, before company overhead — the number that tells you if the core deal makes money.' No accounting jargon appears without a plain-English gloss in the same note. For rows identical across 12 quarters, put the full note on the row label / Q1 cell only.

(b) Add a NEW FIRST TAB called 'Start Here' that tells the WHOLE deal as a plain-English story for someone who has never seen a financial model. It must include, in plain language with NO unexplained jargon:
    - What this deal is in 2 sentences (who sells what to whom for how much).
    - The one weird thing: the warrant is free company stock given to the customer; accounting rules make that count AGAINST revenue (called contra-revenue); it's so big it makes the deal show a LOSS on paper (GAAP) even though it brings in cash. Explain WHY that's not actually alarming (they're paying with stock, not cash) and WHY the stock cost grows when the deal succeeds.
    - A plain-English guide to every tab: one line each saying what you'll find there and why you'd look.
    - How to read the model: which cells are inputs you can change (and what happens), which are calculated, what the colors mean.
    - A glossary of the ~10 key terms (ASC 606, contra-revenue, variable consideration, take-or-pay, DSO, warrant, vesting, tranche, GAAP vs cash, NPV) each defined in ONE plain sentence a non-expert gets.

(c) Every INPUT on the Assumptions tab gets a worked example in plain words in its Example column, using real numbers: e.g. rebate tier — 'If Meta buys 80,000 units total, they cross the 75,000 threshold, so units in that band get 5% off — on a $25,000 chip that's $1,250 saved per unit.'

(d) The FIRST time any accounting term appears in any tab, its note includes a one-line plain-English definition inline.

(e) Review the existing analysis tabs (Analysis — Finance Manager, Analysis — Plain English) and make sure the Plain English one genuinely reads like you're explaining to a friend with no finance background — rewrite any sentence that assumes expertise.

TESTS TO ADD (tests/test_excel_documentation.py):
  - Assert a 'Start Here' tab exists and has > 20 non-empty text rows.
  - Assert 'Start Here' contains the key plain-English concepts (search its text for 'contra-revenue', 'free', 'stock', 'cash', and a glossary section).
  - Assert EVERY calculation row in the Model tab has a non-empty Note-column value.
  - Assert cell comments exist on the key Model calc cells (gross margin, net revenue, rebate, warrant contra).
  - Assert every Assumptions input row has a non-empty Example column.
COMMIT when green.

═══════════════════════════════════════════════════════════
STAGE 5 — END-TO-END VERIFICATION + DEMO
═══════════════════════════════════════════════════════════
DO: Write scripts/build_demo_workbook.py (if not present) that builds the standard deal and saves deal_model_demo.xlsx. Run it. Then load the saved file and scan EVERY cell across ALL tabs for error strings (#REF!, #NAME?, #VALUE!, #DIV/0!) — assert ZERO. Also build the three edge cases (5-tier, warrantless-minimal, 6-tranche) and scan each for zero errors.

TEST TO ADD (tests/test_excel_end_to_end.py): the zero-error scan across the standard + 3 edge-case workbooks.

Write a final summary to gnhf_progress.md: what changed per stage, test counts, any known limitations. COMMIT.

═══════════════════════════════════════════════════════════
When all five stages are committed with green tests, summarize per stage and STOP.
