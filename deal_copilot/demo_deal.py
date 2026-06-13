"""Demo deal package carrying the REAL contract clause text.

The shared test fixture (`tests/fixtures.py`) uses placeholder `raw_text`
("synthetic excerpt for …") so the engine hand-calcs stay terse. The Excel
workbook, by contrast, must be self-documenting: every term row shows the actual
clause text from the source documents. This module builds the same
warrant-bearing AMD–Meta package but threads the **verbatim** §-clause text from
`data/sample_contracts/_doc_a_content.py` / `_doc_b_content.py` into each
`CommercialTerm.raw_text`, with the real document filenames and section labels.

Reused by both `scripts/build_demo_workbook.py` and the Excel golden-file tests,
so the clause text shown in the workbook is exactly what the tests assert against.
"""

from __future__ import annotations

from data.sample_contracts import _doc_a_content as doc_a
from data.sample_contracts import _doc_b_content as doc_b
from deal_copilot.schemas import CommercialTerm, DealPackage, DocumentRef, TermType
from tests.fixtures import synthetic_package_with_warrant

DOC_A_FILENAME = "gpu_purchase_agreement.docx"
DOC_B_FILENAME = "warrant_agreement.docx"


def _section_text(sections, number: int) -> tuple[str, str]:
    """Return (label, joined paragraph text) for a section number."""
    for num, title, paras in sections:
        if num == number:
            return f"§{num}. {title}", "\n\n".join(paras)
    return f"§{number}", ""


# Each commercial term type → the Doc A section that is its source clause.
_TERM_SECTION = {
    TermType.PRICING: 4,
    TermType.VOLUME_COMMITMENT: 3,
    TermType.REBATE: 5,
    TermType.TAKE_OR_PAY: 6,
    TermType.PREPAYMENT: 7,
    TermType.PAYMENT_TERMS: 8,
    TermType.PRICE_PROTECTION_MFN: 9,
    TermType.LIABILITY: 12,
    TermType.WARRANT_EQUITY: 13,
}


def demo_package_with_clauses() -> DealPackage:
    """The warrant-bearing synthetic package with REAL clause text attached to
    every commercial term (and the real document filenames / section labels)."""
    pkg = synthetic_package_with_warrant()
    for term in pkg.terms:
        sec_num = _TERM_SECTION.get(term.term_type)
        if sec_num is None:
            continue
        label, text = _section_text(doc_a.SECTIONS, sec_num)
        term.raw_text = text
        term.source_document = DOC_A_FILENAME
        term.source_section = label
    # Point the document refs at the real, human-readable filenames.
    pkg.documents = [
        DocumentRef(filename=DOC_A_FILENAME, document_type="purchase_agreement"),
        DocumentRef(filename=DOC_B_FILENAME, document_type="warrant_agreement"),
    ]
    return pkg


def warrant_clause_texts() -> dict[str, str]:
    """Verbatim warrant clauses (Doc B) keyed by a short tag, for the Warrant and
    Warrant_Assump tabs."""
    return {
        "grant": _section_text(doc_b.SECTIONS, 1)[1],
        "vesting": _section_text(doc_b.SECTIONS, 2)[1],
        "hurdles": _section_text(doc_b.SECTIONS, 3)[1],
        "final_tranche": _section_text(doc_b.SECTIONS, 4)[1],
    }


__all__ = [
    "demo_package_with_clauses",
    "warrant_clause_texts",
    "DOC_A_FILENAME",
    "DOC_B_FILENAME",
]
