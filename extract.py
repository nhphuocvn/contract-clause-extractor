import argparse
import io
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field
from PyPDF2 import PdfReader

load_dotenv()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class Party(BaseModel):
    name: str
    role: str


class PartiesField(BaseModel):
    value: list[Party]
    source_quote: str = Field(
        description="Verbatim excerpt identifying the parties. Empty string if not found."
    )


class TextField(BaseModel):
    value: str = Field(
        description="Extracted value. Empty string if the field is not present."
    )
    source_quote: str = Field(
        description="Verbatim excerpt copied character-for-character from the contract. Empty string if not found."
    )


class TerminationClauses(BaseModel):
    for_cause: TextField = Field(
        description="Termination right triggered by material breach by either party."
    )
    for_convenience: TextField = Field(
        description="Termination right without cause (typically by customer/licensee with notice)."
    )
    for_non_payment: TextField = Field(
        description="Provider's/licensor's right to terminate or suspend for unpaid fees."
    )


class DataProtection(BaseModel):
    encryption: TextField = Field(
        description="Encryption-at-rest and in-transit specifics (e.g., AES-256, TLS 1.3)."
    )
    data_residency: TextField = Field(
        description="Geographic location where data is stored."
    )
    certifications: TextField = Field(
        description="Security certifications such as SOC 2, ISO 27001."
    )
    compliance_frameworks: TextField = Field(
        description="Privacy/regulatory frameworks such as GDPR, HIPAA, CCPA."
    )


class ContractExtraction(BaseModel):
    parties: PartiesField
    effective_date: TextField
    term_length: TextField
    auto_renewal: TextField
    payment_terms: TextField
    termination_clauses: TerminationClauses
    sla_commitments: TextField
    indemnity_cap: TextField
    limitation_of_liability: TextField
    governing_law: TextField
    confidentiality_period: TextField
    data_protection: DataProtection


class RiskFlag(BaseModel):
    rule: str
    level: str  # high | medium | review_recommended | low_protection
    message: str
    evidence: str


class RiskSummary(BaseModel):
    flags: list[RiskFlag]
    overall_risk: str  # high | medium | review_recommended | low_protection | low


SYSTEM_PROMPT = (
    "You are a contract analysis expert. For each requested field, return both the extracted "
    "value and a source_quote: a verbatim excerpt copied character-for-character from the contract "
    "that supports the value. Do not paraphrase quotes.\n\n"
    "For auto_renewal, the value MUST mention both the renewal cadence and the non-renewal "
    "notice period (e.g. 'successive 1-year terms; 90 days written notice'), and the source_quote "
    "MUST include the full sentence(s) covering both the renewal AND the notice requirement.\n\n"
    "For confidentiality_period, include the numeric duration (e.g. 'five (5) years').\n\n"
    "For limitation_of_liability, include the cap (multiplier or months-of-fees) in the value.\n\n"
    "termination_clauses has three sub-fields: for_cause (material breach), for_convenience "
    "(termination without cause, often by customer with notice), and for_non_payment (provider's "
    "right to terminate or suspend for unpaid fees). Quote each branch separately.\n\n"
    "data_protection has four sub-fields: encryption (at-rest/in-transit specifics), "
    "data_residency (geographic storage location), certifications (SOC 2, ISO 27001, etc.), and "
    "compliance_frameworks (GDPR, HIPAA, CCPA, etc.).\n\n"
    "If a (sub-)field is not present, set value to an empty string (or empty list) and "
    "source_quote to an empty string."
)


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------


def read_contract_bytes(data: bytes, suffix: str) -> str:
    suffix = suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if suffix in (".txt", ".md", ""):
        return data.decode("utf-8")
    raise ValueError(f"Unsupported file type: {suffix} (supported: .txt, .pdf)")


def read_contract(path: Path) -> str:
    return read_contract_bytes(path.read_bytes(), path.suffix)


def extract(client: OpenAI, contract_text: str) -> tuple[ContractExtraction, int]:
    completion = client.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"CONTRACT TEXT:\n{contract_text}"},
        ],
        response_format=ContractExtraction,
        temperature=0,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise RuntimeError(
            f"Model refused or returned no parsed output: {completion.choices[0].message.refusal!r}"
        )
    return parsed, completion.usage.total_tokens


# ---------------------------------------------------------------------------
# Risk scoring
# ---------------------------------------------------------------------------


_WORD_NUMS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100,
}

