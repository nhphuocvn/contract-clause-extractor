import argparse
import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Union

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


class ContractType(BaseModel):
    primary: str = Field(
        description="Short classification label, e.g. 'SaaS subscription agreement', 'Software license agreement', 'Mutual NDA', 'Master Services Agreement', 'Professional services agreement', 'Data Processing Addendum', 'Reseller agreement'."
    )
    confidence: str = Field(description="'high', 'medium', or 'low'.")
    rationale: str = Field(description="One-sentence justification for the classification.")
    applicable_fields: list[str] = Field(
        description="The subset of these 12 extraction field names that are typically present and relevant for this contract type: parties, effective_date, term_length, auto_renewal, payment_terms, termination_clauses, sla_commitments, indemnity_cap, limitation_of_liability, governing_law, confidentiality_period, data_protection. For example, an NDA would not include sla_commitments or payment_terms."
    )


class RiskFinding(BaseModel):
    severity: str = Field(description="'high', 'medium', 'low', or 'informational'.")
    category: str = Field(
        description="Short category label like 'liability', 'auto_renewal', 'data_protection', 'payment'."
    )
    title: str = Field(description="Short headline (under 80 chars).")
    finding: str = Field(
        description="1-3 sentences explaining what is risky and why, in concrete plain English. Write like a paralegal advising a deal owner. Avoid template phrasing."
    )
    standard_deviation: str = Field(
        description="How this contract deviates from the user's standard, naming BOTH the contract value AND the standard threshold. E.g., 'Contract caps liability at 6 months of fees; your standard requires at least 12 months.' Empty string if there is no deviation."
    )
    counter_position: str = Field(
        description="Specific, actionable negotiation suggestion. Empty string if not applicable."
    )


class AIRiskAssessment(BaseModel):
    findings: list[RiskFinding]
    overall_assessment: str = Field(
        description="Two-to-four-sentence plain-English summary of the contract's risk profile."
    )
    overall_risk_level: str = Field(description="'high', 'medium', or 'low'.")


class BasicContractExtraction(BaseModel):
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


class ContractExtraction(BaseModel):
    contract_type: ContractType
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
    ai_risk_assessment: AIRiskAssessment


class RiskFlag(BaseModel):
    rule: str
    level: str  # high | medium | review_recommended | low_protection
    message: str
    evidence: str


class RiskSummary(BaseModel):
    flags: list[RiskFlag]
    overall_risk: str  # high | medium | review_recommended | low_protection | low


ExtractionType = Union[ContractExtraction, BasicContractExtraction]


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


_FIELD_RULES = """For each requested field, return both the extracted value and a source_quote: a verbatim excerpt copied character-for-character from the contract that supports the value. Do not paraphrase quotes.

For auto_renewal, the value MUST mention both the renewal cadence and the non-renewal notice period (e.g., 'successive 1-year terms; 90 days written notice'). The source_quote MUST include the full sentence(s) covering both.

For confidentiality_period, include the numeric duration (e.g., 'five (5) years'). For limitation_of_liability, include the cap (multiplier or months-of-fees) in the value.

termination_clauses has three sub-fields: for_cause (material breach by either party), for_convenience (without cause, often by customer with notice), for_non_payment (provider's right to terminate or suspend for unpaid fees). Quote each branch separately.

data_protection has four sub-fields: encryption, data_residency, certifications, compliance_frameworks.

If a (sub-)field is not present, set value to an empty string (or empty list) and source_quote to an empty string."""


SYSTEM_PROMPT_BASIC = "You are a contract analysis expert. " + _FIELD_RULES


