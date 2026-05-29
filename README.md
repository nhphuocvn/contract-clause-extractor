# Contract Clause Extractor

Contract Clause Extractor is a Python tool that pulls structured fields from commercial contracts using OpenAI's structured-output API, attaches a verbatim source quote to every extracted value so reviewers can verify the extraction against the original document, and applies a configurable set of risk-scoring rules to flag clauses that warrant attention. It ships with a CLI for batch processing (with side-by-side comparison of multiple contracts) and a Streamlit UI for interactive review.

## Features

- **Structured extraction.** Twelve top-level fields — parties, effective date, term length, auto-renewal, payment terms, termination clauses, SLA commitments, indemnity cap, limitation of liability, governing law, confidentiality period, data protection — returned as typed Pydantic objects via OpenAI's `response_format` API. No regex parsing of free-form completions.
- **Sub-schemas for compound clauses.** `termination_clauses` splits into `for_cause`, `for_convenience`, and `for_non_payment`. `data_protection` splits into `encryption`, `data_residency`, `certifications`, and `compliance_frameworks`.
- **Source quotes.** Every extracted value is paired with a verbatim excerpt from the source text, so reviewers can verify each datum without re-reading the full contract.
- **Risk scoring.** Five built-in rules: short auto-renewal notice (< 90 days → *medium*), missing or > 2× liability cap (*high*), governing law outside a configurable favorable list (*review recommended*), missing SLA (*high*), short confidentiality period (< 3 years → *low protection*). Rules are pure Python and easy to extend.
- **Side-by-side comparison.** Running on two or more contracts emits a `comparison_report.json` with a row per key term across all contracts, plus overall risk level and flag count per contract.
- **Streamlit UI.** Drag-and-drop upload (TXT or PDF), per-contract tabs with colored risk badges, an auto-added "Compare" tab when two or more contracts are uploaded, and one-click JSON download.
- **PDF support.** Text-based PDFs are read via PyPDF2 with no separate preprocessing step.

## Tech stack

- Python 3.10+
- OpenAI Python SDK with structured outputs (`response_format`) — model: `gpt-4o-mini`
- Pydantic v2 (extraction schema and risk-summary models)
- Streamlit (web UI)
- PyPDF2 (PDF text extraction)
- python-dotenv (local `.env` loading)

## Installation

```powershell
# 1. Clone the repo
git clone https://github.com/nhphuocvn/contract-clause-extractor.git
cd contract-clause-extractor

# 2. Install dependencies
python -m pip install openai pydantic PyPDF2 python-dotenv streamlit openpyxl

# 3. Configure your OpenAI API key
#    Create a .env file in the project root containing:
#       OPENAI_API_KEY=sk-...
```

The `.env` file is gitignored, so the key will not be committed.

## Usage

### CLI

Process one or more contracts:

```powershell
python extract.py sample_contract.txt sample_contract_2.txt
```

For each input file `foo.txt` or `foo.pdf`, the script writes `foo.json` next to it, prints any risk flags to the terminal, and — when two or more contracts succeed — writes a `comparison_report.json` summarizing the differences.

### Excel export

After running `extract.py`, export the JSON results to an executive Excel workbook:

```powershell
python excel_export.py sample_contract.json sample_contract_2.json -o Portfolio.xlsx
```

The workbook has four sheets:

- **README** — purpose and pipeline notes.
- **Portfolio** — one row per contract with all key fields and risk levels.
- **AI Risk Findings** — flattened paralegal findings across all contracts.
- **Source Quotes** — audit trail pairing every value with its verbatim contract excerpt.

### Streamlit UI

```powershell
streamlit run app.py
```

Opens at `http://localhost:8501`. Upload one or more contracts to see extracted fields, risk flags, and (with two or more contracts) a side-by-side comparison.

## Example output

Per-contract JSON (excerpt):

```json
{
  "parties": {
    "value": [
      {"name": "Acme Cloud Solutions, Inc.", "role": "Provider"},
      {"name": "GlobalTech Enterprises, LLC", "role": "Customer"}
    ],
    "source_quote": "by and between Acme Cloud Solutions, Inc., ..."
  },
  "auto_renewal": {
    "value": "successive one (1) year periods; 90 days written notice of non-renewal",
    "source_quote": "this Agreement shall automatically renew for successive one (1) year periods ... unless either party provides written notice of non-renewal at least ninety (90) days prior to the end of the then-current term."
  },
  "risk_summary": {
    "flags": [],
    "overall_risk": "low"
  }
}
```

In the Streamlit UI, each uploaded contract gets its own tab showing:

- A header row with the file name and an overall risk badge (green for *low*, yellow for *medium* / *low protection*, blue for *review recommended*, red for *high*).
- Color-coded risk flag cards, each containing the rule name, an explanation, and the supporting source quote.
- A sortable, scrollable table of all extracted fields with their values and source quotes.
- A **Download JSON** button to save the full extraction for that contract.

When two or more contracts are uploaded, an additional **Compare** tab shows a side-by-side dataframe of key terms (parties, term length, payment, caps, SLA, governing law, etc.) across all contracts, with a download button for `comparison_report.json`.

## Roadmap

- **RAG-based portfolio search.** Index extracted fields and source clauses across an organization's signed contracts, then answer natural-language queries like *"which of our customers have governing law outside the US?"* or *"show every contract whose confidentiality period is under three years."*
- **Real SEC EDGAR contracts.** Validate the extractor against material contracts filed as 10-K / 10-Q exhibits to test generalization beyond hand-written samples.
- **Additional contract types.** Extend the schemas to cover NDAs, employment agreements, vendor MSAs with statements of work, and procurement contracts. Each type adds its own field set and targeted risk rules.
- **Clause-level diff.** Semantic diff between two versions of the same contract (e.g., redline vs. final) for negotiation history.
- **Human-in-the-loop review.** Per-field confidence scoring and a review queue for low-confidence extractions.

## About the author

Built by [@nhphuocvn](https://github.com/nhphuocvn), drawing on 10+ years of experience in Quote-to-Cash and finance systems transformation. The project addresses a recurring pain point from those years: deal desks, legal, and finance teams spending substantial time on contract review that is largely mechanical — locate the cap, the term, the renewal trigger — work that is well-suited to structured extraction paired with verifiable source quotes.