# Jurisdictions considered low-friction by default. Edit this set for your
# preferred home-jurisdiction profile.
FAVORABLE_JURISDICTIONS = {
    # US states
    "new york", "california", "delaware", "texas", "massachusetts", "illinois",
    "washington", "florida", "georgia", "virginia", "north carolina",
    "pennsylvania", "michigan", "new jersey", "colorado", "arizona", "ohio",
    "united states",
    # UK / Ireland
    "england and wales", "england", "scotland", "united kingdom", "ireland",
    # Other common-law / business-friendly
    "canada", "ontario", "british columbia",
    "singapore", "australia", "new zealand",
}


def _find_number_with_unit(text: str, unit_pattern: str) -> int | None:
    """Find the first numeric value preceding a unit (e.g. "days?", "months?", "years?")."""
    if not text:
        return None
    # Parenthesized: "ninety (90) days" -> 90
    m = re.search(rf"\((\d+)\)\s*{unit_pattern}", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Bare digits: "90 days"
    m = re.search(rf"\b(\d+)\s*{unit_pattern}\b", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Word form: "ninety days"
    word_pat = "|".join(_WORD_NUMS.keys())
    m = re.search(rf"\b({word_pat})\b\s*{unit_pattern}", text, re.IGNORECASE)
    if m:
        return _WORD_NUMS[m.group(1).lower()]
    return None


def _find_multiplier(text: str) -> float | None:
    """Find a 'N times' or 'N x' multiplier (e.g. liability cap of 2x fees)."""
    if not text:
        return None
    # "two (2) times" or "(2) times"
    m = re.search(r"\((\d+(?:\.\d+)?)\)\s*times?\b", text, re.IGNORECASE)
    if m:
        return float(m.group(1))
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*times?\b", text, re.IGNORECASE)
    if m:
        return float(m.group(1))
    word_mults = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                  "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    for w, v in word_mults.items():
        if re.search(rf"\b{w}\b\s*(?:\([^)]*\))?\s*times?\b", text, re.IGNORECASE):
            return float(v)
    return None


_RISK_PRIORITY = ["high", "medium", "review_recommended", "low_protection"]


def _overall_risk(flags: list[RiskFlag]) -> str:
    levels = {f.level for f in flags}
    for lvl in _RISK_PRIORITY:
        if lvl in levels:
            return lvl
    return "low"


def compute_risk_summary(c: ContractExtraction) -> RiskSummary:
    flags: list[RiskFlag] = []

    # Rule 1: auto-renewal notice < 90 days -> medium
    renewal_text = " ".join([c.auto_renewal.value or "", c.auto_renewal.source_quote or ""])
    notice_days = _find_number_with_unit(renewal_text, r"days?")
    if notice_days is not None and notice_days < 90:
        flags.append(RiskFlag(
            rule="auto_renewal_short_notice",
            level="medium",
            message=f"Non-renewal notice period is {notice_days} days (< 90 days threshold).",
            evidence=c.auto_renewal.source_quote,
        ))

    # Rule 2: missing liability cap, or cap > 2x annual fees -> high
    lol = c.limitation_of_liability
    lol_text = " ".join([lol.value or "", lol.source_quote or ""])
    if not lol.value.strip():
        flags.append(RiskFlag(
            rule="missing_liability_cap",
            level="high",
            message="No limitation of liability clause was extracted.",
            evidence="",
        ))
    else:
        lol_lower = lol_text.lower()
        if "unlimited liability" in lol_lower or "no cap" in lol_lower:
            flags.append(RiskFlag(
                rule="liability_cap_explicit_none",
                level="high",
                message="Liability is explicitly uncapped.",
                evidence=lol.source_quote,
            ))
        else:
            mult = _find_multiplier(lol_text)
            months_cap = _find_number_with_unit(lol_text, r"months?")
            if mult is not None and mult > 2:
                flags.append(RiskFlag(
                    rule="liability_cap_too_high",
                    level="high",
                    message=f"Liability cap of {mult}x annual fees exceeds 2x threshold.",
                    evidence=lol.source_quote,
                ))
            elif months_cap is not None and months_cap > 24:
                flags.append(RiskFlag(
                    rule="liability_cap_too_high",
                    level="high",
                    message=f"Liability cap covers {months_cap} months of fees (> 24-month threshold).",
                    evidence=lol.source_quote,
                ))

    # Rule 3: governing law in unfavorable jurisdiction -> review_recommended
    gov = c.governing_law
    if not gov.value.strip():
        flags.append(RiskFlag(
            rule="missing_governing_law",
            level="review_recommended",
            message="No governing law clause was extracted.",
            evidence="",
        ))
    else:
        gov_lower = (gov.value + " " + gov.source_quote).lower()
        if not any(j in gov_lower for j in FAVORABLE_JURISDICTIONS):
            flags.append(RiskFlag(
                rule="unfavorable_jurisdiction",
                level="review_recommended",
                message=f"Governing law not in default favorable list: {gov.value!r}.",
                evidence=gov.source_quote,
            ))

    # Rule 4: missing SLA -> high
    if not c.sla_commitments.value.strip():
        flags.append(RiskFlag(
            rule="missing_sla",
            level="high",
            message="No SLA commitments were extracted.",
            evidence="",
        ))

    # Rule 5: confidentiality period < 3 years -> low_protection
    conf_text = " ".join([c.confidentiality_period.value or "", c.confidentiality_period.source_quote or ""])
    years = _find_number_with_unit(conf_text, r"years?")
    if years is not None and years < 3:
        flags.append(RiskFlag(
            rule="confidentiality_period_short",
            level="low_protection",
            message=f"Confidentiality period is {years} years (< 3 years threshold).",
            evidence=c.confidentiality_period.source_quote,
        ))

    return RiskSummary(flags=flags, overall_risk=_overall_risk(flags))


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


COMPARISON_FIELDS = [
    "parties",
    "effective_date",
    "term_length",
    "auto_renewal",
    "payment_terms",
    "sla_commitments",
    "indemnity_cap",
    "limitation_of_liability",
    "governing_law",
    "confidentiality_period",
]


def _summarize_field(extraction: ContractExtraction, field_name: str) -> str:
    f = getattr(extraction, field_name)
    if field_name == "parties":
        return "; ".join(f"{p.name} ({p.role})" for p in f.value)
    return f.value


def build_comparison(
    results: list[tuple[str, ContractExtraction, RiskSummary]],
) -> dict:
    rows = []
    for field_name in COMPARISON_FIELDS:
        rows.append({
            "field": field_name,
            "values": [_summarize_field(e, field_name) for _, e, _ in results],
        })
    rows.append({
        "field": "overall_risk",
        "values": [r.overall_risk for _, _, r in results],
    })
    rows.append({
        "field": "risk_flag_count",
        "values": [len(r.flags) for _, _, r in results],
    })
    return {
        "contracts": [name for name, _, _ in results],
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Output assembly
# ---------------------------------------------------------------------------


def build_output(extraction: ContractExtraction, risk: RiskSummary) -> dict:
    return {**extraction.model_dump(), "risk_summary": risk.model_dump()}


def process_file(client: OpenAI, path: Path) -> tuple[ContractExtraction, RiskSummary, int]:
    print(f"\n=== {path.name} ===")
    contract_text = read_contract(path)
    extraction, total_tokens = extract(client, contract_text)
    risk = compute_risk_summary(extraction)

    output_path = path.with_suffix(".json")
    output_obj = build_output(extraction, risk)
    output_path.write_text(json.dumps(output_obj, indent=2), encoding="utf-8")

    print(f"  overall_risk: {risk.overall_risk}  |  flags: {len(risk.flags)}")
    for flag in risk.flags:
        print(f"    - [{flag.level}] {flag.rule}: {flag.message}")
    print(f"  saved -> {output_path}  |  tokens: {total_tokens}")
    return extraction, risk, total_tokens


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract structured fields and risk flags from contracts (.txt or .pdf)."
    )
    parser.add_argument("files", nargs="+", help="One or more contract files to process")
    parser.add_argument(
        "--comparison-output",
        default="comparison_report.json",
        help="Path for the comparison report (only written when 2+ files succeed).",
    )
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY is not set (add it to .env).", file=sys.stderr)
        return 2

    client = OpenAI(api_key=api_key)

    results: list[tuple[str, ContractExtraction, RiskSummary]] = []
    exit_code = 0

    for file_arg in args.files:
        path = Path(file_arg)
        if not path.exists():
            print(f"[skip] {path}: file not found", file=sys.stderr)
            exit_code = 1
            continue
        try:
            extraction, risk, _ = process_file(client, path)
            results.append((path.name, extraction, risk))
        except Exception as exc:
            print(f"[error] {path}: {exc}", file=sys.stderr)
            exit_code = 1

    if len(results) >= 2:
        comparison = build_comparison(results)
        comp_path = Path(args.comparison_output)
        comp_path.write_text(json.dumps(comparison, indent=2), encoding="utf-8")
        print(f"\nComparison report -> {comp_path}")

    print("\n--- Extraction complete ---")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