SYSTEM_PROMPT_FULL_TEMPLATE = (
    "You are a contract analysis expert acting as a smart paralegal advising the user on a contract.\n\n"
    + _FIELD_RULES
    + "\n\n"
    "CLASSIFY contract type in `contract_type`:\n"
    "- primary: short label such as 'SaaS subscription agreement', 'Software license agreement', "
    "'Master Services Agreement', 'Mutual NDA', 'Professional services agreement', "
    "'Data Processing Addendum', or 'Reseller agreement'.\n"
    "- confidence: 'high', 'medium', or 'low'\n"
    "- rationale: one sentence justifying the classification\n"
    "- applicable_fields: list of field names from the 12 extraction fields that are typically "
    "present and relevant for this contract type. For example, an NDA would not include "
    "sla_commitments, payment_terms, or indemnity_cap.\n\n"
    "GENERATE `ai_risk_assessment`:\n\n"
    "DECISION RULE (most important): a `RiskFinding` is ONLY for items that are STRICTLY WORSE "
    "than the user's standard. Items that match the standard or are better than the standard "
    "are NOT findings — do not include them. An empty findings list is the correct output for a "
    "contract that aligns with all of the user's standards.\n\n"
    "For each item below, compare the contract value against the user's standard in the "
    "direction shown. Skip items whose field is not in applicable_fields.\n\n"
    "  auto_renewal notice days        — WORSE when FEWER than auto_renewal_notice_min_days\n"
    "  limitation_of_liability         — WORSE when cap (months) is FEWER than "
    "liability_cap_min_months_of_fees, OR multiplier is LESS than liability_cap_min_multiplier_of_annual_fees\n"
    "  indemnity_cap multiplier        — WORSE when LESS than indemnity_cap_min_multiplier_of_annual_fees\n"
    "  sla_commitments uptime %        — WORSE when LOWER than sla_uptime_min_percent\n"
    "  confidentiality_period years    — WORSE when FEWER than confidentiality_period_min_years\n"
    "  payment_terms net days          — WORSE when FEWER than payment_terms_min_net_days "
    "(customer wants MORE time to pay; if contract gives 45 days and min is 30, that is GOOD — "
    "do not flag)\n"
    "  termination_for_cause notice    — WORSE when MORE than termination_for_cause_notice_max_days\n"
    "  termination_for_convenience     — WORSE when MORE than termination_for_convenience_notice_max_days\n"
    "  governing_law jurisdiction      — WORSE when NOT in preferences.preferred_governing_jurisdictions\n"
    "  data_protection.certifications  — WORSE when any required_certifications are missing\n\n"
    "EQUALITY = ACCEPTANCE: contract value EQUAL to the standard is fine, NOT a deviation. Only "
    "strictly worse-direction values become findings.\n"
    "  Example A: standard auto_renewal_notice_min_days = 90, contract has 90 days → NO finding.\n"
    "  Example B: standard auto_renewal_notice_min_days = 90, contract has 60 days → finding "
    "(60 < 90, worse).\n"
    "  Example C: standard payment_terms_min_net_days = 30, contract has net 45 → NO finding "
    "(45 ≥ 30, equal or better for the customer).\n"
    "  Example D: standard payment_terms_min_net_days = 30, contract has net 15 → finding "
    "(15 < 30, customer has less time than they want).\n"
    "  Example E: standard termination_for_convenience_notice_max_days = 90, contract has 90 → "
    "NO finding. Contract has 120 → finding (120 > 90).\n\n"
    "DO NOT create 'this is acceptable', 'this meets your standards', or 'this is in line with' "
    "findings. If something matches the standard, it simply does not appear in findings.\n\n"
    "When you do create a finding, write it like a paralegal: 1-3 sentence `finding` in plain "
    "English that names the specific clause and numbers; `standard_deviation` stating BOTH the "
    "contract value AND the standard threshold; `counter_position` with a specific, actionable "
    "negotiation suggestion. Use severity 'high' for major risks, 'medium' for moderate, 'low' "
    "for minor.\n\n"
    "Beyond the checklist, you may add findings for buyer-side concerns (unusual termination "
    "fees, broad audit rights, suspension clauses, fee uplifts, etc.) IF they are substantive "
    "concerns — not commentary on normal terms.\n\n"
    "Provide `overall_assessment` (2-4 sentences) and `overall_risk_level` ('high', 'medium', "
    "or 'low'). If findings is empty, overall_risk_level is 'low' and overall_assessment briefly "
    "notes the contract aligns with standards.\n\n"
    "COMPANY STANDARD TERMS (the user's negotiation posture):\n{standard_terms_json}"
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


def load_standard_terms(path: Path | str = "standard_terms.json") -> dict:
    """Load standard terms from a JSON file. Returns an empty dict if the file is missing."""
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def save_standard_terms(terms: dict, path: Path | str = "standard_terms.json") -> None:
    Path(path).write_text(json.dumps(terms, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------


def extract(
    client: OpenAI,
    contract_text: str,
    standard_terms: dict | None = None,
) -> tuple[ContractExtraction, int]:
    """Full extraction: structured fields + contract type + AI risk assessment in one call."""
    system_prompt = SYSTEM_PROMPT_FULL_TEMPLATE.format(
        standard_terms_json=json.dumps(standard_terms or {}, indent=2)
    )
    completion = client.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
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


def extract_basic(
    client: OpenAI, contract_text: str
) -> tuple[BasicContractExtraction, int]:
    """Fallback extraction: 12 fields only, no contract type, no AI risk assessment."""
    completion = client.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_BASIC},
            {"role": "user", "content": f"CONTRACT TEXT:\n{contract_text}"},
        ],
        response_format=BasicContractExtraction,
        temperature=0,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise RuntimeError(
            f"Model refused or returned no parsed output: {completion.choices[0].message.refusal!r}"
        )
    return parsed, completion.usage.total_tokens


# ---------------------------------------------------------------------------
# Deterministic risk scoring (fallback / supplementary)
# ---------------------------------------------------------------------------


_WORD_NUMS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100,
}

FAVORABLE_JURISDICTIONS = {
    "new york", "california", "delaware", "texas", "massachusetts", "illinois",
    "washington", "florida", "georgia", "virginia", "north carolina",
    "pennsylvania", "michigan", "new jersey", "colorado", "arizona", "ohio",
    "united states",
    "england and wales", "england", "scotland", "united kingdom", "ireland",
    "canada", "ontario", "british columbia",
    "singapore", "australia", "new zealand",
}


def _find_number_with_unit(text: str, unit_pattern: str) -> int | None:
    if not text:
        return None
    m = re.search(rf"\((\d+)\)\s*{unit_pattern}", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(rf"\b(\d+)\s*{unit_pattern}\b", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    word_pat = "|".join(_WORD_NUMS.keys())
    m = re.search(rf"\b({word_pat})\b\s*{unit_pattern}", text, re.IGNORECASE)
    if m:
        return _WORD_NUMS[m.group(1).lower()]
    return None


def _find_multiplier(text: str) -> float | None:
    if not text:
        return None
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


def compute_risk_summary(c: ExtractionType) -> RiskSummary:
    """Deterministic risk scoring. Works on either BasicContractExtraction or ContractExtraction."""
    flags: list[RiskFlag] = []

    renewal_text = " ".join([c.auto_renewal.value or "", c.auto_renewal.source_quote or ""])
    notice_days = _find_number_with_unit(renewal_text, r"days?")
    if notice_days is not None and notice_days < 90:
        flags.append(RiskFlag(
            rule="auto_renewal_short_notice",
            level="medium",
            message=f"Non-renewal notice period is {notice_days} days (< 90 days threshold).",
            evidence=c.auto_renewal.source_quote,
        ))

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

    if not c.sla_commitments.value.strip():
        flags.append(RiskFlag(
            rule="missing_sla",
            level="high",
            message="No SLA commitments were extracted.",
            evidence="",
        ))

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


def _summarize_field(extraction: ExtractionType, field_name: str) -> str:
    f = getattr(extraction, field_name)
    if field_name == "parties":
        return "; ".join(f"{p.name} ({p.role})" for p in f.value)
    return f.value


def build_comparison(
    results: list[tuple[str, ExtractionType, RiskSummary]],
) -> dict:
    rows = []
    # Add contract type row at the top if available on any
    contract_type_row = {
        "field": "contract_type",
        "values": [
            getattr(getattr(e, "contract_type", None), "primary", "") for _, e, _ in results
        ],
    }
    if any(contract_type_row["values"]):
        rows.append(contract_type_row)

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
    # AI overall if available
    ai_levels = [
        getattr(getattr(e, "ai_risk_assessment", None), "overall_risk_level", "")
        for _, e, _ in results
    ]
    if any(ai_levels):
        rows.append({"field": "ai_overall_risk_level", "values": ai_levels})

    return {
        "contracts": [name for name, _, _ in results],
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Output assembly
# ---------------------------------------------------------------------------


def build_output(extraction: ExtractionType, deterministic_risk: RiskSummary) -> dict:
    return {**extraction.model_dump(), "risk_summary": deterministic_risk.model_dump()}


def process_file(
    client: OpenAI,
    path: Path,
    standard_terms: dict,
) -> tuple[ExtractionType, RiskSummary, int, bool]:
    """Extract a contract end-to-end. Returns (extraction, deterministic_risk, tokens, ai_succeeded)."""
    print(f"\n=== {path.name} ===")
    contract_text = read_contract(path)

    ai_succeeded = True
    try:
        extraction, total_tokens = extract(client, contract_text, standard_terms)
    except Exception as exc:
        print(f"  [warn] AI assessment failed ({type(exc).__name__}: {exc}); falling back to basic extraction + deterministic rules.")
        extraction, total_tokens = extract_basic(client, contract_text)
        ai_succeeded = False

    deterministic = compute_risk_summary(extraction)
    output_path = path.with_suffix(".json")
    output_obj = build_output(extraction, deterministic)
    output_path.write_text(json.dumps(output_obj, indent=2), encoding="utf-8")

    if ai_succeeded and isinstance(extraction, ContractExtraction):
        ct = extraction.contract_type
        ai = extraction.ai_risk_assessment
        print(f"  Contract type: {ct.primary} (confidence: {ct.confidence})")
        print(f"  AI overall: {ai.overall_risk_level} | findings: {len(ai.findings)}")
        for f in ai.findings:
            print(f"    - [{f.severity}] {f.category}: {f.title}")
    else:
        print(f"  Deterministic overall: {deterministic.overall_risk} | flags: {len(deterministic.flags)}")
        for flag in deterministic.flags:
            print(f"    - [{flag.level}] {flag.rule}: {flag.message}")

    print(f"  saved -> {output_path}  |  tokens: {total_tokens}")
    return extraction, deterministic, total_tokens, ai_succeeded


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract structured fields, contract type, and AI risk assessment from contracts (.txt or .pdf)."
    )
    parser.add_argument("files", nargs="+", help="One or more contract files to process")
    parser.add_argument(
        "--standard-terms",
        default="standard_terms.json",
        help="Path to company standard-terms JSON (default: standard_terms.json).",
    )
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

    standard_terms = load_standard_terms(args.standard_terms)
    if not standard_terms:
        print(f"[warn] Standard terms file not found at {args.standard_terms}; running without standards.")

    client = OpenAI(api_key=api_key)

    results: list[tuple[str, ExtractionType, RiskSummary]] = []
    exit_code = 0

    for file_arg in args.files:
        path = Path(file_arg)
        if not path.exists():
            print(f"[skip] {path}: file not found", file=sys.stderr)
            exit_code = 1
            continue
        try:
            extraction, deterministic, _tokens, _ai_ok = process_file(client, path, standard_terms)
            results.append((path.name, extraction, deterministic))
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
